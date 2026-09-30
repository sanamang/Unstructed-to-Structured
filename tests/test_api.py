import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import invoice_pipeline.pipeline as pipeline_module
from invoice_pipeline import models  # noqa: F401
from invoice_pipeline.api import main as api_main
from invoice_pipeline.classification import DocumentClassification
from invoice_pipeline.db import Base, make_session_factory
from invoice_pipeline.schema import ExtractedNumber, ExtractedString, InvoiceExtraction, LineItemExtraction


def _clean_extraction() -> InvoiceExtraction:
    high = 0.95
    return InvoiceExtraction(
        vendor_name=ExtractedString(value="Acme Industrial Supplies", confidence=high, page=1),
        invoice_number=ExtractedString(value="INV-000123", confidence=high, page=1),
        invoice_date=ExtractedString(value="2025-01-01", confidence=high, page=1),
        due_date=ExtractedString(value="2025-01-31", confidence=high, page=1),
        line_items=[
            LineItemExtraction(
                description=ExtractedString(value="Widget", confidence=high, page=1),
                quantity=ExtractedNumber(value=2, confidence=high, page=1),
                unit_price=ExtractedNumber(value=10.0, confidence=high, page=1),
                line_total=ExtractedNumber(value=20.0, confidence=high, page=1),
            )
        ],
        subtotal=ExtractedNumber(value=20.0, confidence=high, page=1),
        tax=ExtractedNumber(value=1.6, confidence=high, page=1),
        total_due=ExtractedNumber(value=21.6, confidence=high, page=1),
        currency=ExtractedString(value="USD", confidence=high, page=1),
    )


@pytest.fixture()
def client(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)

    monkeypatch.setattr(pipeline_module, "UPLOADS_DIR", tmp_path / "uploads")
    monkeypatch.setattr(pipeline_module, "PAGES_DIR", tmp_path / "pages")
    monkeypatch.setattr(api_main, "PAGES_DIR", tmp_path / "pages")
    monkeypatch.setattr(api_main, "UPLOADS_DIR", tmp_path / "uploads")
    monkeypatch.setattr(api_main, "init_db", lambda: None)  # skip touching real Postgres
    monkeypatch.setattr(
        pipeline_module,
        "classify_document",
        lambda doc, client=None: DocumentClassification(doc_type="invoice", confidence=0.98, reasoning="ok"),
    )
    monkeypatch.setattr(pipeline_module, "extract_invoice", lambda doc, client=None: _clean_extraction())

    def override_get_session():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    api_main.app.dependency_overrides[api_main.get_session] = override_get_session

    with TestClient(api_main.app) as test_client:
        yield test_client

    api_main.app.dependency_overrides.clear()


def _upload(client: TestClient, path: str = "manual_test_pdfs/test_invoice_01.pdf"):
    with open(path, "rb") as f:
        return client.post("/api/upload", files={"file": ("test_invoice_01.pdf", f, "application/pdf")})


def test_health_check(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_upload_document_persists_and_returns_detail(client):
    response = _upload(client)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"
    assert body["vendor_name"] == "Acme Industrial Supplies"
    assert body["total_due"] == 21.6
    assert body["page_urls"] == [f"/static/pages/{body['id']}/page_001.png"]
    assert body["field_meta"]["due_date"]["confidence"] == 0.95


def test_list_documents_returns_uploaded_document(client):
    upload_body = _upload(client).json()
    response = client.get("/api/documents")
    assert response.status_code == 200
    ids = [d["id"] for d in response.json()]
    assert upload_body["id"] in ids


def test_list_documents_filters_by_status(client):
    _upload(client)
    accepted = client.get("/api/documents", params={"status": "accepted"}).json()
    pending = client.get("/api/documents", params={"status": "pending_review"}).json()
    assert len(accepted) == 1
    assert len(pending) == 0


def test_get_document_detail_by_id(client):
    doc_id = _upload(client).json()["id"]
    response = client.get(f"/api/documents/{doc_id}")
    assert response.status_code == 200
    assert response.json()["id"] == doc_id


def test_get_document_detail_404_for_unknown_id(client):
    response = client.get("/api/documents/does-not-exist")
    assert response.status_code == 404


def test_review_document_applies_correction_and_logs_it(client):
    doc_id = _upload(client).json()["id"]

    response = client.post(
        f"/api/documents/{doc_id}/review",
        json={"fields": {"vendor_name": "Acme Corrected LLC", "total_due": 21.6}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["vendor_name"] == "Acme Corrected LLC"
    assert body["status"] == "accepted"
    assert body["resolved_at"] is not None

    # Re-fetch to confirm the correction persisted, not just the response echo.
    refetched = client.get(f"/api/documents/{doc_id}").json()
    assert refetched["vendor_name"] == "Acme Corrected LLC"


def test_export_includes_only_accepted_invoices(client):
    _upload(client)  # clean extraction -> auto-accepted

    csv_response = client.get("/api/export/invoices.csv")
    assert csv_response.status_code == 200
    assert csv_response.headers["content-type"].startswith("text/csv")
    assert 'filename="invoices.csv"' in csv_response.headers["content-disposition"]
    lines = csv_response.text.strip().splitlines()
    assert len(lines) == 2 and "INV-000123" in lines[1]

    json_response = client.get("/api/export/invoices.json")
    assert json_response.json()[0]["vendor_name"] == "Acme Industrial Supplies"

    line_items_response = client.get("/api/export/line_items.csv")
    assert "Widget" in line_items_response.text


def test_export_rejects_unknown_filename(client):
    assert client.get("/api/export/secrets.txt").status_code == 404
