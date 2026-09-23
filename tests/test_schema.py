from invoice_pipeline.schema import Invoice, LineItem


def test_line_item_parses():
    item = LineItem(description="Widget", quantity=2, unit_price=10.0, line_total=20.0)
    assert item.line_total == 20.0


def test_invoice_defaults_allow_missing_optional_fields():
    inv = Invoice(vendor_name="Acme", line_items=[])
    assert inv.invoice_number is None
    assert inv.due_date is None
    assert inv.line_items == []


def test_invoice_parses_full_record():
    inv = Invoice(
        vendor_name="Acme",
        invoice_number="INV-001",
        invoice_date="2025-01-01",
        due_date="2025-01-31",
        line_items=[LineItem(description="Widget", quantity=1, unit_price=5.0, line_total=5.0)],
        subtotal=5.0,
        tax=0.5,
        total_due=5.5,
        currency="USD",
    )
    assert len(inv.line_items) == 1
    assert inv.total_due == 5.5
