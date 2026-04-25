# Project Setup Design — GeoSTL Hackathon

**Date:** 2026-04-25  
**Track:** TwelveLabs Geospatial Video Intelligence Hackathon  
**Challenge:** Track 01 — Validating the World's Base Layer (track TBD)  
**Area of focus:** San Francisco, CA

---

## 1. Project Structure & Tech Stack

```
geoSTL-hackathon/
├── .env                     # credentials (gitignored)
├── config/
│   └── settings.py          # bbox, endpoints, all config in one place
├── data/
│   ├── raw/                 # downloaded Overture parquet + Mapillary images
│   ├── processed/           # TwelveLabs results, parsed attributes
│   └── output/              # final GeoJSON/GeoParquet for submission
├── ingest/
│   ├── overture.py          # DuckDB → fetch Places + transportation for SF bbox
│   └── mapillary.py         # fetch sequences, images, GPS tracks
├── process/
│   ├── twelvelabs.py        # upload frames to Bedrock, index with Marengo 3.0
│   ├── embeddings.py        # store/search embeddings in OpenSearch
│   └── pegasus.py           # Pegasus 1.2 → structured feature descriptions
├── analyze/
│   ├── cross_reference.py   # match observations → Overture GERS IDs
│   ├── metrics.py           # precision, recall, F1, RMSE
│   └── export.py            # typed GeoJSON + GeoParquet output
├── serve/
│   ├── main.py              # FastAPI app
│   ├── routes/              # API endpoints
│   └── static/              # Leaflet map + Plotly charts (HTML/JS)
└── requirements.txt
```

### Core Libraries

| Purpose | Library |
|---------|---------|
| Overture data | `duckdb` (primary), `overturemaps` CLI (optional) |
| Geospatial ops | `geopandas`, `shapely`, `pyproj` |
| AWS / Bedrock | `boto3` |
| OpenSearch | `opensearch-py` |
| Web server | `fastapi`, `uvicorn` |
| Map UI | Leaflet.js + Deck.gl |
| Charts | Plotly |
| Config | `python-dotenv` |

---

## 2. Data Flow

Each stage reads from and writes to `data/` so any stage can be re-run independently without re-fetching upstream data.

```
INGEST
  overture.py   → DuckDB queries Overture S3 GeoParquet (SF bbox)
                  → data/raw/overture_places.parquet
                  → data/raw/overture_transport.parquet

  mapillary.py  → Mapillary API v4 (SF bbox sequences)
                  → data/raw/mapillary_sequences.json
                  → data/raw/images/{sequence_id}/
        ↓
PROCESS
  twelvelabs.py → upload frames to S3 workshop bucket
                  → Bedrock/Marengo 3.0 → float[1024] embeddings

  embeddings.py → store embeddings + GPS metadata in OpenSearch
                  → data/processed/indexed_segments.json

  pegasus.py    → 5–10s clips → Bedrock/Pegasus 1.2
                  → {name, category, condition}
                  → data/processed/descriptions.json
        ↓
ANALYZE
  cross_reference.py → spatial join: observations + Overture features
                        proximity < 50m (POIs), IoU > 0.3 (buildings)
                        → typed: stale / missing / miscategorized
                        → GERS ID + confidence score per detection

  metrics.py         → precision, recall, F1 per detection type
                        RMSE vs Overture ground truth
                        → data/output/metrics.json

  export.py          → data/output/detections.geojson
                        data/output/detections.geoparquet
        ↓
SERVE
  FastAPI  →  GET /api/detections   GeoJSON FeatureCollection
           →  GET /api/metrics      {precision, recall, f1, rmse} per type
           →  GET /api/sequences    Mapillary GPS tracks as GeoJSON LineStrings
           →  GET /                 Leaflet map + Plotly charts
```

### Data Contracts Between Stages

- Every record touching Overture carries a `gers_id` field
- Every Mapillary image stored to disk retains `{lat, lon, bearing, timestamp}` in the sequence JSON
- OpenSearch documents schema: `{embedding: float[], lat, lon, sequence_id, frame_id, timestamp}`
- All coordinates in EPSG:4326; UTM projections used internally for distance calculations only

---

## 3. API Integrations

### Mapillary (ingest stage)

```
API v4 base: https://graph.mapillary.com

GET /images?bbox={bbox}&fields=id,geometry,captured_at,sequence_id,compass_angle
GET /image_ids?sequence_id={id}
GET /{image_id}?fields=thumb_2048_url    → download frame image
```

- Auth: `access_token` header — `MLY|27520911074165230|3e2e68fa4d698f850a61649b7335f2df`
- Rate limit: 50k req/day (sufficient for hackathon corridor)

### TwelveLabs via AWS Bedrock (process stage)

