"""
test_pruner_integrity.py
------------------------
Pytest suite for xml_garbage_collector.py

Covers:
  - All orphaned media is removed post-prune
  - All referenced media is preserved post-prune
  - rId targets in .rels are never broken after pruning
  - PruneResult.pruned_bytes < PruneResult.original_bytes (bloat was eliminated)
  - Pipeline CLI exits 0 on a clean synthetic batch
"""

from __future__ import annotations

import io
import struct
import subprocess
import sys
import zipfile
import zlib
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_png() -> bytes:
    """Reproduce the minimal valid 8x8 PNG from the synthetic generator."""
    def _chunk(tag: bytes, data: bytes) -> bytes:
        length = struct.pack(">I", len(data))
        body = tag + data
        crc = struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        return length + body + crc

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = _chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 0, 0, 0, 0))
    raw = b"".join(b"\x00" + bytes([128] * 8) for _ in range(8))
    idat = _chunk(b"IDAT", zlib.compress(raw))
    iend = _chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="png" ContentType="image/png"/>
  <Override PartName="/word/document.xml"
    ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
    Target="word/document.xml"/>
</Relationships>"""

DOC_RELS_WITH_IMAGE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId2"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
    Target="media/referenced.png"/>
</Relationships>"""

DOC_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
            xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <w:body><w:p><w:r><w:t>Hello World</w:t></w:r></w:p></w:body>
</w:document>"""


def _build_docx(tmp_path: Path, orphan_count: int = 3, orphan_size: int = 50_000) -> Path:
    """
    Build a synthetic .docx with:
      - 1 referenced PNG (word/media/referenced.png, anchored in doc rels)
      - `orphan_count` orphaned blobs (word/media/orphan_*.bin, NOT in rels)
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES)
        zf.writestr("_rels/.rels", ROOT_RELS)
        zf.writestr("word/document.xml", DOC_XML)
        zf.writestr("word/_rels/document.xml.rels", DOC_RELS_WITH_IMAGE)
        zf.writestr("word/media/referenced.png", _minimal_png())
        for i in range(orphan_count):
            zf.writestr(f"word/media/orphan_{i}.bin", bytes(range(256)) * (orphan_size // 256))

    docx_path = tmp_path / "test_bloated.docx"
    docx_path.write_bytes(buf.getvalue())
    return docx_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_orphans_removed(tmp_path):
    """All orphaned word/media/* entries must be absent from the pruned output."""
    from src.xml_garbage_collector import prune_docx

    src = _build_docx(tmp_path, orphan_count=4)
    dst = tmp_path / "pruned.docx"
    result = prune_docx(src, dst)

    with zipfile.ZipFile(dst, "r") as zf:
        names = zf.namelist()

    orphans_remaining = [n for n in names if "orphan_" in n]
    assert orphans_remaining == [], f"Orphans still present: {orphans_remaining}"
    assert result.orphan_count == 4


def test_referenced_media_preserved(tmp_path):
    """The legitimately referenced image must survive pruning."""
    from src.xml_garbage_collector import prune_docx

    src = _build_docx(tmp_path, orphan_count=3)
    dst = tmp_path / "pruned.docx"
    prune_docx(src, dst)

    with zipfile.ZipFile(dst, "r") as zf:
        names = zf.namelist()

    assert "word/media/referenced.png" in names, "Referenced image was incorrectly pruned."


def test_rels_not_broken(tmp_path):
    """word/_rels/document.xml.rels must still reference word/media/referenced.png after pruning."""
    from src.xml_garbage_collector import prune_docx

    src = _build_docx(tmp_path)
    dst = tmp_path / "pruned.docx"
    prune_docx(src, dst)

    with zipfile.ZipFile(dst, "r") as zf:
        rels_content = zf.read("word/_rels/document.xml.rels").decode("utf-8")

    assert "media/referenced.png" in rels_content, "Rels file lost reference to retained image."


def test_pruned_bytes_less_than_original(tmp_path):
    """Pruned file must be strictly smaller than the original bloated file."""
    from src.xml_garbage_collector import prune_docx

    src = _build_docx(tmp_path, orphan_count=5, orphan_size=100_000)
    dst = tmp_path / "pruned.docx"
    result = prune_docx(src, dst)

    assert result.pruned_bytes < result.original_bytes, (
        f"Pruned file ({result.pruned_bytes}B) is not smaller than original ({result.original_bytes}B)."
    )
    assert result.bytes_saved > 0


def test_prune_result_dataclass(tmp_path):
    """PruneResult fields must be consistent and non-negative."""
    from src.xml_garbage_collector import prune_docx

    src = _build_docx(tmp_path, orphan_count=2)
    dst = tmp_path / "pruned.docx"
    result = prune_docx(src, dst)

    assert result.original_bytes > 0
    assert result.pruned_bytes > 0
    assert result.orphan_count >= 0
    assert result.retained_count >= 0
    assert 0.0 <= result.reduction_pct <= 100.0
    assert isinstance(result.rids_preserved, set)


def test_pipeline_cli_exits_zero(tmp_path):
    """Full CLI pipeline must exit 0 on a clean synthetic batch."""
    from sample_data.generate_synthetic_bloat import generate_synthetic_docx

    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    clean_dir = tmp_path / "clean"
    tracker = tmp_path / "tracker.xlsx"

    # Generate 3 synthetic files
    for i in range(3):
        generate_synthetic_docx(raw_dir / f"doc_{i}.docx", bloat_bytes=20_000)

    result = subprocess.run(
        [
            sys.executable, "-m", "src.pipeline",
            "--input-dir", str(raw_dir),
            "--output-dir", str(clean_dir),
            "--tracker", str(tracker),
            "--team-size", "2",
        ],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent,
    )
    assert result.returncode == 0, f"Pipeline exited {result.returncode}:\n{result.stderr}"
    assert tracker.exists(), "Master_Tracker.xlsx was not created."
