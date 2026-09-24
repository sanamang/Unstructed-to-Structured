#!/usr/bin/env python
"""Run classification + extraction against one real PDF via the live Anthropic
API. Requires ANTHROPIC_API_KEY (with credit) in .env.

Usage:
    python scripts/run_pipeline_smoke_test.py [path/to/invoice.pdf]

Defaults to manual_test_pdfs/test_invoice_01.pdf if no path is given.
"""

import json
import sys
from pathlib import Path

from invoice_pipeline.classification import classify_document
from invoice_pipeline.extraction import extract_invoice
from invoice_pipeline.ingestion import ingest_file

if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("manual_test_pdfs/test_invoice_01.pdf")
    print(f"Ingesting {path} ...")
    doc = ingest_file(path)
    print(f"  doc_id={doc.doc_id} pages={doc.page_count}")

    print("Classifying ...")
    classification = classify_document(doc)
    print(f"  {classification.doc_type} (confidence={classification.confidence:.2f}) - {classification.reasoning}")

    if classification.doc_type != "invoice":
        print("Not classified as an invoice; skipping extraction.")
        sys.exit(0)

    print("Extracting fields ...")
    extraction = extract_invoice(doc)
    print(json.dumps(extraction.model_dump(), indent=2))

    print("\nCollapsed to plain Invoice values:")
    print(json.dumps(extraction.to_invoice().model_dump(), indent=2))
