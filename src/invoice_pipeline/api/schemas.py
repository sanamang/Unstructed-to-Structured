"""API request/response models. Distinct from invoice_pipeline.schema, which
models the extraction stage's LLM output - these model the review queue's
HTTP surface."""

from __future__ import annotations

import datetime
from typing import Any, Optional

from pydantic import BaseModel


class LineItemOut(BaseModel):
    description: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    line_total: Optional[float] = None


class AdditionalFieldOut(BaseModel):
    label: str
    value: str


class ValidationIssueOut(BaseModel):
    rule: str
    field: Optional[str] = None
    message: str
    severity: str = "error"  # "error" blocks auto-accept; "info" is a note (rows from before severity existed are errors)


class DocumentSummary(BaseModel):
    id: str
    source_filename: str
    doc_type: Optional[str] = None  # null until the document is structured
    classification_confidence: Optional[float] = None
    document_kind: Optional[str] = None  # "receipt", "utility bill", "email", ...
    status: str
    vendor_name: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    total_due: Optional[float] = None
    currency: Optional[str] = None
    issue_count: int
    validation_issues: list[ValidationIssueOut] = []
    min_confidence: Optional[float] = None  # lowest per-field extraction confidence
    created_at: datetime.datetime
    resolved_at: Optional[datetime.datetime] = None


class DocumentDetail(DocumentSummary):
    page_count: int
    page_urls: list[str]
    due_date: Optional[str] = None
    subtotal: Optional[float] = None
    tax: Optional[float] = None
    line_items: list[LineItemOut] = []
    additional_fields: list[AdditionalFieldOut] = []
    field_meta: dict[str, Any] = {}


class ReviewRequest(BaseModel):
    """Full current values for the editable fields, as the reviewer confirmed
    them (unchanged fields are just echoed back)."""

    fields: dict[str, Any]
