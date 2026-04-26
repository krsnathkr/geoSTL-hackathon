import argparse
import json
import logging
import os
from typing import Any

from analyze.cross_reference import cross_reference, load_descriptions
from analyze.export import export_all, to_geojson, to_geoparquet
from analyze.metrics import compute_and_save
from config.settings import DATA_OUTPUT, DATA_PROCESSED, DATA_RAW
from ingest.mapillary import download_frames, fetch_sequences, load_sequences
from ingest.overture import (
    fetch_places,
    fetch_transportation,
    load_places,
    load_transportation,
)
from process.embeddings import ensure_index, index_frames_bulk, save_indexed_manifest
from process.pegasus import process_all_sequences
from process.twelvelabs import embed_frames_batch

logger = logging.getLogger(__name__)

STAGES = ["ingest", "embed", "describe", "analyze"]


def run_pipeline(
    from_stage: str = "ingest",
    to_stage: str = "analyze",
    data_raw_dir: str = DATA_RAW,
    data_processed_dir: str = DATA_PROCESSED,
    data_output_dir: str = DATA_OUTPUT,
    max_images: int | None = None,
    sample_every_n: int = 1,
    max_sequences: int | None = None,
    max_frames_per_clip: int = 10,
    skip_download_frames: bool = False,
    redownload_frames: bool = False,
    skip_embeddings: bool = False,
    skip_transportation: bool = False,
) -> dict[str, Any]:
    selected_stages = _selected_stages(from_stage, to_stage)
    context: dict[str, Any] = {
        "data_raw_dir": data_raw_dir,
        "data_processed_dir": data_processed_dir,
        "data_output_dir": data_output_dir,
    }

    if "ingest" in selected_stages:
        logger.info("Stage ingest: fetching Overture datasets")
        fetch_places(output_dir=data_raw_dir)
        if skip_transportation:
            logger.info("Stage ingest: skipping transportation dataset")
        else:
            fetch_transportation(output_dir=data_raw_dir)

        logger.info("Stage ingest: fetching Mapillary sequences")
        sequences = fetch_sequences(output_dir=data_raw_dir, max_images=max_images)
        if max_sequences is not None:
            sequences = sequences[:max_sequences]

        if not skip_download_frames:
            logger.info("Stage ingest: downloading sampled Mapillary frames")
            download_frames(
                sequences,
                output_dir=data_raw_dir,
                sample_every_n=sample_every_n,
                overwrite_existing=redownload_frames,
            )

        context["sequences"] = sequences

    if "embed" in selected_stages:
        sequences = context.get("sequences") or load_sequences(data_dir=data_raw_dir)
        if max_sequences is not None:
            sequences = sequences[:max_sequences]

        frames = collect_local_frames(
            sequences=sequences,
            images_dir=os.path.join(data_raw_dir, "images"),
            sample_every_n=sample_every_n,
        )
        context["embedded_frames"] = []

        if skip_embeddings:
            logger.info("Stage embed: skipped by flag")
        elif frames:
            logger.info("Stage embed: embedding %d local frames", len(frames))
            embedded_frames = embed_frames_batch(frames)
            try:
                ensure_index()
                index_frames_bulk(embedded_frames)
                save_indexed_manifest(embedded_frames, output_dir=data_processed_dir)
            except Exception as exc:
                # OpenSearch indexing is useful for retrieval, but it is not required
                # for the describe/analyze stages that generate the map outputs.
                logger.warning(
                    "Stage embed: vector index unavailable, continuing without OpenSearch indexing: %s",
                    exc,
                )
            context["embedded_frames"] = embedded_frames
        else:
            logger.warning("Stage embed: no downloaded local frames found")

    if "describe" in selected_stages:
        sequences = context.get("sequences") or load_sequences(data_dir=data_raw_dir)
        if max_sequences is not None:
            sequences = sequences[:max_sequences]

        logger.info("Stage describe: generating structured descriptions")
        descriptions = process_all_sequences(
            sequences=sequences,
            images_dir=os.path.join(data_raw_dir, "images"),
            output_dir=data_processed_dir,
            max_frames_per_clip=max_frames_per_clip,
        )
        context["descriptions"] = descriptions

        logger.info("Stage describe: generating single-frame baseline descriptions")
        baseline_descriptions = process_all_sequences(
            sequences=sequences,
            images_dir=os.path.join(data_raw_dir, "images"),
            output_dir=data_processed_dir,
            max_frames_per_clip=1,
            min_frames_per_clip=1,
            duplicate_single_frame=True,
            output_filename="baseline_descriptions.json",
            s3_prefix="baseline-clips/",
            frame_duration_sec=4.0,  # 2 frames × 4s = 8s clip — avoids Pegasus min-duration rejection
        )
        context["baseline_descriptions"] = baseline_descriptions

    if "analyze" in selected_stages:
        logger.info("Stage analyze: loading artifacts")
        descriptions = context.get("descriptions") or load_descriptions(data_dir=data_processed_dir)
        baseline_descriptions = context.get("baseline_descriptions") or load_json_artifact(
            os.path.join(data_processed_dir, "baseline_descriptions.json")
        )
        transport_segments = None
        if not skip_transportation:
            try:
                transport_segments = load_transportation(data_dir=data_raw_dir)
            except FileNotFoundError:
                logger.warning("Transportation artifact missing; continuing with standalone sidewalk observations")

        logger.info("Stage analyze: cross-referencing observations")
        detections = cross_reference(descriptions, transport_segments)
        baseline_detections = cross_reference(baseline_descriptions, transport_segments)
        export_paths = export_all(detections, output_dir=data_output_dir, exclude_validated=False)
        baseline_export_paths = {
            "geojson": to_geojson(
                baseline_detections,
                output_dir=data_output_dir,
                filename="baseline_detections.geojson",
                exclude_validated=False,  # keep all types so comparison tab has real data
            ),
            "geoparquet": to_geoparquet(
                baseline_detections,
                output_dir=data_output_dir,
                filename="baseline_detections.geoparquet",
                exclude_validated=False,
            ),
        }
        metrics = compute_and_save(
            detections,
            baseline_detections=baseline_detections,
            output_dir=data_output_dir,
        )

        summary = {
            "status": "ok",
            "stages": selected_stages,
            "detections": len(detections),
            "baseline_detections": len(baseline_detections),
            "exports": export_paths,
            "baseline_exports": baseline_export_paths,
            "metrics_path": os.path.join(data_output_dir, "metrics.json"),
            "type_counts": metrics.get("type_counts", {}),
            "has_temporal_advantage": "temporal_advantage" in metrics,
        }
        context["summary"] = summary
        logger.info("Stage analyze: complete")
        return summary

    return {
        "status": "ok",
        "stages": selected_stages,
        "message": "Pipeline stages completed",
    }


