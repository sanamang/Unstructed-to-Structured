"""Three distinct invoice layout renderers built on reportlab.

Deliberately varying layout (label positions, table styles, where totals
sit) is the point: it forces the downstream extraction step to rely on
visual/positional understanding rather than a fixed text template.
"""

from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen.canvas import Canvas

CURRENCY_SYMBOLS = {"USD": "$", "GBP": "£", "EUR": "€"}
PAGE_W, PAGE_H = letter


# The ISO code is printed on every "Total Due" label: a bare "$" is ambiguous
# (USD vs. CAD/AUD/SGD...), especially from a vendor based outside the US.
def _fmt_money(amount: float | None, currency: str) -> str:
    if amount is None:
        return ""
    symbol = CURRENCY_SYMBOLS.get(currency, currency + " ")
    return f"{symbol}{amount:,.2f}"


def _draw_wrapped(c: Canvas, text: str, x: float, y: float, max_width: float, font: str, size: float, leading: float) -> float:
    """Draw left-aligned text wrapped to max_width. Returns y after the last line."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    words = text.split()
    line = ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if stringWidth(candidate, font, size) > max_width and line:
            c.setFont(font, size)
            c.drawString(x, y, line)
            y -= leading
            line = word
        else:
            line = candidate
    if line:
        c.setFont(font, size)
        c.drawString(x, y, line)
        y -= leading
    return y


def render_classic_table(c: Canvas, inv: dict) -> None:
    """Traditional layout: header block top-left, big 'INVOICE' title top-right,
    bordered items table, totals boxed in the bottom-right."""
    currency = inv["currency"]
    margin = 0.75 * inch
    y = PAGE_H - margin

    # Vendor block (top-left)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(margin, y, inv["vendor_name"])
    y -= 18
    c.setFont("Helvetica", 9)
    for line in inv["vendor_address"]:
        c.drawString(margin, y, line)
        y -= 12

    # Title (top-right)
    c.setFont("Helvetica-Bold", 24)
    c.drawRightString(PAGE_W - margin, PAGE_H - margin, "INVOICE")

    # Meta block under title
    meta_y = PAGE_H - margin - 30
    c.setFont("Helvetica", 10)
    if inv.get("invoice_number") is not None:
        c.drawRightString(PAGE_W - margin, meta_y, f"Invoice #: {inv['invoice_number']}")
        meta_y -= 14
    if inv.get("invoice_date") is not None:
        c.drawRightString(PAGE_W - margin, meta_y, f"Invoice Date: {inv['invoice_date']}")
        meta_y -= 14
    if inv.get("due_date") is not None:
        c.drawRightString(PAGE_W - margin, meta_y, f"Due Date: {inv['due_date']}")
        meta_y -= 14

    # Bill To
    y -= 20
    c.setFont("Helvetica-Bold", 10)
    c.drawString(margin, y, "BILL TO")
    y -= 14
    c.setFont("Helvetica", 9)
    c.drawString(margin, y, inv["customer_name"])
    y -= 12
    for line in inv["customer_address"]:
        c.drawString(margin, y, line)
        y -= 12

    # Items table
    y -= 20
    table_top = y
    col_desc_x = margin
    col_qty_x = margin + 3.0 * inch
    col_price_x = margin + 3.8 * inch
    col_total_x = PAGE_W - margin

    c.setFont("Helvetica-Bold", 9)
    c.drawString(col_desc_x, y, "DESCRIPTION")
    c.drawString(col_qty_x, y, "QTY")
    c.drawString(col_price_x, y, "UNIT PRICE")
    c.drawRightString(col_total_x, y, "LINE TOTAL")
    y -= 6
    c.line(margin, y, PAGE_W - margin, y)
    y -= 14

    c.setFont("Helvetica", 9)
    for item in inv["line_items"]:
        c.drawString(col_desc_x, y, item["description"][:48])
        c.drawString(col_qty_x, y, f"{item['quantity']:g}")
        c.drawString(col_price_x, y, _fmt_money(item["unit_price"], currency))
        c.drawRightString(col_total_x, y, _fmt_money(item["line_total"], currency))
        y -= 16

    y -= 4
    c.line(margin, y, PAGE_W - margin, y)
    y -= 20

    # Totals box (bottom-right)
    box_x = PAGE_W - margin - 2.2 * inch
    c.setFont("Helvetica", 10)
    if inv.get("subtotal") is not None:
        c.drawString(box_x, y, "Subtotal:")
        c.drawRightString(col_total_x, y, _fmt_money(inv["subtotal"], currency))
        y -= 16
    if inv.get("tax") is not None:
        c.drawString(box_x, y, "Tax:")
        c.drawRightString(col_total_x, y, _fmt_money(inv["tax"], currency))
        y -= 16
    y -= 4
    c.setFont("Helvetica-Bold", 12)
    c.drawString(box_x, y, f"Total Due ({currency}):")
    c.drawRightString(col_total_x, y, _fmt_money(inv["total_due"], currency))

    c.setFont("Helvetica-Oblique", 8)
    c.drawString(margin, 0.6 * inch, "Thank you for your business.")


def render_modern_minimal(c: Canvas, inv: dict) -> None:
    """Minimal layout: colored header band, thin rules instead of a boxed
    table, totals as a plain stacked block (no box) at bottom-right, and an
    'AMOUNT PAID' decoy line above 'Total Due' to stress position-sensitive
    extraction."""
    currency = inv["currency"]
    accent = colors.HexColor("#2b4f81")
    margin = 0.7 * inch

    # Header band
    c.setFillColor(accent)
    c.rect(0, PAGE_H - 1.3 * inch, PAGE_W, 1.3 * inch, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(margin, PAGE_H - 0.75 * inch, inv["vendor_name"])
    c.setFont("Helvetica", 9)
    addr_y = PAGE_H - 0.95 * inch
    for line in inv["vendor_address"]:
        c.drawString(margin, addr_y, line)
        addr_y -= 11

    c.setFillColor(colors.black)
    y = PAGE_H - 1.7 * inch

    c.setFont("Helvetica-Bold", 14)
    c.drawString(margin, y, "Invoice")
    c.setFont("Helvetica", 9)
    meta_x = margin + 1.3 * inch
    if inv.get("invoice_number") is not None:
        c.drawString(meta_x, y, f"No. {inv['invoice_number']}")
    y -= 14
    if inv.get("invoice_date") is not None:
        c.drawString(margin, y, f"Date issued  {inv['invoice_date']}")
    if inv.get("due_date") is not None:
        c.drawString(meta_x + 1.4 * inch, y, f"Payment due  {inv['due_date']}")
    y -= 26

    c.setFont("Helvetica-Bold", 9)
    c.drawString(margin, y, "BILLED TO")
    y -= 13
    c.setFont("Helvetica", 9)
    c.drawString(margin, y, inv["customer_name"])
    y -= 11
    for line in inv["customer_address"]:
        c.drawString(margin, y, line)
        y -= 11

    y -= 24
    col_desc_x = margin
    col_qty_x = margin + 3.1 * inch
    col_price_x = margin + 3.9 * inch
    col_total_x = PAGE_W - margin

    c.setFillColor(accent)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(col_desc_x, y, "ITEM")
    c.drawString(col_qty_x, y, "QTY")
    c.drawString(col_price_x, y, "RATE")
    c.drawRightString(col_total_x, y, "AMOUNT")
    c.setFillColor(colors.black)
    y -= 4
    c.setStrokeColor(accent)
    c.line(margin, y, PAGE_W - margin, y)
    c.setStrokeColor(colors.black)
    y -= 16

    c.setFont("Helvetica", 9)
    for item in inv["line_items"]:
        c.drawString(col_desc_x, y, item["description"][:48])
        c.drawString(col_qty_x, y, f"{item['quantity']:g}")
        c.drawString(col_price_x, y, _fmt_money(item["unit_price"], currency))
        c.drawRightString(col_total_x, y, _fmt_money(item["line_total"], currency))
        y -= 15
        c.setStrokeColor(colors.HexColor("#dddddd"))
        c.line(margin, y + 5, PAGE_W - margin, y + 5)
        c.setStrokeColor(colors.black)

    y -= 20
    box_x = PAGE_W - margin - 2.3 * inch
    c.setFont("Helvetica", 9)
    if inv.get("subtotal") is not None:
        c.drawString(box_x, y, "Subtotal")
        c.drawRightString(col_total_x, y, _fmt_money(inv["subtotal"], currency))
        y -= 14
    if inv.get("tax") is not None:
        c.drawString(box_x, y, "Tax")
        c.drawRightString(col_total_x, y, _fmt_money(inv["tax"], currency))
        y -= 14

    # Decoy "amount paid" line (always $0, before total) to make position
    # matter for the extractor, not just the nearest label match.
    c.drawString(box_x, y, "Amount Paid")
    c.drawRightString(col_total_x, y, _fmt_money(0.0, currency))
    y -= 18

    c.setStrokeColor(accent)
    c.line(box_x, y + 6, PAGE_W - margin, y + 6)
    c.setStrokeColor(colors.black)
    c.setFont("Helvetica-Bold", 13)
    c.setFillColor(accent)
    c.drawString(box_x, y - 8, f"Total Due ({currency})")
    c.drawRightString(col_total_x, y - 8, _fmt_money(inv["total_due"], currency))
    c.setFillColor(colors.black)


def render_compact(c: Canvas, inv: dict) -> None:
    """Dense, small-margin layout: single top strip with all invoice meta in
    a row, tight table, totals rendered inline (not boxed) directly under the
    table with no extra whitespace."""
    currency = inv["currency"]
    margin = 0.5 * inch
    y = PAGE_H - margin

    c.setFont("Helvetica-Bold", 13)
    c.drawString(margin, y, inv["vendor_name"])
    c.setFont("Helvetica-Bold", 18)
    c.drawRightString(PAGE_W - margin, y, "INVOICE")
    y -= 13
    c.setFont("Helvetica", 8)
    for line in inv["vendor_address"]:
        c.drawString(margin, y, line)
        y -= 10

    y -= 6
    c.setStrokeColor(colors.black)
    c.line(margin, y, PAGE_W - margin, y)
    y -= 12

    meta_parts = []
    if inv.get("invoice_number") is not None:
        meta_parts.append(f"Invoice #{inv['invoice_number']}")
    if inv.get("invoice_date") is not None:
        meta_parts.append(f"Issued {inv['invoice_date']}")
    if inv.get("due_date") is not None:
        meta_parts.append(f"Due {inv['due_date']}")
    c.setFont("Helvetica", 8)
    c.drawString(margin, y, "   |   ".join(meta_parts))
    y -= 10
    c.drawString(margin, y, f"Bill To: {inv['customer_name']}, {', '.join(inv['customer_address'])}")
    y -= 18

    col_desc_x = margin
    col_qty_x = margin + 3.3 * inch
    col_price_x = margin + 4.0 * inch
    col_total_x = PAGE_W - margin

    c.setFont("Helvetica-Bold", 8)
    c.drawString(col_desc_x, y, "DESC")
    c.drawString(col_qty_x, y, "QTY")
    c.drawString(col_price_x, y, "PRICE")
    c.drawRightString(col_total_x, y, "TOTAL")
    y -= 10
    c.setFont("Helvetica", 8)
    for item in inv["line_items"]:
        c.drawString(col_desc_x, y, item["description"][:52])
        c.drawString(col_qty_x, y, f"{item['quantity']:g}")
        c.drawString(col_price_x, y, _fmt_money(item["unit_price"], currency))
        c.drawRightString(col_total_x, y, _fmt_money(item["line_total"], currency))
        y -= 11

    y -= 4
    c.line(margin, y, PAGE_W - margin, y)
    y -= 12

    c.setFont("Helvetica", 8)
    if inv.get("subtotal") is not None:
        c.drawRightString(col_total_x, y, f"Subtotal: {_fmt_money(inv['subtotal'], currency)}")
        y -= 10
    if inv.get("tax") is not None:
        c.drawRightString(col_total_x, y, f"Tax: {_fmt_money(inv['tax'], currency)}")
        y -= 10
    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(col_total_x, y, f"Total Due ({currency}): {_fmt_money(inv['total_due'], currency)}")


TEMPLATES = {
    "classic_table": render_classic_table,
    "modern_minimal": render_modern_minimal,
    "compact": render_compact,
}


def render_invoice_pdf(path: str, inv: dict, template_name: str) -> None:
    c = Canvas(path, pagesize=letter)
    TEMPLATES[template_name](c, inv)
    c.showPage()
    c.save()
