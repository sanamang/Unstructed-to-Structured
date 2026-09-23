"""Synthetic invoice generator.

Produces a set of sample invoices (PDF, with a few rendered as noisy/skewed
"scanned" images instead) plus a matching ground-truth JSON file per invoice,
under sample_data/. The ground truth is used later by the eval script to
score extraction accuracy.

Usage:
    python -m invoice_pipeline.datagen.generate --count 25 --seed 42 \
        --output-dir sample_data
"""

from __future__ import annotations

import argparse
import json
import random
import tempfile
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from invoice_pipeline.datagen.scan_effects import make_scanned_image
from invoice_pipeline.datagen.templates import TEMPLATES, render_invoice_pdf
from invoice_pipeline.datagen.vendors import CUSTOMERS, LINE_ITEM_POOL, VENDORS

TEMPLATE_NAMES = list(TEMPLATES.keys())


@dataclass
class PlannedInvoice:
    index: int
    template_name: str
    vendor: dict
    customer: dict
    deliberate_issues: list[str] = field(default_factory=list)
    is_scanned_simulation: bool = False


def _plan_invoices(count: int, rng: random.Random) -> list[PlannedInvoice]:
    n_missing = max(1, round(count * 0.16))
    n_math_error = max(1, round(count * 0.16))
    n_bad_due_date = max(1, round(count * 0.12))
    n_scanned = max(1, round(count * 0.16))

    issue_slots: list[list[str]] = [[] for _ in range(count)]
    indices = list(range(count))
    rng.shuffle(indices)
    cursor = 0
    for _ in range(n_missing):
        issue_slots[indices[cursor]].append("missing_field")
        cursor += 1
    for _ in range(n_math_error):
        issue_slots[indices[cursor]].append("math_error")
        cursor += 1
    for _ in range(n_bad_due_date):
        issue_slots[indices[cursor]].append("bad_due_date")
        cursor += 1

    # Scanned rendering is layered only on invoices with clean data, so the
    # eval can separate "OCR/vision degraded the read" from "the source data
    # itself was inconsistent."
    clean_indices = [i for i in range(count) if not issue_slots[i]]
    rng.shuffle(clean_indices)
    scanned_indices = set(clean_indices[:n_scanned])

    planned = []
    for i in range(count):
        planned.append(
            PlannedInvoice(
                index=i,
                template_name=TEMPLATE_NAMES[i % len(TEMPLATE_NAMES)],
                vendor=rng.choice(VENDORS),
                customer=rng.choice(CUSTOMERS),
                deliberate_issues=issue_slots[i],
                is_scanned_simulation=i in scanned_indices,
            )
        )
    rng.shuffle(planned)  # decouple template rotation from issue assignment order
    for i, p in enumerate(planned):
        p.index = i
    return planned


def _build_line_items(rng: random.Random) -> list[dict]:
    n_items = rng.randint(1, 6)
    chosen = rng.sample(LINE_ITEM_POOL, k=min(n_items, len(LINE_ITEM_POOL)))
    items = []
    for desc, unit_price, unit in chosen:
        if unit in ("hr", "unit", "box", "pallet"):
            qty = rng.randint(1, 12)
        elif unit == "seat":
            qty = rng.randint(1, 25)
        else:
            qty = 1
        unit_price = round(unit_price * rng.uniform(0.9, 1.12), 2)
        line_total = round(qty * unit_price, 2)
        items.append(
            {
                "description": desc,
                "quantity": float(qty),
                "unit_price": unit_price,
                "line_total": line_total,
            }
        )
    return items


def _build_invoice_data(plan: PlannedInvoice, rng: random.Random) -> dict:
    vendor = plan.vendor
    customer = plan.customer
    line_items = _build_line_items(rng)

    subtotal = round(sum(item["line_total"] for item in line_items), 2)
    tax = round(subtotal * vendor["tax_rate"], 2)
    total_due = round(subtotal + tax, 2)

    invoice_date = date.today() - timedelta(days=rng.randint(5, 200))
    due_date = invoice_date + timedelta(days=rng.choice([15, 30, 45]))

    inv = {
        "vendor_name": vendor["name"],
        "vendor_address": vendor["address"],
        "customer_name": customer["name"],
        "customer_address": customer["address"],
        "invoice_number": f"INV-{2024_000 + plan.index * 7 + rng.randint(0, 6):06d}",
        "invoice_date": invoice_date.isoformat(),
        "due_date": due_date.isoformat(),
        "line_items": line_items,
        "subtotal": subtotal,
        "tax": tax,
        "total_due": total_due,
        "currency": vendor["currency"],
    }

    for issue in plan.deliberate_issues:
        if issue == "missing_field":
            field_to_drop = rng.choice(["due_date", "tax"])
            inv[field_to_drop] = None
        elif issue == "math_error":
            corruption = rng.choice(["line_items_vs_subtotal", "subtotal_tax_vs_total"])
            if corruption == "line_items_vs_subtotal":
                # Stated subtotal no longer matches the sum of line items.
                inv["subtotal"] = round(subtotal + rng.choice([-1, 1]) * rng.uniform(15, 60), 2)
                inv["total_due"] = round(inv["subtotal"] + tax, 2)
            else:
                # Subtotal + tax no longer matches the stated total due.
                inv["total_due"] = round(subtotal + tax + rng.choice([-1, 1]) * rng.uniform(10, 40), 2)
        elif issue == "bad_due_date":
            # Due date set before the invoice date.
            inv["due_date"] = (invoice_date - timedelta(days=rng.randint(1, 20))).isoformat()

    return inv


