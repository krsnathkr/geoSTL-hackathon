# TwelveLabs

## GEOSPATIAL VIDEO INTELLIGENCE HACKATHON
St. Louis April 25-26, 2026

### CHALLENGE TRACK 01
# Geospatial Al for Automated Mapping
## Validating the World's Base Layer

**TRACK SPONSOR**
Overture Maps Foundation

| FORMAT | PLATFORM | MODELS |
| :--- | :--- | :--- |
| 24-hour team build | TwelveLabs via AWS Bedrock | Marengo 3.0. Pegasus 1.2 |

All technical solutions and derived data from this track must be released as open data or open IP.
Software license: Apache 2.0. Data license: CDLA 2.0. Overture's open map data will serve as the reference layer for validation.

TWELVELABS UNDERSTAND EVERY MOMENT
LUMA.COM/9FQSLQQ9

---

### CHALLENGE TRACK 01 OVERVIEW
## Validating the World's Base Layer

**TRACK OVERVIEW**

### Why this matters
Open map data powers humanitarian response, urban planning, and emergency services worldwide. Yet data freshness remains a systemic problem. Overture Maps Foundation's Places dataset contains over 64 million Points of Interest. There is no scalable mechanism to verify whether listed businesses are still operating, whether names and categories are current, or whether new businesses have opened nearby.

Overture's transportation theme has acknowledged coverage gaps in pedestrian infrastructure - sidewalk presence, width, condition, and ADA compliance remain largely unmapped at global scale. Meanwhile, billions of geotagged street-level images already exist in open repositories. Mapillary alone hosts over 2 billion CC BY-SA photos across 190+ countries with GPS tracks tying every frame to a precise location. OpenAerial Map provides openly licensed drone and satellite imagery with native georeferencing. The data to validate and enrich open maps already exists. What is missing is the automated pipeline to process it at machine speed.

### WHY VIDEO INSTEAD OF STATIC IMAGES?
A single photo shows equipment near a bridge. A video sequence shows equipment actively operating on the bridge deck with traffic rerouted. The temporal context confirms the bridge is under construction, not simply adjacent to a work site. That disambiguation is the core value proposition of video foundation models for map validation.

**1-2-50-100**
**VIDEOS PER DAY, PER ANALYST**
The Army Geospatial Center manually reviews aerial imagery to mark "not intact" infrastructure for Soldier safety warnings. Automated video understanding could move one analyst from 1-2 videos per day to 50-100, directly accelerating how fast critical warnings reach deployed forces.

**2B+**
**OPEN STREET-LEVEL IMAGES**
Mapillary hosts 2B+ CC BY-SA photos across 190+ countries with GPS tracks. Overture ships over 64M POls and 2.3B buildings. The reference data and the raw video are both already open the bottleneck is the pipeline.

---

### CHALLENGE TRACK 01 THE CHALLENGE
## What you'll build

**YOUR MISSION**
### Core capabilities
Build automated map validation and enrichment pipelines that process street-level and aerial video against Overture Maps data. Your system should detect discrepancies, surface missing features, and produce open data contributions that flow back into the Overture ecosystem.

**2.1**
**Automated QA for Open Spatial Data**
Build video-powered validation systems that detect map errors, data breakage, and discrepancies in open geospatial datasets. Using Overture Maps Foundation's open map data as the authoritative reference layer, identify and surface mismatches between video-derived observations and existing base layers at machine speed, across the coverage gaps and stale records that manual review would take weeks to catch.

**2.2**
**Spatial Data Enrichment using GeoAl**
Automate enrichment of open geospatial data using street-level and low-altitude aerial video to extract feature attributes at scale. Overture has two priority focus areas: (A) business validation and enrichment - detect and extract business signage, names, and branding from video to validate and enrich Overture's Places data; (B) pedestrian infrastructure mapping - detect sidewalk presence, width, and condition to build out Overture's pedestrian network layer. Benchmark video-based extraction accuracy against still-imagery baselines to quantify the value of temporal context.

