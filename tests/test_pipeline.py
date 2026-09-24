import invoice_pipeline.pipeline as pipeline_module
from invoice_pipeline.classification import DocumentClassification
from invoice_pipeline.models import Document, DocumentStatus
from invoice_pipeline.pipeline import process_document
from invoice_pipeline.schema import ExtractedNumber, ExtractedString, InvoiceExtraction, LineItemExtraction


def _clean_extraction() -> InvoiceExtraction:
    high = 0.95
    return InvoiceExtraction(
        vendor_name=ExtractedString(value="Acme Industrial Supplies", confidence=high, page=1),
        invoice_number=ExtractedString(value="INV-000123", confidence=high, page=1),
        invoice_date=ExtractedString(value="2025-01-01", confidence=high, page=1),
        due_date=ExtractedString(value="2025-01-31", confidence=high, page=1),
        line_items=[
            LineItemExtraction(
                description=ExtractedString(value="Widget", confidence=high, page=1),
                quantity=ExtractedNumber(value=2, confidence=high, page=1),
                unit_price=ExtractedNumber(value=10.0, confidence=high, page=1),
                line_total=ExtractedNumber(value=20.0, confidence=high, page=1),
            )
        ],
        subtotal=ExtractedNumber(value=20.0, confidence=high, page=1),
        tax=ExtractedNumber(value=1.6, confidence=high, page=1),
        total_due=ExtractedNumber(value=21.6, confidence=high, page=1),
        currency=ExtractedString(value="USD", confidence=high, page=1),
    )


def _low_confidence_extraction() -> InvoiceExtraction:
    extraction = _clean_extraction()
    extraction.due_date.confidence = 0.3
    return extraction


def _patch_storage_dirs(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline_module, "UPLOADS_DIR", tmp_path / "uploads")
    monkeypatch.setattr(pipeline_module, "PAGES_DIR", tmp_path / "pages")


def test_process_document_with_clean_extraction_is_accepted(db_session, tmp_path, monkeypatch):
    _patch_storage_dirs(monkeypatch, tmp_path)
    monkeypatch.setattr(
        pipeline_module, "classify_document", lambda doc, client=None: DocumentClassification(
            doc_type="invoice", confidence=0.98, reasoning="looks like an invoice"
        )
    )
    monkeypatch.setattr(pipeline_module, "extract_invoice", lambda doc, client=None: _clean_extraction())

    document = process_document("manual_test_pdfs/test_invoice_01.pdf", session=db_session)

    assert document.status == DocumentStatus.ACCEPTED
    assert document.invoice.vendor_name == "Acme Industrial Supplies"
    assert document.invoice.field_meta["due_date"]["confidence"] == 0.95
    assert document.validation_issues == []
    assert document.resolved_at is not None
    assert (tmp_path / "pages" / document.id / "page_001.png").exists()


def test_process_document_with_low_confidence_is_pending_review(db_session, tmp_path, monkeypatch):
    _patch_storage_dirs(monkeypatch, tmp_path)
    monkeypatch.setattr(
        pipeline_module, "classify_document", lambda doc, client=None: DocumentClassification(
            doc_type="invoice", confidence=0.98, reasoning="looks like an invoice"
        )
    )
    monkeypatch.setattr(pipeline_module, "extract_invoice", lambda doc, client=None: _low_confidence_extraction())

    document = process_document("manual_test_pdfs/test_invoice_01.pdf", session=db_session)

    assert document.status == DocumentStatus.PENDING_REVIEW
    assert document.resolved_at is None
    assert any(issue["rule"] == "low_confidence_field" for issue in document.validation_issues)


def test_process_document_marks_non_invoice_as_unrecognized(db_session, tmp_path, monkeypatch):
    _patch_storage_dirs(monkeypatch, tmp_path)
    monkeypatch.setattr(
        pipeline_module, "classify_document", lambda doc, client=None: DocumentClassification(
            doc_type="unrecognized", confidence=0.9, reasoning="not an invoice"
        )
    )

    def _fail_extract(*args, **kwargs):
        raise AssertionError("extract_invoice should not be called for a non-invoice document")

    monkeypatch.setattr(pipeline_module, "extract_invoice", _fail_extract)

    document = process_document("manual_test_pdfs/test_invoice_01.pdf", session=db_session)

    assert document.status == DocumentStatus.UNRECOGNIZED
    assert document.invoice is None


def test_process_document_is_idempotent_for_the_same_file(db_session, tmp_path, monkeypatch):
    _patch_storage_dirs(monkeypatch, tmp_path)
    call_count = {"classify": 0}

    def _classify(doc, client=None):
        call_count["classify"] += 1
        return DocumentClassification(doc_type="invoice", confidence=0.98, reasoning="ok")

    monkeypatch.setattr(pipeline_module, "classify_document", _classify)
    monkeypatch.setattr(pipeline_module, "extract_invoice", lambda doc, client=None: _clean_extraction())

    first = process_document("manual_test_pdfs/test_invoice_01.pdf", session=db_session)
    second = process_document("manual_test_pdfs/test_invoice_01.pdf", session=db_session)

    assert first.id == second.id
    assert call_count["classify"] == 1
    assert db_session.query(Document).count() == 1
