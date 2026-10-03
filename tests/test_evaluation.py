import json

import pytest

from invoice_pipeline.evaluation import evaluate, format_report, values_match

MANIFEST = "sample_data/manifest.json"


def _perfect_prediction(ground_truth: dict, confidence: float = 0.95) -> dict:
    """What a flawless extractor would return for this ground truth."""

    def s(value):
        return {"value": value, "confidence": confidence, "page": 1}

    extraction = {name: s(ground_truth[name]) for name in (
        "vendor_name", "invoice_number", "invoice_date", "due_date", "subtotal", "tax", "total_due", "currency",
    )}
    extraction["line_items"] = [{k: s(item[k]) for k in item} for item in ground_truth["line_items"]]
    return {
        "classification": {"doc_type": "invoice", "confidence": 0.99, "reasoning": "ok"},
        "extraction": extraction,
    }


@pytest.fixture()
def ground_truth_by_file():
    records = json.loads(open(MANIFEST).read())
    return {r["file"]: r for r in records}


def _predictor(ground_truth_by_file, tweak=None, calls=None):
    def predict(path):
        key = f"{path.parent.name}/{path.name}"
        if calls is not None:
            calls.append(key)
        prediction = _perfect_prediction(ground_truth_by_file[key]["ground_truth"])
        if tweak:
            tweak(key, prediction)
        return prediction

    return predict


def test_values_match_normalizes_text_and_tolerates_rounding():
    assert values_match("vendor_name", "Acme  Corp ", "acme corp")
    assert values_match("total_due", 100.0, 100.004)
    assert not values_match("total_due", 100.0, 100.5)
    assert values_match("due_date", None, None)
    assert not values_match("due_date", None, "2026-01-01")
    assert not values_match("tax", 0.0, None)


def test_perfect_predictions_score_100_percent(tmp_path, ground_truth_by_file):
    report = evaluate(MANIFEST, tmp_path, predict=_predictor(ground_truth_by_file), workers=1)

    assert report["documents"] == 25
    assert report["document_accuracy"] == 1.0
    assert set(report["field_accuracy"].values()) == {1.0}
    assert set(report["line_item_field_accuracy"].values()) == {1.0}
    assert report["most_error_prone_fields"] == []
    # every deliberately flawed invoice should be caught by validation, and
    # every clean one sail straight through
    assert report["flawed_document_catch_rate"] == 1.0
    assert report["straight_through"]["clean_document_rate"] == 1.0
    assert report["straight_through"]["precision"] == 1.0
    assert "Document accuracy" in format_report(report)


def test_wrong_field_on_clean_invoice_is_a_false_accept(tmp_path, ground_truth_by_file):
    clean_files = [f for f, r in ground_truth_by_file.items() if not r["deliberate_issues"]]
    target = clean_files[0]

    def tweak(key, prediction):
        if key == target:
            prediction["extraction"]["vendor_name"]["value"] = "Totally Different Vendor"

    report = evaluate(MANIFEST, tmp_path, predict=_predictor(ground_truth_by_file, tweak), workers=1)

    assert report["most_error_prone_fields"][0]["field"] == "vendor_name"
    assert report["most_error_prone_fields"][0]["examples"][0]["file"] == target
    assert report["field_accuracy"]["vendor_name"] == pytest.approx(24 / 25)
    # vendor name has no business rule behind it, so validation can't catch it
    assert report["straight_through"]["auto_accepted_with_errors"] == [target]


def test_missing_line_item_counts_against_line_item_fields(tmp_path, ground_truth_by_file):
    target = next(f for f, r in ground_truth_by_file.items() if len(r["ground_truth"]["line_items"]) > 1)

    def tweak(key, prediction):
        if key == target:
            prediction["extraction"]["line_items"].pop()

    report = evaluate(MANIFEST, tmp_path, predict=_predictor(ground_truth_by_file, tweak), workers=1)

    assert report["field_accuracy"]["line_items"] == pytest.approx(24 / 25)
    assert report["line_item_field_accuracy"]["unit_price"] < 1.0
    fields = {e["field"] for e in report["most_error_prone_fields"]}
    assert {"line_items.count", "line_items.unit_price"} <= fields


def test_low_confidence_routes_to_review(tmp_path, ground_truth_by_file):
    def tweak(key, prediction):
        prediction["extraction"]["total_due"]["confidence"] = 0.2  # total_due is never absent

    report = evaluate(MANIFEST, tmp_path, predict=_predictor(ground_truth_by_file, tweak), workers=1)
    assert report["straight_through"]["rate"] == 0.0
    assert report["document_accuracy"] == 1.0


def test_predictions_are_cached_between_runs(tmp_path, ground_truth_by_file):
    calls = []
    predict = _predictor(ground_truth_by_file, calls=calls)

    evaluate(MANIFEST, tmp_path, predict=predict, limit=3, workers=1)
    evaluate(MANIFEST, tmp_path, predict=predict, limit=3, workers=1)
    assert len(calls) == 3
    assert len(list((tmp_path / "predictions").glob("*.json"))) == 3

    evaluate(MANIFEST, tmp_path, predict=predict, limit=3, workers=1, refresh=True)
    assert len(calls) == 6


def test_failed_documents_are_reported_not_cached(tmp_path, ground_truth_by_file):
    def predict(path):
        raise RuntimeError("API overloaded")

    report = evaluate(MANIFEST, tmp_path, predict=predict, limit=2, workers=1)

    assert len(report["errors"]) == 2
    assert "API overloaded" in report["errors"][0]["error"]
    assert report["document_accuracy"] == 0.0
    assert report["straight_through"]["rate"] == 0.0
    assert not (tmp_path / "predictions").exists()


def test_unrecognized_classification_scores_as_wrong(tmp_path, ground_truth_by_file):
    def predict(path):
        return {"classification": {"doc_type": "unrecognized", "confidence": 0.9, "reasoning": "?"}, "extraction": None}

    report = evaluate(MANIFEST, tmp_path, predict=predict, limit=2, workers=1)
    assert report["classification_accuracy"] == 0.0
    assert report["straight_through"]["auto_accepted"] == 0
