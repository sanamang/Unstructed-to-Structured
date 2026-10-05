# Sample messy invoices

Real-world-style billing documents that don't look like a tidy invoice
template, with the structured invoice the pipeline extracted from each.
Upload any of them in the review UI to try it.

| File | What makes it messy | Extracted | Result |
| --- | --- | --- | --- |
| [messy_invoice.pdf](messy_invoice.pdf) | A chatty letter. Charges are written as sentences ("retouching 35 product photos, I charge $12/photo"), and a $500 deposit is mentioned but not deducted. | Marguerite Okonkwo, #MO-0917, 4 line items, subtotal 2,069.00 + HST 310.35 = **2,379.35 CAD**, due 2026-10-17 | Auto-accepted |
| [messy_invoice_scan.jpg](messy_invoice_scan.jpg) | The same letter as a noisy, skewed scan | Same values as the PDF | Auto-accepted |
| [numbers_everywhere_invoice.jpg](numbers_everywhere_invoice.jpg) | A dense invoice full of decoy numbers: account, PO and tracking numbers, a backordered line at 0.00, an account summary with a previous balance and a total account balance of 2,378.04, an unapplied early-payment discount, a "RECEIVED" stamp and handwritten approval notes | Northgate Supply Co., #NGS-48213, 6 line items, 1,889.95 + HST 283.49 = **2,173.44 CAD** (not the 2,378.04 account balance) | Auto-accepted |
| [messy_invoice_needs_review.jpg](messy_invoice_needs_review.jpg) | An informal email. The invoice number is uncertain ("2291 or 2297"), one price is crossed out, there's no due date, and the stated subtotal doesn't match the line items | Kowalczyk Plumbing & Heating, #2291, 4 line items, **712.99 CAD** | Sent to review: line items sum to 594.99 but the stated subtotal is 619.99 |

Everything on a document that isn't a standard invoice field (addresses, PO
numbers, payment terms, notes) is kept under `additional_fields`.
