"""Stage 8: evaluation against the synthetic ground truth.

Runs classification + extraction + validation over every invoice in
`sample_data/manifest.json` and scores the output against its ground truth:

- field-level accuracy for every scalar field, `line_items` as a whole, and
  each line-item sub-field (aligned by position)
- document-level accuracy (every field correct)
- straight-through rate (share auto-accepted by validation), plus how many
  of those auto-accepts were actually wrong - the costly failure mode, since
  nothing downstream looks at them again
- flawed-document catch rate (share of invoices with a review-worthy stage-1
  issue - a math error or bad due date - that got routed to review)
- most error-prone fields, with example mismatches
- breakdowns by template and clean-PDF vs. simulated-scan

Model outputs are cached per document under `<run_dir>/predictions/`, so
re-scoring (or tweaking the scoring) never re-bills the API. Pass
`--refresh` to force new predictions.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import anthropic

from invoice_pipeline import config
from invoice_pipeline.classification import classify_document
from invoice_pipeline.extraction import extract_invoice
from invoice_pipeline.ingestion import ingest_file
from invoice_pipeline.schema import Invoice, InvoiceExtraction
from invoice_pipeline.validation import structure_and_validate

NUMBER_TOLERANCE = 0.01

SCALAR_FIELDS = (
    "vendor_name",
    "invoice_number",
    "invoice_date",
    "due_date",
    "subtotal",
    "tax",
    "total_due",
    "currency",
)
NUMERIC_FIELDS = {"subtotal", "tax", "total_due", "quantity", "unit_price", "line_total"}
LINE_ITEM_FIELDS = ("description", "quantity", "unit_price", "line_total")

# Stage-1 issues that should send a document to review. "missing_field" isn't
# one: a missing optional field (due date, tax) is structured as null/filled
# in, not treated as a defect.
REVIEW_WORTHY_ISSUES = {"math_error", "bad_due_date"}


# --- Prediction -------------------------------------------------------------


def predict_document(path: Path, client: Optional[anthropic.Anthropic] = None) -> dict:
    """Classify and (if an invoice) extract one file. Returns a JSON-safe dict
    so it can be cached to disk as-is."""
    doc = ingest_file(path)
    classification = classify_document(doc, client=client)
    extraction = extract_invoice(doc, client=client) if classification.doc_type == "invoice" else None
    return {
        "classification": classification.model_dump(),
        "extraction": extraction.model_dump() if extraction else None,
    }


def load_or_predict(
    record: dict,
    sample_dir: Path,
    predictions_dir: Path,
    predict: Callable[[Path], dict],
    refresh: bool = False,
) -> dict:
    cache_path = predictions_dir / f"{Path(record['file']).stem}.json"
    if cache_path.exists() and not refresh:
        return json.loads(cache_path.read_text())
    try:
        prediction = predict(sample_dir / record["file"])
    except Exception as e:  # one bad document shouldn't sink the whole run
        return {"classification": None, "extraction": None, "error": f"{type(e).__name__}: {e}"}
    predictions_dir.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(prediction, indent=2))
    return prediction


# --- Scoring ----------------------------------------------------------------


def values_match(field_name: str, expected: Any, predicted: Any) -> bool:
    if expected is None or predicted is None:
        return expected is None and predicted is None
    if field_name in NUMERIC_FIELDS:
        try:
            return abs(float(expected) - float(predicted)) <= NUMBER_TOLERANCE
        except (TypeError, ValueError):
            return False
    return _normalize_text(expected) == _normalize_text(predicted)


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value)).strip().casefold()


@dataclass
class DocumentScore:
    file: str
    template: str
    scanned: bool
    deliberate_issues: list[str]
    classified_as: Optional[str]
    error: Optional[str]
    auto_accepted: bool
    field_results: dict[str, bool]  # field name -> correct
    mismatches: list[dict] = field(default_factory=list)

    @property
    def fully_correct(self) -> bool:
        return all(self.field_results.values())


def score_document(record: dict, prediction: dict, confidence_threshold: float) -> DocumentScore:
    expected = Invoice.model_validate(record["ground_truth"])
    classification = prediction.get("classification") or {}
    extraction = (
        InvoiceExtraction.model_validate(prediction["extraction"]) if prediction.get("extraction") else None
    )
    predicted = extraction.to_invoice() if extraction else Invoice()

    field_results: dict[str, bool] = {}
    mismatches: list[dict] = []

    def check(name: str, exp: Any, pred: Any, value_field: str) -> None:
        ok = values_match(value_field, exp, pred)
        field_results[name] = ok
        if not ok:
            mismatches.append({"field": name, "expected": exp, "predicted": pred})

    for name in SCALAR_FIELDS:
        check(name, getattr(expected, name), getattr(predicted, name), name)

    # Sub-fields are aligned by position; a missing predicted item counts as
    # every sub-field wrong, an extra one only shows up in line_items/count.
    items_ok = len(expected.line_items) == len(predicted.line_items)
    for i, exp_item in enumerate(expected.line_items):
        pred_item = predicted.line_items[i] if i < len(predicted.line_items) else None
        for sub in LINE_ITEM_FIELDS:
            exp_val = getattr(exp_item, sub)
            pred_val = getattr(pred_item, sub) if pred_item else None
            ok = values_match(sub, exp_val, pred_val)
            items_ok = items_ok and ok
            if not ok:
                mismatches.append({"field": f"line_items[{i}].{sub}", "expected": exp_val, "predicted": pred_val})
    field_results["line_items"] = items_ok
    if len(expected.line_items) != len(predicted.line_items):
        mismatches.append(
            {"field": "line_items.count", "expected": len(expected.line_items), "predicted": len(predicted.line_items)}
        )

    auto_accepted = (
        extraction is not None
        and not structure_and_validate(extraction, confidence_threshold=confidence_threshold)[1].requires_review
    )

    return DocumentScore(
        file=record["file"],
        template=record.get("template", "unknown"),
        scanned=bool(record.get("is_scanned_simulation")),
        deliberate_issues=list(record.get("deliberate_issues", [])),
        classified_as=classification.get("doc_type"),
        error=prediction.get("error"),
        auto_accepted=auto_accepted,
        field_results=field_results,
        mismatches=mismatches,
    )


def _rate(numerator: int, denominator: int) -> Optional[float]:
    return round(numerator / denominator, 4) if denominator else None


def _segment_summary(scores: list[DocumentScore]) -> dict:
    field_checks = sum(len(s.field_results) for s in scores)
    field_correct = sum(sum(s.field_results.values()) for s in scores)
    return {
        "documents": len(scores),
        "document_accuracy": _rate(sum(s.fully_correct for s in scores), len(scores)),
        "field_accuracy": _rate(field_correct, field_checks),
        "straight_through_rate": _rate(sum(s.auto_accepted for s in scores), len(scores)),
    }


def summarize(scores: list[DocumentScore], line_item_counts: dict[str, int], examples_per_field: int = 3) -> dict:
    """Aggregate per-document scores into the final report. `line_item_counts`
    maps file -> number of ground-truth line items (for sub-field accuracy)."""
    n = len(scores)

    field_accuracy = {
        name: _rate(sum(s.field_results[name] for s in scores), n) for name in SCALAR_FIELDS + ("line_items",)
    }

    total_items = sum(line_item_counts.get(s.file, 0) for s in scores)
    sub_wrong: dict[str, int] = defaultdict(int)
    for s in scores:
        for m in s.mismatches:
            match = re.fullmatch(r"line_items\[\d+\]\.(\w+)", m["field"])
            if match:
                sub_wrong[match.group(1)] += 1
    line_item_field_accuracy = {sub: _rate(total_items - sub_wrong[sub], total_items) for sub in LINE_ITEM_FIELDS}

    # Error-prone ranking groups line_items[3].unit_price etc. under
    # line_items.unit_price so positions don't fragment the counts.
    errors_by_field: dict[str, list[dict]] = defaultdict(list)
    for s in scores:
        for m in s.mismatches:
            key = re.sub(r"\[\d+\]", "", m["field"])
            errors_by_field[key].append({"file": s.file, "expected": m["expected"], "predicted": m["predicted"]})
    most_error_prone = [
        {"field": key, "errors": len(errs), "examples": errs[:examples_per_field]}
        for key, errs in sorted(errors_by_field.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    ]

    auto_accepted = [s for s in scores if s.auto_accepted]
    flawed = [s for s in scores if REVIEW_WORTHY_ISSUES & set(s.deliberate_issues)]
    clean = [s for s in scores if not REVIEW_WORTHY_ISSUES & set(s.deliberate_issues)]

    by_template: dict[str, list[DocumentScore]] = defaultdict(list)
    for s in scores:
        by_template[s.template].append(s)

    return {
        "documents": n,
        "errors": [{"file": s.file, "error": s.error} for s in scores if s.error],
        "classification_accuracy": _rate(sum(s.classified_as == "invoice" for s in scores), n),
        "document_accuracy": _rate(sum(s.fully_correct for s in scores), n),
        "field_accuracy": field_accuracy,
        "line_item_field_accuracy": line_item_field_accuracy,
        "straight_through": {
            "rate": _rate(len(auto_accepted), n),
            "auto_accepted": len(auto_accepted),
            "auto_accepted_with_errors": [s.file for s in auto_accepted if not s.fully_correct],
            "precision": _rate(sum(s.fully_correct for s in auto_accepted), len(auto_accepted)),
            "clean_document_rate": _rate(sum(s.auto_accepted for s in clean), len(clean)),
        },
        "flawed_document_catch_rate": _rate(sum(not s.auto_accepted for s in flawed), len(flawed)),
        "flawed_documents_missed": [s.file for s in flawed if s.auto_accepted],
        "most_error_prone_fields": most_error_prone,
        "by_template": {t: _segment_summary(group) for t, group in sorted(by_template.items())},
        "by_input_type": {
            "clean_pdf": _segment_summary([s for s in scores if not s.scanned]),
            "simulated_scan": _segment_summary([s for s in scores if s.scanned]),
        },
        "per_document": [
            {
                "file": s.file,
                "template": s.template,
                "scanned": s.scanned,
                "deliberate_issues": s.deliberate_issues,
                "classified_as": s.classified_as,
                "auto_accepted": s.auto_accepted,
                "fully_correct": s.fully_correct,
                "mismatches": s.mismatches,
                "error": s.error,
            }
            for s in scores
        ],
    }


def evaluate(
    manifest_path: str | Path,
    run_dir: str | Path,
    predict: Optional[Callable[[Path], dict]] = None,
    refresh: bool = False,
    limit: Optional[int] = None,
    workers: int = 4,
    confidence_threshold: float = config.CONFIDENCE_THRESHOLD,
) -> dict:
    manifest_path = Path(manifest_path)
    sample_dir = manifest_path.parent
    predictions_dir = Path(run_dir) / "predictions"
    records = json.loads(manifest_path.read_text())[:limit]

    if predict is None:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        predict = lambda path: predict_document(path, client=client)  # noqa: E731

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        predictions = list(
            pool.map(lambda r: load_or_predict(r, sample_dir, predictions_dir, predict, refresh), records)
        )

    scores = [score_document(r, p, confidence_threshold) for r, p in zip(records, predictions)]
    line_item_counts = {r["file"]: len(r["ground_truth"]["line_items"]) for r in records}
    return summarize(scores, line_item_counts)


# --- Reporting --------------------------------------------------------------


def _pct(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def format_report(report: dict) -> str:
    st = report["straight_through"]
    lines = [
        f"Evaluated {report['documents']} documents",
        "",
        f"  Classification accuracy:   {_pct(report['classification_accuracy'])}",
        f"  Document accuracy:         {_pct(report['document_accuracy'])}  (every field correct)",
        f"  Straight-through rate:     {_pct(st['rate'])}  ({st['auto_accepted']} auto-accepted)",
        f"    precision:               {_pct(st['precision'])}  (auto-accepts that were fully correct)",
        f"    on clean invoices:       {_pct(st['clean_document_rate'])}",
        f"  Flawed-doc catch rate:     {_pct(report['flawed_document_catch_rate'])}  (routed to review)",
    ]
    if st["auto_accepted_with_errors"]:
        lines.append(f"  !! Auto-accepted with errors: {', '.join(st['auto_accepted_with_errors'])}")
    if report["flawed_documents_missed"]:
        lines.append(f"  !! Flawed docs auto-accepted: {', '.join(report['flawed_documents_missed'])}")
    if report["errors"]:
        lines.append(f"  !! {len(report['errors'])} document(s) failed to process:")
        lines += [f"       {e['file']}: {e['error']}" for e in report["errors"]]

    lines += ["", "Field accuracy:"]
    for name, acc in report["field_accuracy"].items():
        lines.append(f"  {name:<16} {_pct(acc):>7}")
    for name, acc in report["line_item_field_accuracy"].items():
        lines.append(f"  {'  .' + name:<16} {_pct(acc):>7}")

    lines += ["", "Most error-prone fields:"]
    if not report["most_error_prone_fields"]:
        lines.append("  (none - every field matched)")
    for entry in report["most_error_prone_fields"][:10]:
        lines.append(f"  {entry['field']:<24} {entry['errors']} error(s)")
        for ex in entry["examples"]:
            lines.append(f"      {ex['file']}: expected {ex['expected']!r}, got {ex['predicted']!r}")

    for title, segments in (("By template:", report["by_template"]), ("By input type:", report["by_input_type"])):
        lines += ["", title]
        for name, seg in segments.items():
            lines.append(
                f"  {name:<16} n={seg['documents']:<3} doc acc {_pct(seg['document_accuracy']):>7}"
                f"   field acc {_pct(seg['field_accuracy']):>7}"
                f"   straight-through {_pct(seg['straight_through_rate']):>7}"
            )
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Evaluate the pipeline against sample_data ground truth.")
    parser.add_argument("--manifest", default="sample_data/manifest.json")
    parser.add_argument("--run-dir", default="eval_runs/latest", help="where predictions are cached and the report written")
    parser.add_argument("--refresh", action="store_true", help="ignore cached predictions and re-call the API")
    parser.add_argument("--limit", type=int, default=None, help="only evaluate the first N documents")
    parser.add_argument("--workers", type=int, default=4, help="concurrent API requests")
    parser.add_argument("--threshold", type=float, default=config.CONFIDENCE_THRESHOLD)
    args = parser.parse_args(argv)

    report = evaluate(
        args.manifest,
        args.run_dir,
        refresh=args.refresh,
        limit=args.limit,
        workers=args.workers,
        confidence_threshold=args.threshold,
    )
    report_path = Path(args.run_dir) / "report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2))
    print(format_report(report))
    print(f"\nFull report: {report_path}")


if __name__ == "__main__":
    main()
