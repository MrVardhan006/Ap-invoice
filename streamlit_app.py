"""
streamlit_app.py
Streamlit front end for the AP Invoice Exception Assistant.

Reuses the same extraction / reconciliation / chat logic as the original
Flask app (extraction.py, reconciliation.py, chat_engine.py) - only the
UI layer changes. Processed invoices are kept in st.session_state, so each
browser session gets its own in-memory queue (no shared JSON file on disk,
which fits Streamlit Community Cloud's ephemeral filesystem).

Purchase orders are no longer hardcoded sample data - the reviewer uploads
their own PO data as a JSON file, and invoices (up to 10 at a time) are
uploaded and reconciled against it.
"""
import json
import os
import tempfile
import uuid

import streamlit as st

from extraction import extract_invoice, invoice_to_dict
from reconciliation import reconcile, exceptions_to_dicts
from chat_engine import answer_question

MAX_INVOICES_PER_BATCH = 10

EXAMPLE_PO_JSON = """{
  "PO-1001": {
    "po_number": "PO-1001",
    "vendor": "Acme Office Supplies",
    "items": [
      {"item_code": "A-100", "description": "Ergonomic Office Chair", "qty": 10, "unit_price": 120.00, "tax_rate": 8.0}
    ]
  }
}"""

st.set_page_config(page_title="AP Invoice Exception Assistant", page_icon="🧾", layout="wide")


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
def init_state():
    if "store" not in st.session_state:
        st.session_state.store = {}  # invoice_number -> {invoice, exceptions, po}
    if "pos" not in st.session_state:
        st.session_state.pos = {}  # po_number -> {po_number, vendor, items: [...]}
    if "selected_invoice" not in st.session_state:
        st.session_state.selected_invoice = None
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []  # list of (role, text)


