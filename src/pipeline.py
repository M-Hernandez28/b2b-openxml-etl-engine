"""
pipeline.py
-----------
CLI orchestrator for the B2B OpenXML ETL & Sprint Scheduling Engine.

Usage:
    python -m src.pipeline --input-dir ./sample_data/raw_batch \
                           --output-dir ./sample_data/cleaned_batch \
                           --tracker ./sample_data/Master_Tracker_Template.xlsx \
                           --team-size 4
"""

from __future__ import annotations

import argparse
import logging
import random
import sys
from pathlib import Path

from src.xml_garbage_collector import prune_docx
from src.sprint_scheduler import FileMetadata, schedule_sprint

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

PRIORITY_CHOICES = ["P1", "P2", "P3"]


def _estimate_word_count(path: Path) -> int:
    """Approximate word count from file size (650 words/KB heuristic for .docx)."""
    return max(1, int(path.stat().st_size / 1024 * 650))


def _assign_priority(path: Path) -> str:
    """
    Derive a reproducible priority from the filename hash.
    P1 ~15%, P2 ~35%, P3 ~50% — mirrors typical B2B batch distributions.
    """
    seed = hash(path.name) % 100
    if seed < 15:
        return "P1"
    elif seed < 50:
        return "P2"
    return "P3"


def run_pipeline(
    input_dir: Path,
    output_dir: Path,
    tracker_path: Path,
    team_size: int,
) -> int:
    """
    Execute the full ETL + scheduling pipeline.

    Returns
    -------
    int
        Exit code: 0 on success, 1 on any per-file error.
    """
    docx_files = sorted(input_dir.glob("*.docx"))
    if not docx_files:
        logger.error("No .docx files found in %s", input_dir)
        return 1

    logger.info("Pipeline started | %d files | team_size=%d", len(docx_files), team_size)

    total_original = 0
    total_pruned = 0
    file_metadata = []
    exit_code = 0

    for source in docx_files:
        dest = output_dir / source.name
        try:
            result = prune_docx(source, dest)
            total_original += result.original_bytes
            total_pruned += result.pruned_bytes
            file_metadata.append(
                FileMetadata(
                    path=dest,
                    size_bytes=result.pruned_bytes,
                    word_count=_estimate_word_count(source),
                    priority=_assign_priority(source),
                )
            )
        except Exception as exc:
            logger.error("Failed to prune %s: %s", source.name, exc)
            exit_code = 1

    bytes_saved = total_original - total_pruned
    reduction_pct = round((bytes_saved / total_original * 100), 2) if total_original else 0.0

    logger.info(
        "Pruning complete | original=%.2f MB | cleaned=%.2f MB | saved=%.2f MB (%.1f%%)",
        total_original / 1e6,
        total_pruned / 1e6,
        bytes_saved / 1e6,
        reduction_pct,
    )

    if file_metadata:
        sched = schedule_sprint(file_metadata, tracker_path, team_size=team_size)
        logger.info("Sprint tracker written → %s", sched.tracker_path)

    logger.info("Pipeline finished | exit_code=%d", exit_code)
    return exit_code


def main() -> None:
    parser = argparse.ArgumentParser(
        description="B2B OpenXML Garbage Collection & Sprint Scheduling Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--input-dir", required=True, type=Path, help="Directory of source .docx files")
    parser.add_argument("--output-dir", required=True, type=Path, help="Directory for cleaned output .docx files")
    parser.add_argument("--tracker", required=True, type=Path, help="Output path for Master_Tracker.xlsx")
    parser.add_argument("--team-size", type=int, default=4, help="Number of specialists in the sprint pod (default: 4)")
    args = parser.parse_args()

    sys.exit(run_pipeline(args.input_dir, args.output_dir, args.tracker, args.team_size))


if __name__ == "__main__":
    main()
