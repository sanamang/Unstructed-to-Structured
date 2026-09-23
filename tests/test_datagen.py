from datetime import date

from invoice_pipeline.datagen.generate import generate_dataset
from invoice_pipeline.schema import Invoice


def test_generate_dataset_produces_matching_files_and_ground_truth(tmp_path):
    manifest = generate_dataset(count=10, seed=1, output_dir=tmp_path)

    assert len(manifest) == 10
    for record in manifest:
        doc_path = tmp_path / record["file"]
        assert doc_path.exists()
        assert doc_path.suffix in (".pdf", ".jpg")
        # Ground truth must parse into the shared Invoice schema.
        Invoice(**record["ground_truth"])


def test_generate_dataset_is_deterministic_for_a_given_seed(tmp_path):
    m1 = generate_dataset(count=8, seed=7, output_dir=tmp_path / "a")
    m2 = generate_dataset(count=8, seed=7, output_dir=tmp_path / "b")
    assert [r["ground_truth"] for r in m1] == [r["ground_truth"] for r in m2]


def test_clean_invoices_satisfy_arithmetic_and_date_rules(tmp_path):
    manifest = generate_dataset(count=25, seed=42, output_dir=tmp_path)
    clean = [r for r in manifest if not r["deliberate_issues"]]
    assert clean, "expected at least one invoice with no deliberate issues"

    for record in clean:
        gt = record["ground_truth"]
        line_sum = round(sum(li["line_total"] for li in gt["line_items"]), 2)
        assert abs(line_sum - gt["subtotal"]) < 0.01
        assert abs((gt["subtotal"] + gt["tax"]) - gt["total_due"]) < 0.01
        assert date.fromisoformat(gt["due_date"]) > date.fromisoformat(gt["invoice_date"])
        assert gt["vendor_name"] and gt["invoice_number"]


def test_missing_field_invoices_have_a_null_required_field(tmp_path):
    manifest = generate_dataset(count=25, seed=42, output_dir=tmp_path)
    flagged = [r for r in manifest if "missing_field" in r["deliberate_issues"]]
    assert flagged
    for record in flagged:
        gt = record["ground_truth"]
        assert gt["due_date"] is None or gt["tax"] is None


def test_math_error_invoices_break_a_totals_rule(tmp_path):
    manifest = generate_dataset(count=25, seed=42, output_dir=tmp_path)
    flagged = [r for r in manifest if "math_error" in r["deliberate_issues"]]
    assert flagged
    for record in flagged:
        gt = record["ground_truth"]
        line_sum = round(sum(li["line_total"] for li in gt["line_items"]), 2)
        sums_to_subtotal = abs(line_sum - gt["subtotal"]) < 0.01
        totals_add_up = abs((gt["subtotal"] + gt["tax"]) - gt["total_due"]) < 0.01
        assert not (sums_to_subtotal and totals_add_up)


def test_bad_due_date_invoices_precede_invoice_date(tmp_path):
    manifest = generate_dataset(count=25, seed=42, output_dir=tmp_path)
    flagged = [r for r in manifest if "bad_due_date" in r["deliberate_issues"]]
    assert flagged
    for record in flagged:
        gt = record["ground_truth"]
        assert date.fromisoformat(gt["due_date"]) < date.fromisoformat(gt["invoice_date"])


def test_scanned_invoices_are_rendered_as_images_not_pdfs(tmp_path):
    manifest = generate_dataset(count=25, seed=42, output_dir=tmp_path)
    scanned = [r for r in manifest if r["is_scanned_simulation"]]
    assert scanned
    for record in scanned:
        assert record["file"].endswith(".jpg")
