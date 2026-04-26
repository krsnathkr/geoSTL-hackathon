# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a 24-hour hackathon project for the **GeoSTL + TwelveLabs Geospatial Video Intelligence Hackathon** (April 25–26, 2026). The challenge uses TwelveLabs video AI models (via AWS Bedrock) to automate geospatial map validation against [Overture Maps Foundation](https://overturemaps.org/) data.

**Platform:** TwelveLabs via AWS Bedrock  
**Models:** Pegasus 1.2 (video-to-text generation) — Marengo was intentionally not used; see design decision below.  
**Licenses:** Apache 2.0 (code), CDLA 2.0 (data outputs)

## Challenge Track

**Track 01 — Validating the World's Base Layer.** Pick one workflow:

1. **Commercial Corridor Freshness Audit** — validate Overture Places POIs against street-level video; output typed GeoJSON discrepancies (stale/missing/miscategorized) with GERS match IDs and confidence scores
2. **Sidewalk Infrastructure Inventory** — detect sidewalk presence, width, condition, and curb ramp status from 360° sequences; output GeoParquet conforming to Overture's transportation schema extension
3. **Feature Georegistration Benchmarking** — geolocate point features via multi-frame triangulation, compute RMSE and CE90 against OSM/Overture, produce FGDC NSSDA-conforming accuracy report

## TwelveLabs Integration Pattern

**Pegasus 1.2** (structured descriptions):
1. Extract 5–10s clip of detected feature → send to Pegasus → parse response into structured attributes → attach to geospatial feature output

**Why Marengo is not used:**
Mapillary sequences are very short — 10–12 seconds at most. Marengo's semantic search and temporal indexing add value on long continuous footage where you need to find relevant moments across many minutes of video. For clips this short, Marengo provides no meaningful advantage. Skipping it also removes a full indexing round-trip, which meaningfully improves pipeline throughput. The decision was made deliberately — not because of any technical limitation.

## Key Technical Constraints

- **CRS:** All outputs in EPSG:4326 (WGS84). Use UTM projections for internal distance calculations.
- **GERS matching:** Match Overture features by proximity (< 50m for POIs, IoU > 0.3 for buildings) + fuzzy name matching. Always tag GERS IDs in output or detections can't contribute to the open data ecosystem.
- **Georeferencing:** Use natively georeferenced data (Mapillary, OpenAerialMap) to avoid hours lost on manual georeferencing. All outputs must include GPS coordinates.
- **Video sampling:** 30fps × 30min = 54,000 frames — use keyframe/scene-change extraction or fixed-interval sampling (1 frame per 2–5s). Pegasus processes the sampled clips directly; no separate indexing step is needed.
- **Quantitative evaluation required:** Precision, recall, F1 per feature type; geospatial RMSE. Judges require metrics, not just demos.
- **Temporal advantage:** Must demonstrate measurable accuracy gain from video sequences vs. single-frame still-image baselines.

## Suggested Data Sources

| Dataset | Use |
|---------|-----|
| Mapillary (CC BY-SA) | Street-level sequences with native GPS — best starting point |
| OpenAerialMap (CC BY 4.0) | Aerial/drone imagery with native georeferencing |
| Overture Maps (CDLA 2.0) | Reference layer: Places (64M POIs), buildings, transportation |
| OSM via Overpass API (ODbL) | Cross-reference for positional accuracy |

## Required Deliverables

- Deployed application: video input → processing → map output with confidence indicators
- GeoJSON export minimum (GeoParquet preferred for transportation schema)
- Demo video (3–5 min)
- Architecture diagram + TwelveLabs integration writeup
- Validation report with precision/recall/F1 and RMSE metrics vs. baseline
- One-page mission impact brief quantifying operational value

## Judging Weights

| Weight | Criteria |
|--------|----------|
| 30% | Detection accuracy (F1, RMSE < 10m buildings / < 5m linear) |
| 20% | Data quality & enrichment (net new features, GERS match rate) |
| 15% | Temporal reasoning (change detection, condition classification) |
| 15% | Technical implementation (video vs. still-frame advantage, throughput) |
| 10% | Output quality (GeoJSON/GeoParquet, GERS IDs, confidence scores, map viz) |
| 10% | Mission alignment & open data contribution plan |
