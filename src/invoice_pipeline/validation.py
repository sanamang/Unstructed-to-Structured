"""Stage 5: business-rule validation.

Plain-Python checks (no LLM) that decide whether an extracted invoice can be
auto-accepted or must be routed to human review: internal math must be
consistent, dates must be ordered sensibly, the essential fields must be
present, and (when extraction confidence is available) every value that was
read must clear a threshold.

Only vendor_name and total_due are essential - without them there's nothing
to pay. Every other field is optional: if it's simply not on the document it
stays null (or, for tax/subtotal, is filled in by `fill_missing_values`) and
is recorded as an "info" note, which never blocks auto-accept. Any "error"
issue routes the document to review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from invoice_pipeline import config
from invoice_pipeline.schema import Invoice, InvoiceExtraction

AMOUNT_TOLERANCE = 0.02  # cents-level rounding slack across summed line items

REQUIRED_FIELDS = ("vendor_name", "total_due")
OPTIONAL_FIELDS = ("invoice_number", "invoice_date", "due_date", "subtotal", "tax", "currency")

ERROR = "error"  # routes the document to review
INFO = "info"  # recorded for transparency, never blocks auto-accept


@dataclass
class ValidationIssue:
    rule: str
    message: str
    field: Optional[str] = None
    severity: str = ERROR


@dataclass
class ValidationResult:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def requires_review(self) -> bool:
        return any(issue.severity == ERROR for issue in self.issues)


def fill_missing_values(invoice: Invoice) -> tuple[Invoice, list[ValidationIssue]]:
    """Fill in amounts that can be worked out from the rest of the invoice,
    so a document missing them still structures into a complete record.
    Returns the filled invoice plus an info note per filled field.

    - subtotal: sum of the line items, else total_due - tax
    - tax: total_due - subtotal (an invoice with no tax line whose total
      equals its subtotal gets 0)
    """
    invoice = invoice.model_copy(deep=True)
    notes: list[ValidationIssue] = []

    if invoice.subtotal is None:
        if invoice.line_items:
            invoice.subtotal = round(sum(item.line_total for item in invoice.line_items), 2)
            how = "the sum of the line items"
        elif invoice.total_due is not None:
            invoice.subtotal = round(invoice.total_due - (invoice.tax or 0.0), 2)
            how = "total due minus tax"
        else:
            how = None
        if how:
            notes.append(
                ValidationIssue(
                    rule="value_filled_in",
                    field="subtotal",
                    message=f"subtotal isn't on the document; set to {invoice.subtotal:.2f} ({how})",
                    severity=INFO,
                )
            )

    if invoice.tax is None and invoice.total_due is not None and invoice.subtotal is not None:
        difference = round(invoice.total_due - invoice.subtotal, 2)
        invoice.tax = difference if difference > 0 else 0.0
        how = "total due minus subtotal" if invoice.tax else "no tax charged"
        notes.append(
            ValidationIssue(
                rule="value_filled_in",
                field="tax",
                message=f"tax isn't on the document; set to {invoice.tax:.2f} ({how})",
                severity=INFO,
            )
        )

    return invoice, notes


def _check_required_fields(invoice: Invoice) -> list[ValidationIssue]:
    issues = []
    for name in REQUIRED_FIELDS:
        if getattr(invoice, name) is None:
            issues.append(ValidationIssue(rule="required_field_missing", field=name, message=f"{name} is missing"))
    for name in OPTIONAL_FIELDS:
        if getattr(invoice, name) is None:
            issues.append(
                ValidationIssue(
                    rule="optional_field_missing",
                    field=name,
                    message=f"{name} isn't on the document; left empty",
                    severity=INFO,
                )
            )
    if not invoice.line_items:
        issues.append(
            ValidationIssue(
                rule="optional_field_missing",
                field="line_items",
                message="no line items on the document",
                severity=INFO,
            )
        )
    return issues


def _check_line_items_sum_to_subtotal(invoice: Invoice) -> list[ValidationIssue]:
    if invoice.subtotal is None or not invoice.line_items:
        return []
    computed = round(sum(item.line_total for item in invoice.line_items), 2)
    if abs(computed - invoice.subtotal) > AMOUNT_TOLERANCE:
        return [
            ValidationIssue(
                rule="line_items_sum_mismatch",
                field="subtotal",
                message=f"line items sum to {computed:.2f} but subtotal is {invoice.subtotal:.2f}",
            )
        ]
    return []


def _check_totals_add_up(invoice: Invoice) -> list[ValidationIssue]:
    if invoice.subtotal is None or invoice.tax is None or invoice.total_due is None:
        return []
    computed = round(invoice.subtotal + invoice.tax, 2)
    if abs(computed - invoice.total_due) > AMOUNT_TOLERANCE:
        return [
            ValidationIssue(
                rule="totals_mismatch",
                field="total_due",
                message=f"subtotal + tax = {computed:.2f} but total_due is {invoice.total_due:.2f}",
            )
        ]
    return []


def _check_due_date_after_invoice_date(invoice: Invoice) -> list[ValidationIssue]:
    if not invoice.invoice_date or not invoice.due_date:
        return []
    try:
        invoice_date = date.fromisoformat(invoice.invoice_date)
        due_date = date.fromisoformat(invoice.due_date)
    except ValueError:
        return [
            ValidationIssue(
                rule="invalid_date_format",
                field="invoice_date/due_date",
                message=(
                    f"could not parse invoice_date={invoice.invoice_date!r} "
                    f"or due_date={invoice.due_date!r} as ISO dates"
                ),
            )
        ]
    if due_date <= invoice_date:
        return [
            ValidationIssue(
                rule="due_date_not_after_invoice_date",
                field="due_date",
                message=f"due_date {due_date} is not after invoice_date {invoice_date}",
            )
        ]
    return []


def _check_confidence_thresholds(extraction: InvoiceExtraction, threshold: float) -> list[ValidationIssue]:
    """Only values that were actually read are checked. A field the model
    reports as absent (value null) naturally comes back with low confidence;
    that's already covered by the required/optional field rules."""
    issues = []
    scalar_fields = [
        ("vendor_name", extraction.vendor_name),
        ("invoice_number", extraction.invoice_number),
        ("invoice_date", extraction.invoice_date),
        ("due_date", extraction.due_date),
        ("subtotal", extraction.subtotal),
        ("tax", extraction.tax),
        ("total_due", extraction.total_due),
        ("currency", extraction.currency),
    ]
    for name, extracted in scalar_fields:
        if extracted.value is not None and extracted.confidence < threshold:
            issues.append(
                ValidationIssue(
                    rule="low_confidence_field",
                    field=name,
                    message=f"{name} confidence {extracted.confidence:.2f} is below threshold {threshold:.2f}",
                )
            )
    for i, item in enumerate(extraction.line_items):
        for sub_name, extracted in (
            ("description", item.description),
            ("quantity", item.quantity),
            ("unit_price", item.unit_price),
            ("line_total", item.line_total),
        ):
            if extracted.value is not None and extracted.confidence < threshold:
                field_name = f"line_items[{i}].{sub_name}"
                issues.append(
                    ValidationIssue(
                        rule="low_confidence_field",
                        field=field_name,
                        message=f"{field_name} confidence {extracted.confidence:.2f} is below threshold {threshold:.2f}",
                    )
                )
    return issues


