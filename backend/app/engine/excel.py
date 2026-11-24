"""Excel writers for every output file (openpyxl, values + SUBTOTAL rows)."""
from __future__ import annotations

import re

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter as L

from .util import excel_code

ARIAL8 = Font(name="Arial", size=8)
ARIAL8B = Font(name="Arial", size=8, bold=True)
BOLD = Font(bold=True)
HEAD_FILL = PatternFill("solid", fgColor="D9E1F2")
SUB_FILL = PatternFill("solid", fgColor="F2F2F2")
ACT_FILL = PatternFill("solid", fgColor="E2EFDA")
NEXT_FILL = PatternFill("solid", fgColor="EDEDED")
THIN = Side(style="thin", color="BFBFBF")
BOX = Border(top=THIN, bottom=THIN, left=THIN, right=THIN)
QTY_FMT = "#,##0;-#,##0;-"
VAL_FMT = "#,##0.00;-#,##0.00;-"


def _num(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return 0
    f = float(v)
    return int(round(f)) if abs(f - round(f)) < 1e-9 else round(f, 4)


# --------------------------------------------------------------------------- MD61 (ZPIRDAILY)
def write_md61(piv: pd.DataFrame, path: str, settings: dict):
    """Same layout as the ZPIRDaily templates: row 1 labels, row 2 dates, data from row 3."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    heads = ["Requirement plan", "Material", 'Version (Active = "X" /Inactive = Blank)', "Version No"]
    for j, h in enumerate(heads, start=1):
        c = ws.cell(1, j, h)
        c.font = ARIAL8B
    ws.cell(1, 2).number_format = "@"
    dates = list(piv.columns) if not piv.empty else []
    for j, d in enumerate(dates, start=5):
        c = ws.cell(2, j, pd.Timestamp(d).to_pydatetime())
        c.number_format = "dd-mm-yyyy"
        c.font = ARIAL8
        c.alignment = Alignment(horizontal="left")
    r = 3
    for (rp, mat), row in piv.iterrows():
        ws.cell(r, 1, rp).font = ARIAL8
        c = ws.cell(r, 2, excel_code(mat))
        c.font = ARIAL8
        c.alignment = Alignment(horizontal="left")
        ws.cell(r, 3, settings.get("active_flag", "X")).font = ARIAL8
        c = ws.cell(r, 4, settings.get("version_no", "00"))
        c.font = ARIAL8
        c.number_format = "@"
        for j, v in enumerate(row.values, start=5):
            c = ws.cell(r, j, _num(v))
            c.font = ARIAL8
            c.number_format = "0"
        r += 1
    widths = {"A": 17.8, "B": 20.2, "C": 12.3, "D": 8.5}
    for k, w in widths.items():
        ws.column_dimensions[k].width = w
    for j in range(5, 5 + len(dates)):
        ws.column_dimensions[L(j)].width = 10.5
    ws.freeze_panes = "E3"
    wb.save(path)


# --------------------------------------------------------------------------- ZVA_SCH
def write_zva(z: pd.DataFrame, path: str):
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    heads = ["Ref (Mandatory)", "Part code", "Part code", "Delivery date (Mandatory)", "Quantity (Mandatory)", "MRC ID"]
    for j, h in enumerate(heads, start=1):
        ws.cell(1, j, h).font = BOLD
    for i, row in enumerate(z.itertuples(index=False), start=2):
        vals = list(row)
        ws.cell(i, 1, excel_code(str(vals[0])))
        ws.cell(i, 2, excel_code(str(vals[1])))
        ws.cell(i, 3, excel_code(str(vals[2])))
        c = ws.cell(i, 4, vals[3])
        c.number_format = "@"
        ws.cell(i, 5, _num(vals[4]))
        ws.cell(i, 6, int(vals[5]))
    for j, w in enumerate([16, 10, 22, 24, 20, 9], start=1):
        ws.column_dimensions[L(j)].width = w
    ws.freeze_panes = "A2"
    wb.save(path)


# --------------------------------------------------------------------------- Order book
def _hdr(ws, row, col, text, fill=HEAD_FILL, wrap=True):
    c = ws.cell(row, col, text)
    c.font = BOLD
    c.fill = fill
    c.border = BOX
    c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=wrap)
    return c


def _period_fill(p):
    if p["part"] == "actual":
        return ACT_FILL
    return HEAD_FILL if p["in_fy"] else NEXT_FILL


def write_order_book(ob: dict, path: str, run_date: pd.Timestamp, usd_inr: float, fy: str):
    part, pq, pv, sm, periods = ob["part"], ob["pq"], ob["pv"], ob["summary"], ob["periods"]
    plabels = [p["label"] for p in periods]
    data = part.copy()
    for p in periods:
        data[f"Q {p['label']}"] = pq[p["key"]]
        data[f"V {p['label']}"] = pv[p["key"]]
    for c in sm.columns:
        data[c] = sm[c]
    data = data.reset_index()
    # FY totals stay FY-only while the month columns run to run month + 11: say so in the headers
    display = {"Total Qty": f"{fy} Total Qty", "Total Value": f"{fy} Total Value",
               "Firm/PO Qty": f"Firm/PO Qty {fy}", "Estimate/Plan Qty": f"Estimate/Plan Qty {fy}",
               "Firm/PO Value": f"Firm/PO Value {fy}", "Estimate/Plan Value": f"Estimate/Plan Value {fy}"}
    run_p = [p for p in periods if p["month"] == ob["run_month"]]
    split_note = (f"{run_p[0]['label']} = invoiced to run date, {run_p[1]['label']} = open (incl. past-due not yet "
                  f"invoiced)") if len(run_p) == 2 else ""

    wb = Workbook()

    # ---------------- Sheet 1: summary
    ws = wb.active
    ws.title = "1.Order book summary"
    ws["A1"] = f"Order book {fy} - all values in INR Lacs"
    ws["A1"].font = Font(bold=True, size=13)
    ws["A2"] = (f"Run date {run_date:%d-%b-%Y}  |  USD/INR {usd_inr:g}  |  Actual = sales register; Open = Firm "
                f"(MRC / Open PO) + Plan (MRC / S&OP) at VLD price  |  {split_note}  |  {fy} columns cover "
                f"Apr-{ob['fy0']:%y} to Mar-{ob['fy_end']:%y}; months after that are shown for the 12-month view")
    ws["A2"].font = Font(italic=True, size=9)

    value_cols = ["Actual YTD Value", "Firm/PO Value", "Estimate/Plan Value", "H1 Value", "H2 Value", "Total Value"]
    value_heads = ["Actual YTD", f"Firm/PO {fy}", f"Estimate/plan {fy}", "H1", "H2", f"FCST {fy}"]

    def block(start_row, group_cols, title):
        ws.cell(start_row, 1, title).font = Font(bold=True, size=11)
        hr = start_row + 1
        col = 1
        for g in group_cols:
            _hdr(ws, hr, col, g)
            col += 1
        first_val_col = col
        for h in value_heads:
            _hdr(ws, hr, col, h)
            col += 1
        for p in periods:
            _hdr(ws, hr, col, f"{p['label']}\n{p['tag']}", fill=_period_fill(p))
            col += 1
        last_col = col - 1
        ws.row_dimensions[hr].height = 42
        g = data.groupby(group_cols, dropna=False)
        agg = g[value_cols + [f"V {lab}" for lab in plabels]].sum().reset_index()
        agg = agg.sort_values("Total Value", ascending=False) if len(group_cols) == 1 else agg.sort_values(group_cols)
        r = hr + 1
        for row in agg.itertuples(index=False):
            vals = list(row)
            for j in range(len(group_cols)):
                ws.cell(r, 1 + j, vals[j]).border = BOX
            for j, v in enumerate(vals[len(group_cols):]):
                c = ws.cell(r, first_val_col + j, float(v))
                c.number_format = VAL_FMT
                c.border = BOX
            r += 1
        ws.cell(r, 1, "TOTAL").font = BOLD
        for j in range(first_val_col, last_col + 1):
            c = ws.cell(r, j, f"=SUM({L(j)}{hr + 1}:{L(j)}{r - 1})")
            c.number_format = VAL_FMT
            c.font = BOLD
            c.fill = SUB_FILL
            c.border = BOX
        return r + 2

    nxt = block(4, ["New Terms", "Segment", "EXIM Category"], "By segment")
    block(nxt, ["New Terms", "Customer"], "By customer")
    ws.column_dimensions["A"].width = 18
    ws.column_dimensions["B"].width = 26
    ws.column_dimensions["C"].width = 16
    for j in range(4, 4 + len(value_heads) + len(periods)):
        ws.column_dimensions[L(j)].width = 12
    ws.freeze_panes = "A6"

    # ---------------- Sheet 2: part family
    ws2 = wb.create_sheet("2.Part family order book")
    fam_cols = ["New Terms", "Segment", "EXIM Category", "Customer", "Family", "Model1"]
    fam_vals = (["H1 Qty", "H2 Qty", "Total Qty", "H1 Value", "H2 Value", "Total Value", "Firm/PO Value",
                 "Estimate/Plan Value"] + [f"Q {lab}" for lab in plabels] + [f"V {lab}" for lab in plabels])
    fam = data.groupby(fam_cols, dropna=False)[fam_vals].sum().reset_index().sort_values(fam_cols)
    _write_table(ws2, fam, fam_cols, fam_vals, periods, title=f"Part family level order book {fy}", display=display)

    # ---------------- Sheet 3: part level
    ws3 = wb.create_sheet("3.Part level order book")
    id_cols = ["cust_code", "sap_code", "Description", "New Terms", "Segment", "EXIM Category", "Dom/Export",
               "Customer", "Cell Description", "Family", "Model1", "Model", "class_source", "sales_org", "vld_price",
               "currency", "ex_rate", "unit_price_inr", "price_status"]
    pretty = {"cust_code": "Customer Code", "sap_code": "Material", "class_source": "Classified from",
              "sales_org": "Sales Org", "vld_price": "VLD Price", "currency": "Currency", "ex_rate": "Ex Rate",
              "unit_price_inr": "Unit Price (INR)", "price_status": "Price status"}
    part_vals = ([f"Q {lab}" for lab in plabels] + [f"V {lab}" for lab in plabels] +
                 ["Actual YTD Qty", "Firm/PO Qty", "Estimate/Plan Qty", "Actual YTD Value", "Firm/PO Value",
                  "Estimate/Plan Value", "H1 Qty", "H2 Qty", "Total Qty", "H1 Value", "H2 Value", "Total Value"])
    p3 = data[id_cols + part_vals].copy()
    p3["sap_code"] = p3["sap_code"].map(excel_code)
    p3["cust_code"] = p3["cust_code"].map(excel_code)
    p3 = p3.rename(columns=pretty)
    _write_table(ws3, p3, [pretty.get(c, c) for c in id_cols], part_vals, periods,
                 title=f"Part level order book {fy}", display=display,
                 num_id={"VLD Price": "#,##0.00", "Ex Rate": "0.00", "Unit Price (INR)": "#,##0.00"})
    wb.save(path)


def _write_table(ws, df, id_cols, val_cols, periods, title, display=None, num_id=None):
    """Row 1 title, row 2 SUBTOTAL, row 3 group band, row 4 headers, data from row 5."""
    num_id = num_id or {}
    display = display or {}
    ws.cell(1, 1, title).font = Font(bold=True, size=12)
    ws.cell(2, 1, "Subtotal (filtered)").font = Font(italic=True, size=9)
    hr, first = 4, 5
    by_label = {p["label"]: p for p in periods}
    col = 1
    for c in id_cols:
        _hdr(ws, hr, col, c)
        col += 1
    for c in val_cols:
        label = c
        fill = HEAD_FILL
        if c.startswith("Q ") or c.startswith("V "):
            p = by_label[c[2:]]
            label = f"{p['label']}\n{p['tag']}"
            fill = _period_fill(p)
            band = "Qty" if c.startswith("Q ") else "Value (INR Lacs)"
            ws.cell(3, col, band).font = Font(bold=True, size=9)
        else:
            label = display.get(c, c)
            if "Value" in label:
                label = label.replace("Value", "Value (Lacs)")
        _hdr(ws, hr, col, label, fill=fill)
        col += 1
    last_row = first + len(df) - 1
    nid = len(id_cols)
    for i, row in enumerate(df.itertuples(index=False), start=first):
        vals = list(row)
        for j in range(nid):
            v = vals[j]
            if isinstance(v, float) and pd.isna(v):
                v = None
            if isinstance(v, pd.Timestamp):
                v = v.to_pydatetime()
            c = ws.cell(i, 1 + j, v)
            fmt = num_id.get(id_cols[j])
            if fmt:
                c.number_format = fmt
        for j, v in enumerate(vals[nid:]):
            name = val_cols[j]
            c = ws.cell(i, nid + 1 + j, float(v) if v is not None and not pd.isna(v) else 0.0)
            c.number_format = QTY_FMT if (name.startswith("Q ") or "Qty" in name) else VAL_FMT
    for j in range(nid + 1, nid + len(val_cols) + 1):
        c = ws.cell(2, j, f"=SUBTOTAL(9,{L(j)}{first}:{L(j)}{max(last_row, first)})")
        name = val_cols[j - nid - 1]
        c.number_format = QTY_FMT if (name.startswith("Q ") or "Qty" in name) else VAL_FMT
        c.font = BOLD
        c.fill = SUB_FILL
    ws.row_dimensions[hr].height = 42
    for j in range(1, nid + 1):
        ws.column_dimensions[L(j)].width = 14
    for j in range(nid + 1, nid + len(val_cols) + 1):
        ws.column_dimensions[L(j)].width = 11
    ws.freeze_panes = ws.cell(first, nid + 1)
    ws.auto_filter.ref = f"A{hr}:{L(nid + len(val_cols))}{max(last_row, hr)}"


# --------------------------------------------------------------------------- Run report
def _sheet_name(name: str, used: set) -> str:
    s = re.sub(r"[\[\]:*?/\\]", "-", name)[:31]
    base, i = s, 2
    while s in used:
        s = f"{base[:28]}~{i}"
        i += 1
    used.add(s)
    return s


def write_report(summary_rows: list[tuple], tables: dict[str, pd.DataFrame], path: str):
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    used = {"Summary"}
    r = 1
    for row in summary_rows:
        for j, v in enumerate(row, start=1):
            if isinstance(v, pd.Timestamp):
                v = v.to_pydatetime()
            c = ws.cell(r, j, v)
            if len(row) == 1:
                c.font = Font(bold=True, size=11)
        r += 1
    ws.column_dimensions["A"].width = 52
    for col in "BCDEF":
        ws.column_dimensions[col].width = 18
    for name, df in tables.items():
        if df is None or df.empty:
            continue
        sh = wb.create_sheet(_sheet_name(name, used))
        sh.cell(1, 1, name).font = Font(bold=True, size=11)
        for j, c in enumerate(df.columns, start=1):
            _hdr(sh, 2, j, str(c).replace("_", " "), wrap=False)
            sh.column_dimensions[L(j)].width = max(12, min(40, len(str(c)) + 4))
        for i, row in enumerate(df.itertuples(index=False), start=3):
            for j, v in enumerate(row, start=1):
                if isinstance(v, pd.Timestamp):
                    v = None if pd.isna(v) else v.to_pydatetime()
                    c = sh.cell(i, j, v)
                    c.number_format = "dd-mm-yyyy"
                    continue
                if isinstance(v, float) and pd.isna(v):
                    v = None
                sh.cell(i, j, v)
        sh.freeze_panes = "A3"
        sh.auto_filter.ref = f"A2:{L(len(df.columns))}{len(df) + 2}"
    wb.save(path)
