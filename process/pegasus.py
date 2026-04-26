"""
Generate structured sidewalk-inventory descriptions from video clips via Pegasus 1.2 on Bedrock.

Pegasus accepts VIDEO only (not still images). This module:
  1. Stitches sampled JPEG frames into a short MP4 clip via ffmpeg
  2. Uploads the clip to S3
  3. Calls Pegasus via InvokeModelWithResponseStream
  4. Parses the text response into a sidewalk observation record

Output: data/processed/descriptions.json
"""

import json
import logging
import os
import re
import subprocess
import tempfile
from typing import Optional

from config.settings import (
    AWS_REGION,
    CLIP_FRAME_DURATION_SEC,
    CLIP_OUTPUT_FPS,
    DATA_PROCESSED,
    FRAME_SAMPLE_INTERVAL,
    PEGASUS_MODEL_ID,
    S3_WORKSHOP_BUCKET,
)
from process.twelvelabs import get_bedrock_client, upload_to_s3, _s3_location

logger = logging.getLogger(__name__)

DEFAULT_PROMPT = (
    "You are a trained sidewalk infrastructure inspector analyzing a street-level video clip. "
    "Your task is to produce a precise Sidewalk Infrastructure Inventory record. "
    "Focus exclusively on pedestrian infrastructure — ignore businesses, vehicles, and non-sidewalk scenery.\n\n"
    "Return valid JSON with exactly these keys:\n"
    "{\n"
    '  "name": "<nearby street or intersection name if legible on signage, otherwise use sidewalk_segment>",\n'
    '  "category": "sidewalk",\n'
    '  "sidewalk_presence": "<one of: present, absent, unclear — present means a defined pedestrian path is clearly visible>",\n'
    '  "condition": "<one of: good, fair, poor, blocked, under_construction, unknown — rate the walkable surface quality>",\n'
    '  "sidewalk_width_m": <REQUIRED numeric width estimate in meters as a float whenever sidewalk_presence is present — you MUST provide a best-guess estimate even with limited reference objects; use contextual cues: a person walking occupies ~0.6m, a wheelchair ~0.7m, a standard door ~0.9m, a parked car ~1.8m, a lane ~3.6m; only use null if sidewalk_presence is absent or unclear>,\n'
    '  "width_category": "<one of: narrow, standard, wide, unknown — narrow: <1.2m (single person barely fits), standard: 1.2–1.8m (two people can pass), wide: >1.8m (ample space); derive directly from sidewalk_width_m; unknown only if sidewalk_width_m is null>",\n'
    '  "curb_ramp_status": "<one of: present_compliant, present_noncompliant, absent, unclear, not_applicable — present_compliant means the ramp has a smooth slope and tactile dome pad; present_noncompliant means a ramp exists but is cracked, too steep, missing detectable warning surface, or otherwise ADA-deficient; not_applicable when there is no intersection or curb transition in view>",\n'
    '  "curb_ramp_details": "<describe specific curb ramp observations: slope quality, detectable warning surface (yellow dome tiles), lip height, alignment with crosswalk — or null if not visible>",\n'
    '  "surface_material": "<one of: concrete, asphalt, brick_paver, gravel, dirt, mixed, unknown>",\n'
    '  "surface_defects": "<array of observed defects: cracking, heaving, spalling, potholes, missing_panels, vegetation_encroachment, uneven_joint, or []>",\n'
    '  "obstructions": "<array of items blocking the walkway: utility_pole, street_sign, tree_roots, parked_vehicle, garbage_bin, construction_barrier, scaffolding, or []>",\n'
    '  "hazards": "<array of safety hazards: pothole, debris, standing_water, ice, exposed_rebar, broken_glass, steep_cross_slope, narrow_passage, or []>",\n'
    '  "crossing_features": "<array of at-grade crossing features visible: marked_crosswalk, unmarked_crosswalk, tactile_paving, pedestrian_signal, ped_push_button, median_refuge, raised_crosswalk, or []>",\n'
    '  "lighting": "<one of: adequate, inadequate, unknown — based on visible luminaires or ambient light conditions>",\n'
    '  "description": "<2-3 sentences of factual observations: confirm sidewalk presence, estimate width with reference objects used, describe surface and condition, note curb ramp compliance, list any safety concerns>"\n'
    "}\n\n"
    "Measurement guidance:\n"
    "- narrow (<1.2m): two people cannot pass comfortably side-by-side\n"
    "- standard (1.2–1.8m): two people can pass; typical residential sidewalk\n"
    "- wide (>1.8m): ample space, typical commercial or boulevard sidewalk\n"
    "- Use parked cars (~1.8m wide), lane markings (~3.6m), or door widths (~0.9m) as scale references\n\n"
    "Curb ramp compliance guidance:\n"
    "- Compliant: smooth slope ≤8.3%, detectable warning surface (yellow truncated dome tiles) present and intact, ≥0.9m wide, aligned with crossing direction\n"
    "- Non-compliant: missing dome tiles, cracked/broken ramp, lip >1cm at gutter, ramp misaligned with crosswalk, slope appears steep\n"
    "- Absent: curb with vertical drop and no ramp at an intersection\n\n"
    "Rules:\n"
    "- Only report what is directly observable in the video — do not infer or guess.\n"
    "- If sidewalk_presence is present, sidewalk_width_m MUST be a number — never null. Make your best estimate using any visible reference objects or proportions.\n"
    "- If sidewalk_presence is absent or unclear, set width_category to unknown and sidewalk_width_m to null.\n"
    "- Set curb_ramp_status to not_applicable if no intersection, driveway apron, or curb drop is visible.\n"
    "- Do not invent street names, business names, or POI labels.\n"
    "- surface_defects and obstructions must be arrays (use [] if none).\n"
    "- sidewalk_width_m must be a number or null — never a string.\n"
    "Respond with JSON only. No markdown fences, no commentary, no extra text."
)


