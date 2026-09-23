#!/usr/bin/env python
"""Convenience entrypoint: python scripts/generate_sample_data.py [--count N] [--seed N]"""

from invoice_pipeline.datagen.generate import main

if __name__ == "__main__":
    main()
