import os
from dotenv import load_dotenv

load_dotenv()

BBOX = {
    "min_lon": -105.285,
    "min_lat": 39.990,
    "max_lon": -105.245,
    "max_lat": 40.020,
}

AWS_REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
AWS_ACCOUNT_ID = os.getenv("AWS_ACCOUNT_ID", "")
S3_WORKSHOP_BUCKET = "twelvelabs-bedrock-workshop-workshopbucket-f4zu1jcvakku"
S3_VECTOR_BUCKET = "twelvelabs-aws-vectorbucket-tkjkgf05ulh8"
OPENSEARCH_ENDPOINT = "https://ee6qftmunca9x55uvgj5.us-east-1.aoss.amazonaws.com"
OPENSEARCH_INDEX = "geostl-embeddings"

def _default_twelvelabs_model_id(model: str, region: str) -> str:
    """Return the Bedrock inference profile ID for the active AWS region."""
    region_prefix = region.split("-", 1)[0]
    if model == "marengo":
        return f"{region_prefix}.twelvelabs.marengo-embed-2-7-v1:0"
    if model == "pegasus":
        return f"{region_prefix}.twelvelabs.pegasus-1-2-v1:0"
    raise ValueError(f"Unsupported TwelveLabs model: {model}")


# Allow explicit env overrides, but default to the Bedrock inference profiles
# required for the current AWS region.
MARENGO_MODEL_ID = os.getenv(
    "MARENGO_MODEL_ID",
    _default_twelvelabs_model_id("marengo", AWS_REGION),
)
PEGASUS_MODEL_ID = os.getenv(
    "PEGASUS_MODEL_ID",
    _default_twelvelabs_model_id("pegasus", AWS_REGION),
)

MAPILLARY_ACCESS_TOKEN = os.getenv("MAPILLARY_ACCESS_TOKEN", "")
MAPILLARY_API_BASE = "https://graph.mapillary.com"

FRAME_SAMPLE_INTERVAL = 5   # seconds between sampled frames
POI_MATCH_RADIUS_M = 50     # meters for Overture proximity match
UTM_CRS = "EPSG:32613"      # UTM zone 13N for Colorado
WGS84_CRS = "EPSG:4326"

OVERTURE_RELEASE = "2026-04-15.0"
OVERTURE_S3_BASE = f"s3://overturemaps-us-west-2/release/{OVERTURE_RELEASE}"

DATA_RAW = "data/raw"
DATA_PROCESSED = "data/processed"
DATA_OUTPUT = "data/output"
