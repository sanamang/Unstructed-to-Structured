"""Shared invoice data schema.

Used both by the synthetic data generator (as the ground-truth shape) and,
in a later stage, by the extraction pipeline (as the target output shape).
Keeping one definition means eval can compare extracted output to ground
truth field-for-field without a translation layer.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class LineItem(BaseModel):
    description: str
    quantity: float
    unit_price: float
    line_total: float


class Invoice(BaseModel):
    vendor_name: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None  # ISO 8601 date string, e.g. "2025-03-14"
    due_date: Optional[str] = None
    line_items: list[LineItem] = []
    subtotal: Optional[float] = None
    tax: Optional[float] = None
    total_due: Optional[float] = None
    currency: Optional[str] = None
