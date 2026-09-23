import json
from pathlib import Path

import pytest

from invoice_pipeline.ingestion import (
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


def test_ingest_rejects_unsupported_file_type(tmp_path):
    bogus = tmp_path / "not_a_doc.txt"
    bogus.write_text("hello")
    with pytest.raises(UnsupportedFileTypeError):
        ingest_file(bogus)


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