def collect_local_frames(
    sequences: list[dict],
    images_dir: str,
    sample_every_n: int = 1,
) -> list[dict]:
    frames = []
    for sequence in sequences:
        seq_id = sequence.get("sequence_id", "")
        seq_frames = sequence.get("frames", [])
        for frame in seq_frames[::sample_every_n]:
            local_path = os.path.join(images_dir, seq_id, f"{frame['id']}.jpg")
            if not os.path.exists(local_path):
                continue
            frames.append(
                {
                    "id": frame["id"],
                    "local_path": local_path,
                    "lat": frame.get("lat"),
                    "lon": frame.get("lon"),
                    "bearing": frame.get("bearing"),
                    "timestamp": frame.get("timestamp", ""),
                    "sequence_id": seq_id,
                }
            )
    return frames


def _selected_stages(from_stage: str, to_stage: str) -> list[str]:
    try:
        start_index = STAGES.index(from_stage)
        end_index = STAGES.index(to_stage)
    except ValueError as exc:
        raise ValueError(f"Unknown stage: {exc}") from exc

    if end_index < start_index:
        raise ValueError("to_stage must come after from_stage")

    return STAGES[start_index : end_index + 1]


def load_json_artifact(path: str) -> list[dict]:
    if not os.path.exists(path):
        logger.warning("Artifact missing: %s", path)
        return []

    with open(path) as fh:
        data = json.load(fh)
    return data if isinstance(data, list) else []


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the GeoSTL hackathon pipeline")
    parser.add_argument("--from-stage", default="ingest", choices=STAGES)
    parser.add_argument("--to-stage", default="analyze", choices=STAGES)
    parser.add_argument("--data-raw-dir", default=DATA_RAW)
    parser.add_argument("--data-processed-dir", default=DATA_PROCESSED)
    parser.add_argument("--data-output-dir", default=DATA_OUTPUT)
    parser.add_argument("--max-images", type=int)
    parser.add_argument("--sample-every-n", type=int, default=1)
    parser.add_argument("--max-sequences", type=int)
    parser.add_argument("--max-frames-per-clip", type=int, default=10)
    parser.add_argument("--skip-download-frames", action="store_true")
    parser.add_argument("--redownload-frames", action="store_true")
    parser.add_argument("--skip-embeddings", action="store_true")
    parser.add_argument("--skip-transportation", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))
    result = run_pipeline(
        from_stage=args.from_stage,
        to_stage=args.to_stage,
        data_raw_dir=args.data_raw_dir,
        data_processed_dir=args.data_processed_dir,
        data_output_dir=args.data_output_dir,
        max_images=args.max_images,
        sample_every_n=args.sample_every_n,
        max_sequences=args.max_sequences,
        max_frames_per_clip=args.max_frames_per_clip,
        skip_download_frames=args.skip_download_frames,
        redownload_frames=args.redownload_frames,
        skip_embeddings=args.skip_embeddings,
        skip_transportation=args.skip_transportation,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