**2.3**
**Multimodal Positional Accuracy Assessment**
Automatically identify and geolocate map features from street-level video. Cross-reference against OpenStreetMap and Overture Maps data to generate positional accuracy assessments using standard metrics: RMSE and CE90.

---

### CHALLENGE TRACK 01 TARGET WORKFLOWS
## Pick one. Ship it.

### 01 Commercial Corridor Freshness Audit

**SCENARIO**
A municipal GIS team validates whether Overture Places data reflects ground truth along a 3 km commercial corridor.

**SYSTEM PROCESSING**
* **INPUT** Geotagged street-level video (Mapillary sequences or dashcam with GPS).
* Cross-reference Overture's Places dataset against video observations
* Flag stale records: businesses showing closed/vacant storefronts (boarded windows, "for lease" signage)
* Identify missing places: new businesses visible in video with no Overture match within 50m
* Detect category mismatches: Overture entry exists but video shows different use
* Resolve ambiguities: cases where temporal context clarifies what single frames cannot
* **OUTPUT** GeoJSON feature collection with each discrepancy typed (stale / missing/miscategorized / ambiguous), GERS match ID, confidence score, and linked video evidence for human review.

### 02 Sidewalk Infrastructure Inventory

**SCENARIO**
A city accessibility office builds a complete pedestrian infrastructure inventory for ADA transition plan compliance.

**SYSTEM PROCESSING**
* **INPUT** Mapillary 360° sequences (e.g., GoPro MAX2 from the OSM US / Mapillary Camera Grant Program).
* Extract sidewalk presence / absence per street side
* Cross-reference against Overture transportation edges to identify pedestrian layer gaps
* Estimate width (narrow < 1.2m / standard 1.2-1.8m/wide>1.8m)
* Assess surface condition (good/fair/poor/ impassable)
* Identify curb ramp status (compliant / non-compliant / missing) at intersections
* Benchmark video-sequence extraction against single-frame baselines to quantify accuracy gains
* **OUTPUT** GeoParquet conforming to Overture's transportation schema extension, with width, condition, curb ramp status, and video evidence links per segment. Include precision / recall / F1 comparison of video-sequence vs. single-frame detection on identical street segments.

---

### 03 Feature Georegistration Benchmarking

**SCENARIO**
An analyst quantifies positional accuracy of map features derived from street-level video against authoritative references.

**SYSTEM PROCESSING**
* **INPUT** Geotagged Mapillary sequences with structure-from-motion processing.
* Detect well-defined point features (fire hydrants, utility poles, traffic signals, bus stops)
* Compute 3D positions via multi-frame triangulation
* Cross-reference against OSM (Overpass API) and Overture (GERS spatial join)
* Calculate per-feature positional error: horizontal distance to reference coordinates
* Aggregate as RMSE and CE90 per feature class using ASPRS Edition 2 methodology. Detect systematic bias: consistent directional offsets with vector error plots
* **OUTPUT** FGDC NSSDA-conforming accuracy report with per-class RMSE / CE90 tables, error histograms, spatial vector maps, and summary benchmarked against standard thresholds (< 10m for buildings, < 5m for linear features).

---

### CHALLENGE TRACK 01 DATA
## Suggested datasets

**SOURCE DATA**
### What to work with
All recommended datasets are openly licensed and compatible with the track's Apache 2.0 / CDLA 2.0 IP requirements. Use natively georeferenced data wherever possible to avoid spending hackathon time on manual georeferencing. For a 24-hour hackathon, start with Mapillary for street-level validation or OpenAerialMap for aerial mapping. Both provide native georeferencing, which eliminates the single largest time sink in video-to-map pipelines.

**REFERENCE**
### Dataset reference

