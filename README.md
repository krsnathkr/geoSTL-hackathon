# geoSTL-hackathon

I built this GeoSTL hackathon project for street-level sidewalk infrastructure inventory using Mapillary imagery, Overture Maps data, AWS Bedrock-hosted TwelveLabs models, and a FastAPI review dashboard.

My current implemented workflow is centered on `02 - Sidewalk Infrastructure Inventory`: I ingest street imagery and map data, generate structured sidewalk observations from short video clips, convert those observations into geospatial findings, and serve the results in a browser-based review UI.

## Technical Documentation

### Problem statement

I am trying to answer a practical question: how much sidewalk-related information can I recover from street-level video, and how does a short multi-frame video clip compare with a single-frame baseline for detecting sidewalk presence, curb ramps, obstructions, hazards, and related pedestrian-accessibility issues?

### End-to-end architecture

```text
+---------------------------+    +----------------------------+    +-------------------------------+
| INPUT SOURCES             |    | INGEST                     |    | DESCRIBE                      |
+---------------------------+    | ingest/mapillary.py        |    | process/pegasus.py            |
| Mapillary Graph API       | -> | ingest/overture.py         | -> +-------------------------------+
| Street-level JPEGs with   |    +----------------------------+    | Frames → ffmpeg → MP4 clip    |
| native GPS coordinates.   |    | Fetch Mapillary sequences  |    | S3 upload → Bedrock Pegasus   |
|                           |    | and download sampled       |    | Returns structured JSON per   |
| Overture Maps via DuckDB  |    | frames. Pull Overture      |    | clip: sidewalk_presence,      |
| (S3): transportation      |    | places and transport       |    | condition, width_m,           |
| segments and POIs for     |    | segments from S3 via       |    | curb_ramp_status, hazards,    |
| GERS context.             |    | DuckDB.                    |    | obstructions, surface, etc.   |
|                           |    |                            |    |                               |
| Optional: YouTube streams |    | → data/raw/                |    | Baseline path: same flow      |
| via yt-dlp for recurring  |    |   images/ sequences.json   |    | with one frame per clip for   |
| live monitoring.          |    |   *.parquet                |    | video-vs-still comparison.    |
+---------------------------+    +----------------------------+    |                               |
                                                                   | → data/processed/             |
                                                                   |   descriptions.json           |
                                         (↓ flow continues below)  |   baseline_descriptions.json  |
                                                                   +-------------------------------+
+---------------------------+    +----------------------------+    +-------------------------------+
| INTERMEDIATE DATA         |    | ANALYZE                    |    | SERVE / REVIEW                |
+---------------------------+    | analyze/cross_reference.py |    | serve/ (FastAPI)              |
| data/processed/           | -> | analyze/export.py          | -> +-------------------------------+
|   descriptions.json       |    | analyze/metrics.py         |    | Interactive map of all        |
|   baseline_descriptions   |    +----------------------------+    | detections and sequences.     |
|   .json                   |    | Obs → finding types:       |    | Baseline vs video tab.        |
|                           |    | sidewalk_missing, blocked_ |    | Metrics: F1, RMSE,            |
| data/raw/*.parquet        |    | path, narrow_sidewalk,     |    | temporal advantage.           |
| Overture segments used    |    | poor_condition, ADA non-   |    | Human review + sign-off.      |
| for spatial join.         |    | compliant_ramp, and more.  |    | Follow-up video upload.       |
|                           |    | Spatial join to nearest    |    | Optional live camera feed.    |
| Staged artifacts allow    |    | Overture transport seg.    |    |                               |
| any stage to rerun        |    | Compute confidence scores, |    | → data/output/                |
| without repeating earlier |    | GeoJSON/Parquet exports,   |    |   detections.geojson          |
| expensive API calls.      |    | F1/RMSE/temporal metrics.  |    |   metrics.json                |
+---------------------------+    +----------------------------+    +-------------------------------+
```

### Pipeline stages

My main orchestrator is [`run_pipeline.py`](run_pipeline.py), which exposes four explicit stages:

| Stage | Primary module(s) | What it does | Main artifacts |
| --- | --- | --- | --- |
| `ingest` | `ingest/mapillary.py`, `ingest/overture.py` | Pulls Mapillary imagery and Overture geospatial data into local storage | `data/raw/*` |
| `describe` | `process/pegasus.py` | Converts sampled frame sets into MP4 clips and asks Pegasus for structured sidewalk observations | `data/processed/descriptions.json`, `data/processed/baseline_descriptions.json` |
| `analyze` | `analyze/cross_reference.py`, `analyze/export.py`, `analyze/metrics.py` | Classifies findings, links them to nearby transportation segments when available, exports geospatial outputs, and computes comparison metrics | `data/output/*` |

