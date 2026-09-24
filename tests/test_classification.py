from invoice_pipeline.classification import DocumentClassification, classify_document
from invoice_pipeline.ingestion import ingest_file


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


def test_classify_document_returns_parsed_output(tmp_path):
    doc = ingest_file("manual_test_pdfs/test_invoice_01.pdf")
    expected = DocumentClassification(doc_type="invoice", confidence=0.97, reasoning="Has line items and a total due.")
    fake_client = _FakeClient(expected)

    result = classify_document(doc, client=fake_client, model="claude-opus-5")

    assert result == expected
    # sanity check the request actually included an image block per page
    content = fake_client.messages.last_call_kwargs["messages"][0]["content"]
    assert any(block["type"] == "image" for block in content)
    assert fake_client.messages.last_call_kwargs["output_format"] is DocumentClassification