| DATASET | LICENSE | FORMAT | GEOREF | TYPE | BEST FOR |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Mapillary | CC BY-SA | JPEG seq + GPS tracks, vector API | Yes (GPS) | Street-level | POI validation, signage, sidewalks |
| OpenAerialMap | CC BY 4.0/ ODbL | GeoTIFF, COG, TMS tiles (STAC API) | Yes (native) | Aerial / Drone | Building footprints, road geometry |
| Mapillary Vistas | CC BY-NC-SA | JPEG + semantic labels (124 classes) | No | Street-level | Pre-labeled training data for CV |
| xView2 | CC BY-NC-SA 4.0 | GeoTIFF pairs (pre/post disaster) | Yes (native) | Satellite | Damage assessment, change detection |
| SpaceNet | CC BY-SA 4.0 | GeoTIFF + GeoJSON labels | Yes (native) | Satellite | Building/road extraction w/ labels |
| Overture Maps | CDLA 2.0 | GeoParquet via DuckDB / Athena / STAC | Yes (native) | Vector | Reference: Places, buildings, roads |
| OpenStreetMap | ODBL | PBF/XML via Overpass API | Yes (native) | Vector | Reference: all feature types |
| USGS 3DEP LIDAR | Public Domain | LAZ point clouds, COG DEMS | Yes (native) | Elevation | Terrain, bridge clearance |
| Sentinel-2 L2A | CC BY-SA 3.0 IGO | COG via STAC (Element 84) | Yes (native) | Satellite | Temporal land-use change |

---

### CHALLENGE TRACK 01 JUDGING
## HOW YOU'LL BE JUDGED

### Scoring rubric
Your project will be evaluated against the criteria below. Weights sum to 100%.

**Evaluation criteria**

| Weight | Criteria |
| :--- | :--- |
| **30%** | **Detection Accuracy:** Precision, Recall, F1 by feature type; geospatial RMSE (<10m buildings, < 5m linear); false positive rate per km² |
| **20%** | **Data Quality & Enrichment:** Net new features contributed to Overture / OSM; attribute completeness (name, category, hours); GERS ID match rate |
| **15%** | **Temporal Reasoning:** Change detection accuracy (pre/post); condition classification; evidence quality (video clips linked to detections) |
| **15%** | **Technical Implementation:** Video vs. still-frame advantage demonstrated; Marengo / Pegasus integration depth; throughput (frames/sec, km²/hour) |
| **10%** | **Output Quality & Usability:** GeoJSON/GeoParquet exports; GERS ID tagging; confidence scores; map viz; human-in-the-loop review |
| **10%** | **Mission Alignment & Contribution:** Operational relevance to Overture POI / pedestrian data; open data contribution plan; scalability |

---

### CHALLENGE TRACK 01
## SUBMISSION
### What to turn in

**Working System** (REQUIRED)
* Deployed application that processes video and outputs geospatial features
* Map visualization showing detected features with confidence indicators
* Export results in standard geospatial formats (GeoJSON minimum)
* Demo video (3-5 min): video input → processing → map output with detected features
* Include at least one example of change detection or condition assessment

**Technical Documentation** (REQUIRED)
* Architecture diagram: video input → feature extraction → geospatial output
* Feature detection approach: what signals indicate buildings, roads, infrastructure
* Temporal analysis method: how you detect changes or assess conditions
* TwelveLabs integration: which APIs / models, how they're used, and why
* Coordinate system handling: how video frames are georeferenced
* GitHub repository with setup instructions and code

**Validation Report** (REQUIRED)
* Ground truth dataset: manually labeled features for accuracy assessment
* Quantitative metrics: precision, recall, F1, geospatial accuracy (RMSE)
* Qualitative analysis: where does the system excel, where does it struggle
* Comparison baseline: performance vs. manual review or simple CV approaches. Processing benchmarks: time to process, cost per km² analyzed

**Mission Impact Brief** (REQUIRED)
* One-page summary quantifying operational value for a target end-user
* Example: "Reduces infrastructure condition assessment from 14 hrs per video to 10 min automated + 30 min validation, enabling 28x faster map updates for deployed forces."
* Identify specific Army, NGA, or emergency response use cases

