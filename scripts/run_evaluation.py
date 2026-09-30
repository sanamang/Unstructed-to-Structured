#!/usr/bin/env python
"""Convenience entrypoint: python scripts/run_evaluation.py [--limit N] [--refresh] [--workers N]

Calls the live Anthropic API for any document without a cached prediction
under eval_runs/latest/predictions/ - needs a funded ANTHROPIC_API_KEY.
"""

from invoice_pipeline.evaluation import main

if __name__ == "__main__":
    main()
