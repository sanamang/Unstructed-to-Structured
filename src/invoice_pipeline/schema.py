"""Shared invoice data schema.

Used both by the synthetic data generator (as the ground-truth shape) and,
in a later stage, by the extraction pipeline (as the target output shape).
Keeping one definition means eval can compare extracted output to ground
truth field-for-field without a translation layer.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


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


class ExtractedString(BaseModel):
    value: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)
    page: Optional[int] = None


class ExtractedNumber(BaseModel):
    value: Optional[float] = None
    confidence: float = Field(ge=0.0, le=1.0)
    page: Optional[int] = None


class LineItemExtraction(BaseModel):
    description: ExtractedString
    quantity: ExtractedNumber
    unit_price: ExtractedNumber
    line_total: ExtractedNumber


class InvoiceExtraction(BaseModel):
    """Output shape of the extraction stage: every field carries a confidence
    score and, where applicable, the page it was read from. `to_invoice()`
    collapses this down to the plain `Invoice` shape used by validation/eval."""

    vendor_name: ExtractedString
    invoice_number: ExtractedString
    invoice_date: ExtractedString
    due_date: ExtractedString
    line_items: list[LineItemExtraction] = []
    subtotal: ExtractedNumber
    tax: ExtractedNumber
    total_due: ExtractedNumber
    currency: ExtractedString

    def to_invoice(self) -> Invoice:
        return Invoice(
            vendor_name=self.vendor_name.value,
            invoice_number=self.invoice_number.value,
            invoice_date=self.invoice_date.value,
            due_date=self.due_date.value,
            line_items=[
                LineItem(
                    description=li.description.value or "",
                    quantity=li.quantity.value if li.quantity.value is not None else 0.0,
                    unit_price=li.unit_price.value if li.unit_price.value is not None else 0.0,
                    line_total=li.line_total.value if li.line_total.value is not None else 0.0,
                )
                for li in self.line_items
            ],
            subtotal=self.subtotal.value,
            tax=self.tax.value,
            total_due=self.total_due.value,
            currency=self.currency.value,
        )
