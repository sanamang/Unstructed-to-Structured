"""Centralized configuration loaded from environment variables / .env."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://invoice_pipeline:invoice_pipeline@localhost:5433/invoice_pipeline",
)
CONFIDENCE_THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.75"))

# Where uploaded source files and rasterized page images are stored on disk.
STORAGE_DIR = os.environ.get("STORAGE_DIR", "var")

# Both default to Opus 5: best layout/position understanding, which matters
# for disambiguating fields like "Total Due" from a nearby "Amount Paid".
# Override via env if you want to trade accuracy for cost while iterating.
CLASSIFICATION_MODEL = os.environ.get("CLASSIFICATION_MODEL", "claude-opus-5")
EXTRACTION_MODEL = os.environ.get("EXTRACTION_MODEL", "claude-opus-5")
