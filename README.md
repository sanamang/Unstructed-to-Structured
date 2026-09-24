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
  schema.py            # shared Invoice/LineItem schema + InvoiceExtraction (value+confidence+page wrappers)
  config.py             # env-driven settings (API key, model ids, confidence threshold, DB url)
  ingestion.py           # Stage 2: normalize PDF/image input into per-page images
  classification.py      # Stage 3: invoice vs. unrecognized, via Claude vision
  extraction.py           # Stage 4: structured field extraction, via Claude vision + structured outputs
  validation.py            # Stage 5: plain-Python business rules + confidence threshold
  datagen/              # Stage 1: synthetic sample invoice + ground-truth generator
    vendors.py           # vendor/customer/line-item pools
    templates.py          # 3 distinct reportlab invoice layouts
    scan_effects.py        # PDF -> noisy/skewed "bad scan" image rendering
    generate.py            # orchestrator + CLI
sample_data/
  invoices/             # generated PDFs and scanned .jpg renders
  ground_truth/         # one JSON per invoice, matching schema.Invoice
  manifest.json          # full list of generated records
manual_test_pdfs/
  test_invoice_*.pdf    # plain invoices for ad hoc manual pipeline testing
  reference_values.json  # expected field values for those PDFs (not eval fixtures)
scripts/
  generate_sample_data.py       # convenience CLI wrapper for stage 1
  generate_manual_test_pdfs.py  # generates the manual_test_pdfs/ set
  run_pipeline_smoke_test.py    # live classify + extract against one real PDF
tests/
  test_schema.py
  test_datagen.py
  test_ingestion.py
  test_classification.py  # mocked Anthropic client - no API key/credit needed
  test_extraction.py      # mocked Anthropic client - no API key/credit needed
  test_validation.py      # business rules + integration check against sample_data ground truth
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

## Stage 2 — Ingestion layer

Normalizes an incoming PDF or image file into a list of per-page RGB images at
a consistent DPI, with a stable content-hash `doc_id`. This is the shape every
later stage (classification, extraction, review UI) consumes — pages are sent
directly to Claude's vision input rather than run through OCR-then-parse,
since layout position matters for disambiguating fields like "Total Due" vs.
"Amount Paid".

```python
from invoice_pipeline.ingestion import ingest_file, save_pages

doc = ingest_file("manual_test_pdfs/test_invoice_01.pdf")
print(doc.doc_id, doc.page_count)       # e.g. "a1b2c3d4e5f6..." 1
save_pages(doc, "var/pages")             # writes var/pages/<doc_id>/page_001.png ...
```

Handles both PDF (rasterized via PyMuPDF) and image input (PNG/JPEG/TIFF/BMP,
loaded directly as a single page) through the same `ingest_file`/`ingest_bytes`
entrypoints.

A few plain sample PDFs for manually exercising ingestion (and later stages)
are generated separately from the eval fixtures in `sample_data/`:

```bash
python scripts/generate_manual_test_pdfs.py --count 3 --seed 123
```

This writes to `manual_test_pdfs/` along with a `reference_values.json` you
can eyeball against the pipeline's output — these aren't wired into the eval
script, they're just for quick manual runs.

## Stage 3 — Classification

`classify_document(doc)` sends the ingested page image(s) to Claude with a
structured `DocumentClassification` output (`doc_type`: `"invoice"` or
`"unrecognized"`, a confidence score, and one-sentence reasoning), via
`client.messages.parse(..., output_format=DocumentClassification)`. Runs
before extraction so the pipeline can gate on document type before spending
tokens extracting fields from something that isn't an invoice.

## Stage 4 — Extraction

`extract_invoice(doc)` extracts the full invoice field set — vendor name,
invoice number, dates, line items, subtotal, tax, total due, currency — as an
`InvoiceExtraction`, where **every field is wrapped with its own `confidence`
(0–1) and source `page` number**, via the same structured-output mechanism.
The prompt explicitly warns the model about decoy fields (e.g. an "Amount
Paid: $0.00" line sitting right above "Total Due" in the `modern_minimal`
sample template) and tells it to prefer visual position/emphasis over nearest
matching label. Call `.to_invoice()` on the result to collapse it down to a
plain `Invoice` for validation or comparison against ground truth.

Both stages default to `claude-opus-5` (best layout/position understanding),
configurable via `CLASSIFICATION_MODEL` / `EXTRACTION_MODEL` in `.env`.

Both `classify_document()` and `extract_invoice()` take an optional `client`
argument, so tests inject a fake `Anthropic` client and never hit the network
— see `tests/test_classification.py` / `tests/test_extraction.py`. To try it
against the live API (needs a funded `ANTHROPIC_API_KEY` in `.env`):

```bash
python scripts/run_pipeline_smoke_test.py manual_test_pdfs/test_invoice_02.pdf
```

Verified manually against all 3 `manual_test_pdfs/` invoices — extracted
values matched `reference_values.json` exactly, including correctly picking
"Total Due" over the "Amount Paid" decoy on the `modern_minimal` template.

## Stage 5 — Validation

`validate_invoice(invoice, extraction=None, confidence_threshold=0.75)` runs
plain-Python business rules against a collapsed `Invoice` — no LLM involved.
Any single issue routes the document to human review; there's no partial
credit / auto-accept-with-a-warning.

Rules:
- **Required fields non-null**: vendor_name, invoice_number, invoice_date,
  due_date, subtotal, tax, total_due, currency, and at least one line item
- **Line items sum to subtotal** (within a 2-cent rounding tolerance)
- **Subtotal + tax = total due** (same tolerance)
- **Due date is after invoice date** (strictly after — equal dates are flagged too)
- **Per-field confidence threshold**: when you pass the stage-4 `InvoiceExtraction`
  (not just the collapsed `Invoice`), every field's confidence is checked against
  `confidence_threshold` (env `CONFIDENCE_THRESHOLD`, default 0.75) — pass only
  a plain `Invoice` (e.g. a human-corrected record) to validate business rules
  without confidence in the picture

Returns a `ValidationResult` with a list of `ValidationIssue(rule, field,
message)` and a `.requires_review` bool.

The test suite validates every fixture in `sample_data/ground_truth/` and
confirms each deliberate-issue category from stage 1 trips the rule you'd
expect (`missing_field` → `required_field_missing`, `math_error` →
`line_items_sum_mismatch`/`totals_mismatch`, `bad_due_date` →
`due_date_not_after_invoice_date`), and that every clean invoice passes clean
— a closed loop between the synthetic data generator and the validator.

## Tests

```bash
python -m pytest tests/ -q
```

Covers: schema parsing (`Invoice`/`LineItem`/`InvoiceExtraction`), generator
determinism, that each deliberate-issue category (`missing_field`,
`math_error`, `bad_due_date`) and the clean/scanned invoices have the
properties later validation/eval stages check for, ingestion round-tripping,
classification/extraction request shape + `InvoiceExtraction.to_invoice()`
(mocked Anthropic client, no API key/credit needed), and every validation
rule individually plus end-to-end against `sample_data/ground_truth/`.

## Roadmap (subsequent stages)

6. Review queue — FastAPI backend + React frontend to inspect/correct flagged
   documents; every correction logged for eval feedback
7. Output layer — Postgres system-of-record table + CSV/JSON export
8. Evaluation script — field-level accuracy, straight-through rate,
   most-error-prone-fields breakdown against `sample_data/ground_truth`