---

### Bonus Points
* Multi-temporal analysis to track infrastructure evolution over weeks / months
* Damage severity scoring: graduated (minor → moderate → severe → destroyed)
* Direct export to QGIS, ArcGIS, or OpenStreetMap editing tools
* Uncertainty quantification: explicit detection confidence and error bounds
* Real-time processing of video streams, not just archived footage
* MGRS output for defense applications

BONUS

---

### CHALLENGE TRACK 01 PLATFORM
## What you're working with

**TWELVELABS VIDEO FOUNDATION MODELS**
### Marengo 3.0 Pegasus 1.2 via AWS Bedrock
All participants receive AWS compute credits and developer accounts with access to TwelveLabs models through Amazon Bedrock. Bedrock provides enterprise-grade deployment with security, compliance, and scalability. Build production-ready prototypes on the same infrastructure that defense, intelligence, and industrial organizations deploy at scale.

**MARENGO 3.0**
**Multimodal embeddings**
Semantic search across visual, audio, and temporal dimensions. Find moments using natural language no manual tagging required.

**PRACTICAL PATTERN**
1.  Upload video to TwelveLabs via Bedrock
2.  Index the video with Marengo
3.  Search with natural-language queries
4.  Extract timestamped results
5.  Map timestamps to GPS / metadata

**PEGASUS 1.2**
**Video-to-text generation**
Generate structured descriptions, condition assessments, and natural-language summaries of video segments for reports and downstream automation.

**PRACTICAL PATTERN**
1.  Extract a 5-10s clip of the detected feature
2.  Send to Pegasus for description generation
3.  Parse into structured attributes
4.  Attach to the output feature / finding

---

### CHALLENGE TRACK 01 BUILD NOTES
## Technical considerations

**BEFORE YOU START**
### Things that will bite you
Spend 10 minutes reading these. They encode pitfalls from prior hackathons and will save you hours on Saturday.

**Georeferencing pipeline**
Choose data with native GPS to avoid manual georeferencing, which can consume 6+ hours of your hackathon. Best: Mapillary sequences (sub-5m in urban areas). Good: OpenAerial Map GeoTIFFs. Acceptable: drone video with GPS overlay. Avoid: YouTube drone footage without georeference metadata. All outputs should use EPSG:4326 (WGS84). MGRS output earns bonus points.

**Video-to-frame sampling**
30 min of 30fps drone footage yields 54,000 frames. Use keyframe extraction (scene-change detection), fixed-interval sampling (1 frame per 2-5 sec), or overlap-aware sampling for aerial. This is where Marengo's temporal understanding pays off - search for feature moments ("business signage visible from street level") and process only those segments.

**TwelveLabs API integration**
Marengo 3.0 for semantic search and temporal understanding: upload index → search by natural language → extract timestamps → map to GPS. Pegasus 1.2 for video-to-text: extract a 5-10s clip of the detected feature → describe → parse into structured attributes (name, category, condition) → attach to the geospatial feature output.

**CRS and GERS matching**
All outputs in EPSG:4326. Project to UTM for distance calculations. GERS provides stable IDs for cross-referencing - match by proximity (< 50m for POIs, loU > 0.3 for buildings), augment with fuzzy name matching. Report your match rate and which Overture release you validated against (=20% ID churn between releases).

### COMMON PITFALLS
**Avoid these**
* Overscoping: attempting all three workflows in 24 hours. Pick one and execute it well.
* Georeferencing time sink: 12+ hours manually georeferencing YouTube drone footage. Use Mapillary or OpenAerialMap.
* No quantitative evaluation: producing a demo with no precision / recall numbers. You need metrics.
* Ignoring temporal advantage: not comparing video-based detection against still-frame baselines.
* Missing GERS ID tagging: if detections can't be cross-referenced to Overture, they don't contribute to the open data ecosystem.
* Forgetting open licensing: code and data outputs must use Apache 2.0 and CDLA 2.0 respectively.
