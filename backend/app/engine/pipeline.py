"""One weekly run: read inputs -> demand -> MD61 Firm/Plan -> ZVA_SCH -> order book -> run report."""
from __future__ import annotations

import os
import time
from typing import Optional

import pandas as pd

from . import excel
from .demand import Issues, build_demand, window
from .outputs import build_md61, build_order_book, build_zva
from .readers import READERS
from .util import fy_label

SLOT_LABELS = {
    "master": "Master (classification)",
    "va31": "VA31 line items",
    "mrc": "MRC schedule (CAT)",
    "po_sop": "PO & S&OP",
    "vld": "VLD SAP pricing",
    "sales": "Sales register",
}


class InputError(Exception):
    def __init__(self, slot: str, message: str):
        super().__init__(f"{SLOT_LABELS.get(slot, slot)}: {message}")
        self.slot = slot


def read_inputs(paths: dict) -> dict:
    data = {}
    for slot, path in paths.items():
        if not path:
            data[slot] = None
            continue
        try:
            data[slot] = READERS[slot](path)
        except ValueError as e:
            raise InputError(slot, str(e)) from e
        except Exception as e:  # unreadable file etc.
            raise InputError(slot, f"could not be read ({type(e).__name__}: {e})") from e
    return data


def firm_snapshot(demand: pd.DataFrame) -> pd.DataFrame:
    f = demand[demand["zone"] == "Firm"]
    return f.groupby(["cust_code", "sap_code", "orig_date"], as_index=False)["qty"].sum()


def compare_firm(curr: pd.DataFrame, prev: Optional[pd.DataFrame]) -> pd.DataFrame:
    if prev is None or prev.empty:
        return pd.DataFrame()
    prev = prev.copy()
    prev["orig_date"] = pd.to_datetime(prev["orig_date"])
    prev["cust_code"] = prev["cust_code"].astype(str)
    prev["sap_code"] = prev["sap_code"].astype(str)
    m = curr.merge(prev, on=["cust_code", "sap_code", "orig_date"], how="outer", suffixes=("_now", "_last"))
    m = m.fillna({"qty_now": 0, "qty_last": 0})
    m["change"] = m["qty_now"] - m["qty_last"]
    m = m[m["change"].abs() > 1e-9].copy()
    m["type"] = m.apply(lambda r: "New" if r.qty_last == 0 else ("Removed" if r.qty_now == 0 else
                                                                  ("Increased" if r.change > 0 else "Reduced")), axis=1)
    m = m.rename(columns={"orig_date": "date", "cust_code": "customer_code", "sap_code": "sap_code",
                          "qty_last": "last_run_qty", "qty_now": "this_run_qty"})
    return m[["type", "customer_code", "sap_code", "date", "last_run_qty", "this_run_qty", "change"]].sort_values(
        ["customer_code", "sap_code", "date"])


