"""Stage 3: classify an ingested document as an invoice or not.

Runs before extraction so the pipeline can be extended to other document
types later without extraction ever running on something it can't handle.
"""

from __future__ import annotations

from typing import Literal, Optional

import anthropic
from pydantic import BaseModel, Field

from invoice_pipeline import config
from invoice_pipeline.ingestion import IngestedDocument, pages_to_content_blocks

CLASSIFICATION_PROMPT = """You are a document classifier for an accounts-payable intake pipeline.

Look at the attached page image(s) of a single document and decide whether this \
document is a vendor invoice: a bill from a vendor/supplier requesting payment, \
typically showing a vendor name, an invoice number, one or more line items, and a \
total amount due.

Classify it as "invoice" only if you're reasonably confident. Otherwise classify it \
as "unrecognized" (e.g. it's a receipt, packing slip, purchase order, contract, \
letter, blank page, or something else / illegible).

Give a confidence score from 0 to 1 and a one-sentence reason for your decision."""


class DocumentClassification(BaseModel):
    doc_type: Literal["invoice", "unrecognized"]
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


def classify_document(
    doc: IngestedDocument,
    client: Optional[anthropic.Anthropic] = None,
    model: Optional[str] = None,
) -> DocumentClassification:
    client = client or anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    model = model or config.CLASSIFICATION_MODEL

    content = pages_to_content_blocks(doc.pages) + [{"type": "text", "text": CLASSIFICATION_PROMPT}]
    response = client.messages.parse(
        model=model,
        max_tokens=1024,
        messages=[{"role": "user", "content": content}],
        output_format=DocumentClassification,
    )
    return response.parsed_output