def _coerce_float(value) -> float | None:
    if value in (None, "", "null"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        return [item.strip() for item in stripped.split(",") if item.strip()]
    return [str(value).strip()] if str(value).strip() else []


def frames_to_clip(
    frame_paths: list[str],
    fps: int = CLIP_OUTPUT_FPS,
    output_path: Optional[str] = None,
    frame_duration_sec: float = CLIP_FRAME_DURATION_SEC,
) -> str:
    """
    Stitch a list of JPEG frame paths into an MP4 clip using ffmpeg.

    Each image is shown for frame_duration_sec, then encoded at fps for smooth playback.
    Returns the path to the created MP4 file.
    """
    if not frame_paths:
        raise ValueError("frame_paths is empty — cannot create clip")

    if output_path is None:
        suffix = ".mp4"
        fd, output_path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)

    # Write frame paths to a concat file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as concat_file:
        for path in frame_paths:
            concat_file.write(f"file '{os.path.abspath(path)}'\n")
            concat_file.write(f"duration {frame_duration_sec:.4f}\n")
        # Repeat the last frame once so ffmpeg honors the final duration entry.
        concat_file.write(f"file '{os.path.abspath(frame_paths[-1])}'\n")
        concat_path = concat_file.name

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", concat_path,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-r", str(fps),
        # Scale down to max 1280px wide (Pegasus rejects 4K), keep aspect ratio,
        # ensure dimensions are divisible by 2 for yuv420p compatibility.
        "-vf", "scale='min(1280,iw)':-2",
        "-movflags", "+faststart",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    os.unlink(concat_path)

    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{result.stderr}")

    logger.debug("Created clip: %s (%d frames)", output_path, len(frame_paths))
    return output_path


def describe_clip(
    s3_uri: str,
    prompt: str = DEFAULT_PROMPT,
    client=None,
) -> str:
    """
    Call Pegasus 1.2 on a video clip already in S3.

    Uses InvokeModelWithResponseStream and returns the full accumulated response text.
    """
    if client is None:
        client = get_bedrock_client()

    body = json.dumps({
        "inputPrompt": prompt,
        "mediaSource": {
            "s3Location": _s3_location(s3_uri),
        },
        "temperature": 0.1,
        "maxOutputTokens": 800,
    })

    response = client.invoke_model_with_response_stream(
        modelId=PEGASUS_MODEL_ID,
        body=body,
        contentType="application/json",
        accept="application/json",
    )

    chunks = []
    for event in response["body"]:
        chunk = event.get("chunk")
        if chunk:
            raw = chunk["bytes"].decode("utf-8")
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                chunks.append(raw)
                continue

            text_piece = data.get("message")
            if text_piece is None:
                text_piece = (
                    data.get("outputText")
                    or data.get("text")
                    or data.get("completion")
                    or ""
                )
            chunks.append(text_piece)

    return "".join(chunks).strip()


