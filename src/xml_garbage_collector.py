"""
xml_garbage_collector.py
------------------------
OpenXML Binary Media Pruner using zipfile + ElementTree .rels traversal.

Algorithm:
  1. Stream .docx container in-memory (no filesystem extraction).
  2. Parse ALL relationship files (.rels) to build a whitelist of actively
     referenced r:embed / r:link media targets.
  3. Rewrite the ZIP, dropping every word/media/* entry NOT in the whitelist.
  4. Return a PruneResult dataclass with telemetry.
"""

from __future__ import annotations

import io
import json
import logging
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Set
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
MEDIA_PREFIX = "word/media/"


@dataclass
class PruneResult:
    """Telemetry container returned after pruning a single .docx file."""
    source_path: str
    original_bytes: int
    pruned_bytes: int
    orphan_count: int
    retained_count: int
    rids_preserved: Set[str] = field(default_factory=set)

    @property
    def bytes_saved(self) -> int:
        return self.original_bytes - self.pruned_bytes

    @property
    def reduction_pct(self) -> float:
        if self.original_bytes == 0:
            return 0.0
        return round((self.bytes_saved / self.original_bytes) * 100, 2)

    def to_json(self) -> str:
        return json.dumps({
            "source": self.source_path,
            "original_bytes": self.original_bytes,
            "pruned_bytes": self.pruned_bytes,
            "bytes_saved": self.bytes_saved,
            "reduction_pct": self.reduction_pct,
            "orphan_count": self.orphan_count,
            "retained_count": self.retained_count,
        })


def _collect_referenced_targets(zf: zipfile.ZipFile) -> Set[str]:
    """
    Parse every *.rels entry in the ZIP to collect the full set of
    media targets that are actively referenced by the document.
    Returns a set of normalized archive member paths (e.g. 'word/media/image1.png').
    """
    referenced: Set[str] = set()
    for name in zf.namelist():
        if not name.endswith(".rels"):
            continue
        try:
            data = zf.read(name)
            root = ET.fromstring(data)
        except ET.ParseError:
            logger.warning("Could not parse rels file: %s — skipping.", name)
            continue

        rels_dir = name.rsplit("/", 1)[0] if "/" in name else ""
        for rel in root.findall(f"{{{RELS_NS}}}Relationship"):
            target = rel.get("Target", "")
            if not target:
                continue
            # Resolve relative targets against the .rels file location
            if target.startswith("/"):
                resolved = target.lstrip("/")
            elif rels_dir.endswith("_rels"):
                parent = rels_dir[: -len("_rels")].rstrip("/")
                resolved = f"{parent}/{target}" if parent else target
            else:
                resolved = f"{rels_dir}/{target}" if rels_dir else target

            # Normalize double slashes
            resolved = resolved.replace("//", "/")
            if MEDIA_PREFIX in resolved or resolved.startswith(MEDIA_PREFIX):
                # Normalize to archive root-relative path
                idx = resolved.find(MEDIA_PREFIX)
                normalized = resolved[idx:]
                referenced.add(normalized)

    return referenced


def prune_docx(source_path: Path, output_path: Path) -> PruneResult:
    """
    Prune orphaned binary media from a .docx file.

    Parameters
    ----------
    source_path : Path
        Absolute path to the input .docx file.
    output_path : Path
        Absolute path where the cleaned .docx will be written.

    Returns
    -------
    PruneResult
        Telemetry dataclass with byte counts and orphan statistics.
    """
    original_bytes = source_path.stat().st_size
    output_path.parent.mkdir(parents=True, exist_ok=True)

    buf = io.BytesIO()

    with zipfile.ZipFile(source_path, "r") as zf_in:
        referenced = _collect_referenced_targets(zf_in)

        all_media = {n for n in zf_in.namelist() if n.startswith(MEDIA_PREFIX) and not n.endswith("/")}
        orphaned = all_media - referenced
        retained = all_media & referenced

        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf_out:
            for item in zf_in.infolist():
                if item.filename in orphaned:
                    continue  # Drop the orphan
                data = zf_in.read(item.filename)
                zf_out.writestr(item, data)

    output_path.write_bytes(buf.getvalue())
    pruned_bytes = output_path.stat().st_size

    result = PruneResult(
        source_path=str(source_path),
        original_bytes=original_bytes,
        pruned_bytes=pruned_bytes,
        orphan_count=len(orphaned),
        retained_count=len(retained),
        rids_preserved={r.split("/")[-1] for r in retained},
    )
    logger.info(result.to_json())
    return result
