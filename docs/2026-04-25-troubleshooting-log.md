# Troubleshooting Log: Current Pipeline State

Date: 2026-04-25
Repository: `geoSTL-hackathon`

## Goal

This project is trying to:

1. Ingest Overture places and Mapillary street imagery.
2. Download frames from Mapillary sequences.
3. Send frames and clips through TwelveLabs models on AWS Bedrock.
4. Compare observed POIs against Overture places.
5. Export dashboard-ready outputs:
   - `data/output/detections.geojson`
   - `data/output/baseline_detections.geojson`
   - `data/output/metrics.json`

The web app depends on those generated artifacts. If they are missing, the app can load while still looking mostly empty.

## What Was Broken

The pipeline had two sets of issues.

### Ingest issues

- Overture bucket path was outdated and returned `404`.
- Overture geometry decoding did not handle the live `bytearray` shape.
- Overture transportation query still used obsolete `road` columns.
- Mapillary full-city requests were too large and triggered repeated API failures.
- Mapillary sequence grouping used `sequence_id`, but the live API now exposes `sequence`.

### Downstream issues

- The `embed` stage succeeded on Bedrock, then failed on OpenSearch with `AuthenticationException(401)`.
- Sparse `describe` results could produce an empty GeoDataFrame without the expected schema, causing `analyze/export` to crash with `KeyError: 'detection_type'`.
- Mapillary downloads used `thumb_2048_url` instead of preferring the highest available image URL.

## Fixes Applied

### Overture

Updated:

- `config/settings.py`
- `ingest/overture.py`

Changes:

- switched the Overture base bucket to `overturemaps-us-west-2`
- added geometry coercion support for `memoryview`, `bytearray`, `list`, and `tuple`
- updated transportation queries to current schema fields like `subclass`, `road_surface`, and `road_flags`

### Mapillary

Updated:

- `ingest/mapillary.py`
- `tests/test_ingest_mapillary.py`

Changes:

- tiled the bbox and added adaptive subdivision for large API queries
- grouped sequences using `sequence` when `sequence_id` is absent
- changed image downloads to prefer `thumb_original_url`
- added fallback to `thumb_2048_url` and `thumb_1024_url`
- added overwrite support so existing cached frames can be re-downloaded at higher quality

### Pipeline robustness

Updated:

- `run_pipeline.py`
- `analyze/cross_reference.py`
- `analyze/export.py`
- `tests/test_run_pipeline.py`
- `tests/test_analyze_cross_reference.py`
- `tests/test_analyze_export.py`

Changes:

- made OpenSearch indexing non-fatal so the pipeline can continue into `describe` and `analyze`
- ensured empty detection results preserve the expected export schema
- added regression tests for OpenSearch auth failure and empty detection exports

## Current Verified State

### Tests

Current test result:

- `85 passed, 1 warning`

### Dashboard/API

Currently working:

- FastAPI app loads
- dashboard frontend renders
- basemap renders
- sequence API can serve route geometry
- detections, baseline detections, and metrics can now be generated

### Pipeline

A verified successful run was:

```bash
./.venv/bin/python run_pipeline.py \
  --from-stage ingest \
  --to-stage analyze \
  --max-images 200 \
  --sample-every-n 5 \
  --redownload-frames \
  --skip-transportation
```

Observed outputs from that run:

- `40` Mapillary sequences fetched
- `133` local frames downloaded
- `59` local frames embedded
- `17` multi-frame descriptions produced
- `17` final detections exported
- `40` baseline detections exported

Generated artifacts:

- `data/output/detections.geojson`
- `data/output/detections.geoparquet`
- `data/output/baseline_detections.geojson`
- `data/output/baseline_detections.geoparquet`
- `data/output/metrics.json`

## What Improved

The pipeline now completes through `analyze` on a practical path.

Notable improvement after switching Mapillary downloads to higher-resolution image URLs:

- Pegasus was no longer limited to only `unknown` outputs
- at least one sequence produced a real business label: `ETHAN ALLEN`
- exported detections increased from the earlier small successful run to `17`

## What Is Still Wrong

### 1. OpenSearch auth is still broken

Status:

- still broken

Observed behavior:

- OpenSearch `HEAD` request returns `401`

Impact:

- vector indexing is unavailable
- semantic retrieval features depending on AOSS are still not operational

Why the rest still works:

- current `describe` and `analyze` stages do not require the vector index

### 2. Transportation ingest is still a slow bottleneck

Status:

- not verified as reliable in the full end-to-end feedback loop

Observed behavior:

- transportation ingest can run for a long time with little feedback

Impact:

- it slows repeated debugging runs
- it is reasonable to use `--skip-transportation` while validating imagery and analysis

### 3. Frame coverage is still too sparse

Status:

- main remaining quality issue

Observed behavior:

- many sequences still log `fewer than 2 downloaded frames — skipping`

Why:

- the verified run used `--sample-every-n 5`

Impact:

- many sequences never reach the multi-frame Pegasus path
- output quality remains limited even though the pipeline now runs

## Recommended Next Step

The highest-leverage next run is denser Mapillary sampling:

```bash
./.venv/bin/python run_pipeline.py \
  --from-stage ingest \
  --to-stage analyze \
  --max-images 200 \
  --sample-every-n 1 \
  --redownload-frames \
  --skip-transportation
```

That should answer the next real question:

- whether the current quality limit is mostly caused by sparse frame coverage rather than model behavior
