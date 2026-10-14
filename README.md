# AP INVOICE EXCEPTION ASSISTANT

## About This Project:

AP Invoice Exception Assistant is a Python and Streamlit application that helps users:

- Extract invoice details from PDF documents.
- Reconcile vendor invoices against purchase orders.
- Identify invoice discrepancies and exceptions.
- Review invoice line items and reconciliation results.
- Ask questions about flagged invoices using an interactive chat interface.
- Process multiple invoice PDFs in a single session.

This project demonstrates PDF processing, data extraction, purchase order reconciliation, exception detection, and AI-assisted analysis.

## Project Modules:

| Module Name | Description | Files |
|---|---|---|
| Invoice Extraction | Extracts invoice headers and line items from PDFs | `extraction.py` |
| Reconciliation Engine | Compares invoice data with purchase orders and identifies discrepancies | `reconciliation.py` |
| Exception Analysis | Displays exception details and reconciliation results | `reconciliation.py` |
| Invoice Q&A Assistant | Answers questions about invoice exceptions | `chat_engine.py` |
| Streamlit Interface | Provides invoice uploads, processing, and review screens | `streamlit_app.py` |
| Data Management | Handles purchase order data in JSON format | JSON files |

## Key Features:

**Invoice PDF Extraction:**
- Extract invoice details and line items.
- Process multiple invoice documents.

**Purchase Order Reconciliation:**
- Compare invoice items against purchase order records.
- Identify pricing and quantity discrepancies.

**Exception Detection:**
- Highlight flagged invoices.
- Display exception details and explanations.

**Interactive Q&A:**
- Ask why an invoice was flagged.
- Investigate available reconciliation results.

**Batch Processing:**
- Upload and process multiple invoices in one session.

## Agile Project Development:

- **Planning:** Identified the need to simplify invoice verification and exception analysis.
- **Development:** Implemented PDF extraction and structured invoice data processing.
- **Reconciliation:** Developed logic to compare invoices with purchase order information.
- **Integration:** Connected reconciliation results to the Streamlit interface.
- **Enhancement:** Added an interactive question-answering interface for investigating invoice exceptions.

## Technologies Used:

**Backend:**

Python • PDF Extraction • Reconciliation Logic

**Frontend:**

Streamlit • Interactive Data Presentation

**Data Processing:**

JSON • Invoice Parsing • Exception Analysis

**AI Assistance:**

Invoice Question Answering • Context-Based Analysis
