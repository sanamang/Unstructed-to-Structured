"""Stage 6 backend: review queue API.

Lists flagged (and accepted/unrecognized) documents, serves the original
page images alongside extracted fields, accepts human corrections, and logs
every corrected field to the Correction table.
"""

from __future__ import annotations

import json
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from invoice_pipeline.api.schemas import DocumentDetail, DocumentSummary, ReviewRequest
from invoice_pipeline.db import SessionLocal, init_db
from invoice_pipeline.export import accepted_invoices, invoices_csv, line_items_csv, to_json
from invoice_pipeline.models import Correction, Document, DocumentStatus, InvoiceRecord, utcnow
from invoice_pipeline.pipeline import PAGES_DIR, UPLOADS_DIR, process_document


@asynccontextmanager
async def lifespan(app: FastAPI):
    PAGES_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    app.mount("/static/pages", StaticFiles(directory=PAGES_DIR), name="pages")
    yield


app = FastAPI(title="Invoice Extraction Pipeline API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SCALAR_INVOICE_FIELDS = (
    "vendor_name",
    "invoice_number",
    "invoice_date",
    "due_date",
    "subtotal",
    "tax",
    "total_due",
    "currency",
)

EXPORTS = {
    "invoices.csv": (invoices_csv, "text/csv"),
    "line_items.csv": (line_items_csv, "text/csv"),
    "invoices.json": (to_json, "application/json"),
}


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _page_urls(document: Document) -> list[str]:
    return [f"/static/pages/{document.id}/page_{n:03d}.png" for n in range(1, document.page_count + 1)]


def _to_summary(document: Document) -> DocumentSummary:
    invoice = document.invoice
    return DocumentSummary(
        id=document.id,
        source_filename=document.source_filename,
        doc_type=document.doc_type,
        classification_confidence=document.classification_confidence,
        status=document.status.value,
        vendor_name=invoice.vendor_name if invoice else None,
        total_due=invoice.total_due if invoice else None,
        issue_count=len(document.validation_issues or []),
        created_at=document.created_at,
    )


def _to_detail(document: Document) -> DocumentDetail:
    invoice = document.invoice
    return DocumentDetail(
        **_to_summary(document).model_dump(),
        page_count=document.page_count,
        page_urls=_page_urls(document),
        invoice_number=invoice.invoice_number if invoice else None,
        invoice_date=invoice.invoice_date if invoice else None,
        due_date=invoice.due_date if invoice else None,
        subtotal=invoice.subtotal if invoice else None,
        tax=invoice.tax if invoice else None,
        currency=invoice.currency if invoice else None,
        line_items=invoice.line_items if invoice else [],
        field_meta=invoice.field_meta if invoice else {},
        validation_issues=document.validation_issues or [],
        resolved_at=document.resolved_at,
    )


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/documents", response_model=list[DocumentSummary])
def list_documents(status: Optional[str] = None, session: Session = Depends(get_session)):
    query = session.query(Document)
    if status:
        try:
            query = query.filter(Document.status == DocumentStatus(status))
        except ValueError:
            raise HTTPException(400, f"invalid status {status!r}")
    documents = query.order_by(Document.created_at.desc()).all()
    return [_to_summary(d) for d in documents]


@app.get("/api/documents/{doc_id}", response_model=DocumentDetail)
def get_document(doc_id: str, session: Session = Depends(get_session)):
    document = session.get(Document, doc_id)
    if document is None:
        raise HTTPException(404, "document not found")
    return _to_detail(document)


@app.get("/api/export/{filename}")
def export_accepted(filename: str, session: Session = Depends(get_session)):
    """Download accepted invoices as invoices.csv, line_items.csv, or invoices.json."""
    if filename not in EXPORTS:
        raise HTTPException(404, f"unknown export {filename!r}; expected one of {sorted(EXPORTS)}")
    render, media_type = EXPORTS[filename]
    return Response(
        content=render(accepted_invoices(session)),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/upload", response_model=DocumentDetail)
def upload_document(file: UploadFile = File(...), session: Session = Depends(get_session)):
    suffix = Path(file.filename or "upload").suffix or ".pdf"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file.file.read())
        tmp_path = Path(tmp.name)
    try:
        document = process_document(tmp_path, session=session, original_filename=file.filename or tmp_path.name)
    finally:
        tmp_path.unlink(missing_ok=True)
    return _to_detail(document)


@app.post("/api/documents/{doc_id}/review", response_model=DocumentDetail)
def review_document(doc_id: str, payload: ReviewRequest, session: Session = Depends(get_session)):
    document = session.get(Document, doc_id)
    if document is None:
        raise HTTPException(404, "document not found")
    if document.invoice is None:
        raise HTTPException(400, "document has no extracted invoice to review")

    invoice_record: InvoiceRecord = document.invoice
    now = utcnow()

    for field_name in SCALAR_INVOICE_FIELDS:
        if field_name not in payload.fields:
            continue
        new_value = payload.fields[field_name]
        old_value = getattr(invoice_record, field_name)
        if new_value != old_value:
            session.add(
                Correction(
                    document_id=doc_id,
                    field=field_name,
                    original_value=None if old_value is None else str(old_value),
                    corrected_value=None if new_value is None else str(new_value),
                    corrected_at=now,
                )
            )
            setattr(invoice_record, field_name, new_value)

    if "line_items" in payload.fields:
        new_items = payload.fields["line_items"]
        if new_items != invoice_record.line_items:
            session.add(
                Correction(
                    document_id=doc_id,
                    field="line_items",
                    original_value=json.dumps(invoice_record.line_items),
                    corrected_value=json.dumps(new_items),
                    corrected_at=now,
                )
            )
            invoice_record.line_items = new_items

    document.status = DocumentStatus.ACCEPTED
    document.resolved_at = now
    session.commit()
    session.refresh(document)
    return _to_detail(document)
