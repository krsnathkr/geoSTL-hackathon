import os
from dotenv import load_dotenv

load_dotenv()

BBOX = {
    "min_lon": -122.52,
    "min_lat": 37.70,
    "max_lon": -122.35,
    "max_lat": 37.81,
}

AWS_REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
S3_WORKSHOP_BUCKET = "twelvelabs-bedrock-workshop-workshopbucket-f4zu1jcvakku"
S3_VECTOR_BUCKET = "twelvelabs-aws-vectorbucket-tkjkgf05ulh8"
OPENSEARCH_ENDPOINT = "https://ee6qftmunca9x55uvgj5.us-east-1.aoss.amazonaws.com"
OPENSEARCH_INDEX = "geostl-embeddings"

# Verify these from workshop notebook if calls fail
MARENGO_MODEL_ID = "twelvelabs.marengo-embed-2-7-v1:0"
PEGASUS_MODEL_ID = "twelvelabs.pegasus-1-2-v1:0"

MAPILLARY_ACCESS_TOKEN = os.getenv("MAPILLARY_ACCESS_TOKEN", "")
MAPILLARY_API_BASE = "https://graph.mapillary.com"

FRAME_SAMPLE_INTERVAL = 5   # seconds between sampled frames
POI_MATCH_RADIUS_M = 50     # meters for Overture proximity match
UTM_CRS = "EPSG:32610"      # UTM zone 10N for San Francisco
WGS84_CRS = "EPSG:4326"

OVERTURE_RELEASE = "2026-04-15.0"
OVERTURE_S3_BASE = f"s3://overturemaps-us-east-1/release/{OVERTURE_RELEASE}"

DATA_RAW = "data/raw"
DATA_PROCESSED = "data/processed"
DATA_OUTPUT = "data/output"
