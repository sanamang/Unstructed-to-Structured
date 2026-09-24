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


class ValidationIssueOut(BaseModel):
    rule: str
    field: Optional[str] = None
    message: str


class DocumentSummary(BaseModel):
    id: str
    source_filename: str
    doc_type: str
    classification_confidence: float
    status: str
    vendor_name: Optional[str] = None
    total_due: Optional[float] = None
    issue_count: int
    created_at: datetime.datetime


class DocumentDetail(DocumentSummary):
    page_count: int
    page_urls: list[str]
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    subtotal: Optional[float] = None
    tax: Optional[float] = None
    currency: Optional[str] = None
    line_items: list[LineItemOut] = []
    field_meta: dict[str, Any] = {}
    validation_issues: list[ValidationIssueOut] = []
    resolved_at: Optional[datetime.datetime] = None


class ReviewRequest(BaseModel):
    """Full current values for the editable fields, as the reviewer confirmed
    them (unchanged fields are just echoed back)."""

    fields: dict[str, Any]
