"""Turns the raw inputs into one demand table (Firm + Plan) keyed by customer, SAP code and date.

Rules (all from the Master 'Notes' / 'process' sheets and the 19-Nov upload files):
  * CAT customers come from the MRC download. Item ID + delivery location -> Master MRC CODE + Location
    gives the SAP code and customer code. Status decides the zone (settings['status_zone']).
  * Every other customer: Open PO sheet = Firm, S&OP plan sheet = Plan.
  * MRC quantity = Ordered Qty - MAX(Shipped Qty, Received Qty); the date is Ship Date.
  * Dates before the 1st of the run month are moved to the 1st of the run month (past dues).
  * Only dates up to the end of the plan horizon are kept.
"""
from __future__ import annotations

import pandas as pd

from .util import add_months, month_end, month_start, norm_status

DEMAND_COLS = ["source", "zone", "cust_code", "sap_code", "date", "orig_date", "qty", "status", "ref"]


class Issues:
    """Collects exception rows per category for the run report."""

    def __init__(self):
        self.tables: dict[str, list[dict]] = {}
        self.notes: list[str] = []

    def add(self, category: str, **row):
        self.tables.setdefault(category, []).append(row)

    def frame(self, category: str) -> pd.DataFrame:
        return pd.DataFrame(self.tables.get(category, []))

    def counts(self) -> dict[str, int]:
        return {k: len(v) for k, v in self.tables.items()}


def window(run_date: pd.Timestamp, settings: dict) -> tuple[pd.Timestamp, pd.Timestamp]:
    start = month_start(run_date)
    end = month_end(add_months(start, int(settings.get("plan_horizon_months", 13))))
    return start, end


def _apply_dates(df: pd.DataFrame, run_date: pd.Timestamp, settings: dict, issues: Issues, source: str) -> pd.DataFrame:
    start, end = window(run_date, settings)
    df = df.copy()
    df["orig_date"] = df["date"]
    beyond = df["date"] > end
    if beyond.any():
        b = df[beyond].groupby(["source", "zone", "cust_code"]).agg(
            lines=("qty", "size"), qty=("qty", "sum"), first_date=("date", "min"), last_date=("date", "max"))
        for (src, zone, cc), r in b.iterrows():
            issues.add("Beyond plan horizon (info, not uploaded)", source=src, zone=zone, customer_code=cc,
                       lines=int(r.lines), qty=r.qty, first_date=r.first_date, last_date=r.last_date, horizon_end=end)
    df = df[~beyond]
    if settings.get("past_due_to_month_start", True):
        past = df["date"] < start
        df.loc[past, "date"] = start
    return df


def build_mrc_demand(mrc: pd.DataFrame, master: pd.DataFrame, run_date, settings, issues: Issues) -> pd.DataFrame:
    zone_map = {norm_status(k): v for k, v in settings["status_zone"].items()}
    mm = master[master["is_mrc"]].drop_duplicates(["mrc_code", "location"])
    key = {(a, b): (c, d) for a, b, c, d in zip(mm.mrc_code, mm.location, mm.sap_code, mm.cust_code)}
    # fallback: MRC code alone when it maps to a single SAP code + customer
    g = mm.groupby("mrc_code").agg(n=("cust_code", "nunique"), sap=("sap_code", "first"), cc=("cust_code", "first"))
    by_code = {k: (v.sap, v.cc) for k, v in g[g.n == 1].iterrows()}

    rows = []
    for r in mrc.itertuples(index=False):
        zone = zone_map.get(r.status)
        if zone is None:
            issues.add("Unknown MRC status (excluded)", sheet=r.sheet, excel_row=r.excel_row, item=r.item,
                       location=r.location, status=r.status_raw, qty=r.qty, ship_date=r.date)
            continue
        if zone.lower() == "ignore":
            continue
        if r.qty <= 0:
            if r.qty < 0:
                issues.add("Negative open qty (excluded)", sheet=r.sheet, excel_row=r.excel_row, item=r.item,
                           location=r.location, status=r.status_raw, ordered=r.ordered, shipped=r.shipped,
                           received=r.received, qty=r.qty)
            continue
        if r.date is None or pd.isna(r.date):
            issues.add("No date (excluded)", source="MRC", sheet=r.sheet, excel_row=r.excel_row, item=r.item, qty=r.qty)
            continue
        hit = key.get((r.item, r.location))
        how = "item+location"
        if hit is None:
            hit = by_code.get(r.item)
            if hit is not None:
                how = "item only"
                issues.add("MRC mapped on item only (location not in Master)", sheet=r.sheet, excel_row=r.excel_row,
                           item=r.item, location=r.location, sap_code=hit[0], customer_code=hit[1], qty=r.qty)
            else:
                issues.add("MRC item not in Master (excluded)", sheet=r.sheet, excel_row=r.excel_row, item=r.item,
                           location=r.location, status=r.status_raw, qty=r.qty, ship_date=r.date)
                continue
        rows.append(dict(source=f"MRC {r.sheet}", zone=zone, cust_code=hit[1], sap_code=hit[0],
                         date=r.date, qty=r.qty, status=r.status, ref=f"{r.item} @ {r.location} ({how})"))
    df = pd.DataFrame(rows, columns=[c for c in DEMAND_COLS if c != "orig_date"])
    return _apply_dates(df, run_date, settings, issues, "MRC")