I serve the output viewer through a FastAPI app in [`serve/main.py`](serve/main.py) with static frontend assets in [`serve/static/`](serve/static/).

## How Pegasus is used

### Pegasus

Pegasus is the critical model for my current sidewalk inventory outputs. I use it in [`process/pegasus.py`](process/pegasus.py).

Current implemented uses:

- Short multi-frame clip understanding for the main `descriptions.json` path.
- Single-frame duplicated clip understanding for the `baseline_descriptions.json` comparison path.

Why Pegasus is the right fit here:

- The task is not just object recognition. It needs structured interpretation of sidewalk presence, width, curb ramp compliance, obstructions, hazards, crossing features, and condition.
- Many sidewalk cues are temporal or viewpoint-dependent. A short clip can reveal context that a single still frame misses.
- The project explicitly compares video-derived detections with a still-frame baseline through `metrics.json` so the value of temporal context can be measured rather than assumed.

Important implementation detail:

- Pegasus accepts `VIDEO`, not still images. The code therefore stitches sampled JPEGs into MP4 clips with `ffmpeg`, uploads the clip to S3, and invokes Pegasus through Bedrock streaming responses.
- The baseline path still goes through Pegasus, but with `max_frames_per_clip=1`, `duplicate_single_frame=True`, and a longer effective frame duration so Bedrock accepts the clip as a valid video.

## Repository and setup instructions

### Repository structure

| Path | Purpose |
| --- | --- |
| `config/` | Central settings, bbox defaults, model IDs, output paths |
| `ingest/` | Mapillary and Overture ingestion |
| `process/` | TwelveLabs/Bedrock model calls, clip generation, and live camera support |
| `analyze/` | Observation classification, geospatial matching, metrics, exports |
| `serve/` | FastAPI app, API routes, and static dashboard |
| `tests/` | Unit and API tests |
| `run_pipeline.py` | Main CLI entrypoint for staged pipeline execution |
| `docs/` | Troubleshooting and project notes |

### Prerequisites

Tested workflow assumptions in this repository:

- Python 3.12
- `ffmpeg` installed and available on `PATH`
- `yt-dlp` installed and available on `PATH` for the optional live-camera flow
- AWS credentials with access to:
  - Bedrock Runtime
  - the configured S3 bucket used for clip/frame uploads
- A valid Mapillary access token

### Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

If you are on macOS and do not already have system tools installed:

```bash
brew install ffmpeg yt-dlp
```

### Getting the data snapshot

The pipeline artifacts are too large for GitHub and are hosted on Google Drive. Two archives are available — pick based on how deep you want to go:

