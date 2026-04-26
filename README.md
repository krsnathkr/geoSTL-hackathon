# geoSTL-hackathon

This is a hackathon organzied by GeoSTL and TwelveLabs.

We have to use twelve-labs API to analyze the video data and extract the geospatial information.

I will have to get the data from:

1. overture - https://docs.overturemaps.org/getting-data/
2. mapillary

## Run the pipeline

Use the local virtualenv so the Python dependencies match the tested environment.

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

## Current Status

What is working:

- Overture places ingest
- Mapillary sequence ingest
- Mapillary frame redownload with higher-resolution image preference
- Bedrock embed and Pegasus describe stages
- `analyze` exports for detections, baseline detections, and metrics
- FastAPI dashboard and data routes

What is still limited:

- OpenSearch auth still returns `401`, so vector indexing is skipped
- Overture transportation ingest is still slow for iterative debugging
- detection quality is currently limited more by sparse frame sampling than by outright pipeline failure

Best current verification run:

```bash
./.venv/bin/python run_pipeline.py --from-stage ingest --to-stage analyze --max-images 200 --sample-every-n 5 --redownload-frames --skip-transportation
```

Best next quality-focused run:

```bash
./.venv/bin/python run_pipeline.py --from-stage ingest --to-stage analyze --max-images 200 --sample-every-n 1 --redownload-frames --skip-transportation
```

## Run the dashboard

```bash
./.venv/bin/python -m uvicorn serve.main:app --host 127.0.0.1 --port 8000
```
