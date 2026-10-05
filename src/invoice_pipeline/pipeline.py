"""Ties stages 2-5 together in two steps, which the API exposes separately:

1. `ingest_upload` - store the file, rasterize its pages, and persist a
   Document in `uploaded` status. No model calls.
2. `structure_document` - classify it and, if it's an invoice, extract and
   validate it, then move it to pending_review / accepted / unrecognized.

`process_document` runs both back to back.
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
from invoice_pipeline.validation import structure_and_validate

STORAGE_DIR = Path(config.STORAGE_DIR)
UPLOADS_DIR = STORAGE_DIR / "uploads"
PAGES_DIR = STORAGE_DIR / "pages"


class AlreadyStructuredError(Exception):
    pass


def ingest_upload(
    source_path: str | Path,
    session: Session,
    original_filename: Optional[str] = None,
) -> Document:
    """Store and rasterize a file and persist it as `uploaded`. Idempotent by
    content hash - re-uploading the same bytes returns the existing row, in
    whatever state it's in, rather than creating a duplicate."""
    source_path = Path(source_path)
    doc = ingest_file(source_path)

    existing = session.get(Document, doc.doc_id)
    if existing is not None:
        return existing

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    stored_path = UPLOADS_DIR / f"{doc.doc_id}{source_path.suffix.lower()}"
    if not stored_path.exists():
        shutil.copyfile(source_path, stored_path)
    save_pages(doc, PAGES_DIR)

    record = Document(
        id=doc.doc_id,
        source_filename=original_filename or source_path.name,
        file_path=str(stored_path),
        status=DocumentStatus.UPLOADED,
        validation_issues=[],
        page_count=doc.page_count,
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def structure_document(
    record: Document,
    session: Session,
    client: Optional[anthropic.Anthropic] = None,
) -> Document:
    """Classify an uploaded document and, if it's an invoice, extract and
    validate its fields. Only runs once per document, so a double-click
    can't bill the API twice."""
    if record.status != DocumentStatus.UPLOADED:
        raise AlreadyStructuredError(f"document {record.id} is already structured ({record.status.value})")

    doc = ingest_file(record.file_path)
    classification = classify_document(doc, client=client)
    record.doc_type = classification.doc_type
    record.classification_confidence = classification.confidence
    record.document_kind = classification.document_kind or None

    if classification.doc_type != "invoice":
        record.status = DocumentStatus.UNRECOGNIZED
        session.commit()
        session.refresh(record)
        return record

    extraction = extract_invoice(doc, client=client)
    invoice, validation = structure_and_validate(extraction, confidence_threshold=config.CONFIDENCE_THRESHOLD)
    status = DocumentStatus.PENDING_REVIEW if validation.requires_review else DocumentStatus.ACCEPTED

    record.status = status
    record.validation_issues = [
        {"rule": i.rule, "field": i.field, "message": i.message, "severity": i.severity} for i in validation.issues
    ]
    record.resolved_at = None if status == DocumentStatus.PENDING_REVIEW else utcnow()
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
        additional_fields=[f.model_dump() for f in invoice.additional_fields],
        field_meta=extraction.model_dump(),
    )
    session.commit()
    session.refresh(record)
    return record


def process_document(
    source_path: str | Path,
    session: Session,
    client: Optional[anthropic.Anthropic] = None,
    original_filename: Optional[str] = None,
) -> Document:
    """Upload and structure in one go. Idempotent by content hash - a file
    that's already been structured is returned as-is without re-running
    (and re-billing) classification/extraction."""
    record = ingest_upload(source_path, session, original_filename=original_filename)
    if record.status == DocumentStatus.UPLOADED:
        record = structure_document(record, session, client=client)
    return record
