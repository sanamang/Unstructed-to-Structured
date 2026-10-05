from invoice_pipeline.extraction import extract_invoice
from invoice_pipeline.ingestion import ingest_file
from invoice_pipeline.schema import (
    AdditionalField,
    ExtractedNumber,
    ExtractedString,
    InvoiceExtraction,
    LineItemExtraction,
    complete_line_item,
)


class _FakeParsedResponse:
    def __init__(self, parsed_output):
        self.parsed_output = parsed_output


class _FakeMessages:
    def __init__(self, parsed_output):
        self._parsed_output = parsed_output
        self.last_call_kwargs = None

    def parse(self, **kwargs):
        self.last_call_kwargs = kwargs
        return _FakeParsedResponse(self._parsed_output)


class _FakeClient:
    def __init__(self, parsed_output):
        self.messages = _FakeMessages(parsed_output)


def _sample_extraction() -> InvoiceExtraction:
    return InvoiceExtraction(
        vendor_name=ExtractedString(value="Acme Industrial Supplies", confidence=0.99, page=1),
        invoice_number=ExtractedString(value="INV-000123", confidence=0.95, page=1),
        invoice_date=ExtractedString(value="2025-01-01", confidence=0.9, page=1),
        due_date=ExtractedString(value="2025-01-31", confidence=0.9, page=1),
        line_items=[
            LineItemExtraction(
                description=ExtractedString(value="Widget", confidence=0.9, page=1),
                quantity=ExtractedNumber(value=2, confidence=0.9, page=1),
                unit_price=ExtractedNumber(value=10.0, confidence=0.9, page=1),
                line_total=ExtractedNumber(value=20.0, confidence=0.9, page=1),
            )
        ],
        subtotal=ExtractedNumber(value=20.0, confidence=0.9, page=1),
        tax=ExtractedNumber(value=1.6, confidence=0.85, page=1),
        total_due=ExtractedNumber(value=21.6, confidence=0.95, page=1),
        currency=ExtractedString(value="USD", confidence=0.99, page=1),
    )


def test_extract_invoice_returns_parsed_output():
    doc = ingest_file("manual_test_pdfs/test_invoice_01.pdf")
    expected = _sample_extraction()
    fake_client = _FakeClient(expected)

    result = extract_invoice(doc, client=fake_client, model="claude-opus-5")

    assert result == expected
    content = fake_client.messages.last_call_kwargs["messages"][0]["content"]
    assert any(block["type"] == "image" for block in content)
    assert fake_client.messages.last_call_kwargs["output_format"] is InvoiceExtraction


def test_extraction_to_invoice_collapses_wrappers_to_plain_values():
    extraction = _sample_extraction()
    invoice = extraction.to_invoice()

    assert invoice.vendor_name == "Acme Industrial Supplies"
    assert invoice.total_due == 21.6
    assert len(invoice.line_items) == 1
    assert invoice.line_items[0].line_total == 20.0


def test_extraction_to_invoice_derives_missing_line_item_numbers():
    extraction = _sample_extraction()  # 2 x 10.00 = 20.00
    extraction.line_items[0].quantity.value = None
    assert extraction.to_invoice().line_items[0].quantity == 2.0


def test_extraction_to_invoice_zeroes_line_item_numbers_it_cannot_derive():
    extraction = _sample_extraction()
    item = extraction.line_items[0]
    item.quantity.value = item.unit_price.value = item.line_total.value = None
    line = extraction.to_invoice().line_items[0]
    assert (line.quantity, line.unit_price, line.line_total) == (0.0, 0.0, 0.0)


def test_complete_line_item_cases():
    assert complete_line_item(3, 40.0, None) == (3, 40.0, 120.0)  # total from qty x price
    assert complete_line_item(None, None, 55.0) == (1.0, 55.0, 55.0)  # amount-only line
    assert complete_line_item(4, None, 22.0) == (4, 5.5, 22.0)  # price from total / qty
    assert complete_line_item(None, 7.5, None) == (1.0, 7.5, 7.5)  # a price alone
    assert complete_line_item(2, None, None) == (2, 0.0, 0.0)  # nothing to work from


def test_extraction_carries_additional_fields_through():
    extraction = _sample_extraction()
    extraction.additional_fields = [AdditionalField(label="PO number", value="88-4410")]
    assert extraction.to_invoice().additional_fields[0].value == "88-4410"
