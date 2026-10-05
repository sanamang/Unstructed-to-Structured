"""Stage 3: classify an ingested document as a billing document or not.

Runs before extraction so tokens aren't spent extracting fields from
something with no charges on it. "invoice" is deliberately broad: anything
that bills for, charges for, or records payment for goods or services,
however informal (a receipt, a utility bill, an email listing work and a
price, a handwritten note). Only documents with no charges at all are
"unrecognized".
"""

from __future__ import annotations

from typing import Literal, Optional

import anthropic
from pydantic import BaseModel, Field

from invoice_pipeline import config
from invoice_pipeline.ingestion import IngestedDocument, pages_to_content_blocks

CLASSIFICATION_PROMPT = """You are a document classifier for an accounts-payable intake pipeline.

Look at the attached page image(s) of a single document and decide whether it is a \
billing document: anything where someone charges for, bills for, or records payment \
for goods or services, with at least one amount of money attached to that charge.

Be inclusive. Real-world bills are messy, so all of these count as "invoice":
- formal invoices in any layout or language, however cluttered
- receipts and till slips, paid or unpaid
- utility, phone, rent and subscription bills, and account statements
- emails, letters, text messages or chat screenshots that list work done and a price
- handwritten or scribbled notes, job sheets and timesheets with amounts
- photos or scans that are skewed, blurry, partly cut off or low quality, as long \
as some charge and amount can be made out
A document does NOT need an invoice number, a date, line items, tax or a total to \
count. It does not need the word "invoice".

Classify as "unrecognized" only when there is no charge for goods or services at \
all: a blank page, a photo of something that isn't a document, a contract or \
letter with no amounts billed, marketing material, or a page too damaged to read \
any amount. A purchase order or quote (an offer to buy or sell, not a bill) is \
also "unrecognized".

Also give a short document_kind describing what it actually is (e.g. "invoice", \
"receipt", "utility bill", "email", "handwritten note", "statement"), a confidence \
score from 0 to 1, and a one-sentence reason for your decision."""


class DocumentClassification(BaseModel):
    doc_type: Literal["invoice", "unrecognized"]
    document_kind: str = ""
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
