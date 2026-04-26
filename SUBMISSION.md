# SideSight

**Elevator Pitch:**
AI-powered sidewalk inventory using TwelveLabs Pegasus on Mapillary street-level video — detecting hazards, missing curb ramps, and ADA issues across city blocks with confidence-scored GeoJSON output.

---

## Inspiration

Municipal sidewalk surveys are slow and expensive. Field crews audit 8–12 blocks per hour — a mid-sized city can take years to complete a single pass. Mapillary already has the footage. I wanted to see how much of that manual labor could be automated away with a well-engineered AI pipeline.

---

## What It Does

**SideSight** ingests Mapillary street-level video for any city bounding box, runs it through TwelveLabs Pegasus 1.2 (via AWS Bedrock), and produces a confidence-scored map of sidewalk conditions — presence, width, curb ramp status, surface defects, obstructions, and hazards — cross-referenced against Overture Maps with GERS IDs attached.

On a demo run over 7.25 km² of San Francisco, it produced **252 detections** (mean confidence 86.59%) including 45 actionable infrastructure issues — in under 30 minutes. A field crew would take the better part of a day to cover the same ground. That's an **~85% reduction in survey time**, and the AI flags only the locations worth sending someone to.

At city scale, that translates to millions saved annually in labor costs — and a continuously updatable inventory instead of a survey that's stale the moment the crew leaves.

---

## How I Built It

Four-stage pipeline:

1. **Ingest** — Mapillary Graph API with a recursive 8×8 tile grid (handles rate limits gracefully); Overture transportation + Places data pulled from S3 via DuckDB.
2. **Clip** — JPEGs encoded to MP4 via ffmpeg. A duplicate-frame "baseline" clip is generated alongside each real clip as the single-frame control condition.
3. **Describe** — Clips uploaded to S3, submitted to Pegasus 1.2 on Bedrock. Prompt extracts 14 structured JSON fields (sidewalk width, curb ramp compliance, surface defects, etc.) from the streaming response.
4. **Analyze** — Detections spatially joined to Overture segments (GERS IDs attached), classified into 14 types, then scored: F1 per type, RMSE, and a video vs. baseline temporal advantage comparison.

FastAPI + Leaflet.js dashboard with filter controls, video playback, a human review workflow, and a metrics tab.

---

## Challenges I Ran Into

Getting Pegasus to return clean, parseable JSON every time was the hardest part — it required heavy prompt engineering with domain-specific reference scales (e.g., "a standard wheelchair is ~0.7m wide") and regex-based fallback parsing. Building valid Bedrock-compatible MP4s from sparse Mapillary JPEGs via ffmpeg also took significant tuning — early attempts were rejected by the API entirely. And with no labeled ground-truth dataset available in 24 hours, I had to design a confidence-proxy metrics framework that's honest about its limitations while still being rigorous enough to evaluate.

---

## Accomplishments I'm Proud Of

- 252 detections across 7.25 km² with F1 scores from 0.80–0.93
- Built-in video vs. single-frame baseline benchmarking — most projects skip this entirely
- GeoParquet output conforming to Overture's transportation schema, GERS IDs included, ready to feed back into the open data ecosystem
- Human review workflow built into the dashboard from day one
- 79 passing tests in a 24-hour hackathon

---

## What I Learned

Prompt engineering for structured geospatial extraction is genuinely hard — domain knowledge has to be baked into the prompt, not assumed. I also learned that Marengo wasn't the right tool here: Mapillary clips are 10–12 seconds, and Marengo's value is on long continuous footage. Switching to Pegasus-only removed an entire indexing round-trip and improved throughput with no downside.

---

## What's Next for SideSight

- Scale to full city corridors and transit routes
- Temporal change detection — diff the same area across months to catch new damage or completed repairs
- Direct export to city 311 APIs as pre-filled service requests
- Batch contribution of validated detections back to Overture Maps

---

## Built With

| Category | Technologies |
|---|---|
| **AI / Video Intelligence** | TwelveLabs Pegasus 1.2 |
| **Cloud** | AWS Bedrock, AWS S3 |
| **Backend** | Python 3.12, FastAPI, Uvicorn |
| **Geospatial** | GeoPandas, Shapely, PyProj, GeoParquet, PyArrow |
| **Data** | DuckDB, Pandas |
| **Media Processing** | ffmpeg |
| **APIs** | Mapillary Graph API, Overture Maps (S3/Parquet) |
| **Frontend** | JavaScript, HTML/CSS, Leaflet.js 1.9.4, Plotly.js |
| **Testing** | pytest, httpx |
| **AWS SDK** | boto3 |

**Devpost tags:** Python, FastAPI, AWS, AWS Bedrock, Amazon S3, JavaScript, Leaflet.js, GeoPandas, DuckDB, TwelveLabs, Mapillary, Overture Maps, GeoJSON, GeoParquet, Computer Vision, Geospatial, Accessibility
