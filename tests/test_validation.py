import json
from pathlib import Path

from invoice_pipeline.schema import (
    ExtractedNumber,
    ExtractedString,
    Invoice,
    InvoiceExtraction,
    LineItem,
    LineItemExtraction,
)
from invoice_pipeline.validation import INFO, fill_missing_values, structure_and_validate, validate_invoice

SAMPLE_DATA = Path(__file__).resolve().parent.parent / "sample_data"


def _clean_invoice(**overrides) -> Invoice:
    defaults = dict(
        vendor_name="Acme Industrial Supplies",
        invoice_number="INV-000123",
        invoice_date="2025-01-01",
        due_date="2025-01-31",
        line_items=[LineItem(description="Widget", quantity=2, unit_price=10.0, line_total=20.0)],
        subtotal=20.0,
        tax=1.6,
        total_due=21.6,
        currency="USD",
    )
    defaults.update(overrides)
    return Invoice(**defaults)


def test_clean_invoice_has_no_issues():
    result = validate_invoice(_clean_invoice())
    assert result.issues == []
    assert result.requires_review is False


def test_missing_essential_field_is_flagged():
    for name in ("vendor_name", "total_due"):
        result = validate_invoice(_clean_invoice(**{name: None}))
        assert result.requires_review is True
        assert any(i.rule == "required_field_missing" and i.field == name for i in result.issues)


def test_missing_optional_field_is_noted_but_does_not_block():
    result = validate_invoice(_clean_invoice(due_date=None, invoice_number=None, currency=None))
    assert result.requires_review is False
    noted = {i.field for i in result.issues if i.rule == "optional_field_missing"}
    assert noted == {"due_date", "invoice_number", "currency"}
    assert all(i.severity == INFO for i in result.issues)


def test_empty_line_items_is_noted_but_does_not_block():
    result = validate_invoice(_clean_invoice(line_items=[]))
    assert result.requires_review is False
    assert any(i.rule == "optional_field_missing" and i.field == "line_items" for i in result.issues)


def test_missing_tax_is_filled_from_total_minus_subtotal():
    invoice, notes = fill_missing_values(_clean_invoice(tax=None))
    assert invoice.tax == 1.6
    assert [(n.field, n.severity) for n in notes] == [("tax", INFO)]
    assert validate_invoice(invoice).requires_review is False


def test_missing_tax_with_total_equal_to_subtotal_is_zero():
    invoice, _ = fill_missing_values(_clean_invoice(tax=None, total_due=20.0))
    assert invoice.tax == 0.0


def test_missing_subtotal_is_filled_from_line_items():
    invoice, notes = fill_missing_values(_clean_invoice(subtotal=None))
    assert invoice.subtotal == 20.0
    assert notes[0].field == "subtotal"


def test_missing_subtotal_and_tax_without_line_items_falls_back_to_total():
    invoice, _ = fill_missing_values(_clean_invoice(subtotal=None, tax=None, line_items=[]))
    assert invoice.subtotal == 21.6
    assert invoice.tax == 0.0


def test_fill_does_not_mask_inconsistent_totals():
    # No tax line, and the total is *less* than the subtotal: tax becomes 0
    # and the totals rule still catches the inconsistency.
    invoice, _ = fill_missing_values(_clean_invoice(tax=None, total_due=15.0))
    assert invoice.tax == 0.0
    assert any(i.rule == "totals_mismatch" for i in validate_invoice(invoice).issues)


def test_fill_leaves_the_original_invoice_untouched():
    original = _clean_invoice(tax=None)
    fill_missing_values(original)
    assert original.tax is None


def test_line_items_not_summing_to_subtotal_is_flagged():
    result = validate_invoice(_clean_invoice(subtotal=999.0, total_due=1000.6))
    assert any(i.rule == "line_items_sum_mismatch" for i in result.issues)


def test_subtotal_plus_tax_not_equal_total_is_flagged():
    result = validate_invoice(_clean_invoice(total_due=500.0))
    assert any(i.rule == "totals_mismatch" for i in result.issues)


def test_rounding_within_tolerance_is_not_flagged():
    result = validate_invoice(_clean_invoice(subtotal=20.0, tax=1.6, total_due=21.61))
    assert not any(i.rule == "totals_mismatch" for i in result.issues)


def test_due_date_before_invoice_date_is_flagged():
    result = validate_invoice(_clean_invoice(invoice_date="2025-02-01", due_date="2025-01-15"))
    assert any(i.rule == "due_date_not_after_invoice_date" for i in result.issues)


def test_due_date_equal_to_invoice_date_is_flagged():
    result = validate_invoice(_clean_invoice(invoice_date="2025-02-01", due_date="2025-02-01"))
    assert any(i.rule == "due_date_not_after_invoice_date" for i in result.issues)


