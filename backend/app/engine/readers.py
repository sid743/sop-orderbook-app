"""Readers for every input file. Each returns tidy pandas frames with normalised codes.

The readers find header rows and columns by name, so small layout changes in the
SAP / customer downloads (extra columns, moved columns, extra title rows) do not
break a run. If a required column is missing they raise ValueError with a clear
message, which the API passes back to the user.
"""
from __future__ import annotations

import pandas as pd

from .util import (
    find_header_row,
    frame_from_header,
    norm_code,
    norm_header,
    norm_status,
    pick_col,
    read_raw_sheets,
    to_date,
    to_num,
)

MASTER_ATTRS = [
    "Dom/Export", "Input source", "Description", "Location", "Customer Code", "New Terms",
    "Segment", "EXIM Category", "Customer", "Cell Description", "Family", "Model1", "Model",
]


# --------------------------------------------------------------------------- Master
def read_master(path: str) -> pd.DataFrame:
    sheets = read_raw_sheets(path)
    for name, raw in sheets.items():
        hr = find_header_row(raw, ["SAP CODE", "Customer Code"])
        if hr is None:
            continue
        df = frame_from_header(raw, hr)
        out = pd.DataFrame()
        out["mrc_code"] = df[pick_col(df, "MRC CODE")].map(norm_code)
        out["sap_code"] = df[pick_col(df, "SAP CODE")].map(norm_code)
        out["location"] = df[pick_col(df, "Location")].map(norm_code)
        out["cust_code"] = df[pick_col(df, "Customer Code")].map(norm_code)
        out["input_source"] = df[pick_col(df, "Input source")].astype(str).str.strip()
        rename = {
            "Dom/Export": ("Dom/Export",),
            "Description": ("Description",),
            "New Terms": ("New Terms",),
            "Segment": ("Segment",),
            "EXIM Category": ("EXIM Category", "EXIM Catergory"),
            "Customer": ("Customer",),
            "Cell Description": ("Cell Description",),
            "Family": ("Family",),
            "Model1": ("Model1",),
            "Model": ("Model",),
        }
        for target, cands in rename.items():
            col = pick_col(df, *cands, required=False)
            if col is None:
                out[target] = ""
            else:
                out[target] = df[col].map(lambda v: "" if v is None or str(v).strip().lower() == "nan" else str(v).strip())
        out["master_row"] = df.index + hr + 2  # Excel row number for messages
        out["sheet"] = name
        out = out[out["sap_code"] != ""].reset_index(drop=True)
        out["is_mrc"] = out["input_source"].str.upper().str.contains("MRC")
        return out
    raise ValueError("Master file: no sheet with 'SAP CODE' and 'Customer Code' columns was found.")


# --------------------------------------------------------------------------- MRC
def read_mrc(path: str) -> pd.DataFrame:
    """All sheets of the CAT MRC download (Export + Domestic). Qty = Ordered - MAX(Shipped, Received)."""
    sheets = read_raw_sheets(path)
    frames = []
    for name, raw in sheets.items():
        hr = None
        for item_label in ("Item ID", "Item Id"):
            hr = find_header_row(raw, ["Status", item_label, "Ordered Qty"])
            if hr is not None:
                break
        if hr is None:
            continue
        df = frame_from_header(raw, hr)
        item = pick_col(df, "Item ID", "Item Id")
        loc = pick_col(df, "Deliver To", "Delivery To")
        ordered = pick_col(df, "Ordered Qty")
        shipped = pick_col(df, "Shipped Qty")
        received = pick_col(df, "Received Qty")
        ship = pick_col(df, "Ship Date")
        line = pick_col(df, "Line ID", "Line Id", required=False)
        deliv = pick_col(df, "Delivery Date", required=False)
        out = pd.DataFrame()
        out["item"] = df[item].map(norm_code)
        out["location"] = df[loc].map(norm_code)
        out["status_raw"] = df[pick_col(df, "Status")].map(lambda v: "" if v is None else str(v).strip())
        out["status"] = out["status_raw"].map(norm_status)
        o = df[ordered].map(to_num)
        s = df[shipped].map(to_num)
        r = df[received].map(to_num)
        out["ordered"] = o
        out["shipped"] = s
        out["received"] = r
        out["qty"] = o - pd.concat([s, r], axis=1).max(axis=1)
        out["date"] = df[ship].map(to_date)
        out["delivery_date"] = df[deliv].map(to_date) if deliv else None
        out["line_id"] = df[line].map(lambda v: "" if v is None else str(v)) if line else ""
        out["sheet"] = name
        out["excel_row"] = df.index + hr + 2
        out = out[out["item"] != ""]
        frames.append(out)
    if not frames:
        raise ValueError("MRC file: no sheet with 'Status', 'Item ID' and 'Ordered Qty' columns was found.")
    return pd.concat(frames, ignore_index=True)


