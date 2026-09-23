# Invoice Extraction Pipeline

An end-to-end unstructured-to-structured document extraction pipeline for vendor
invoices (PDF and scanned images): classify → extract fields with confidence
scores → validate against business rules → route low-confidence/failing docs to
a human review queue → write accepted records to a system-of-record table.

Built as a staged project. Each stage is independently runnable and testable.

## Stack

- Python 3.11+, FastAPI, SQLAlchemy + Postgres, Pydantic
- Anthropic Python SDK (Claude, vision input) for extraction
- reportlab for synthetic sample invoice generation, PyMuPDF/Pillow/numpy for
  scanned-document simulation
- React + Vite for the review queue frontend (stage 6)

## Project layout

```
src/invoice_pipeline/
  schema.py            # shared Invoice/LineItem Pydantic schema (ground truth + extraction target)
  datagen/              # Stage 1: synthetic sample invoice + ground-truth generator
    vendors.py           # vendor/customer/line-item pools
    templates.py          # 3 distinct reportlab invoice layouts
    scan_effects.py        # PDF -> noisy/skewed "bad scan" image rendering
    generate.py            # orchestrator + CLI
sample_data/
  invoices/             # generated PDFs and scanned .jpg renders
  ground_truth/         # one JSON per invoice, matching schema.Invoice
  manifest.json          # full list of generated records
scripts/
  generate_sample_data.py # convenience CLI wrapper
tests/
  test_schema.py
  test_datagen.py
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # fill in ANTHROPIC_API_KEY once you reach the extraction stage
```

## Stage 1 — Synthetic sample data generator

Generates a set of realistic sample invoices as PDFs (a few rendered instead as
noisy/skewed JPEGs to simulate bad scans), each with a matching ground-truth
JSON file for later accuracy evaluation.

Deliberate variation baked in:
- 3 distinct visual layouts/templates (`classic_table`, `modern_minimal`, `compact`)
- 10 vendor profiles across USD/GBP/EUR
- ~16% of invoices missing a required field (`due_date` or `tax` set to `null`)
- ~16% with a math error (line items don't sum to the stated subtotal, or
  subtotal + tax doesn't equal the total due)
- ~12% with an invalid date order (due date before invoice date)
- ~16% rendered as a degraded "scan" (skew, gaussian noise, blur, JPEG
  recompression) instead of a clean PDF

Run it:

```bash
python scripts/generate_sample_data.py --count 25 --seed 42
# or: python -m invoice_pipeline.datagen.generate --count 25 --seed 42
```

This writes to `sample_data/invoices/`, `sample_data/ground_truth/`, and
`sample_data/manifest.json`. Generation is deterministic for a given `--seed`.

Each ground-truth file looks like:

```json
{
  "file": "invoices/invoice_003_scan.jpg",
  "doc_type": "invoice",
  "template": "modern_minimal",
  "vendor_id": "pixel_forge_studio",
  "is_scanned_simulation": true,
  "deliberate_issues": [],
  "ground_truth": {
    "vendor_name": "...",
    "invoice_number": "...",
    "invoice_date": "2026-08-24",
    "due_date": "2026-09-08",
    "line_items": [{"description": "...", "quantity": 7, "unit_price": 2.92, "line_total": 20.44}],
    "subtotal": 2966.19,
    "tax": 593.24,
    "total_due": 3559.43,
    "currency": "EUR"
  }
}
```

## Tests

```bash
python -m pytest tests/ -q
```

Covers: schema parsing (`Invoice`/`LineItem`), generator determinism, and that
each deliberate-issue category (`missing_field`, `math_error`, `bad_due_date`)
and the clean/scanned invoices actually have the properties the later
validation and eval stages will check for.

## Roadmap (subsequent stages)

2. Ingestion layer — accept PDF/image, normalize to page images
3. Classification — invoice vs. not-an-invoice, via Claude vision
4. Extraction — strict JSON schema, confidence scores + page refs, via Claude
   structured output/tool use
5. Validation — plain-Python business rules (sums, date order, required
   fields, confidence threshold) that route failures to human review
6. Review queue — FastAPI backend + React frontend to inspect/correct flagged
   documents; every correction logged for eval feedback
7. Output layer — Postgres system-of-record table + CSV/JSON export
8. Evaluation script — field-level accuracy, straight-through rate,
   most-error-prone-fields breakdown against `sample_data/ground_truth`