def parse_description(raw_text: str) -> dict:
    """
    Parse Pegasus output into a sidewalk observation record.

    Tries JSON first; falls back to regex extraction.
    """
    # Strip markdown code fences if present
    text = re.sub(r"```(?:json)?\s*", "", raw_text).strip().rstrip("```").strip()

    try:
        data = json.loads(text)
        return {
            "name": data.get("name", ""),
            "category": data.get("category", "sidewalk"),
            "sidewalk_presence": data.get("sidewalk_presence", "unclear"),
            "condition": data.get("condition", "unknown"),
            "sidewalk_width_m": _coerce_float(data.get("sidewalk_width_m")),
            "width_category": data.get("width_category", "unknown"),
            "curb_ramp_status": data.get("curb_ramp_status", "unclear"),
            "curb_ramp_details": data.get("curb_ramp_details"),
            "surface_material": data.get("surface_material", "unknown"),
            "surface_defects": _coerce_list(data.get("surface_defects")),
            "obstructions": _coerce_list(data.get("obstructions")),
            "hazards": _coerce_list(data.get("hazards")),
            "crossing_features": _coerce_list(data.get("crossing_features")),
            "lighting": data.get("lighting", "unknown"),
            "description": data.get("description", ""),
            "raw": raw_text,
        }
    except (json.JSONDecodeError, ValueError):
        pass

    # Regex fallback
    name_m = re.search(r'"?name"?\s*[=:]\s*"([^"]+)"', text, re.IGNORECASE)
    cat_m = re.search(r'"?category"?\s*[=:]\s*"([^"]+)"', text, re.IGNORECASE)
    cond_m = re.search(r'"?condition"?\s*[=:]\s*"([^"]+)"', text, re.IGNORECASE)
    sidewalk_presence_m = re.search(r'"?sidewalk_presence"?\s*[=:]\s*"([^"]+)"', text, re.IGNORECASE)
    sidewalk_width_m = re.search(r'"?sidewalk_width_m"?\s*[=:]\s*("?[\d\.]+"?|null)', text, re.IGNORECASE)
    width_cat_m = re.search(r'"?width_category"?\s*[=:]\s*"([^"]+)"', text, re.IGNORECASE)
    curb_ramp_status_m = re.search(r'"?curb_ramp_status"?\s*[=:]\s*"([^"]+)"', text, re.IGNORECASE)
    curb_ramp_details_m = re.search(r'"?curb_ramp_details"?\s*[=:]\s*"([^"]+)"', text, re.IGNORECASE)
    surface_material_m = re.search(r'"?surface_material"?\s*[=:]\s*"([^"]+)"', text, re.IGNORECASE)
    surface_defects_m = re.search(r'"?surface_defects"?\s*[=:]\s*\[([^\]]*)\]', text, re.IGNORECASE)
    obstructions_m = re.search(r'"?obstructions"?\s*[=:]\s*\[([^\]]*)\]', text, re.IGNORECASE)
    hazards_m = re.search(r'"?hazards"?\s*[=:]\s*\[([^\]]*)\]', text, re.IGNORECASE)
    crossing_features_m = re.search(r'"?crossing_features"?\s*[=:]\s*\[([^\]]*)\]', text, re.IGNORECASE)
    lighting_m = re.search(r'"?lighting"?\s*[=:]\s*"([^"]+)"', text, re.IGNORECASE)
    desc_m = re.search(r'"?description"?\s*[=:]\s*"([^"]+)"', text, re.IGNORECASE)

    return {
        "name": name_m.group(1) if name_m else "",
        "category": cat_m.group(1) if cat_m else "sidewalk",
        "sidewalk_presence": sidewalk_presence_m.group(1) if sidewalk_presence_m else "unclear",
        "condition": cond_m.group(1) if cond_m else "unknown",
        "sidewalk_width_m": _coerce_float(sidewalk_width_m.group(1).strip('"') if sidewalk_width_m else None),
        "width_category": width_cat_m.group(1) if width_cat_m else "unknown",
        "curb_ramp_status": curb_ramp_status_m.group(1) if curb_ramp_status_m else "unclear",
        "curb_ramp_details": curb_ramp_details_m.group(1) if curb_ramp_details_m else None,
        "surface_material": surface_material_m.group(1) if surface_material_m else "unknown",
        "surface_defects": _coerce_list(surface_defects_m.group(1) if surface_defects_m else None),
        "obstructions": _coerce_list(obstructions_m.group(1) if obstructions_m else None),
        "hazards": _coerce_list(hazards_m.group(1) if hazards_m else None),
        "crossing_features": _coerce_list(crossing_features_m.group(1) if crossing_features_m else None),
        "lighting": lighting_m.group(1) if lighting_m else "unknown",
        "description": desc_m.group(1) if desc_m else "",
        "raw": raw_text,
    }