# --------------------------------------------------------------------------- PO & S&OP
def read_po_sop(path: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (open_po, sop). Open PO = firm zone, S&OP = plan zone (monthly columns)."""
    sheets = read_raw_sheets(path)
    po_frames, sop_frames = [], []
    for name, raw in sheets.items():
        # S&OP sheet: Customer code + Material + month columns as real dates
        hr = find_header_row(raw, ["Customer code", "Material"])
        if hr is None:
            continue
        df = frame_from_header(raw, hr)
        date_cols = [c for c in df.columns if isinstance(c, pd.Timestamp)]
        cc = pick_col(df, "Customer Code")
        mat = pick_col(df, "Material")
        nm = pick_col(df, "Name", required=False)
        qty_col = pick_col(df, "Qty", "Quantity", required=False) if not date_cols else None
        if date_cols and qty_col is None:
            long = df[[cc, mat] + ([nm] if nm else []) + date_cols].melt(
                id_vars=[cc, mat] + ([nm] if nm else []), var_name="date", value_name="qty")
            out = pd.DataFrame()
            out["cust_code"] = long[cc].map(norm_code)
            out["material"] = long[mat].map(norm_code)
            out["material_raw"] = long[mat].map(lambda v: "" if v is None else str(v).strip())
            out["name"] = long[nm].map(lambda v: "" if v is None else str(v)) if nm else ""
            out["date"] = long["date"].map(to_date)
            out["qty"] = long["qty"].map(to_num)
            out["sheet"] = name
            out = out[(out["material"] != "") & (out["cust_code"] != "")]
            sop_frames.append(out)
        else:
            qty_col = pick_col(df, "Qty", "Quantity")
            date_col = None
            for c in df.columns:
                h = norm_header(c)
                if "ex works" in h or "completion" in h or h in ("date", "delivery date", "due date"):
                    date_col = c
                    break
            if date_col is None:
                raise ValueError(f"PO & S&OP file, sheet '{name}': no date column (e.g. 'Best Ex Works') found.")
            sn = pick_col(df, "SN", required=False)
            out = pd.DataFrame()
            out["cust_code"] = df[cc].map(norm_code)
            out["material"] = df[mat].map(norm_code)
            out["material_raw"] = df[mat].map(lambda v: "" if v is None else str(v).strip())
            out["name"] = df[nm].map(lambda v: "" if v is None else str(v)) if nm else ""
            out["sn"] = df[sn].map(lambda v: "" if v is None else str(v)) if sn else ""
            out["date_raw"] = df[date_col].map(lambda v: "" if v is None else str(v))
            out["date"] = df[date_col].map(to_date)
            out["qty"] = df[qty_col].map(to_num)
            out["sheet"] = name
            out["excel_row"] = df.index + hr + 2
            out = out[(out["material"] != "") & (out["cust_code"] != "")]
            po_frames.append(out)
    if not po_frames and not sop_frames:
        raise ValueError("PO & S&OP file: no sheet with 'Customer Code' and 'Material' columns was found.")
    po = pd.concat(po_frames, ignore_index=True) if po_frames else pd.DataFrame(
        columns=["cust_code", "material", "material_raw", "name", "sn", "date_raw", "date", "qty", "sheet", "excel_row"])
    sop = pd.concat(sop_frames, ignore_index=True) if sop_frames else pd.DataFrame(
        columns=["cust_code", "material", "material_raw", "name", "date", "qty", "sheet"])
    return po, sop


# --------------------------------------------------------------------------- VLD
def read_vld(path: str) -> pd.DataFrame:
    """SAP V/LD condition list: Sales Org sections, a material line, then PR00 records."""
    sheets = read_raw_sheets(path)
    recs = []
    for name, raw in sheets.items():
        hr = find_header_row(raw, ["CnTy", "Amount"], max_rows=30)
        if hr is None:
            continue
        hdr = [norm_header(v) for v in raw.iloc[hr].tolist()]

        def idx(label, default=None):
            label = norm_header(label)
            return hdr.index(label) if label in hdr else default

        i_cnty = idx("CnTy")
        i_amt = idx("Amount")
        i_cur = idx("Unit", i_amt + 1 if i_amt is not None else None)
        i_per = idx("per")
        i_vf = idx("Valid From")
        i_vt = idx("Valid to")
        i_rest = idx("ReSt")
        org_label, org_code, material = "", "", ""
        for i in range(len(raw)):
            row = raw.iloc[i].tolist()
            first = str(row[0]).strip() if row[0] is not None else ""
            if first.lower().startswith("sales org"):
                text = " ".join(str(v) for v in row[1:] if v is not None and str(v) != "nan").strip()
                org_label = text
                org_code = text.split()[0] if text else ""
                continue
            if first.lower().startswith("distr"):
                continue
            cnty = row[i_cnty] if i_cnty is not None else None
            amt = row[i_amt] if i_amt is not None else None
            cnty_s = "" if cnty is None or str(cnty) == "nan" else str(cnty).strip()
            if cnty_s and (amt is None or str(amt) == "nan"):
                if norm_header(cnty_s) in ("material", "cnty"):
                    continue
                material = norm_code(cnty_s)
                continue
            if cnty_s and amt is not None and str(amt) != "nan" and norm_header(cnty_s) != "cnty":
                try:
                    amount = float(amt)
                except (TypeError, ValueError):
                    continue
                per = to_num(row[i_per]) if i_per is not None else 1.0
                recs.append(dict(
                    org=org_code, org_label=org_label, material=material, cond=cnty_s,
                    rest=("" if i_rest is None or row[i_rest] is None or str(row[i_rest]) == "nan" else str(row[i_rest])),
                    amount=amount, currency=str(row[i_cur]).strip().upper() if i_cur is not None and row[i_cur] is not None else "",
                    per=per if per else 1.0,
                    valid_from=to_date(row[i_vf]) if i_vf is not None else None,
                    valid_to=to_date(row[i_vt]) if i_vt is not None else None,
                ))
    if not recs:
        raise ValueError("VLD file: no condition records found (expected 'CnTy' and 'Amount' header).")
    df = pd.DataFrame(recs)
    df["unit_price"] = df["amount"] / df["per"]
    df["is_export_org"] = df["org_label"].str.upper().str.contains("EXPORT")
    return df


# --------------------------------------------------------------------------- Sales register
def read_sales(path: str) -> pd.DataFrame:
    sheets = read_raw_sheets(path)
    for name, raw in sheets.items():
        hr = find_header_row(raw, ["Material Code", "Quantity"])
        if hr is None:
            continue
        df = frame_from_header(raw, hr)
        date_col = pick_col(df, "Posting Date", "Billing Date", "Invoice Date", required=False)
        if date_col is None:
            # The SAP layout labels the date column "Accounting Document"; pick the column that holds dates.
            best, best_count = None, 0
            for c in df.columns:
                count = int(df[c].map(lambda v: not isinstance(v, (int, float, str)) and to_date(v) is not None).sum())
                if count > best_count:
                    best, best_count = c, count
            if best is None or best_count < 0.8 * len(df):
                raise ValueError("Sales register: could not find the posting/billing date column.")
            date_col = best
        out = pd.DataFrame()
        out["date"] = df[date_col].map(to_date)
        out["material"] = df[pick_col(df, "Material Code")].map(norm_code)
        desc = pick_col(df, "Material Dscription", "Material Description", required=False)
        out["description"] = df[desc].map(lambda v: "" if v is None else str(v)) if desc else ""
        out["qty"] = df[pick_col(df, "Quantity")].map(to_num)
        out["amount"] = df[pick_col(df, "Amount in Local Curr", "Amount in Local Currency", "Amount")].map(to_num)
        out["cust_code"] = df[pick_col(df, "Customer Code")].map(norm_code)
        cn = pick_col(df, "Customer Name", required=False)
        out["cust_name"] = df[cn].map(lambda v: "" if v is None else str(v)) if cn else ""
        out["excel_row"] = df.index + hr + 2
        out = out[out["material"] != ""].reset_index(drop=True)
        return out
    raise ValueError("Sales register: no sheet with 'Material Code' and 'Quantity' columns was found.")


# --------------------------------------------------------------------------- VA31 line items
def read_va31(path: str) -> pd.DataFrame:
    sheets = read_raw_sheets(path)
    frames = []
    for name, raw in sheets.items():
        hr = find_header_row(raw, ["Sales Document", "Material"])
        if hr is None:
            continue
        df = frame_from_header(raw, hr)
        out = pd.DataFrame()
        out["sales_doc"] = df[pick_col(df, "Sales Document")].map(norm_code)
        out["item"] = df[pick_col(df, "Item (SD)", "Item")].map(norm_code)
        out["cust_code"] = df[pick_col(df, "Sold-To Party", "Sold-to party", "Customer")].map(norm_code)
        out["material"] = df[pick_col(df, "Material")].map(norm_code)
        out["sheet"] = name
        out = out[(out["sales_doc"] != "") & (out["material"] != "")]
        frames.append(out)
    if not frames:
        raise ValueError("VA31 line item file: no sheet with 'Sales Document' and 'Material' columns was found.")
    return pd.concat(frames, ignore_index=True).drop_duplicates()


READERS = {
    "master": read_master,
    "va31": read_va31,
    "mrc": read_mrc,
    "po_sop": read_po_sop,
    "vld": read_vld,
    "sales": read_sales,
}
