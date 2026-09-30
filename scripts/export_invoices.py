#!/usr/bin/env python
"""Convenience entrypoint: python scripts/export_invoices.py [--format csv|json] [--out DIR] [--since ISO]"""

from invoice_pipeline.export import main

if __name__ == "__main__":
    main()