def build_po_sop_demand(po: pd.DataFrame, sop: pd.DataFrame, master: pd.DataFrame, run_date, settings,
                        issues: Issues) -> pd.DataFrame:
    mp = master[~master["is_mrc"]]
    by_pair = mp.drop_duplicates(["mrc_code", "cust_code"]).set_index(["mrc_code", "cust_code"])["sap_code"]
    by_code = mp.drop_duplicates("mrc_code").set_index("mrc_code")["sap_code"]
    rows = []
    po_missing: dict = {}
    other_cust: set = set()

    def resolve(mat, cc, label, extra):
        if (mat, cc) in by_pair.index:
            return by_pair.loc[(mat, cc)]
        if mat in by_code.index:
            if (label, mat, cc) not in other_cust:
                other_cust.add((label, mat, cc))
                issues.add("PO/S&OP material under another customer in Master", source=label, customer_code=cc,
                           material=mat, master_customer_code=mp.loc[mp.mrc_code == mat, "cust_code"].iloc[0])
            return by_code.loc[mat]
        return None

    for r in po.itertuples(index=False):
        if r.qty <= 0:
            continue
        if r.date is None or pd.isna(r.date):
            issues.add("No date (excluded)", source="Open PO", sheet=r.sheet, excel_row=r.excel_row,
                       customer_code=r.cust_code, material=r.material_raw, qty=r.qty, date_text=r.date_raw)
            continue
        sap = resolve(r.material, r.cust_code, "Open PO", {"qty": r.qty})
        if sap is None:
            k = (r.cust_code, r.material_raw)
            po_missing.setdefault(k, {"name": r.name, "qty": 0.0, "dates": [], "rows": []})
            po_missing[k]["qty"] += r.qty
            po_missing[k]["dates"].append(r.date)
            po_missing[k]["rows"].append(str(r.excel_row))
            continue
        rows.append(dict(source="Open PO", zone="Firm", cust_code=r.cust_code, sap_code=sap, date=r.date,
                         qty=r.qty, status="PO", ref=f"SN {r.sn}" if r.sn else ""))

    for (cc, mat), info in po_missing.items():
        issues.add("PO/S&OP material not in Master (excluded)", source="Open PO", customer_code=cc, name=info["name"],
                   material=mat, qty=info["qty"], months=", ".join(sorted({d.strftime("%b-%y") for d in info["dates"]})),
                   excel_rows=", ".join(info["rows"][:20]) + (" ..." if len(info["rows"]) > 20 else ""))
    sop = sop[sop["qty"] > 0]
    missing = {}
    for r in sop.itertuples(index=False):
        if r.date is None or pd.isna(r.date):
            continue
        sap = resolve(r.material, r.cust_code, "S&OP", {"qty": r.qty, "month": r.date})
        if sap is None:
            k = (r.cust_code, r.material_raw)
            missing.setdefault(k, {"name": r.name, "qty": 0.0, "months": []})
            missing[k]["qty"] += r.qty
            missing[k]["months"].append(r.date.strftime("%b-%y"))
            continue
        rows.append(dict(source="S&OP", zone="Plan", cust_code=r.cust_code, sap_code=sap, date=r.date,
                         qty=r.qty, status="S&OP", ref=""))
    for (cc, mat), info in missing.items():
        issues.add("PO/S&OP material not in Master (excluded)", source="S&OP", customer_code=cc, name=info["name"],
                   material=mat, qty=info["qty"], months=", ".join(info["months"]))

    df = pd.DataFrame(rows, columns=[c for c in DEMAND_COLS if c != "orig_date"])
    df = _apply_dates(df, run_date, settings, issues, "PO/S&OP")

    # A firm PO and an S&OP quantity for the same part in the same month are both real demand
    # (confirmed 24-Nov-2026): both are uploaded and both are counted, no netting and no report line.
    return df


def build_demand(inputs: dict, run_date: pd.Timestamp, settings: dict, issues: Issues) -> pd.DataFrame:
    master = inputs["master"]
    parts = [build_mrc_demand(inputs["mrc"], master, run_date, settings, issues)]
    po, sop = inputs["po_sop"]
    parts.append(build_po_sop_demand(po, sop, master, run_date, settings, issues))
    demand = pd.concat([p for p in parts if not p.empty], ignore_index=True)
    demand["qty"] = demand["qty"].astype(float)
    return demand[DEMAND_COLS]