def validate_invoice(
    invoice: Invoice,
    extraction: Optional[InvoiceExtraction] = None,
    confidence_threshold: float = config.CONFIDENCE_THRESHOLD,
) -> ValidationResult:
    """Run every business rule against `invoice`. Pass `extraction` (the
    confidence/page-annotated output of stage 4) to also enforce the
    per-field confidence threshold - omit it to validate a plain Invoice
    (e.g. a human-corrected record) on business rules alone."""
    issues: list[ValidationIssue] = []
    issues += _check_required_fields(invoice)
    issues += _check_line_items_sum_to_subtotal(invoice)
    issues += _check_totals_add_up(invoice)
    issues += _check_due_date_after_invoice_date(invoice)
    if extraction is not None:
        issues += _check_confidence_thresholds(extraction, confidence_threshold)
    return ValidationResult(issues=issues)


def structure_and_validate(
    extraction: InvoiceExtraction,
    confidence_threshold: float = config.CONFIDENCE_THRESHOLD,
) -> tuple[Invoice, ValidationResult]:
    """Collapse an extraction to a plain Invoice, fill in derivable amounts,
    and validate it. This is the decision the pipeline (and eval) act on."""
    invoice, notes = fill_missing_values(extraction.to_invoice())
    result = validate_invoice(invoice, extraction=extraction, confidence_threshold=confidence_threshold)
    result.issues = notes + result.issues
    return invoice, result
