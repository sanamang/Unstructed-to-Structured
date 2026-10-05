"""Stage 4: extract structured invoice fields from page images.

Sends page images directly to Claude's vision input (rather than OCR text)
and forces schema-conformant JSON via structured outputs, since layout
position carries meaning plain-text OCR discards (e.g. a number sitting
under "Total Due" vs. under a nearby "Amount Paid" line). Every field comes
back with a confidence score and, where applicable, the page it was read
from, so stage 5 can route low-confidence extractions to human review.
"""

from __future__ import annotations

import datetime
from typing import Optional

import anthropic

from invoice_pipeline import config
from invoice_pipeline.ingestion import IngestedDocument, pages_to_content_blocks
from invoice_pipeline.schema import InvoiceExtraction

EXTRACTION_PROMPT = """You are turning a billing document into a structured invoice \
record for an accounts-payable system. You are given one or more page images of a \
single document. It may be a formal invoice, but it may just as well be a receipt, a \
utility bill, an email, a letter, a handwritten note or a blurry phone photo, in any \
language and any layout. Don't expect any particular labels or structure: work out \
what each piece of information means from context, the way a careful bookkeeper would.

Extract these fields: vendor_name, invoice_number, invoice_date, due_date, line_items \
(description, quantity, unit_price, line_total for each), subtotal, tax, total_due, \
currency, and additional_fields.

What each field means, whatever the document calls it:
- vendor_name: whoever is charging or being paid - a company, a shop, or a person's \
name if that's all there is. Not the customer being billed.
- invoice_number: any identifier the sender gives this bill (bill #, ref, receipt or \
transaction number, statement number). If the document hesitates between values, use \
the one it settles on.
- invoice_date: the date of the bill (issue/statement/receipt/sent date, or the date \
the work was billed). due_date: when payment is due. Work dates out from relative \
wording ("due in 15 days", "net 30", "tuesday the 22nd") using the other dates on \
the document.
- line_items: every individual charge, however it's written - a table row, a bullet, \
a sentence ("retouching 35 photos at $12 each"). Credits and discounts are line \
items with negative amounts. Don't include payments, previous balances or summary \
lines (subtotal, tax, total) as line items.
- subtotal: the amount before tax. tax: the total tax charged (sum of all tax lines \
such as VAT, GST, HST, PST, TVA, sales tax).
- total_due: the final amount this bill asks to be paid (or, on a receipt, the amount \
paid for it). Watch for decoys: an "Amount Paid" line, a previous balance, an account \
balance across several bills, an early-payment discount that isn't applied, a quote \
for future work. Use the label attached to each value and visual emphasis (the final, \
most prominent amount) to pick the right one.
- additional_fields: every other piece of information on the document that a \
bookkeeper might want, as label/value pairs - e.g. PO number, account or customer \
number, bill-to and ship-to, vendor address/phone/email/tax registration, payment \
terms and methods, deposits, discounts offered, notes. Use short, plain labels.

Formatting rules:
- invoice_date and due_date must be ISO 8601 (YYYY-MM-DD). For an ambiguous format \
(03/09/2026) use the convention of the document's country/language. For a date written \
without a year, take the year from other dates on the document; if there are none, \
use the most recent such date on or before today (given below), with lower confidence.
- currency must be a 3-letter ISO 4217 code (USD, CAD, EUR, GBP...), inferred from \
symbols, text, or the vendor's location. A bare "$" with a Canadian address is CAD.
- All amounts are plain numbers: no currency symbols or thousands separators, and a \
decimal point (convert "1.150,00" or "85,00" to 1150.00 and 85.00).
- Report only what the document actually shows. If a number is missing or illegible, \
set its value to null rather than computing or guessing it - the system fills \
missing amounts in afterwards. A line item that shows only an amount (a flat fee, a \
parts charge) has quantity 1 and unit_price equal to its line_total: that is the \
standard reading, not a guess.
- For every field, give a confidence from 0.0 to 1.0 that the value is correct, and \
the 1-indexed page you read it from. A field that's absent gets value null and a \
low confidence."""


def extract_invoice(
    doc: IngestedDocument,
    client: Optional[anthropic.Anthropic] = None,
    model: Optional[str] = None,
) -> InvoiceExtraction:
    client = client or anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    model = model or config.EXTRACTION_MODEL

    prompt = f"{EXTRACTION_PROMPT}\n\nToday's date is {datetime.date.today().isoformat()}."
    content = pages_to_content_blocks(doc.pages) + [{"type": "text", "text": prompt}]
    response = client.messages.parse(
        model=model,
        max_tokens=16000,
        messages=[{"role": "user", "content": content}],
        output_format=InvoiceExtraction,
    )
    return response.parsed_output
