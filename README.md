# AP Invoice Exception Assistant (Streamlit)

Upload your purchase order data, then upload up to 10 vendor invoice PDFs at
once to reconcile them and ask "why was this flagged?" — every answer is
grounded in the extracted data, not generated freely.

## Files

All files live in one flat folder (no subfolders) so they can be dragged
straight into a GitHub repo:

- `streamlit_app.py` — the app entry point
- `extraction.py` — pulls header + line items out of the invoice PDF
- `reconciliation.py` — compares invoice lines against the PO and flags mismatches
- `chat_engine.py` — answers "why was this flagged?" from the computed data
- `requirements.txt` — Python dependencies

## How it works

1. Upload a JSON file describing your purchase order(s) — the sidebar shows
   the expected format under "What should this file look like?".
2. Upload up to 10 invoice PDFs at once, pick which PO each one reconciles
   against, and click **Process**.
3. Click **View** on any processed invoice to see its line items, flagged
   exceptions, and ask follow-up questions in the chat box.

## Deploy on Streamlit Community Cloud

1. Create a new GitHub repo and drag-and-drop all the files above into it (root of the repo, no subfolders).
2. Go to [share.streamlit.io](https://share.streamlit.io) → **Deploy an app**.
3. Pick your repo/branch, and set **Main file path** to `streamlit_app.py`.
4. Click **Deploy**.

## Run locally

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```