def test_unparseable_date_is_flagged():
    result = validate_invoice(_clean_invoice(invoice_date="not-a-date"))
    assert any(i.rule == "invalid_date_format" for i in result.issues)


def _extraction_with_confidence(low_field_confidence: float) -> InvoiceExtraction:
    high = 0.95
    return InvoiceExtraction(
        vendor_name=ExtractedString(value="Acme", confidence=high),
        invoice_number=ExtractedString(value="INV-1", confidence=high),
        invoice_date=ExtractedString(value="2025-01-01", confidence=high),
        due_date=ExtractedString(value="2025-01-31", confidence=low_field_confidence),
        line_items=[
            LineItemExtraction(
                description=ExtractedString(value="Widget", confidence=high),
                quantity=ExtractedNumber(value=2, confidence=high),
                unit_price=ExtractedNumber(value=10.0, confidence=high),
                line_total=ExtractedNumber(value=20.0, confidence=high),
            )
        ],
        subtotal=ExtractedNumber(value=20.0, confidence=high),
        tax=ExtractedNumber(value=1.6, confidence=high),
        total_due=ExtractedNumber(value=21.6, confidence=high),
        currency=ExtractedString(value="USD", confidence=high),
    )


def test_low_confidence_field_is_flagged_when_extraction_provided():
    extraction = _extraction_with_confidence(low_field_confidence=0.4)
    result = validate_invoice(_clean_invoice(), extraction=extraction, confidence_threshold=0.75)
    assert any(i.rule == "low_confidence_field" and i.field == "due_date" for i in result.issues)


def test_high_confidence_extraction_adds_no_issues():
    extraction = _extraction_with_confidence(low_field_confidence=0.95)
    result = validate_invoice(_clean_invoice(), extraction=extraction, confidence_threshold=0.75)
    assert result.issues == []


def test_low_confidence_on_an_absent_value_is_not_flagged():
    # The model reports a field it couldn't find as null with low confidence;
    # the optional-field rule already covers that, so it isn't double-flagged.
    extraction = _extraction_with_confidence(low_field_confidence=0.05)
    extraction.due_date.value = None
    _, result = structure_and_validate(extraction, confidence_threshold=0.75)
    assert not any(i.rule == "low_confidence_field" for i in result.issues)
    assert result.requires_review is False


def test_without_extraction_confidence_is_not_checked():
    # No extraction passed -> confidence never enters the picture, even
    # though a real extraction would have flagged something.
    result = validate_invoice(_clean_invoice())
    assert result.issues == []


# --- Integration: validate against every stage-1 ground-truth fixture, ---
# --- confirming stage 5's rules actually catch what stage 1 deliberately  ---
# --- broke.                                                               ---

def _load_manifest():
    return json.loads((SAMPLE_DATA / "manifest.json").read_text())


def test_clean_ground_truth_invoices_pass_validation():
    manifest = _load_manifest()
    clean = [r for r in manifest if not r["deliberate_issues"]]
    assert clean
    for record in clean:
        invoice = Invoice(**record["ground_truth"])
        result = validate_invoice(invoice)
        assert result.issues == [], f"{record['file']} unexpectedly failed: {result.issues}"


def test_missing_field_ground_truth_invoices_structure_without_review():
    # A missing due date or tax line is structured as null / filled in, not
    # treated as a defect.
    manifest = _load_manifest()
    flagged = [r for r in manifest if r["deliberate_issues"] == ["missing_field"]]
    assert flagged
    for record in flagged:
        invoice, notes = fill_missing_values(Invoice(**record["ground_truth"]))
        result = validate_invoice(invoice)
        assert not result.requires_review, f"{record['file']}: {result.issues}"
        assert notes or any(i.rule == "optional_field_missing" for i in result.issues)


def test_math_error_ground_truth_invoices_fail_a_totals_check():
    manifest = _load_manifest()
    flagged = [r for r in manifest if "math_error" in r["deliberate_issues"]]
    assert flagged
    for record in flagged:
        invoice = Invoice(**record["ground_truth"])
        result = validate_invoice(invoice)
        assert result.requires_review
        assert any(i.rule in ("line_items_sum_mismatch", "totals_mismatch") for i in result.issues)


def test_bad_due_date_ground_truth_invoices_fail_date_order_check():
    manifest = _load_manifest()
    flagged = [r for r in manifest if "bad_due_date" in r["deliberate_issues"]]
    assert flagged
    for record in flagged:
        invoice = Invoice(**record["ground_truth"])
        result = validate_invoice(invoice)
        assert result.requires_review
        assert any(i.rule == "due_date_not_after_invoice_date" for i in result.issues)
