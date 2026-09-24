"""Ties stages 2-5 together: ingest a file, classify it, and - if it's an
invoice - extract and validate it, then persist a Document (+ InvoiceRecord
for invoices) row. This is what the API's upload endpoint calls.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

import anthropic
from sqlalchemy.orm import Session

from invoice_pipeline import config
from invoice_pipeline.classification import classify_document
from invoice_pipeline.extraction import extract_invoice
from invoice_pipeline.ingestion import ingest_file, save_pages
from invoice_pipeline.models import Document, DocumentStatus, InvoiceRecord, utcnow
from invoice_pipeline.validation import validate_invoice

STORAGE_DIR = Path(config.STORAGE_DIR)
UPLOADS_DIR = STORAGE_DIR / "uploads"
PAGES_DIR = STORAGE_DIR / "pages"


def process_document(
    source_path: str | Path,
    session: Session,
    client: Optional[anthropic.Anthropic] = None,
    original_filename: Optional[str] = None,
) -> Document:
    """Run the full pipeline on a file and persist the result. Idempotent by
    content hash - re-processing the same bytes returns the existing row
    rather than re-running (and re-billing) classification/extraction."""
    source_path = Path(source_path)
    doc = ingest_file(source_path)
    original_filename = original_filename or source_path.name

    existing = session.get(Document, doc.doc_id)
    if existing is not None:
        return existing

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    stored_path = UPLOADS_DIR / f"{doc.doc_id}{source_path.suffix.lower()}"
    if not stored_path.exists():
        shutil.copyfile(source_path, stored_path)
    save_pages(doc, PAGES_DIR)

    classification = classify_document(doc, client=client)

    if classification.doc_type != "invoice":
        record = Document(
            id=doc.doc_id,
            source_filename=original_filename,
            file_path=str(stored_path),
            doc_type=classification.doc_type,
            classification_confidence=classification.confidence,
            status=DocumentStatus.UNRECOGNIZED,
            validation_issues=[],
            page_count=doc.page_count,
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        return record

    extraction = extract_invoice(doc, client=client)
    invoice = extraction.to_invoice()
    validation = validate_invoice(invoice, extraction=extraction, confidence_threshold=config.CONFIDENCE_THRESHOLD)
    status = DocumentStatus.PENDING_REVIEW if validation.requires_review else DocumentStatus.ACCEPTED

    record = Document(
        id=doc.doc_id,
        source_filename=original_filename,
        file_path=str(stored_path),
        doc_type=classification.doc_type,
        classification_confidence=classification.confidence,
        status=status,
        validation_issues=[{"rule": i.rule, "field": i.field, "message": i.message} for i in validation.issues],
        page_count=doc.page_count,
        resolved_at=None if status == DocumentStatus.PENDING_REVIEW else utcnow(),
    )
    record.invoice = InvoiceRecord(
        vendor_name=invoice.vendor_name,
        invoice_number=invoice.invoice_number,
        invoice_date=invoice.invoice_date,
        due_date=invoice.due_date,
        subtotal=invoice.subtotal,
        tax=invoice.tax,
        total_due=invoice.total_due,
        currency=invoice.currency,
        line_items=[li.model_dump() for li in invoice.line_items],
        field_meta=extraction.model_dump(),
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record
