"""
chat_engine.py
Answers reviewer questions like "why was invoice #123 flagged?" using ONLY
the stored, already-computed extraction + reconciliation data for that
invoice. No generative model call is required for correctness - every
answer is templated from real field values, so it can never "hallucinate"
a reason that isn't backed by the underlying data.

If a question can't be grounded (unknown invoice number, no matching
exception), the engine says so explicitly rather than guessing.
"""
import re
from difflib import SequenceMatcher


def _find_invoice_number(question: str, known_numbers):
    q_upper = question.upper()
    # Direct substring match against known invoice numbers - most reliable,
    # since invoice numbers are specific tokens (e.g. "INV-9001") unlikely
    # to appear by coincidence.
    for num in known_numbers:
        if num.upper() in q_upper:
            return num
    # otherwise fuzzy match the whole question against known invoice numbers
    best, best_score = None, 0.0
    for num in known_numbers:
        score = SequenceMatcher(None, num.upper(), q_upper).ratio()
        if score > best_score:
            best, best_score = num, score
    return best if best_score > 0.3 else None


def answer_question(question: str, store: dict, invoice_number: str = None) -> str:
    """
    store: { invoice_number: {"invoice": {...}, "exceptions": [...], "po": {...}} }
    invoice_number: optional explicit scope (e.g. passed by the invoice detail
        page, which knows exactly which invoice is open). When given and
        valid, this takes priority over parsing the number out of free text -
        free-text parsing is a fallback for a global/queue-level chat, not
        the primary path once the reviewer is already looking at one invoice.
    """
    known_numbers = list(store.keys())
    if not known_numbers:
        return "I don't have any processed invoices yet — upload an invoice and PO first."

    if invoice_number and invoice_number in store:
        inv_num = invoice_number
    else:
        inv_num = _find_invoice_number(question, known_numbers)
        if inv_num is None:
            if len(known_numbers) == 1:
                # Only one invoice loaded - safe to assume that's the subject.
                inv_num = known_numbers[0]
            else:
                return (
                    f"I couldn't tell which invoice you mean. Invoices I currently have on file: "
                    f"{', '.join(known_numbers)}. Try e.g. \"why was invoice #{known_numbers[0]} flagged?\""
                )

    record = store[inv_num]
    exceptions = record["exceptions"]
    invoice = record["invoice"]
    q_lower = question.lower()

    if not exceptions:
        return (
            f"Invoice {inv_num} has no exceptions — all {len(invoice['items'])} line item(s) "
            f"matched PO {invoice.get('po_number') or record['po'].get('po_number')} on price, "
            f"quantity, and tax within tolerance."
        )

    # If the question references a specific line item, filter to it
    item_filter = None
    for item in invoice["items"]:
        desc_words = item["description"].lower().split()
        if any(w in q_lower for w in desc_words if len(w) > 3):
            item_filter = item["description"]
            break

    relevant = exceptions
    if item_filter:
        relevant = [e for e in exceptions if e["invoice_line_desc"] == item_filter]
        if not relevant:
            return f'Line "{item_filter}" on invoice {inv_num} was not flagged — it matched the PO within tolerance.'

    # Type-specific filter (price / qty / tax)
    type_map = {"price": "PRICE_MISMATCH", "quantity": "QTY_MISMATCH", "qty": "QTY_MISMATCH",
                "tax": "TAX_MISMATCH", "not on": "NOT_ON_PO", "missing": "NOT_ON_PO",
                "unauthorized": "NOT_ON_PO", "extra item": "NOT_ON_PO"}
    for kw, etype in type_map.items():
        if kw in q_lower:
            typed = [e for e in relevant if e["exception_type"] == etype]
            if typed:
                relevant = typed
            break

    lines = [f"Invoice {inv_num} has {len(exceptions)} exception(s). Here's why:\n"]
    for e in relevant:
        sev = e["severity"].upper()
        lines.append(f"• [{sev} | {e['exception_type']}] {e['explanation']}")

    if len(relevant) < len(exceptions) and not item_filter:
        lines.append(f"\n({len(exceptions) - len(relevant)} additional exception(s) exist on this invoice — ask for more detail to see them all.)")

    return "\n".join(lines)