def run(paths: dict, run_date: pd.Timestamp, usd_inr: float, settings: dict, out_dir: str,
        prev_firm: Optional[pd.DataFrame] = None, prev_label: str = "") -> dict:
    t0 = time.time()
    os.makedirs(out_dir, exist_ok=True)
    run_date = pd.Timestamp(run_date).normalize()
    inputs = read_inputs(paths)
    for req in ("master", "mrc", "po_sop", "vld", "sales"):
        if inputs.get(req) is None:
            raise InputError(req, "file is required for a run.")
    issues = Issues()
    demand = build_demand(inputs, run_date, settings, issues)

    firm_piv, firm_info, firm_map = build_md61(demand, "Firm", settings, issues)
    plan_piv, plan_info, _ = build_md61(demand, "Plan", settings, issues)
    zva = build_zva(demand, firm_map, inputs.get("va31"), issues)
    ob = build_order_book(demand, inputs["sales"], inputs["master"], inputs["vld"], run_date, usd_inr, issues,
                          fallback_sales=bool(settings.get("price_fallback_sales", False)))
    snap = firm_snapshot(demand)
    changes = compare_firm(snap, prev_firm)

    fy = fy_label(run_date)
    tag = run_date.strftime("%d.%m.%Y")
    files = {
        "md61_firm": f"7.ZPIRDaily(MD61) - Firm - {tag}.xlsx",
        "md61_plan": f"8.ZPIRDaily(MD61) - Plan - {tag}.xlsx",
        "zva_sch": f"9.ZVA_SCH({run_date:%d%m%Y}).xlsx",
        "order_book": f"Order Book {fy} - {tag}.xlsx",
        "report": f"Run report - {tag}.xlsx",
    }
    excel.write_md61(firm_piv, os.path.join(out_dir, files["md61_firm"]), settings)
    excel.write_md61(plan_piv, os.path.join(out_dir, files["md61_plan"]), settings)
    excel.write_zva(zva, os.path.join(out_dir, files["zva_sch"]))
    excel.write_order_book(ob, os.path.join(out_dir, files["order_book"]), run_date, usd_inr, fy)
    snap.to_csv(os.path.join(out_dir, "_firm_snapshot.csv"), index=False)
    demand.to_csv(os.path.join(out_dir, "_demand.csv"), index=False)

    # ---------------- totals for the UI and the report
    sm = ob["summary"]
    by_zone_source = demand.groupby(["source", "zone"])["qty"].sum().reset_index()
    start, end = window(run_date, settings)
    seg = ob["part"].join(sm).groupby(["New Terms"])["Total Value"].sum().sort_values(ascending=False)
    counts = issues.counts()
    if not changes.empty:
        counts["Firm zone changes vs last run"] = len(changes)
    totals = {
        "firm_qty": float(demand.loc[demand.zone == "Firm", "qty"].sum()),
        "plan_qty": float(demand.loc[demand.zone == "Plan", "qty"].sum()),
        "ob_total_lacs": float(sm["Total Value"].sum()),
        "ob_actual_lacs": float(sm["Actual YTD Value"].sum()),
        "ob_firm_lacs": float(sm["Firm/PO Value"].sum()),
        "ob_plan_lacs": float(sm["Estimate/Plan Value"].sum()),
        "ob_parts": int(len(sm)),
        "zva_lines": int(len(zva)),
    }
    summary = {
        "run_date": run_date.strftime("%Y-%m-%d"),
        "usd_inr": usd_inr,
        "fy": fy,
        "horizon": [start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")],
        "md61": {"Firm": firm_info, "Plan": plan_info},
        "totals": totals,
        "by_source": [dict(source=r.source, zone=r.zone, qty=float(r.qty)) for r in by_zone_source.itertuples()],
        "by_new_terms_lacs": {k: float(v) for k, v in seg.items()},
        "issue_counts": counts,
        "notes": issues.notes,
        "files": files,
        "compared_with": prev_label if not changes.empty or prev_firm is not None else "",
        "seconds": round(time.time() - t0, 1),
    }

    # ---------------- run report workbook
    rows = [
        ("Run summary",),
        ("Run date", run_date.to_pydatetime()),
        ("USD/INR rate used", usd_inr),
        ("Financial year", fy),
        ("Demand window (past dues moved to)", start.to_pydatetime(), "to", end.to_pydatetime()),
        ("Status -> zone", ", ".join(f"{k}={v}" for k, v in settings["status_zone"].items())),
        ("Max MD61 date columns", settings.get("max_date_columns")),
        ("Compared with run", prev_label or "(no earlier run)"),
        (),
        ("Quantities by source",),
        ("Source", "Zone", "Qty"),
    ]
    rows += [(r.source, r.zone, float(r.qty)) for r in by_zone_source.itertuples()]
    rows += [(), ("MD61 files",), ("File", "Rows", "Date columns", "Qty", "Months turned monthly")]
    for z, info in (("Firm", firm_info), ("Plan", plan_info)):
        rows.append((files["md61_firm" if z == "Firm" else "md61_plan"], info["rows"], info["columns"], info["qty"],
                     ", ".join(info["collapsed_months"]) or "-"))
    rows += [(), ("Order book (INR Lacs)",), ("Actual YTD", totals["ob_actual_lacs"]), ("Firm/PO", totals["ob_firm_lacs"]),
             ("Estimate/plan", totals["ob_plan_lacs"]), (f"FCST {fy}", totals["ob_total_lacs"]), (),
             ("Exceptions (see sheets)",), ("Category", "Rows")]
    rows += [(k, v) for k, v in sorted(counts.items())]
    if issues.notes:
        rows += [(), ("Notes",)] + [(n,) for n in issues.notes]
    tables = {k: issues.frame(k) for k in sorted(issues.tables)}
    if not changes.empty:
        tables = {"Firm zone changes vs last run": changes, **tables}
    excel.write_report(rows, tables, os.path.join(out_dir, files["report"]))
    summary["seconds"] = round(time.time() - t0, 1)
    return summary
