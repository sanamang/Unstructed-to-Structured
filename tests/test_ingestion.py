import json
from email.message import EmailMessage
from pathlib import Path

import pytest
from PIL import Image

from invoice_pipeline.ingestion import (
    MAX_PAGE_EDGE,
    PageImage,
    UnsupportedFileTypeError,
    ingest_file,
    save_pages,
)

SAMPLE_DATA = Path(__file__).resolve().parent.parent / "sample_data"


def _first_sample(suffix: str) -> Path:
    manifest = json.loads((SAMPLE_DATA / "manifest.json").read_text())
    for record in manifest:
        if record["file"].endswith(suffix):
            return SAMPLE_DATA / record["file"]
    pytest.skip(f"no sample file with suffix {suffix} found")


def test_ingest_pdf_produces_one_page_per_pdf_page():
    doc = ingest_file(_first_sample(".pdf"))
    assert doc.page_count == 1
    page = doc.pages[0]
    assert page.width > 0 and page.height > 0
    assert page.image.mode == "RGB"


def test_ingest_scanned_jpg_produces_single_page():
    doc = ingest_file(_first_sample(".jpg"))
    assert doc.page_count == 1
    assert doc.pages[0].image.mode == "RGB"


def test_ingest_is_deterministic_doc_id_for_same_bytes():
    path = _first_sample(".pdf")
    doc1 = ingest_file(path)
    doc2 = ingest_file(path)
    assert doc1.doc_id == doc2.doc_id


def test_ingest_rejects_unreadable_file(tmp_path):
    bogus = tmp_path / "not_a_doc.bin"
    bogus.write_bytes(bytes(range(256)) * 4)
    with pytest.raises(UnsupportedFileTypeError):
        ingest_file(bogus)


def test_ingest_rejects_empty_file(tmp_path):
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")
    with pytest.raises(UnsupportedFileTypeError):
        ingest_file(empty)


def test_ingest_text_file_renders_pages(tmp_path):
    note = tmp_path / "bill.txt"
    note.write_text("Tom's Moving Co.\n3 movers x 5 hrs @ $45/hr = $675\nTotal $933.50\n")
    doc = ingest_file(note)
    assert doc.page_count == 1
    assert doc.pages[0].image.mode == "RGB"


def test_ingest_eml_includes_body_and_pdf_attachment(tmp_path):
    message = EmailMessage()
    message["From"] = "dave@plumbing.example"
    message["Subject"] = "bill"
    message.set_content("faucet 189.99, total 218.49")
    message.add_attachment(
        _first_sample(".pdf").read_bytes(), maintype="application", subtype="pdf", filename="invoice.pdf"
    )
    path = tmp_path / "bill.eml"
    path.write_bytes(message.as_bytes())
    assert ingest_file(path).page_count == 2  # the email body, then the attached PDF


def test_ingest_html_file_renders_pages(tmp_path):
    page = tmp_path / "bill.html"
    page.write_text("<h1>Receipt</h1><table><tr><td>Coffee</td><td>$4.50</td></tr></table>")
    assert ingest_file(page).page_count == 1


def test_ingest_sniffs_files_without_an_extension(tmp_path):
    pdf = tmp_path / "upload"
    pdf.write_bytes(_first_sample(".pdf").read_bytes())
    assert ingest_file(pdf).page_count == 1
    text = tmp_path / "pasted"
    text.write_text("lawn care - mowed 3x @ 40")
    assert ingest_file(text).page_count == 1


def test_ingest_image_is_rotated_upright_flattened_and_downscaled(tmp_path):
    # Landscape pixels with an EXIF "rotate 90" flag, as phones save photos.
    photo = Image.new("RGB", (5000, 3000), "white")
    exif = Image.Exif()
    exif[0x0112] = 6
    photo_path = tmp_path / "photo.jpg"
    photo.save(photo_path, exif=exif)
    page = ingest_file(photo_path).pages[0]
    assert page.height > page.width  # displayed upright (portrait)
    assert max(page.width, page.height) <= MAX_PAGE_EDGE

    transparent = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    png_path = tmp_path / "transparent.png"
    transparent.save(png_path)
    assert ingest_file(png_path).pages[0].image.getpixel((50, 50)) == (255, 255, 255)


def test_ingest_multi_page_tiff_keeps_every_page(tmp_path):
    frames = [Image.new("RGB", (200, 300), color) for color in ("white", "gray", "black")]
    path = tmp_path / "fax.tiff"
    frames[0].save(path, save_all=True, append_images=frames[1:])
    assert ingest_file(path).page_count == 3


def test_ingest_webp(tmp_path):
    path = tmp_path / "photo.webp"
    Image.new("RGB", (300, 400), "white").save(path)
    assert ingest_file(path).page_count == 1


def test_large_page_is_sent_as_jpeg():
    noisy = Image.effect_noise((2400, 2400), 100).convert("RGB")
    media_type, _ = PageImage(page_number=1, image=noisy).to_api_image()
    assert media_type == "image/jpeg"


def test_page_image_encodes_to_base64_png():
    doc = ingest_file(_first_sample(".pdf"))
    encoded = doc.pages[0].to_base64_png()
    assert isinstance(encoded, str)
    assert len(encoded) > 100


def test_save_pages_writes_png_per_page(tmp_path):
    doc = ingest_file(_first_sample(".pdf"))
    written = save_pages(doc, tmp_path)
    assert len(written) == doc.page_count
    for p in written:
        assert p.exists()
        assert p.suffix == ".png"