def process_sequence_clip(
    sequence_id: str,
    frame_paths: list[str],
    frame_meta: list[dict],
    s3_prefix: str = "clips/",
    bucket: str = S3_WORKSHOP_BUCKET,
    client=None,
) -> dict:
    """
    Full pipeline for one sequence: stitch → upload → describe → parse.

    frame_meta: list of frame dicts with {id, lat, lon, bearing, timestamp}.
    Returns a dict with sequence_id, description fields, centroid lat/lon, and frame evidence.
    """
    clip_path = None
    try:
        clip_path = frames_to_clip(frame_paths)
        s3_key = f"{s3_prefix}{sequence_id}.mp4"
        s3_uri = upload_to_s3(clip_path, s3_key, bucket=bucket)

        raw_text = describe_clip(s3_uri, client=client)
        parsed = parse_description(raw_text)

        # Compute centroid of sampled frames
        lats = [f["lat"] for f in frame_meta if f.get("lat")]
        lons = [f["lon"] for f in frame_meta if f.get("lon")]
        centroid_lat = sum(lats) / len(lats) if lats else None
        centroid_lon = sum(lons) / len(lons) if lons else None

        return {
            "sequence_id": sequence_id,
            "clip_s3_uri": s3_uri,
            "name": parsed["name"],
            "category": parsed["category"],
            "sidewalk_presence": parsed["sidewalk_presence"],
            "condition": parsed["condition"],
            "sidewalk_width_m": parsed["sidewalk_width_m"],
            "width_category": parsed["width_category"],
            "curb_ramp_status": parsed["curb_ramp_status"],
            "curb_ramp_details": parsed["curb_ramp_details"],
            "surface_material": parsed["surface_material"],
            "surface_defects": parsed["surface_defects"],
            "obstructions": parsed["obstructions"],
            "hazards": parsed["hazards"],
            "crossing_features": parsed["crossing_features"],
            "lighting": parsed["lighting"],
            "description": parsed.get("description", ""),
            "lat": centroid_lat,
            "lon": centroid_lon,
            "frame_ids": [f["id"] for f in frame_meta],
            "raw_response": parsed["raw"],
        }
    finally:
        if clip_path and os.path.exists(clip_path):
            os.unlink(clip_path)


def process_all_sequences(
    sequences: list[dict],
    images_dir: str,
    output_dir: str = DATA_PROCESSED,
    max_frames_per_clip: int = 10,
    min_frames_per_clip: int = 2,
    duplicate_single_frame: bool = False,
    output_filename: str = "descriptions.json",
    s3_prefix: str = "clips/",
    client=None,
) -> list[dict]:
    """
    Process every sequence: stitch frames → Pegasus → parse → save JSON manifest.

    sequences: output of mapillary.load_sequences()
    images_dir: root of data/raw/images/{sequence_id}/{frame_id}.jpg
    """
    os.makedirs(output_dir, exist_ok=True)

    if client is None:
        client = get_bedrock_client()

    all_results = []
    out_path = os.path.join(output_dir, output_filename)

    for seq in sequences:
        seq_id = seq["sequence_id"]
        frames = seq["frames"]

        # Collect frame paths that were actually downloaded
        seq_img_dir = os.path.join(images_dir, seq_id)
        sampled = []
        for frame in frames[:max_frames_per_clip]:
            path = os.path.join(seq_img_dir, f"{frame['id']}.jpg")
            if os.path.exists(path):
                sampled.append((path, frame))

        if duplicate_single_frame and len(sampled) == 1:
            sampled = [sampled[0], sampled[0]]

        if len(sampled) < min_frames_per_clip:
            logger.warning(
                "Sequence %s: fewer than %d downloaded frames — skipping",
                seq_id,
                min_frames_per_clip,
            )
            continue

        paths, metas = zip(*sampled)
        try:
            result = process_sequence_clip(
                seq_id,
                list(paths),
                list(metas),
                s3_prefix=s3_prefix,
                client=client,
            )
            all_results.append(result)
            logger.info(
                "Sequence %s → name=%r category=%r condition=%r",
                seq_id, result["name"], result["category"], result["condition"],
            )
        except Exception as exc:
            logger.error("Failed to process sequence %s: %s", seq_id, exc)
            continue

        with open(out_path, "w") as f:
            json.dump(all_results, f, indent=2)

    logger.info("Saved descriptions → %s (%d sequences)", out_path, len(all_results))

    return all_results
