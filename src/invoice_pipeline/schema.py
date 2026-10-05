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


class AdditionalField(BaseModel):
    """Anything on the document outside the fixed invoice fields (PO number,
    account number, bill-to, payment terms, deposits, notes...), kept as a
    label/value pair so no information is dropped whatever the layout."""

    label: str
    value: str


def complete_line_item(
    quantity: Optional[float], unit_price: Optional[float], line_total: Optional[float]
) -> tuple[float, float, float]:
    """Fill a line item's missing numbers from the ones that are present
    (quantity x unit price = line total; an amount-only line is quantity 1),
    and set anything that still can't be worked out to 0."""
    q, p, t = quantity, unit_price, line_total
    if t is None and q is not None and p is not None:
        t = round(q * p, 2)
    if t is not None:
        if q is None and p:
            q = round(t / p, 4)
        elif q is None:
            q, p = 1.0, t
        if p is None:
            p = round(t / q, 4) if q else t
    elif p is not None:  # a price with no quantity or total
        q, t = 1.0, p
    return (q or 0.0, p or 0.0, t or 0.0)


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
    additional_fields: list[AdditionalField] = []


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
    additional_fields: list[AdditionalField] = []

    def to_invoice(self) -> Invoice:
        line_items = []
        for li in self.line_items:
            quantity, unit_price, line_total = complete_line_item(
                li.quantity.value, li.unit_price.value, li.line_total.value
            )
            line_items.append(
                LineItem(
                    description=li.description.value or "",
                    quantity=quantity,
                    unit_price=unit_price,
                    line_total=line_total,
                )
            )
        return Invoice(
            vendor_name=self.vendor_name.value,
            invoice_number=self.invoice_number.value,
            invoice_date=self.invoice_date.value,
            due_date=self.due_date.value,
            line_items=line_items,
            subtotal=self.subtotal.value,
            tax=self.tax.value,
            total_due=self.total_due.value,
            currency=self.currency.value,
            additional_fields=self.additional_fields,
        )