```python
# Step 1: upload frame to S3 workshop bucket
s3.upload_file(local_path, "twelvelabs-bedrock-workshop-workshopbucket-f4zu1jcvakku", s3_key)

# Step 2: Marengo 3.0 — generate embedding
bedrock.invoke_model(
    modelId="twelvelabs.marengo-retrieval-2-7@v1",
    body={"inputType": "IMAGE", "inputS3Uri": s3_uri}
)  # → float[1024]

# Step 3: Pegasus 1.2 — structured description
bedrock.invoke_model(
    modelId="twelvelabs.pegasus-1-2@v1",
    body={"inputType": "IMAGE", "inputS3Uri": s3_uri,
          "prompt": "Describe any business signage, name, and category visible."}
)  # → text → parse into {name, category, condition}
```

### OpenSearch Serverless (process + analyze stages)

- Endpoint: `https://ee6qftmunca9x55uvgj5.us-east-1.aoss.amazonaws.com`
- Auth: SigV4 via `boto3` credentials (no separate password)
- Index name: `geostl-embeddings`

```python
# Index a frame
client.index(index="geostl-embeddings", body={
    "embedding": [...],   # 1024-dim float array
    "lat": 37.7749, "lon": -122.4194,
    "sequence_id": "abc123", "frame_id": "frame_0042",
    "timestamp": "2024-03-15T10:23:00Z"
})

# KNN search
client.search(index="geostl-embeddings", body={
    "knn": {"embedding": {"vector": query_embedding, "k": 10}}
})
```

---

## 4. Web UI

Single-page app served by FastAPI from `serve/static/`. Plain HTML + JS — no build step.

### Layout

```
┌──────────────────────────────────────────────────────────────┐
│  HEADER: GeoSTL Video Intelligence — San Francisco           │
├─────────────────────────┬────────────────────────────────────┤
│                         │  SIDEBAR                           │
│   LEAFLET MAP           │  ┌─ Filter ──────────────────────┐ │
│                         │  │ ☑ Stale ☑ Missing ☑ Miscat.  │ │
│   • markers per type    │  └──────────────────────────────┘ │
│   • sequence paths      │                                    │
│     as GPS track lines  │  ┌─ Detection detail ────────────┐ │
│   • click marker →      │  │ Name: Blue Bottle Coffee      │ │
│     highlights sequence │  │ Type: stale  Score: 0.87      │ │
│     path on map         │  │ GERS: 123abc...               │ │
│                         │  │                               │ │
│                         │  │  ┌─────────────────────────┐  │ │
│                         │  │  │  MAPILLARY IMAGE VIEWER  │  │ │
│                         │  │  │  [actual street photo]   │  │ │
│                         │  │  │  ← frame 42 of 180 →     │  │ │
│                         │  │  └─────────────────────────┘  │ │
│                         │  │  [↗ Open in Mapillary]        │ │
│                         │  └──────────────────────────────┘ │
├─────────────────────────┴────────────────────────────────────┤
│  METRICS ROW                                                  │
│  [Precision/Recall/F1 bar] [RMSE by type] [Detections/km²]  │
└──────────────────────────────────────────────────────────────┘
```

### Marker Colors
- Red — stale (business closed/vacant)
- Orange — missing (new business with no Overture match)
- Yellow — miscategorized (Overture entry has wrong category)

### Image Viewer
- Fetches `thumb_2048_url` from Mapillary API on click — no local storage needed
- Prev/Next arrows step through adjacent frames in the same sequence
- "Open in Mapillary" deep-link to the frame on mapillary.com

---

## 5. Configuration

`config/settings.py` — single source of truth for all tuneable values:

```python
BBOX = {
    "min_lon": -122.52, "min_lat": 37.70,
    "max_lon": -122.35, "max_lat": 37.81
}

AWS_REGION = "us-east-1"
S3_WORKSHOP_BUCKET = "twelvelabs-bedrock-workshop-workshopbucket-f4zu1jcvakku"
S3_VECTOR_BUCKET = "twelvelabs-aws-vectorbucket-tkjkgf05ulh8"
OPENSEARCH_ENDPOINT = "https://ee6qftmunca9x55uvgj5.us-east-1.aoss.amazonaws.com"
OPENSEARCH_INDEX = "geostl-embeddings"

# Verify exact model IDs from Bedrock console or hackathon workshop docs
MARENGO_MODEL_ID = "twelvelabs.marengo-retrieval-2-7@v1"
PEGASUS_MODEL_ID = "twelvelabs.pegasus-1-2@v1"

MAPILLARY_ACCESS_TOKEN = ""   # loaded from .env
FRAME_SAMPLE_INTERVAL = 5     # seconds between sampled frames
POI_MATCH_RADIUS_M = 50       # meters for Overture proximity match
```

`.env` holds secrets only:
```
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_SESSION_TOKEN=...
MAPILLARY_ACCESS_TOKEN=...
```

---

## 6. Key Constraints

- **Licenses:** Code → Apache 2.0; data outputs → CDLA 2.0
- **CRS:** EPSG:4326 for all outputs; UTM for internal distance math
- **GERS IDs:** Every detection must carry a GERS match ID — required for Overture contribution
- **Metrics required:** Judges need precision/recall/F1 and RMSE numbers, not just a demo
- **Temporal advantage:** Must show accuracy comparison of video sequence vs. single-frame baseline
- **Frame sampling:** Use Marengo semantic search to find relevant moments rather than processing all frames