def process_upload(uploaded_file, po_number: str, pos: dict):
    """Save the uploaded PDF to a temp file, extract it, reconcile against the
    chosen PO, and store the result in session state."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(uploaded_file.getbuffer())
        tmp_path = tmp.name

    try:
        invoice = extract_invoice(tmp_path)
    except Exception as e:
        st.error(f"Extraction failed for {uploaded_file.name}: {e}")
        return None
    finally:
        os.unlink(tmp_path)

    if not invoice.po_number or invoice.po_number not in pos:
        invoice.po_number = po_number

    if invoice.invoice_number == "UNKNOWN" or invoice.invoice_number in st.session_state.store:
        invoice.invoice_number = f"{invoice.invoice_number}-{uuid.uuid4().hex[:6].upper()}"

    po = pos[po_number]
    exceptions = reconcile(invoice, po)

    st.session_state.store[invoice.invoice_number] = {
        "invoice": invoice_to_dict(invoice),
        "exceptions": exceptions_to_dicts(exceptions),
        "po": po,
    }
    return invoice.invoice_number


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
def render_po_uploader():
    st.header("1. Purchase orders")
    po_file = st.file_uploader("Upload PO data (JSON)", type=["json"], key="po_file")

    if po_file is not None:
        try:
            data = json.loads(po_file.getvalue().decode("utf-8"))
            st.session_state.pos = data
            st.success(f"Loaded {len(data)} PO(s): {', '.join(data.keys())}")
        except Exception as e:
            st.error(f"Couldn't parse that JSON file: {e}")

    with st.expander("What should this file look like?"):
        st.code(EXAMPLE_PO_JSON, language="json")
        st.caption("Top-level keys are PO numbers. Each PO needs a vendor and a list of line items.")


def render_invoice_uploader(pos: dict):
    st.header("2. Invoices")
    if not pos:
        st.info("Upload your PO data above first — invoices are reconciled against it.")
        return

    files = st.file_uploader(
        f"Upload up to {MAX_INVOICES_PER_BATCH} invoice PDFs",
        type=["pdf"],
        accept_multiple_files=True,
        key="invoice_files",
    )

    if not files:
        return

    if len(files) > MAX_INVOICES_PER_BATCH:
        st.error(f"You selected {len(files)} files — please select at most {MAX_INVOICES_PER_BATCH} at a time.")
        files = files[:MAX_INVOICES_PER_BATCH]

    po_options = list(pos.keys())
    st.caption("Pick which PO each invoice should be reconciled against (defaults to the first PO):")
    choices = {}
    for f in files:
        choices[f.name] = st.selectbox(f.name, options=po_options, key=f"po_choice_{f.name}")

    if st.button(f"Process {len(files)} invoice(s)", type="primary"):
        processed = []
        with st.spinner("Extracting and reconciling..."):
            for f in files:
                inv_num = process_upload(f, choices[f.name], pos)
                if inv_num:
                    processed.append(inv_num)
        if processed:
            st.session_state.selected_invoice = None
            st.session_state.chat_history = []
            st.success(f"Processed {len(processed)} invoice(s): {', '.join(processed)}")
            st.rerun()


def render_sidebar():
    with st.sidebar:
        render_po_uploader()
        st.divider()
        render_invoice_uploader(st.session_state.pos)
        st.divider()
        if st.button("Reset everything"):
            st.session_state.store = {}
            st.session_state.pos = {}
            st.session_state.selected_invoice = None
            st.session_state.chat_history = []
            st.rerun()


def render_queue():
    st.subheader("Processed invoices")
    store = st.session_state.store
    if not store:
        st.info("No invoices processed yet — upload PO data and invoices from the sidebar to get started.")
        return

    for num, record in store.items():
        exc = record["exceptions"]
        high = sum(1 for e in exc if e["severity"] == "high")
        status = "🚩 FLAGGED" if exc else "✅ CLEAN"
        cols = st.columns([3, 3, 2, 2, 2])
        cols[0].markdown(f"**{num}**")
        cols[1].write(record["invoice"]["vendor"])
        cols[2].write(record["invoice"].get("po_number") or "-")
        cols[3].write(f"{len(exc)} exception(s), {high} high")
        if cols[4].button("View", key=f"view_{num}"):
            st.session_state.selected_invoice = num
            st.session_state.chat_history = []
            st.rerun()
        st.markdown(f"Status: {status}")
        st.divider()


SEVERITY_COLOR = {"high": "🔴", "medium": "🟠", "low": "🟡"}


def render_invoice_detail():
    inv_num = st.session_state.selected_invoice
    record = st.session_state.store.get(inv_num)
    if not record:
        st.warning("Invoice not found.")
        return

    invoice = record["invoice"]
    exceptions = record["exceptions"]
    po = record["po"]

    if st.button("← Back to queue"):
        st.session_state.selected_invoice = None
        st.rerun()

    st.subheader(f"Invoice {inv_num}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Vendor", invoice["vendor"])
    c2.metric("PO", invoice.get("po_number") or "-")
    c3.metric("Date", invoice.get("invoice_date") or "-")
    c4.metric("Exceptions", len(exceptions))

    st.markdown("#### Line items")
    st.dataframe(
        [
            {
                "Description": it["description"],
                "Qty": it["qty"],
                "Unit price": it["unit_price"],
                "Tax %": it["tax_rate"],
                "Line total": it["line_total"],
            }
            for it in invoice["items"]
        ],
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("#### Exceptions")
    if not exceptions:
        st.success(f"No exceptions — all line items matched PO {po.get('po_number')} within tolerance.")
    else:
        for e in exceptions:
            icon = SEVERITY_COLOR.get(e["severity"], "⚪")
            with st.expander(f"{icon} [{e['severity'].upper()}] {e['exception_type']} — {e['invoice_line_desc']}"):
                st.write(e["explanation"])
                st.json(e["detail"])

    st.markdown("#### Ask about this invoice")
    for role, text in st.session_state.chat_history:
        with st.chat_message(role):
            st.write(text)

    question = st.chat_input("e.g. why was the office chair line flagged?")
    if question:
        st.session_state.chat_history.append(("user", question))
        answer = answer_question(question, st.session_state.store, invoice_number=inv_num)
        st.session_state.chat_history.append(("assistant", answer))
        st.rerun()


def main():
    init_state()

    st.title("🧾 AP Invoice Exception Assistant")
    st.caption(
        "Upload your purchase order data, then upload up to "
        f"{MAX_INVOICES_PER_BATCH} vendor invoice PDFs at once to reconcile them and ask "
        "why any line was flagged — every answer is grounded in the extracted data, "
        "not generated freely."
    )

    render_sidebar()

    if st.session_state.selected_invoice:
        render_invoice_detail()
    else:
        render_queue()


if __name__ == "__main__":
    main()
