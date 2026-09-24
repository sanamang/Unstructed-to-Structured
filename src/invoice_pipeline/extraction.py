"""Stage 4: extract structured invoice fields from page images.

Sends page images directly to Claude's vision input (rather than OCR text)
and forces schema-conformant JSON via structured outputs, since layout
position carries meaning plain-text OCR discards (e.g. a number sitting
under "Total Due" vs. under a nearby "Amount Paid" line). Every field comes
back with a confidence score and, where applicable, the page it was read
from, so stage 5 can route low-confidence extractions to human review.
"""

from __future__ import annotations

from typing import Optional

import anthropic

from invoice_pipeline import config
from invoice_pipeline.ingestion import IngestedDocument, pages_to_content_blocks
from invoice_pipeline.schema import InvoiceExtraction

EXTRACTION_PROMPT = """You are extracting structured data from a vendor invoice for an \
accounts-payable system. You are given one or more page images of a single invoice.

Extract these fields: vendor_name, invoice_number, invoice_date, due_date, line_items \
(description, quantity, unit_price, line_total for each), subtotal, tax, total_due, \
and currency.

Rules:
- Read values from their visual position on the page, not just nearby text. Invoices \
often have a decoy line near the total (e.g. "Amount Paid: $0.00") - use the label \
that is actually attached to each value, and the visual emphasis/position (total due \
is usually the final, most prominent amount), to avoid picking the wrong number.
- invoice_date and due_date must be ISO 8601 (YYYY-MM-DD). If a date is ambiguous, use \
your best reading of the format shown on the document.
- currency must be a 3-letter ISO 4217 code (e.g. USD, GBP, EUR), inferred from the \
currency symbol or text shown.
- subtotal, tax, total_due, unit_price, and line_total must be plain numbers with no \
currency symbols or thousands separators.
- If a field is missing, illegible, or not present on the document, set its value to \
null and give it a low confidence score - do not guess or invent a value.
- For every field, give a confidence score from 0.0 to 1.0 reflecting how certain you \
are the extracted value is correct, and the 1-indexed page number you read it from \
(omit page for fields with no single source page, like a computed subtotal you can \
still see printed - use the page it's printed on).
- For each line item, give quantity, unit_price, and line_total their own confidence \
and page."""


def extract_invoice(
    doc: IngestedDocument,
    client: Optional[anthropic.Anthropic] = None,
    model: Optional[str] = None,
) -> InvoiceExtraction:
    client = client or anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    model = model or config.EXTRACTION_MODEL

    content = pages_to_content_blocks(doc.pages) + [{"type": "text", "text": EXTRACTION_PROMPT}]
    response = client.messages.parse(
        model=model,
        max_tokens=16000,
        messages=[{"role": "user", "content": content}],
        output_format=InvoiceExtraction,
    )
    return response.parsed_output