| Archive | Size | What it enables |
| --- | --- | --- |
| [`geoSTL-data-artifacts.zip`](https://drive.google.com/file/d/1cxNSSrYIBFn4wDafd7_aJ2sW1y3J2sw0/view?usp=sharing) | ~4.1 MB | Run the dashboard, inspect all findings, re-run the `analyze` stage |
| `geoSTL-data-images.zip` | ~23 GB | Re-run the `describe` stage (Pegasus video processing) from the original frames |

> **Note on the full image archive:** The raw Mapillary frame dataset is approximately 23 GB. Uploading it to a file host within the hackathon window was not feasible — a full upload would have taken over 2 hours on the available connection. The images are not included in a hosted archive. If you need to work with the raw frames, use **Option C** below to regenerate them directly from the Mapillary API in 20–40 minutes. The pipeline is fully reproducible from that starting point.

---

#### Option A — Dashboard only (recommended for most users)

Downloads in seconds. No API keys needed.

```bash
# 1. Download geoSTL-data-artifacts.zip from the link above, then:
unzip -o geoSTL-data-artifacts.zip

# 2. Launch the dashboard
./.venv/bin/python -m uvicorn serve.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`.

---

#### Option B — Full dataset with raw Mapillary frames

Download both archives and extract them in order. Requires ~22 GB of free disk space.

```bash
# 1. Artifacts (metadata, descriptions, output files)
unzip -o geoSTL-data-artifacts.zip

# 2. Raw images — download geoSTL-data-images.zip from the link above, then:
unzip -o geoSTL-data-images.zip
```

After extracting both, the complete directory layout is:

```
data/
├── raw/
│   ├── mapillary_sequences.json          # Ordered sequence + frame metadata (11 MB)
│   ├── overture_places.parquet           # Overture Places snapshot, SF bbox (952 KB)
│   ├── overture_transport.parquet        # Overture transportation segments, SF bbox (592 KB)
│   └── images/
│       └── <sequence_id>/                # 1,059 Mapillary sequences
│           └── <frame_id>.jpg            # 13,741 JPEG frames total (~22 GB)
├── processed/
│   ├── descriptions.json                 # Pegasus multi-frame sidewalk observations (508 KB)
│   └── baseline_descriptions.json        # Single-frame baseline observations (804 KB)
└── output/
    ├── detections.geojson                # Dashboard-ready sidewalk findings (432 KB)
    ├── detections.geoparquet             # Geospatial export (84 KB)
    ├── baseline_detections.geojson       # Baseline findings for comparison (580 KB)
    ├── baseline_detections.geoparquet    # Baseline geospatial export (80 KB)
    ├── metrics.json                      # Precision/recall/F1, RMSE, temporal advantage metrics
    ├── event_reviews.json                # Human review annotations
    └── event_followups.json              # Follow-up video analysis results
```

With the full dataset, you can re-run any pipeline stage:

```bash
# Re-run just the analyze stage (no images needed)
./.venv/bin/python run_pipeline.py --from-stage analyze --to-stage analyze

# Re-run from Pegasus video processing (requires images + AWS credentials)
./.venv/bin/python run_pipeline.py --from-stage describe --to-stage analyze
```

---

#### Option C — Regenerate everything from scratch

Skip both downloads and run the full pipeline yourself (requires Mapillary and AWS credentials — see [Environment variables](#environment-variables) below):

```bash
./.venv/bin/python run_pipeline.py --from-stage ingest --to-stage analyze --max-images 200 --sample-every-n 5
```

Takes 20–40 minutes depending on network speed and Bedrock throughput.

### Environment variables

Create a local `.env` file with the variables the code reads from [`config/settings.py`](config/settings.py):

```bash
MAPILLARY_ACCESS_TOKEN=...
AWS_DEFAULT_REGION=us-east-1
AWS_ACCOUNT_ID=...

# Optional bbox override
BBOX_MIN_LON=-122.425
BBOX_MIN_LAT=37.755
BBOX_MAX_LON=-122.395
BBOX_MAX_LAT=37.780

# Optional model override
PEGASUS_MODEL_ID=us.twelvelabs.pegasus-1-2-v1:0

# Optional clip tuning
CLIP_OUTPUT_FPS=30
CLIP_FRAME_DURATION_SEC=1.0
```

Notes:

- If `PEGASUS_MODEL_ID` is omitted, the repo derives the Bedrock inference-profile ID from the active AWS region.
- `AWS_ACCOUNT_ID` is used to populate `bucketOwner` in the Bedrock S3 payload, which matters for Bedrock-hosted TwelveLabs requests in this repo.

### Main pipeline commands

Run the full pipeline:

```bash
./.venv/bin/python run_pipeline.py --from-stage ingest --to-stage analyze --max-images 200 --sample-every-n 5
```

Useful variations:

```bash
./.venv/bin/python run_pipeline.py --from-stage analyze --to-stage analyze
./.venv/bin/python run_pipeline.py --from-stage ingest --to-stage ingest --skip-download-frames
./.venv/bin/python run_pipeline.py --from-stage ingest --to-stage analyze --skip-transportation
./.venv/bin/python run_pipeline.py --from-stage ingest --to-stage ingest --redownload-frames
./.venv/bin/python run_pipeline.py --from-stage ingest --to-stage analyze --skip-transportation --redownload-frames --sample-every-n 1
```

Run the dashboard:

```bash
./.venv/bin/python -m uvicorn serve.main:app --host 127.0.0.1 --port 8000
```

Then open `http://127.0.0.1:8000`.

### Tests

Run the local tests with the repo virtualenv:

```bash
./.venv/bin/python -m pytest -q
```

Current local verification on April 26, 2026:

- `79 passed`
- `1 failed`

The failing test is `tests/test_process_pegasus.py::test_parse_missing_fields_uses_defaults`, which still expects the older default category `"other"` even though the current parser defaults to `"sidewalk"`.

### About `package.json`

This repository contains a `package.json`, but my implemented pipeline, API, and dashboard flow are Python-first. You do not need Node.js to run the main ingest -> analyze -> serve workflow described above.

## Dataset documentation

### Input datasets

| Dataset | Source | Role in pipeline | Local artifact(s) |
| --- | --- | --- | --- |
| Mapillary street imagery | Mapillary Graph API | Primary street-level visual input; grouped into sequences and downloaded as frame JPEGs | `data/raw/mapillary_sequences.json`, `data/raw/images/...` |
| Overture Places | Overture Maps S3 release | Contextual place inventory; currently ingested and stored, but not the main matching source for the sidewalk export path | `data/raw/overture_places.parquet` |
| Overture Transportation | Overture Maps S3 release | Nearest-segment spatial context for sidewalk observations during `analyze` | `data/raw/overture_transport.parquet` |
| Optional live camera streams | YouTube stream URLs | Demonstration of recurring capture -> Pegasus analysis for live monitoring | `data/output/live_cameras.json` plus temporary MP4 clips |

### Geographic scope

The default configured bbox in [`config/settings.py`](config/settings.py) is a San Francisco area window:

- `min_lon = -122.425`
- `min_lat = 37.755`
- `max_lon = -122.395`
- `max_lat = 37.780`

This can be overridden through environment variables, which means results are only reproducible if the same bbox is used.

### Checked-in data snapshot vs runtime paths

The default runtime paths are:

- `data/raw`
- `data/processed`
- `data/output`

This repository also includes a checked-in `data/boulder/raw/` snapshot that can be useful as an example artifact set, but my orchestrated pipeline uses the `data/raw`, `data/processed`, and `data/output` directories unless I explicitly change code or settings.

## Preprocessing and transformation details

### 1. Mapillary preprocessing

Implemented in [`ingest/mapillary.py`](ingest/mapillary.py):

- Queries the configured bbox in tiles instead of one oversized request.
- Recursively subdivides tiles when repeated Mapillary failures occur.
- Retrieves image fields including `sequence`, timestamp, geometry, bearing, and multiple image URL sizes.
- Groups flat image responses into ordered per-sequence records.
- Prefers `thumb_original_url` for downloads, with fallbacks to `thumb_2048_url` and `thumb_1024_url`.
- Supports sparse sampling through `sample_every_n`.
- Supports cache replacement through `--redownload-frames`.

Why this matters:

- Large-city Mapillary queries are fragile if sent as a single bbox.
- Full-resolution imagery improves Pegasus output quality.
- Sparse frame sampling is a major tradeoff between runtime and detection quality.

### 2. Overture preprocessing

Implemented in [`ingest/overture.py`](ingest/overture.py):

- Reads current Overture release parquet directly from S3 through DuckDB.
- Loads both `places` and `transportation/segment` themes.
- Filters rows to the configured bbox before local export.
- Converts returned geometry values into GeoPandas-compatible shapes, handling multiple raw geometry encodings.

Why this matters:

- Transportation segments are the spatial reference layer used in the current `analyze` stage.
- The repo keeps the Overture release pinned in configuration so runs are less likely to silently drift when Overture publishes a new release.

### 3. Pegasus clip preprocessing

Implemented in [`process/pegasus.py`](process/pegasus.py):

- Samples each Mapillary sequence down to a bounded frame set.
- Converts JPEG sequences into MP4 clips with `ffmpeg`.
- Scales clips to a maximum width of 1280 pixels for Bedrock compatibility.
- Uploads clips to S3.
- Sends a structured prompt to Pegasus asking for sidewalk-inventory JSON only.
- Parses streamed model output back into normalized Python dictionaries.

The structured schema includes fields such as:

- `sidewalk_presence`
- `condition`
- `sidewalk_width_m`
- `width_category`
- `curb_ramp_status`
- `surface_material`
- `surface_defects`
- `obstructions`
- `hazards`
- `crossing_features`
- `lighting`
- `description`

### 4. Baseline generation

Also implemented in [`process/pegasus.py`](process/pegasus.py) via `process_all_sequences(...)`:

- Runs a second describe pass with one frame per sequence.
- Duplicates that frame into a minimally valid short video.
- Saves results separately as `baseline_descriptions.json`.

Why this matters:

- The project is explicitly measuring whether multi-frame temporal context improves detection coverage and confidence.

### 5. Spatial analysis and finding generation

Implemented in [`analyze/cross_reference.py`](analyze/cross_reference.py):

- Converts Pegasus observation records into point geometries.
- Optionally joins each observation to the nearest Overture transportation segment.
- Converts model outputs into operational finding types such as:
  - `sidewalk_missing`
  - `curb_ramp_missing`
  - `ada_noncompliant_ramp`
  - `poor_condition`
  - `blocked_path`
  - `narrow_sidewalk`
  - `surface_defect`
  - `poor_lighting`
- Assigns a confidence proxy based on observation completeness.

### 6. Export and metrics

Implemented in [`analyze/export.py`](analyze/export.py) and [`analyze/metrics.py`](analyze/metrics.py):

- Exports detections to GeoJSON for the dashboard.
- Exports detections to GeoParquet for downstream geospatial use.
- Exports baseline detections separately for comparison.
- Writes `metrics.json` with:
  - per-type precision/recall/F1 proxies
  - RMSE proxy from transport matching distance
  - density metrics
  - total detection counts
  - temporal advantage metrics comparing video vs baseline

## Output artifacts

### Raw artifacts

| Path | Description |
| --- | --- |
| `data/raw/mapillary_sequences.json` | Ordered Mapillary sequence/frame metadata |
| `data/raw/images/<sequence_id>/<frame_id>.jpg` | Downloaded Mapillary frames |
| `data/raw/overture_places.parquet` | Local Overture Places snapshot for the bbox |
| `data/raw/overture_transport.parquet` | Local Overture transportation snapshot for the bbox |

### Processed artifacts

| Path | Description |
| --- | --- |
| `data/processed/descriptions.json` | Main Pegasus multi-frame observations |
| `data/processed/baseline_descriptions.json` | Single-frame baseline observations |

### Final output artifacts

| Path | Description |
| --- | --- |
| `data/output/detections.geojson` | Main dashboard-ready geospatial findings |
| `data/output/detections.geoparquet` | Main geospatial export |
| `data/output/baseline_detections.geojson` | Baseline findings for comparison |
| `data/output/baseline_detections.geoparquet` | Baseline geospatial export |
| `data/output/metrics.json` | Detection and temporal comparison metrics |
| `data/output/live_cameras.json` | Optional recurring live-camera analysis store |

## Reproducibility notes

### What is reproducible

I consider the following parts reasonably reproducible if I hold the environment steady:

- Python dependencies are pinned in [`requirements.txt`](requirements.txt).
- The Overture release is pinned in configuration as `2026-04-15.0`.
- The pipeline stages and output paths are explicit and scriptable.
- The bbox can be held constant through environment variables.
- The baseline comparison path is implemented in code, not as a manual notebook step.

### What is not fully deterministic

My repo still depends on external systems whose behavior can drift:

- Mapillary coverage changes over time.
- Overture releases change over time, even though this repo pins one release by default.
- Bedrock/TwelveLabs responses are model-generated and may vary slightly.
- AWS permissions and Bedrock availability can change independently of the codebase.

### Recommended reproducibility workflow

For a clean rerun on the same area:

1. Use the same `.env` bbox and AWS/Mapillary configuration.
2. Recreate the virtualenv and install `requirements.txt`.
3. Re-download frames if image quality matters:

```bash
./.venv/bin/python run_pipeline.py --from-stage ingest --to-stage analyze --max-images 200 --sample-every-n 1 --redownload-frames --skip-transportation
```

4. Save the produced `data/raw`, `data/processed`, and `data/output` artifacts for the exact run you want to preserve.

### Recommended fast-iteration workflow

For debugging model and export behavior without paying the full transportation-ingest cost:

```bash
./.venv/bin/python run_pipeline.py --from-stage ingest --to-stage analyze --max-images 200 --sample-every-n 5 --redownload-frames --skip-transportation
```

### Known limitations

- The current analyze/export path is sidewalk-finding oriented, not a generalized POI inventory.
- Many quality failures are caused by sparse frame coverage, not only by model quality.
- The current local test suite has one stale expectation around Pegasus default category parsing.

## Dashboard and review layer

I serve a static dashboard through the FastAPI app, and it consumes the generated artifacts through API routes in [`serve/routes/data.py`](serve/routes/data.py).

Current UI capabilities:

- Map visualization of detections and sequences
- Detection detail panel
- Metrics tab
- Video-vs-baseline comparison tab
- Human review workflow
- Follow-up video upload flow
- Optional live camera monitoring flow

This means my repository is not only a model-calling demo. It includes working pipeline code, artifact generation, and an interface for inspecting and reviewing the results.
