"""Stage 5: business-rule validation.

Plain-Python checks (no LLM) that decide whether an extracted invoice can be
auto-accepted or must be routed to human review: internal math must be
consistent, dates must be ordered sensibly, the essential fields must be
present, and (when extraction confidence is available) every value that was
read must clear a threshold.

No field is required for a document to be structured. A missing amount is
worked out from the other amounts where possible and otherwise set to 0 (see
`fill_missing_values`); a missing text field or date stays null. Each is
recorded as an "info" note, which never blocks auto-accept. Two gaps do
route to review, because the record can't be paid without a person looking
at it: no vendor, and no amount anywhere on the document. Any "error" issue
routes the document to review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from invoice_pipeline import config
from invoice_pipeline.schema import Invoice, InvoiceExtraction

AMOUNT_TOLERANCE = 0.02  # cents-level rounding slack across summed line items

REQUIRED_FIELDS = ("vendor_name",)
# Amounts never stay null - fill_missing_values sets them - so only text and
# date fields can be reported missing here.
OPTIONAL_FIELDS = ("invoice_number", "invoice_date", "due_date", "currency")

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


def _filled(name: str, value: float, how: str) -> ValidationIssue:
    return ValidationIssue(
        rule="value_filled_in",
        field=name,
        message=f"{name} isn't on the document; set to {value:.2f} ({how})",
        severity=INFO,
    )


def fill_missing_values(invoice: Invoice) -> tuple[Invoice, list[ValidationIssue]]:
    """Fill in every missing amount, so any document structures into a
    complete record. Each amount is worked out from the others where
    possible, else set to 0. Returns the filled invoice plus an info note per
    filled field. It never hides an inconsistency: the totals rules still
    run on the filled values.

    - subtotal: sum of the line items, else total_due - tax, else 0
    - tax: total_due - subtotal (0 if that isn't positive), else 0
    - total_due: subtotal + tax
    """
    invoice = invoice.model_copy(deep=True)
    notes: list[ValidationIssue] = []
    line_sum = round(sum(item.line_total for item in invoice.line_items), 2)

    if invoice.subtotal is None:
        if invoice.line_items and (line_sum or invoice.total_due is None):
            invoice.subtotal, how = line_sum, "the sum of the line items"
        elif invoice.total_due is not None:
            invoice.subtotal, how = round(invoice.total_due - (invoice.tax or 0.0), 2), "total due minus tax"
        else:
            invoice.subtotal, how = 0.0, "no amounts to work it out from"
        notes.append(_filled("subtotal", invoice.subtotal, how))

    if invoice.tax is None:
        if invoice.total_due is not None:
            difference = round(invoice.total_due - invoice.subtotal, 2)
            invoice.tax = difference if difference > 0 else 0.0
            how = "total due minus subtotal" if invoice.tax else "no tax charged"
        else:
            invoice.tax, how = 0.0, "no tax shown"
        notes.append(_filled("tax", invoice.tax, how))

    if invoice.total_due is None:
        invoice.total_due = round(invoice.subtotal + invoice.tax, 2)
        notes.append(_filled("total_due", invoice.total_due, "subtotal plus tax"))

    return invoice, notes


def _line_item_fill_notes(extraction: InvoiceExtraction) -> list[ValidationIssue]:
    """One info note per line item that had numbers missing on the document
    (InvoiceExtraction.to_invoice fills them in)."""
    notes = []
    for i, item in enumerate(extraction.line_items):
        missing = [
            name
            for name, extracted in (
                ("quantity", item.quantity),
                ("unit_price", item.unit_price),
                ("line_total", item.line_total),
            )
            if extracted.value is None
        ]
        if missing:
            notes.append(
                ValidationIssue(
                    rule="value_filled_in",
                    field=f"line_items[{i}]",
                    message=(
                        f"line item {i + 1} has no {', '.join(missing)} on the document; "
                        "worked out from its other numbers, else set to 0"
                    ),
                    severity=INFO,
                )
            )
    return notes


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
    has_amount = any(
        value for value in (invoice.subtotal, invoice.tax, invoice.total_due)
    ) or any(item.line_total for item in invoice.line_items)
    if not has_amount:
        issues.append(
            ValidationIssue(
                rule="no_amount_found",
                field="total_due",
                message="no amount could be read from the document; amounts set to 0",
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
    notes += _line_item_fill_notes(extraction)
    result = validate_invoice(invoice, extraction=extraction, confidence_threshold=confidence_threshold)
    result.issues = notes + result.issues
    return invoice, result
