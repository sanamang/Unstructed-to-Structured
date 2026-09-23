#!/usr/bin/env python
"""Generate a small set of plain invoice PDFs for manually testing ingestion
and extraction, separate from the eval fixtures in sample_data/.

Usage:
    python scripts/generate_manual_test_pdfs.py [--count N] [--seed N]
"""

import argparse
from pathlib import Path

from invoice_pipeline.datagen.generate import generate_manual_test_pdfs

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--seed", type=int, default=123)
    parser.add_argument("--output-dir", type=Path, default=Path("manual_test_pdfs"))
    args = parser.parse_args()

    manifest = generate_manual_test_pdfs(args.count, args.seed, args.output_dir)
    print(f"Generated {len(manifest)} plain test invoices in {args.output_dir}/")
    for record in manifest:
        print(f"  {record['file']}  ({record['template']}, vendor={record['vendor_id']})")
