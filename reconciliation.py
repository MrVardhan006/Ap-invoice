"""
reconciliation.py
Compares extracted invoice line items against a mock Purchase Order and
produces a list of Exceptions (mismatches) with fully traceable field-level
detail. This is deliberately NOT an LLM call - matching and flagging is
plain, inspectable Python so every flag can be defended line-by-line.
"""
from dataclasses import dataclass, field, asdict
from difflib import SequenceMatcher
from typing import List, Optional, Dict

PRICE_TOLERANCE_PCT = 1.0   # allow <=1% price variance before flagging
QTY_TOLERANCE_UNITS = 0.0   # any quantity difference is flagged
TAX_TOLERANCE_PCT = 0.5     # allow <=0.5 percentage-point tax variance
DESC_MATCH_THRESHOLD = 0.55  # fuzzy match cutoff for line-item pairing


@dataclass
class Exception_:
    invoice_line_desc: str
    po_line_desc: Optional[str]
    exception_type: str  # PRICE_MISMATCH | QTY_MISMATCH | TAX_MISMATCH | NOT_ON_PO
    severity: str  # low | medium | high
    detail: Dict
    explanation: str


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _match_line_items(invoice_items, po_items):
    """Greedy best-match pairing of invoice lines to PO lines by description
    similarity. Returns list of (invoice_item, po_item_or_None)."""
    po_pool = list(enumerate(po_items))
    pairs = []
    for inv_item in invoice_items:
        best_score, best_idx, best_po = 0.0, None, None
        for idx, po_item in po_pool:
            score = _similarity(inv_item.description, po_item["description"])
            if score > best_score:
                best_score, best_idx, best_po = score, idx, po_item
        if best_score >= DESC_MATCH_THRESHOLD:
            pairs.append((inv_item, best_po))
            po_pool = [(i, p) for i, p in po_pool if i != best_idx]
        else:
            pairs.append((inv_item, None))
    return pairs


def reconcile(invoice, po: dict) -> List[Exception_]:
    exceptions: List[Exception_] = []
    pairs = _match_line_items(invoice.items, po.get("items", []))

    for inv_item, po_item in pairs:
        if po_item is None:
            exceptions.append(Exception_(
                invoice_line_desc=inv_item.description,
                po_line_desc=None,
                exception_type="NOT_ON_PO",
                severity="high",
                detail={
                    "invoice_description": inv_item.description,
                    "invoice_qty": inv_item.qty,
                    "invoice_unit_price": inv_item.unit_price,
                    "po_number": po.get("po_number"),
                },
                explanation=(
                    f'"{inv_item.description}" appears on the invoice '
                    f'(qty {inv_item.qty} @ ${inv_item.unit_price:.2f}) but no line item on '
                    f'PO {po.get("po_number")} matches it closely enough (best fuzzy match '
                    f'below the {DESC_MATCH_THRESHOLD:.0%} similarity threshold). This is either '
                    f'an unauthorized/added item or a description that diverged too far from the PO text.'
                ),
            ))
            continue

        # Price check
        po_price = po_item["unit_price"]
        if po_price > 0:
            pct_diff = abs(inv_item.unit_price - po_price) / po_price * 100
        else:
            pct_diff = 100.0 if inv_item.unit_price != po_price else 0.0
        if pct_diff > PRICE_TOLERANCE_PCT:
            delta = inv_item.unit_price - po_price
            severity = "high" if pct_diff > 10 else "medium"
            exceptions.append(Exception_(
                invoice_line_desc=inv_item.description,
                po_line_desc=po_item["description"],
                exception_type="PRICE_MISMATCH",
                severity=severity,
                detail={
                    "invoice_unit_price": inv_item.unit_price,
                    "po_unit_price": po_price,
                    "delta": round(delta, 2),
                    "pct_diff": round(pct_diff, 1),
                    "po_number": po.get("po_number"),
                    "po_line_item": po_item.get("item_code"),
                },
                explanation=(
                    f'Line "{inv_item.description}" is priced at ${inv_item.unit_price:.2f}/unit on the '
                    f'invoice, but PO {po.get("po_number")} line {po_item.get("item_code", "")} specifies '
                    f'${po_price:.2f}/unit — a {"+" if delta > 0 else ""}${delta:.2f} '
                    f'({pct_diff:.1f}%) {"overage" if delta > 0 else "shortfall"} versus the agreed PO price.'
                ),
            ))

        # Quantity check
        qty_diff = inv_item.qty - po_item["qty"]
        if abs(qty_diff) > QTY_TOLERANCE_UNITS:
            severity = "high" if abs(qty_diff) > po_item["qty"] * 0.2 else "medium"
            exceptions.append(Exception_(
                invoice_line_desc=inv_item.description,
                po_line_desc=po_item["description"],
                exception_type="QTY_MISMATCH",
                severity=severity,
                detail={
                    "invoice_qty": inv_item.qty,
                    "po_qty": po_item["qty"],
                    "delta": qty_diff,
                    "po_number": po.get("po_number"),
                    "po_line_item": po_item.get("item_code"),
                },
                explanation=(
                    f'Line "{inv_item.description}" bills {inv_item.qty} units, but PO '
                    f'{po.get("po_number")} line {po_item.get("item_code", "")} authorized only '
                    f'{po_item["qty"]} units — a difference of {"+" if qty_diff > 0 else ""}{qty_diff:g} units. '
                    f'{"This is a potential over-billing." if qty_diff > 0 else "Fewer units were billed than ordered; verify partial delivery."}'
                ),
            ))

        # Tax check
        inv_tax = inv_item.tax_rate or 0.0
        po_tax = po_item.get("tax_rate", 0.0) or 0.0
        tax_diff = inv_tax - po_tax
        if abs(tax_diff) > TAX_TOLERANCE_PCT:
            exceptions.append(Exception_(
                invoice_line_desc=inv_item.description,
                po_line_desc=po_item["description"],
                exception_type="TAX_MISMATCH",
                severity="medium",
                detail={
                    "invoice_tax_rate": inv_tax,
                    "po_tax_rate": po_tax,
                    "delta": round(tax_diff, 2),
                    "po_number": po.get("po_number"),
                },
                explanation=(
                    f'Line "{inv_item.description}" was invoiced with a {inv_tax:g}% tax rate, but the PO '
                    f'{po.get("po_number")} specifies {po_tax:g}% for this line — a '
                    f'{"+" if tax_diff > 0 else ""}{tax_diff:.1f} percentage-point difference. This could '
                    f'indicate a tax-jurisdiction error or an incorrect tax code applied at billing.'
                ),
            ))

    return exceptions


def exceptions_to_dicts(exceptions: List[Exception_]) -> List[dict]:
    return [asdict(e) for e in exceptions]
