"""
extraction.py
Extracts structured header + line-item data from an uploaded vendor invoice PDF.

Strategy (documented tradeoff for the demo video):
  1. Try pdfplumber's native table detection first - works well for invoices
     that use real PDF table structures (most ERP/accounting-system exports).
  2. Fall back to a regex-based line parser for invoices that render line
     items as plain text rows (common with simple templates / scanned-then-
     retyped invoices).
  3. Header fields (invoice #, PO #, vendor, date) are pulled with targeted
     regexes anywhere in the page text, independent of the table parse.

This is a deterministic, rule-based extractor rather than an LLM-vision call.
Tradeoff: less robust to wildly unstructured layouts than an LLM extractor,
but 100% traceable - every extracted value can be pointed back to an exact
line of source text, which matters a lot for an AP exception workflow where
"trust me" answers aren't good enough.
"""
import re
import pdfplumber
from dataclasses import dataclass, field, asdict
from typing import List, Optional


@dataclass
class LineItem:
    description: str
    qty: float
    unit_price: float
    tax_rate: float  # percent, e.g. 8.0 for 8%
    line_total: float
    source_text: str = ""  # raw row text, for traceability


@dataclass
class Invoice:
    invoice_number: str
    po_number: Optional[str]
    vendor: str
    invoice_date: Optional[str]
    items: List[LineItem] = field(default_factory=list)
    raw_text: str = ""


HEADER_PATTERNS = {
    "invoice_number": [
        r"invoice\s*(?:#|no\.?|number)\s*[:\-]?\s*([A-Za-z0-9\-]+)",
    ],
    "po_number": [
        r"(?:purchase\s*order|po)\s*(?:#|no\.?|number)?\s*[:\-]?\s*(PO[\-\s]?[A-Z0-9\-]+|[A-Z0-9\-]{4,})",
    ],
    "vendor": [
        r"(?:vendor|from|supplier)\s*[:\-]\s*(.+)",
    ],
    "invoice_date": [
        r"(?:invoice\s*date|date)\s*[:\-]\s*([0-9]{1,4}[\/\-][0-9]{1,2}[\/\-][0-9]{1,4})",
    ],
}

# Line item row pattern for the plain-text fallback parser.
# Expects: Description ... Qty  UnitPrice  TaxRate%  LineTotal
LINE_ITEM_RE = re.compile(
    r"^(?P<desc>.+?)\s+"
    r"(?P<qty>\d+(?:\.\d+)?)\s+"
    r"\$?(?P<unit_price>\d+(?:\.\d+)?)\s+"
    r"(?P<tax_rate>\d+(?:\.\d+)?)\%?\s+"
    r"\$?(?P<line_total>\d+(?:\.\d+)?)\s*$"
)


def _extract_header(text: str) -> dict:
    header = {"invoice_number": None, "po_number": None, "vendor": None, "invoice_date": None}
    for field_name, patterns in HEADER_PATTERNS.items():
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                header[field_name] = m.group(1).strip()
                break
    return header


def _parse_table(table: List[List[Optional[str]]]) -> List[LineItem]:
    """Parse a pdfplumber-extracted table into LineItems using header-row
    column detection."""
    if not table or len(table) < 2:
        return []

    header_row = [(_normalize_col(c) if c else "") for c in table[0]]
    col_idx = {}
    for i, col in enumerate(header_row):
        if col in ("description", "item", "itemdescription"):
            col_idx["description"] = i
        elif col in ("qty", "quantity"):
            col_idx["qty"] = i
        elif col in ("unitprice", "price", "rate", "unitcost"):
            col_idx["unit_price"] = i
        elif col in ("tax", "taxrate", "taxpct", "vat"):
            col_idx["tax_rate"] = i
        elif col in ("total", "linetotal", "amount"):
            col_idx["line_total"] = i

    required = {"description", "qty", "unit_price"}
    if not required.issubset(col_idx.keys()):
        return []

    items = []
    for row in table[1:]:
        if row is None or all(c is None or str(c).strip() == "" for c in row):
            continue
        try:
            desc = str(row[col_idx["description"]]).strip()
            qty = _to_float(row[col_idx["qty"]])
            unit_price = _to_float(row[col_idx["unit_price"]])
            tax_rate = _to_float(row[col_idx["tax_rate"]]) if "tax_rate" in col_idx else 0.0
            if "line_total" in col_idx:
                line_total = _to_float(row[col_idx["line_total"]])
            else:
                line_total = round(qty * unit_price * (1 + tax_rate / 100), 2)
            if desc and qty is not None and unit_price is not None:
                items.append(LineItem(
                    description=desc, qty=qty, unit_price=unit_price,
                    tax_rate=tax_rate or 0.0, line_total=line_total,
                    source_text=" | ".join(str(c) for c in row if c),
                ))
        except (ValueError, TypeError, IndexError):
            continue
    return items


def _parse_text_lines(text: str) -> List[LineItem]:
    items = []
    for line in text.splitlines():
        m = LINE_ITEM_RE.match(line.strip())
        if m:
            d = m.groupdict()
            items.append(LineItem(
                description=d["desc"].strip(),
                qty=float(d["qty"]),
                unit_price=float(d["unit_price"]),
                tax_rate=float(d["tax_rate"]),
                line_total=float(d["line_total"]),
                source_text=line.strip(),
            ))
    return items


def _normalize_col(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _to_float(v) -> Optional[float]:
    if v is None:
        return None
    s = str(v).replace("$", "").replace(",", "").replace("%", "").strip()
    if s == "" or s == "-":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def extract_invoice(pdf_path: str) -> Invoice:
    full_text = ""
    all_items: List[LineItem] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            full_text += page_text + "\n"

            # Strategy 1: native table extraction
            tables = page.extract_tables()
            for table in tables:
                parsed = _parse_table(table)
                if parsed:
                    all_items.extend(parsed)

    # Strategy 2: fallback to text-line regex parsing if tables gave nothing
    if not all_items:
        all_items = _parse_text_lines(full_text)

    header = _extract_header(full_text)

    invoice = Invoice(
        invoice_number=header["invoice_number"] or "UNKNOWN",
        po_number=header["po_number"],
        vendor=header["vendor"] or "Unknown Vendor",
        invoice_date=header["invoice_date"],
        items=all_items,
        raw_text=full_text,
    )
    return invoice


def invoice_to_dict(inv: Invoice) -> dict:
    d = asdict(inv)
    return d
