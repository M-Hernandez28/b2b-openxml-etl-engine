"""
generate_synthetic_bloat.py
---------------------------
Generates synthetic .docx test payloads containing:
  - 1-3 legitimately referenced images (anchored in the document body)
  - N orphaned binary blobs in word/media/ with NO .rels references

Usage:
    python sample_data/generate_synthetic_bloat.py --count 25 --bloat-mb 5
"""

from __future__ import annotations

import argparse
import io
import os
import random
import string
import struct
import zipfile
from pathlib import Path

LOREM = (
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
    "Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. "
    "Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris. "
)

CONTENT_TYPES_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="png" ContentType="image/png"/>
  <Override PartName="/word/document.xml"
    ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

RELS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
    Target="word/document.xml"/>
</Relationships>"""

DOC_RELS_TEMPLATE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
{relationships}
</Relationships>"""

DOC_XML_TEMPLATE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
            xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
            xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
            xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
            xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">
  <w:body>
    <w:p><w:r><w:t>{text}</w:t></w:r></w:p>
{drawings}
    <w:sectPr/>
  </w:body>
</w:document>"""

DRAWING_TEMPLATE = """    <w:p>
      <w:r>
        <w:drawing>
          <wp:inline>
            <wp:extent cx="1000000" cy="1000000"/>
            <wp:docPr id="{draw_id}" name="Image{draw_id}"/>
            <a:graphic>
              <a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
                <pic:pic>
                  <pic:nvPicPr>
                    <pic:cNvPr id="{draw_id}" name="Image{draw_id}"/>
                    <pic:cNvPicPr/>
                  </pic:nvPicPr>
                  <pic:blipFill>
                    <a:blip r:embed="{rid}"/>
                    <a:stretch><a:fillRect/></a:stretch>
                  </pic:blipFill>
                  <pic:spPr>
                    <a:xfrm><a:off x="0" y="0"/><a:ext cx="1000000" cy="1000000"/></a:xfrm>
                    <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
                  </pic:spPr>
                </pic:pic>
              </a:graphicData>
            </a:graphic>
          </wp:inline>
        </w:drawing>
      </w:r>
    </w:p>"""

IMAGE_REL_TEMPLATE = (
    '  <Relationship Id="{rid}" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
    'Target="media/{filename}"/>'
)


def _make_minimal_png(width: int = 8, height: int = 8) -> bytes:
    """Generate a valid minimal 8x8 grey PNG in pure Python (no Pillow required)."""
    import zlib

    def _chunk(tag: bytes, data: bytes) -> bytes:
        length = struct.pack(">I", len(data))
        body = tag + data
        crc = struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        return length + body + crc

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    ihdr = _chunk(b"IHDR", ihdr_data)

    raw_rows = b"".join(b"\x00" + bytes([128] * width) for _ in range(height))
    compressed = zlib.compress(raw_rows)
    idat = _chunk(b"IDAT", compressed)
    iend = _chunk(b"IEND", b"")

    return signature + ihdr + idat + iend


def _make_orphan_blob(size_bytes: int) -> bytes:
    """Generate a random binary blob to simulate orphaned media (e.g., hidden TIFF/JPEG residue)."""
    return bytes(random.getrandbits(8) for _ in range(size_bytes))


def generate_synthetic_docx(output_path: Path, bloat_bytes: int, referenced_images: int = 2) -> dict:
    """
    Build a synthetic .docx with injected orphaned binary media.

    Parameters
    ----------
    output_path : Path
        Where to write the .docx file.
    bloat_bytes : int
        Total bytes of orphaned (unreferenced) blobs to inject.
    referenced_images : int
        How many legitimate PNG images to embed with proper .rels anchoring.

    Returns
    -------
    dict
        Manifest entry: {path, original_size, orphan_count, ref_count}
    """
    buf = io.BytesIO()
    png_data = _make_minimal_png()

    ref_image_names = [f"ref_image_{i+1}.png" for i in range(referenced_images)]
    orphan_count = random.randint(3, 8)
    orphan_bytes_each = max(1024, bloat_bytes // orphan_count)

    relationships = []
    drawings = []
    for i, img_name in enumerate(ref_image_names):
        rid = f"rId{i+2}"
        relationships.append(IMAGE_REL_TEMPLATE.format(rid=rid, filename=img_name))
        drawings.append(DRAWING_TEMPLATE.format(rid=rid, draw_id=i+1))

    doc_xml = DOC_XML_TEMPLATE.format(
        text=LOREM * random.randint(1, 5),
        drawings="\n".join(drawings),
    )
    doc_rels = DOC_RELS_TEMPLATE.format(relationships="\n".join(relationships))

    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES_XML)
        zf.writestr("_rels/.rels", RELS_XML)
        zf.writestr("word/document.xml", doc_xml)
        zf.writestr("word/_rels/document.xml.rels", doc_rels)

        # Legitimately referenced images
        for img_name in ref_image_names:
            zf.writestr(f"word/media/{img_name}", png_data)

        # Orphaned binary blobs (NOT in any .rels)
        for j in range(orphan_count):
            ext = random.choice(["tiff", "jpg", "emf", "wmf", "bin"])
            blob_name = f"orphan_{j+1}_{''.join(random.choices(string.ascii_lowercase, k=6))}.{ext}"
            zf.writestr(f"word/media/{blob_name}", _make_orphan_blob(orphan_bytes_each))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(buf.getvalue())
    size = output_path.stat().st_size

    return {
        "path": str(output_path),
        "size_bytes": size,
        "size_kb": round(size / 1024, 2),
        "orphan_count": orphan_count,
        "referenced_images": referenced_images,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic bloated .docx test payloads")
    parser.add_argument("--count", type=int, default=10, help="Number of .docx files to generate (default: 10)")
    parser.add_argument("--bloat-mb", type=float, default=2.0, help="Orphaned binary blob size per file in MB (default: 2.0)")
    parser.add_argument("--output-dir", type=Path, default=Path("sample_data/raw_batch"), help="Output directory")
    args = parser.parse_args()

    bloat_bytes = int(args.bloat_mb * 1024 * 1024)
    print(f"\n[Synthetic Generator] Creating {args.count} files with ~{args.bloat_mb:.1f} MB orphan bloat each...")
    print(f"Output → {args.output_dir.resolve()}\n")

    manifest = []
    for i in range(args.count):
        fname = f"batch_doc_{i+1:03d}.docx"
        entry = generate_synthetic_docx(
            output_path=args.output_dir / fname,
            bloat_bytes=bloat_bytes,
            referenced_images=random.randint(1, 3),
        )
        manifest.append(entry)
        print(f"  [{i+1:3d}/{args.count}] {fname}  {entry['size_kb']:.1f} KB  "
              f"(orphans={entry['orphan_count']}, refs={entry['referenced_images']})")

    total_mb = sum(e["size_bytes"] for e in manifest) / 1e6
    print(f"\nTotal generated: {total_mb:.2f} MB across {len(manifest)} files.")
    print("Run the pipeline to prune:\n")
    print("  python -m src.pipeline \\")
    print(f"    --input-dir {args.output_dir} \\")
    print(f"    --output-dir sample_data/cleaned_batch \\")
    print(f"    --tracker sample_data/Master_Tracker_Template.xlsx \\")
    print(f"    --team-size 4\n")


if __name__ == "__main__":
    main()
