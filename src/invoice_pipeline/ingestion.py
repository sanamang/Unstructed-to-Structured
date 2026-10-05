"""Ingestion layer: turn an incoming PDF or image file into a normalized set
of per-page images.

Downstream stages (classification, extraction) send page images directly to
Claude's vision input rather than running OCR-then-parse, since layout
position (a number under "Total Due" vs "Amount Paid") carries meaning that
plain-text OCR throws away. This module's only job is: accept whatever the
user drops in (PDF, a photo or scan in any common image format, a pasted
email or text file, an HTML page), decode it, and hand back a list of page
images at a consistent DPI/format, plus a stable document id. Text-like
inputs are laid out on letter-size pages so every document reaches the model
(and the review UI) the same way. A file with an unknown or missing
extension is sniffed by content.
"""

from __future__ import annotations

import base64
import email
import email.policy
import hashlib
import html
import io
from dataclasses import dataclass
from pathlib import Path

import pymupdf
from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError

try:  # iPhone photos are HEIC by default
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIF_SUFFIXES = {".heic", ".heif"}
except ImportError:  # pragma: no cover - optional dependency
    HEIF_SUFFIXES = set()

SUPPORTED_PDF_SUFFIXES = {".pdf"}
SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".gif"} | HEIF_SUFFIXES
# Laid out onto pages by MuPDF. .eml is parsed first so the model sees the
# decoded message body rather than raw MIME.
SUPPORTED_TEXT_SUFFIXES = {".txt", ".text", ".md", ".csv", ".tsv", ".log", ".json", ".xml", ".eml"}
SUPPORTED_HTML_SUFFIXES = {".html", ".htm"}
# Other document formats MuPDF opens natively.
SUPPORTED_MUPDF_SUFFIXES = {".xps", ".oxps", ".epub", ".svg", ".fb2", ".mobi"}
SUPPORTED_SUFFIXES = (
    SUPPORTED_PDF_SUFFIXES
    | SUPPORTED_IMAGE_SUFFIXES
    | SUPPORTED_TEXT_SUFFIXES
    | SUPPORTED_HTML_SUFFIXES
    | SUPPORTED_MUPDF_SUFFIXES
)

DEFAULT_DPI = 200
# Longest page edge, in pixels. A 200 DPI letter page (1700x2200) fits; a
# 12-megapixel phone photo or an oversized PDF page is scaled down to it,
# which keeps every page well inside the API's image limits.
MAX_PAGE_EDGE = 2400
# Base64 image payloads over 5 MB are rejected by the API. A page whose PNG
# would come close (a noisy photo) is sent as JPEG instead.
MAX_PNG_BYTES = 3_500_000
TEXT_PAGE_WIDTH, TEXT_PAGE_HEIGHT = 612, 792  # US letter, in points


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

    def to_api_image(self) -> tuple[str, str]:
        """(media_type, base64 data) for the Messages API: PNG, or JPEG when
        the PNG would be too large to send."""
        buf = io.BytesIO()
        self.image.save(buf, format="PNG")
        if buf.tell() <= MAX_PNG_BYTES:
            return "image/png", base64.b64encode(buf.getvalue()).decode("ascii")
        buf = io.BytesIO()
        self.image.save(buf, format="JPEG", quality=90)
        return "image/jpeg", base64.b64encode(buf.getvalue()).decode("ascii")


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


def _rasterize(doc: pymupdf.Document, dpi: int) -> list[Image.Image]:
    images = []
    for page in doc:
        long_side = max(page.rect.width, page.rect.height) or 1
        zoom = min(dpi / 72, MAX_PAGE_EDGE / long_side)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        images.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
    doc.close()
    return images


def _rasterize_pdf(data: bytes, dpi: int) -> list[Image.Image]:
    return _rasterize(pymupdf.open(stream=data, filetype="pdf"), dpi)


def _rasterize_reflowable(data: bytes, filetype: str, dpi: int) -> list[Image.Image]:
    """Lay out a text/HTML/ebook-style document on letter pages and render it."""
    doc = pymupdf.open(stream=data, filetype=filetype)
    if doc.is_reflowable:
        doc.layout(width=TEXT_PAGE_WIDTH, height=TEXT_PAGE_HEIGHT, fontsize=10)
    return _rasterize(doc, dpi)


def _normalize_image(img: Image.Image) -> Image.Image:
    """Upright, RGB on a white background, and no larger than MAX_PAGE_EDGE."""
    img = ImageOps.exif_transpose(img)  # phone photos store rotation as a tag
    if img.mode in ("RGBA", "LA", "P", "PA"):
        img = img.convert("RGBA")
        background = Image.new("RGB", img.size, "white")
        background.paste(img, mask=img.getchannel("A"))
        img = background
    else:
        img = img.convert("RGB")
    if max(img.size) > MAX_PAGE_EDGE:
        img.thumbnail((MAX_PAGE_EDGE, MAX_PAGE_EDGE), Image.LANCZOS)
    return img


