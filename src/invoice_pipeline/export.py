"""Stage 7: output layer.

Exports accepted invoices (auto-accepted or human-resolved) from the system
of record as CSV or JSON for downstream systems. Pending-review and
unrecognized documents are never exported - accepted is the only status
that means "a human or the validator has signed off on these values".

CSV comes as two files, since line items are one-to-many: `invoices.csv`
(one row per invoice) and `line_items.csv` (one row per line item, keyed by
document_id). JSON is a single list of invoices with line items nested.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import io
import json
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from invoice_pipeline.models import Document, DocumentStatus

INVOICE_COLUMNS = (
    "document_id",
    "source_filename",
    "vendor_name",
    "invoice_number",
    "invoice_date",
    "due_date",
    "subtotal",
    "tax",
    "total_due",
    "currency",
    "line_item_count",
    "human_corrected",
    "resolved_at",
)

LINE_ITEM_COLUMNS = (
    "document_id",
    "invoice_number",
    "line_number",
    "description",
    "quantity",
    "unit_price",
    "line_total",
)


def accepted_invoices(session: Session, since: Optional[datetime.datetime] = None) -> list[dict]:
    """Every accepted invoice as a plain dict (line items nested), ordered by
    resolution time. `since` filters to invoices resolved at or after it, for
    incremental exports."""
    query = session.query(Document).filter(
        Document.status == DocumentStatus.ACCEPTED,
        Document.invoice.has(),
    )
    if since is not None:
        query = query.filter(Document.resolved_at >= since)
    documents = query.order_by(Document.resolved_at, Document.id).all()

    records = []
    for document in documents:
        invoice = document.invoice
        records.append(
            {
                "document_id": document.id,
                "source_filename": document.source_filename,
                "vendor_name": invoice.vendor_name,
                "invoice_number": invoice.invoice_number,
                "invoice_date": invoice.invoice_date,
                "due_date": invoice.due_date,
                "subtotal": invoice.subtotal,
                "tax": invoice.tax,
                "total_due": invoice.total_due,
                "currency": invoice.currency,
                "line_items": list(invoice.line_items or []),
                "human_corrected": len(document.corrections) > 0,
                "resolved_at": document.resolved_at.isoformat() if document.resolved_at else None,
            }
        )
    return records


def to_json(records: list[dict]) -> str:
    return json.dumps(records, indent=2)


def invoices_csv(records: list[dict]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=INVOICE_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for record in records:
        row = {column: record.get(column) for column in INVOICE_COLUMNS}
        row["line_item_count"] = len(record["line_items"])
        writer.writerow(row)
    return buffer.getvalue()


def line_items_csv(records: list[dict]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=LINE_ITEM_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for record in records:
        for n, item in enumerate(record["line_items"], start=1):
            writer.writerow(
                {
                    "document_id": record["document_id"],
                    "invoice_number": record["invoice_number"],
                    "line_number": n,
                    "description": item.get("description"),
                    "quantity": item.get("quantity"),
                    "unit_price": item.get("unit_price"),
                    "line_total": item.get("line_total"),
                }
            )
    return buffer.getvalue()


def write_export(records: list[dict], out_dir: str | Path, fmt: str = "csv") -> list[Path]:
    """Write `records` (from `accepted_invoices`) to `out_dir` and return the
    files written."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if fmt == "json":
        path = out_dir / "invoices.json"
        path.write_text(to_json(records))
        return [path]
    if fmt == "csv":
        invoices_path = out_dir / "invoices.csv"
        line_items_path = out_dir / "line_items.csv"
        invoices_path.write_text(invoices_csv(records))
        line_items_path.write_text(line_items_csv(records))
        return [invoices_path, line_items_path]
    raise ValueError(f"unsupported export format {fmt!r} (expected 'csv' or 'json')")


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Export accepted invoices from the system of record.")
    parser.add_argument("--format", choices=("csv", "json"), default="csv")
    parser.add_argument("--out", default="exports", help="output directory (default: exports/)")
    parser.add_argument(
        "--since",
        type=datetime.datetime.fromisoformat,
        default=None,
        help="only invoices resolved at or after this ISO timestamp, e.g. 2026-09-01",
    )
    args = parser.parse_args(argv)

    from invoice_pipeline.db import SessionLocal, init_db

    init_db()
    with SessionLocal() as session:
        records = accepted_invoices(session, since=args.since)
    paths = write_export(records, args.out, fmt=args.format)
    print(f"Exported {len(records)} accepted invoice(s):")
    for path in paths:
        print(f"  {path}")


if __name__ == "__main__":
    main()