def generate_dataset(count: int, seed: int, output_dir: Path) -> list[dict]:
    rng = random.Random(seed)
    invoices_dir = output_dir / "invoices"
    ground_truth_dir = output_dir / "ground_truth"
    invoices_dir.mkdir(parents=True, exist_ok=True)
    ground_truth_dir.mkdir(parents=True, exist_ok=True)

    plans = _plan_invoices(count, rng)
    manifest = []

    for plan in plans:
        inv_data = _build_invoice_data(plan, rng)
        base_name = f"invoice_{plan.index:03d}"

        if plan.is_scanned_simulation:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
                render_invoice_pdf(tmp.name, inv_data, plan.template_name)
                file_name = f"{base_name}_scan.jpg"
                make_scanned_image(tmp.name, str(invoices_dir / file_name), seed=rng.randint(0, 2**31 - 1))
        else:
            file_name = f"{base_name}.pdf"
            render_invoice_pdf(str(invoices_dir / file_name), inv_data, plan.template_name)

        ground_truth = {
            "vendor_name": inv_data["vendor_name"],
            "invoice_number": inv_data["invoice_number"],
            "invoice_date": inv_data["invoice_date"],
            "due_date": inv_data["due_date"],
            "line_items": inv_data["line_items"],
            "subtotal": inv_data["subtotal"],
            "tax": inv_data["tax"],
            "total_due": inv_data["total_due"],
            "currency": inv_data["currency"],
        }

        record = {
            "file": f"invoices/{file_name}",
            "doc_type": "invoice",
            "template": plan.template_name,
            "vendor_id": plan.vendor["id"],
            "is_scanned_simulation": plan.is_scanned_simulation,
            "deliberate_issues": plan.deliberate_issues,
            "ground_truth": ground_truth,
        }

        gt_path = ground_truth_dir / f"{base_name}.json"
        gt_path.write_text(json.dumps(record, indent=2))
        manifest.append(record)

    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def generate_manual_test_pdfs(count: int, seed: int, output_dir: Path) -> list[dict]:
    """Generate a small set of plain, clean invoice PDFs (no deliberate data
    issues, no scan degradation) for ad hoc manual testing of the ingestion/
    extraction pipeline outside of the eval fixture set in sample_data/.
    Still writes a reference JSON per PDF so you can eyeball whether the
    pipeline's output matches, but these aren't wired into the eval script.
    """
    rng = random.Random(seed)
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = []
    for i in range(count):
        plan = PlannedInvoice(
            index=i,
            template_name=TEMPLATE_NAMES[i % len(TEMPLATE_NAMES)],
            vendor=rng.choice(VENDORS),
            customer=rng.choice(CUSTOMERS),
            deliberate_issues=[],
            is_scanned_simulation=False,
        )
        inv_data = _build_invoice_data(plan, rng)
        file_name = f"test_invoice_{i + 1:02d}.pdf"
        render_invoice_pdf(str(output_dir / file_name), inv_data, plan.template_name)

        record = {
            "file": file_name,
            "template": plan.template_name,
            "vendor_id": plan.vendor["id"],
            "reference_values": {
                "vendor_name": inv_data["vendor_name"],
                "invoice_number": inv_data["invoice_number"],
                "invoice_date": inv_data["invoice_date"],
                "due_date": inv_data["due_date"],
                "line_items": inv_data["line_items"],
                "subtotal": inv_data["subtotal"],
                "tax": inv_data["tax"],
                "total_due": inv_data["total_due"],
                "currency": inv_data["currency"],
            },
        }
        manifest.append(record)

    (output_dir / "reference_values.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic sample invoices + ground truth.")
    parser.add_argument("--count", type=int, default=25)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-dir", type=Path, default=Path("sample_data"))
    args = parser.parse_args()

    manifest = generate_dataset(args.count, args.seed, args.output_dir)

    n_scanned = sum(1 for r in manifest if r["is_scanned_simulation"])
    n_with_issues = sum(1 for r in manifest if r["deliberate_issues"])
    print(f"Generated {len(manifest)} invoices in {args.output_dir}/invoices")
    print(f"  scanned/noisy renders: {n_scanned}")
    print(f"  with deliberate data issues: {n_with_issues}")
    print(f"  clean, well-formed: {len(manifest) - n_with_issues}")
    print(f"Ground truth JSON written to {args.output_dir}/ground_truth")


if __name__ == "__main__":
    main()
