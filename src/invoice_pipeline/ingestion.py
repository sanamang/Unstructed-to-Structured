"""Ingestion layer: turn an incoming PDF or image file into a normalized set
of per-page images.

Downstream stages (classification, extraction) send page images directly to
Claude's vision input rather than running OCR-then-parse, since layout
position (a number under "Total Due" vs "Amount Paid") carries meaning that
plain-text OCR throws away. This module's only job is: accept whatever the
user drops in (single/multi-page PDF, PNG, JPEG), decode it, and hand back a
list of page images at a consistent DPI/format, plus a stable document id.
"""

from __future__ import annotations

import base64
import hashlib
import io
from dataclasses import dataclass
from pathlib import Path

import pymupdf
from PIL import Image

SUPPORTED_PDF_SUFFIXES = {".pdf"}
SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
SUPPORTED_SUFFIXES = SUPPORTED_PDF_SUFFIXES | SUPPORTED_IMAGE_SUFFIXES

DEFAULT_DPI = 200


class UnsupportedFileTypeError(ValueError):
    pass


@dataclass
class PageImage:
    page_number: int  # 1-indexed
    image: Image.Image

    @property
    def width(self) -> int:
        return self.image.width

    @property
    def height(self) -> int:
        return self.image.height

    def to_base64_png(self) -> str:
        buf = io.BytesIO()
        self.image.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("ascii")


@dataclass
class IngestedDocument:
    source_path: Path
    doc_id: str
    pages: list[PageImage]

    @property
    def page_count(self) -> int:
        return len(self.pages)


def _doc_id_for_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def _rasterize_pdf(data: bytes, dpi: int) -> list[Image.Image]:
    doc = pymupdf.open(stream=data, filetype="pdf")
    zoom = dpi / 72
    matrix = pymupdf.Matrix(zoom, zoom)
    images = []
    for page in doc:
        pix = page.get_pixmap(matrix=matrix)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        images.append(img)
    doc.close()
    return images


def ingest_bytes(data: bytes, suffix: str, dpi: int = DEFAULT_DPI) -> IngestedDocument:
    """Ingest raw file bytes given a filename suffix (e.g. ".pdf", ".jpg")."""
    suffix = suffix.lower()
    doc_id = _doc_id_for_bytes(data)

    if suffix in SUPPORTED_PDF_SUFFIXES:
        page_images = _rasterize_pdf(data, dpi)
    elif suffix in SUPPORTED_IMAGE_SUFFIXES:
        page_images = [Image.open(io.BytesIO(data)).convert("RGB")]
    else:
        raise UnsupportedFileTypeError(
            f"Unsupported file type {suffix!r}; expected one of {sorted(SUPPORTED_SUFFIXES)}"
        )

    pages = [PageImage(page_number=i + 1, image=img) for i, img in enumerate(page_images)]
    return IngestedDocument(source_path=Path(f"<bytes>{suffix}"), doc_id=doc_id, pages=pages)


def ingest_file(path: str | Path, dpi: int = DEFAULT_DPI) -> IngestedDocument:
    path = Path(path)
    data = path.read_bytes()
    doc = ingest_bytes(data, suffix=path.suffix, dpi=dpi)
    doc.source_path = path
    return doc


def pages_to_content_blocks(pages: list[PageImage]) -> list[dict]:
    """Build Claude Messages API image content blocks for a list of pages,
    each preceded by a page-number text block so the model can cite which
    page it read a field from."""
    blocks: list[dict] = []
    for page in pages:
        blocks.append({"type": "text", "text": f"Page {page.page_number}:"})
        blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": page.to_base64_png(),
                },
            }
        )
    return blocks


def save_pages(doc: IngestedDocument, output_dir: str | Path) -> list[Path]:
    """Persist normalized page images as PNGs, e.g. for the review UI to
    display or for caching so extraction doesn't need to re-rasterize."""
    output_dir = Path(output_dir) / doc.doc_id
    output_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for page in doc.pages:
        out_path = output_dir / f"page_{page.page_number:03d}.png"
        page.image.save(out_path, format="PNG")
        written.append(out_path)
    return written
