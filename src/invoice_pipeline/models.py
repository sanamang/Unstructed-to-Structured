"""ORM models for the review queue / system of record.

Document is one row per ingested file. It starts as `uploaded` (stored and
rasterized only) and moves to pending_review / accepted / unrecognized once
it's structured. InvoiceRecord holds the *current*
structured invoice data for a document - initially the extraction output
collapsed to plain values, overwritten in place as a human reviewer edits
fields. Correction is an append-only log of every human edit (field,
original value, corrected value) - the eval/feedback data.
"""

from __future__ import annotations

import datetime
import enum
from typing import Optional

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from invoice_pipeline.db import Base


def utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class DocumentStatus(str, enum.Enum):
    UPLOADED = "uploaded"  # stored + rasterized, not yet classified/extracted
    PENDING_REVIEW = "pending_review"
    ACCEPTED = "accepted"
    UNRECOGNIZED = "unrecognized"  # classified as not-an-invoice; no extraction run


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # ingestion doc_id (content hash)
    source_filename: Mapped[str] = mapped_column(String)
    file_path: Mapped[str] = mapped_column(String)  # where the original upload is stored on disk
    # Classification output ("invoice" / "unrecognized"); null until structured.
    doc_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    classification_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # What the document actually is ("receipt", "utility bill", "email", ...).
    document_kind: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[DocumentStatus] = mapped_column(Enum(DocumentStatus), default=DocumentStatus.UPLOADED)
    validation_issues: Mapped[list] = mapped_column(JSON, default=list)  # [{rule, field, message}, ...]
    page_count: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)
    resolved_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)

    invoice: Mapped[Optional["InvoiceRecord"]] = relationship(
        back_populates="document", uselist=False, cascade="all, delete-orphan"
    )
    corrections: Mapped[list["Correction"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class InvoiceRecord(Base):
    __tablename__ = "invoice_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), unique=True)

    vendor_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    invoice_number: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    invoice_date: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    due_date: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    subtotal: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tax: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total_due: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    line_items: Mapped[list] = mapped_column(JSON, default=list)
    # Everything else on the document, as [{label, value}, ...].
    additional_fields: Mapped[list] = mapped_column(JSON, default=list)

    # Raw stage-4 InvoiceExtraction dump (value/confidence/page per field) -
    # the review UI reads this to show confidence badges, independent of
    # whatever the current (possibly human-corrected) values above are.
    field_meta: Mapped[dict] = mapped_column(JSON, default=dict)

    document: Mapped["Document"] = relationship(back_populates="invoice")


class Correction(Base):
    __tablename__ = "corrections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    field: Mapped[str] = mapped_column(String)
    original_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    corrected_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    corrected_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)

    document: Mapped["Document"] = relationship(back_populates="corrections")