def _load_images(data: bytes) -> list[Image.Image]:
    """Every frame of an image file (multi-page TIFFs are common for faxed
    and scanned invoices)."""
    img = Image.open(io.BytesIO(data))
    frames = [_normalize_image(frame.copy()) for frame in ImageSequence.Iterator(img)]
    # An animated GIF's frames are not pages.
    return frames[:1] if img.format == "GIF" else frames


def _email_to_html(data: bytes) -> tuple[bytes, list[tuple[str, bytes]]]:
    """Decode a raw .eml into a simple HTML page (headers + body) plus any
    attachments that are themselves documents (PDFs, images), so a bill
    sent as an attachment is still read."""
    message = email.message_from_bytes(data, policy=email.policy.default)
    header_lines = [
        f"<b>{name}:</b> {html.escape(str(message[name]))}<br>"
        for name in ("From", "To", "Date", "Subject")
        if message[name]
    ]
    body = message.get_body(preferencelist=("plain", "html"))
    if body is None:
        body_html = ""
    elif body.get_content_type() == "text/html":
        body_html = body.get_content()
    else:
        body_html = f"<pre style='white-space: pre-wrap'>{html.escape(body.get_content())}</pre>"

    attachments = []
    for part in message.iter_attachments():
        filename = part.get_filename() or ""
        suffix = Path(filename).suffix.lower()
        if suffix in SUPPORTED_PDF_SUFFIXES | SUPPORTED_IMAGE_SUFFIXES:
            attachments.append((suffix, part.get_content()))

    page = "<html><body>" + "".join(header_lines) + "<hr>" + body_html + "</body></html>"
    return page.encode("utf-8"), attachments


def _sniff_suffix(data: bytes) -> str:
    """Guess a file type from its content, for uploads with an unknown or
    missing extension."""
    if data.lstrip()[:5] == b"%PDF-":
        return ".pdf"
    try:
        Image.open(io.BytesIO(data)).verify()
        return ".png"  # any Pillow-readable image; the suffix only selects the loader
    except (UnidentifiedImageError, OSError, SyntaxError):
        pass
    head = data[:2048].lower()
    if b"<html" in head or b"<!doctype html" in head:
        return ".html"
    if head.startswith((b"from:", b"received:", b"return-path:", b"mime-version:", b"date:", b"subject:")):
        return ".eml"
    try:
        data.decode("utf-8")
        return ".txt"
    except UnicodeDecodeError:
        pass
    try:
        pymupdf.open(stream=data).close()  # anything else MuPDF can read
        return ".xps"
    except Exception:
        raise UnsupportedFileTypeError(
            f"Couldn't read this file; expected a PDF, an image, or a text/HTML/email document "
            f"({', '.join(sorted(SUPPORTED_SUFFIXES))})"
        )


def _decode_text(data: bytes) -> bytes:
    """Re-encode text of unknown encoding as UTF-8, which MuPDF expects."""
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(encoding).encode("utf-8")
        except UnicodeDecodeError:
            continue
    return data


def _render_pages(data: bytes, suffix: str, dpi: int) -> list[Image.Image]:
    if suffix not in SUPPORTED_SUFFIXES:
        suffix = _sniff_suffix(data)

    if suffix in SUPPORTED_PDF_SUFFIXES:
        return _rasterize_pdf(data, dpi)
    if suffix in SUPPORTED_IMAGE_SUFFIXES:
        return _load_images(data)
    if suffix == ".eml":
        page_html, attachments = _email_to_html(data)
        pages = _rasterize_reflowable(page_html, "html", dpi)
        for attachment_suffix, attachment in attachments:
            pages += _render_pages(attachment, attachment_suffix, dpi)
        return pages
    if suffix in SUPPORTED_HTML_SUFFIXES:
        return _rasterize_reflowable(_decode_text(data), "html", dpi)
    if suffix in SUPPORTED_TEXT_SUFFIXES:
        return _rasterize_reflowable(_decode_text(data), "txt", dpi)
    return _rasterize(pymupdf.open(stream=data, filetype=suffix.lstrip(".")), dpi)


def ingest_bytes(data: bytes, suffix: str, dpi: int = DEFAULT_DPI) -> IngestedDocument:
    """Ingest raw file bytes given a filename suffix (e.g. ".pdf", ".jpg").
    An unknown or empty suffix is sniffed from the content."""
    suffix = suffix.lower()
    doc_id = _doc_id_for_bytes(data)

    if not data.strip():
        raise UnsupportedFileTypeError("The file is empty")
    try:
        page_images = _render_pages(data, suffix, dpi)
    except UnsupportedFileTypeError:
        raise
    except Exception as e:  # corrupt or mislabeled file
        raise UnsupportedFileTypeError(f"Couldn't read this {suffix or 'file'}: {e}") from e
    if not page_images:
        raise UnsupportedFileTypeError("The file has no pages")

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
        media_type, data = page.to_api_image()
        blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": data,
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
