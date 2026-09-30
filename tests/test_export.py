import csv
import datetime
import io
import json

from invoice_pipeline.export import accepted_invoices, invoices_csv, line_items_csv, to_json, write_export
from invoice_pipeline.models import Correction, Document, DocumentStatus, InvoiceRecord


def _add_document(session, doc_id, status, resolved_at=None, invoice_number="INV-1", with_invoice=True):
    document = Document(
        id=doc_id,
        source_filename=f"{doc_id}.pdf",
        file_path=f"var/uploads/{doc_id}.pdf",
        doc_type="invoice" if with_invoice else "unrecognized",
        classification_confidence=0.97,
        status=status,
        validation_issues=[],
        page_count=1,
        resolved_at=resolved_at,
    )
    if with_invoice:
        document.invoice = InvoiceRecord(
            vendor_name="Acme, Inc.",
            invoice_number=invoice_number,
            invoice_date="2026-01-01",
            due_date="2026-01-31",
            subtotal=30.0,
            tax=3.0,
            total_due=33.0,
            currency="USD",
            line_items=[
                {"description": "Widget", "quantity": 2, "unit_price": 10.0, "line_total": 20.0},
                {"description": "Gadget", "quantity": 1, "unit_price": 10.0, "line_total": 10.0},
            ],
            field_meta={},
        )
    session.add(document)
    session.commit()
    return document


def _seed(session):
    _add_document(session, "accepted_1", DocumentStatus.ACCEPTED, datetime.datetime(2026, 9, 1), "INV-1")
    _add_document(session, "accepted_2", DocumentStatus.ACCEPTED, datetime.datetime(2026, 9, 20), "INV-2")
    _add_document(session, "pending", DocumentStatus.PENDING_REVIEW, None, "INV-3")
    _add_document(session, "junk", DocumentStatus.UNRECOGNIZED, None, with_invoice=False)
    session.add(Correction(document_id="accepted_2", field="tax", original_value="3.5", corrected_value="3.0"))
    session.commit()


def test_only_accepted_invoices_are_exported_in_resolution_order(db_session):
    _seed(db_session)
    records = accepted_invoices(db_session)
    assert [r["document_id"] for r in records] == ["accepted_1", "accepted_2"]
    assert [r["human_corrected"] for r in records] == [False, True]
    assert records[0]["line_items"][0]["description"] == "Widget"


def test_since_filters_by_resolved_at(db_session):
    _seed(db_session)
    records = accepted_invoices(db_session, since=datetime.datetime(2026, 9, 10))
    assert [r["document_id"] for r in records] == ["accepted_2"]


def test_invoices_csv_has_one_row_per_invoice(db_session):
    _seed(db_session)
    rows = list(csv.DictReader(io.StringIO(invoices_csv(accepted_invoices(db_session)))))
    assert len(rows) == 2
    assert rows[0]["vendor_name"] == "Acme, Inc."  # comma survives quoting
    assert rows[0]["total_due"] == "33.0"
    assert rows[0]["line_item_count"] == "2"
    assert rows[1]["human_corrected"] == "True"


def test_line_items_csv_has_one_row_per_line_item(db_session):
    _seed(db_session)
    rows = list(csv.DictReader(io.StringIO(line_items_csv(accepted_invoices(db_session)))))
    assert len(rows) == 4
    assert [(r["document_id"], r["line_number"]) for r in rows[:2]] == [("accepted_1", "1"), ("accepted_1", "2")]
    assert rows[2]["invoice_number"] == "INV-2"


def test_json_export_nests_line_items(db_session):
    _seed(db_session)
    data = json.loads(to_json(accepted_invoices(db_session)))
    assert len(data) == 2
    assert len(data[1]["line_items"]) == 2
    assert data[1]["resolved_at"].startswith("2026-09-20")


def test_write_export_writes_files(db_session, tmp_path):
    _seed(db_session)
    records = accepted_invoices(db_session)
    csv_paths = write_export(records, tmp_path, fmt="csv")
    json_paths = write_export(records, tmp_path, fmt="json")
    assert sorted(p.name for p in csv_paths + json_paths) == ["invoices.csv", "invoices.json", "line_items.csv"]
    assert all(p.exists() for p in csv_paths + json_paths)


def test_empty_export_still_has_headers(db_session):
    assert invoices_csv([]).startswith("document_id,source_filename,")
    assert line_items_csv([]).startswith("document_id,invoice_number,line_number,")
    assert to_json([]) == "[]"
