"""Builds the output tables (as DataFrames) from the demand table and the other inputs."""
from __future__ import annotations

import pandas as pd

from .demand import Issues
from .util import add_months, fy_label, fy_start, mat_sort_key, month_end, month_start


# --------------------------------------------------------------------------- MD61 date columns
def collapse_dates(dates, max_cols: int) -> tuple[dict, list]:
    """Notes rule: max 97 date columns; if more, go monthly from the last month backwards.

    Returns (mapping original date -> column date, list of months turned monthly).
    """
    uniq = sorted(set(pd.Timestamp(d) for d in dates))
    mapping = {d: d for d in uniq}
    collapsed = []
    for m in sorted({month_start(d) for d in uniq}, reverse=True):
        if len(set(mapping.values())) <= max_cols:
            break
        for d in uniq:
            if month_start(d) == m:
                mapping[d] = m
        collapsed.append(m)
    return mapping, sorted(collapsed)


def build_md61(demand: pd.DataFrame, zone: str, settings: dict, issues: Issues):
    """Returns (pivot frame rows=(req_plan, material), cols=dates, info dict)."""
    prefix = settings["firm_prefix"] if zone == "Firm" else settings["plan_prefix"]
    d = demand[demand["zone"] == zone].copy()
    info = {"zone": zone, "rows": 0, "columns": 0, "qty": 0.0, "collapsed_months": [], "too_many_columns": False}
    if d.empty:
        return pd.DataFrame(), info, {}
    max_cols = int(settings.get("max_date_columns", 97))
    mapping, collapsed = collapse_dates(d["date"], max_cols)
    d["col_date"] = d["date"].map(mapping)
    d["req_plan"] = prefix + d["cust_code"]
    piv = d.pivot_table(index=["req_plan", "sap_code"], columns="col_date", values="qty", aggfunc="sum", fill_value=0)
    piv = piv.loc[piv.sum(axis=1) > 0]
    order = sorted(piv.index, key=lambda k: (k[0], mat_sort_key(k[1])))
    piv = piv.loc[order]
    piv = piv[sorted(piv.columns)]
    info.update(rows=len(piv), columns=len(piv.columns), qty=float(piv.values.sum()),
                collapsed_months=[m.strftime("%b-%Y") for m in collapsed],
                too_many_columns=len(piv.columns) > max_cols)
    for m in collapsed:
        issues.add("MD61 months turned monthly (97-column rule)", file=f"MD61 {zone}", month=m.strftime("%b-%Y"),
                   column_date=m)
    if info["too_many_columns"]:
        issues.add("MD61 still over the column limit", file=f"MD61 {zone}", columns=len(piv.columns), limit=max_cols)
    return piv, info, mapping


# --------------------------------------------------------------------------- ZVA_SCH (VA31 upload)
def build_zva(demand: pd.DataFrame, firm_mapping: dict, va31: pd.DataFrame | None, issues: Issues) -> pd.DataFrame:
    cols = ["Ref (Mandatory)", "Part code", "Part code ", "Delivery date (Mandatory)", "Quantity (Mandatory)", "MRC ID"]
    firm = demand[demand["zone"] == "Firm"].copy()
    if firm.empty:
        return pd.DataFrame(columns=cols)
    if va31 is None or va31.empty:
        issues.notes.append("ZVA_SCH not built: no VA31 line item master uploaded.")
        return pd.DataFrame(columns=cols)
    firm["col_date"] = firm["date"].map(lambda x: firm_mapping.get(x, x))
    agg = firm.groupby(["cust_code", "sap_code", "col_date"], as_index=False)["qty"].sum()
    lines = va31.groupby(["cust_code", "material"])
    lookup = {k: g.sort_values(["sales_doc", "item"], key=lambda s: s.map(mat_sort_key)) for k, g in lines}
    out = []
    reported = set()
    for r in agg.itertuples(index=False):
        g = lookup.get((r.cust_code, r.sap_code))
        if g is None or g.empty:
            if (r.cust_code, r.sap_code) not in reported:
                tot = agg[(agg.cust_code == r.cust_code) & (agg.sap_code == r.sap_code)]["qty"].sum()
                issues.add("ZVA_SCH: no VA31 line item (left out)", customer_code=r.cust_code, sap_code=r.sap_code,
                           firm_qty=tot)
                reported.add((r.cust_code, r.sap_code))
            continue
        if len(g) > 1:
            if (r.cust_code, r.sap_code) not in reported:
                tot = agg[(agg.cust_code == r.cust_code) & (agg.sap_code == r.sap_code)]["qty"].sum()
                issues.add("ZVA_SCH: several VA31 line items (left out)", customer_code=r.cust_code,
                           sap_code=r.sap_code, firm_qty=tot,
                           line_items=", ".join(f"{a}/{b}" for a, b in zip(g.sales_doc, g.item)))
                reported.add((r.cust_code, r.sap_code))
            continue
        line = g.iloc[0]
        out.append({"ref": line.sales_doc, "item": line["item"], "mat": r.sap_code, "date": r.col_date, "qty": r.qty})
    if not out:
        return pd.DataFrame(columns=cols)
    z = pd.DataFrame(out)
    z = z.sort_values(by=["ref", "item", "date"], key=lambda s: s.map(mat_sort_key) if s.name in ("ref", "item") else s)
    z = z.reset_index(drop=True)
    res = pd.DataFrame({
        cols[0]: z["ref"], cols[1]: z["item"], cols[2]: z["mat"],
        cols[3]: z["date"].map(lambda d: d.strftime("%d.%m.%Y")), cols[4]: z["qty"], cols[5]: range(1, len(z) + 1),
    })
    return res


# --------------------------------------------------------------------------- Prices (VLD only)
def build_prices(parts: pd.DataFrame, vld: pd.DataFrame, run_date: pd.Timestamp, usd_inr: float,
                 issues: Issues, sales: pd.DataFrame | None = None, fallback_sales: bool = False) -> pd.DataFrame:
    """parts: cust_code, sap_code, dom_exp. Returns one price row per part.

    Price = VLD PR00 record valid on the run date (else the latest record), USD converted at the run's rate.
    Optional (setting, off by default): parts with no VLD record take the last invoice price.
    """
    last_inv = {}
    if fallback_sales and sales is not None and not sales.empty:
        pos = sales[(sales["qty"] > 0) & (sales["amount"] > 0)].dropna(subset=["date"]).sort_values("date")
        for r in pos.itertuples(index=False):
            last_inv[(r.cust_code, r.material)] = (r.amount / r.qty, r.date)
    v = vld[vld["amount"] > 0].copy()
    by_mat = {k: g for k, g in v.groupby("material")}
    rows = []
    for p in parts.itertuples(index=False):
        g = by_mat.get(p.sap_code)
        res = dict(cust_code=p.cust_code, sap_code=p.sap_code, price_status="Missing in VLD", sales_org="",
                   vld_price=0.0, currency="", ex_rate=None, unit_price_inr=0.0, valid_from=None, valid_to=None)
        if g is not None:
            want_export = str(p.dom_exp).strip().lower() == "export"
            pref = g[g["is_export_org"] == want_export]
            note = ""
            if pref.empty:
                pref = g
                note = "other sales org; "
            valid = pref[(pref["valid_from"] <= run_date) & (pref["valid_to"] >= run_date)]
            if not valid.empty:
                rec = valid.sort_values("valid_from").iloc[-1]
                status = "Valid on run date"
            else:
                rec = pref.sort_values(["valid_to", "valid_from"]).iloc[-1]
                status = ("Latest record expired " + rec.valid_to.strftime("%d.%m.%Y")) if rec.valid_to is not None and rec.valid_to < run_date else "Latest record (future)"
            cur = rec.currency
            if cur == "INR":
                rate, inr = 1.0, rec.unit_price
            elif cur == "USD":
                rate, inr = usd_inr, rec.unit_price * usd_inr
            else:
                rate, inr = None, 0.0
                status = f"No rate for {cur}"
            res.update(price_status=(note + status), sales_org=rec.org, vld_price=rec.unit_price, currency=cur,
                       ex_rate=rate, unit_price_inr=inr, valid_from=rec.valid_from, valid_to=rec.valid_to)
        elif (p.cust_code, p.sap_code) in last_inv:
            price, when = last_inv[(p.cust_code, p.sap_code)]
            res.update(price_status=f"Not in VLD - last invoice {when:%d.%m.%Y}", sales_org="Sales register",
                       vld_price=price, currency="INR", ex_rate=1.0, unit_price_inr=price)
        rows.append(res)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- Order book
ATTRS = ["New Terms", "Segment", "EXIM Category", "Dom/Export", "Customer", "Cell Description", "Family", "Model1",
         "Model", "Description"]


def _attributes(keys: pd.DataFrame, master: pd.DataFrame, sales: pd.DataFrame, issues: Issues) -> pd.DataFrame:
    by_pair = master.drop_duplicates(["sap_code", "cust_code"]).set_index(["sap_code", "cust_code"])
    by_sap = master.drop_duplicates("sap_code").set_index("sap_code")
    cust_names = sales.drop_duplicates("cust_code").set_index("cust_code")["cust_name"] if not sales.empty else pd.Series(dtype=str)
    descs = sales.dropna(subset=["date"]).sort_values("date").drop_duplicates("material", keep="last").set_index("material")["description"] if not sales.empty else pd.Series(dtype=str)
    rows = []
    for k in keys.itertuples(index=False):
        if (k.sap_code, k.cust_code) in by_pair.index:
            src = by_pair.loc[(k.sap_code, k.cust_code)]
            how = "Master"
        elif k.sap_code in by_sap.index:
            src = by_sap.loc[k.sap_code]
            how = "Master (other customer code)"
        else:
            src = None
            how = "Not in Master"
        row = {"cust_code": k.cust_code, "sap_code": k.sap_code, "class_source": how}
        for a in ATTRS:
            row[a] = "" if src is None else (src.get(a, "") or "")
        if src is None:
            row["New Terms"] = "Not in Master"
            row["Customer"] = cust_names.get(k.cust_code, k.cust_code)
            row["Dom/Export"] = "Export" if k.cust_code.startswith("32") else "Domestic"
        if not row["Description"]:
            row["Description"] = descs.get(k.sap_code, "")
        rows.append(row)
    return pd.DataFrame(rows)


def order_book_periods(run_date: pd.Timestamp) -> tuple[list[dict], list, pd.Timestamp]:
    """Column periods: FY start .. run month + 11. The run month is split into invoiced (1st..run date)
    and open (run date+1..month end; also carries past-due orders not yet invoiced)."""
    fy0 = fy_start(run_date)
    run_m = month_start(run_date)
    last_m = add_months(run_m, 11)
    fy_last = add_months(fy0, 11)
    months, m = [], fy0
    while m <= last_m:
        months.append(m)
        m = add_months(m, 1)
    periods = []
    for m in months:
        in_fy = m <= fy_last
        base = dict(month=m, in_fy=in_fy, half=("H1" if m.month in (4, 5, 6, 7, 8, 9) else "H2") if in_fy else "")
        if m < run_m:
            periods.append({**base, "key": f"{m:%Y-%m}", "label": m.strftime("%b-%y"), "tag": "Actual", "part": "actual"})
        elif m == run_m:
            end_day = month_end(m).day
            periods.append({**base, "key": f"{m:%Y-%m} A", "label": f"{m:%b-%y} 01-{run_date.day:02d}",
                            "tag": "Actual", "part": "actual"})
            open_label = (f"{m:%b-%y} {run_date.day + 1:02d}-{end_day:02d}" if run_date.day < end_day
                          else f"{m:%b-%y} open")
            periods.append({**base, "key": f"{m:%Y-%m} O", "label": open_label, "tag": "Open", "part": "open"})
        else:
            tag = "Open" if in_fy else f"Open {fy_label(m)}"
            periods.append({**base, "key": f"{m:%Y-%m}", "label": m.strftime("%b-%y"), "tag": tag, "part": "open"})
    return periods, months, last_m


def build_order_book(demand: pd.DataFrame, sales: pd.DataFrame, master: pd.DataFrame, vld: pd.DataFrame,
                     run_date: pd.Timestamp, usd_inr: float, issues: Issues, fallback_sales: bool = False) -> dict:
    fy0 = fy_start(run_date)
    fy_months = [add_months(fy0, i) for i in range(12)]
    fy_end = add_months(fy0, 12) - pd.Timedelta(days=1)
    run_m = month_start(run_date)
    periods, months, last_m = order_book_periods(run_date)
    last_end = month_end(last_m)

    # actual sales inside the FY up to the run date
    s = sales.dropna(subset=["date"]).copy()
    before = s[s["date"] < fy0]
    if not before.empty:
        for (cc, name), g in before.groupby(["cust_code", "cust_name"]):
            issues.add("Sales rows dated before FY start (excluded)", customer_code=cc, customer=name, rows=len(g),
                       qty=g["qty"].sum(), amount_inr=g["amount"].sum(),
                       dates=", ".join(sorted({d.strftime("%d.%m.%Y") for d in g["date"]})))
    after = s[s["date"] > run_date]
    if not after.empty:
        issues.add("Sales rows dated after run date (excluded)", rows=len(after), amount_inr=after["amount"].sum())
    s = s[(s["date"] >= fy0) & (s["date"] <= run_date)]
    s["month"] = s["date"].map(month_start)
    s = s.rename(columns={"material": "sap_code"})
    act = s.groupby(["cust_code", "sap_code", "month"], as_index=False).agg(qty=("qty", "sum"), amount=("amount", "sum"))

    # open demand up to run month + 11 (dates already past-due adjusted; anything still dated before
    # the run month is shown in the run month's open column)
    d = demand[(demand["date"] <= last_end)].copy()
    d["month"] = d["date"].map(lambda x: max(month_start(x), run_m))
    opn = d.groupby(["cust_code", "sap_code", "zone", "month"], as_index=False)["qty"].sum()

    keys = pd.concat([act[["cust_code", "sap_code"]], opn[["cust_code", "sap_code"]]]).drop_duplicates()
    keys = keys.sort_values(["cust_code", "sap_code"], key=lambda c: c.map(mat_sort_key)).reset_index(drop=True)
    attrs = _attributes(keys, master, sales, issues)
    prices = build_prices(attrs[["cust_code", "sap_code", "Dom/Export"]].rename(columns={"Dom/Export": "dom_exp"}),
                          vld, run_date, usd_inr, issues, sales=sales, fallback_sales=fallback_sales)
    part = attrs.merge(prices, on=["cust_code", "sap_code"], how="left")

    def pivot(frame, value, filt=None):
        f = frame if filt is None else frame[filt(frame)]
        if f.empty:
            return pd.DataFrame(0.0, index=pd.MultiIndex.from_frame(keys), columns=months)
        p = f.pivot_table(index=["cust_code", "sap_code"], columns="month", values=value, aggfunc="sum", fill_value=0)
        return p.reindex(index=pd.MultiIndex.from_frame(keys), columns=months, fill_value=0).fillna(0)

    act_q = pivot(act, "qty")
    act_v = pivot(act, "amount") / 1e5
    firm_q = pivot(opn, "qty", lambda f: f["zone"] == "Firm")
    plan_q = pivot(opn, "qty", lambda f: f["zone"] == "Plan")
    price = part.set_index(["cust_code", "sap_code"])["unit_price_inr"].reindex(act_q.index).fillna(0)
    open_q = firm_q + plan_q
    open_v = open_q.mul(price, axis=0) / 1e5

    # one column per period (the run month has two)
    pq = pd.DataFrame(index=act_q.index)
    pv = pd.DataFrame(index=act_q.index)
    for p in periods:
        m = p["month"]
        if p["part"] == "actual":
            pq[p["key"]] = act_q[m]
            pv[p["key"]] = act_v[m]
        else:
            pq[p["key"]] = open_q[m]
            pv[p["key"]] = open_v[m]

    part = part.set_index(["cust_code", "sap_code"]).reindex(act_q.index)
    fy_keys = [p["key"] for p in periods if p["in_fy"]]
    h1 = [p["key"] for p in periods if p["half"] == "H1"]
    h2 = [p["key"] for p in periods if p["half"] == "H2"]
    summary_cols = pd.DataFrame({
        "Actual YTD Qty": act_q[fy_months].sum(axis=1),
        "Firm/PO Qty": firm_q[fy_months].sum(axis=1),
        "Estimate/Plan Qty": plan_q[fy_months].sum(axis=1),
        "Actual YTD Value": act_v[fy_months].sum(axis=1),
        "Firm/PO Value": firm_q[fy_months].sum(axis=1) * price / 1e5,
        "Estimate/Plan Value": plan_q[fy_months].sum(axis=1) * price / 1e5,
        "H1 Qty": pq[h1].sum(axis=1), "H2 Qty": pq[h2].sum(axis=1), "Total Qty": pq[fy_keys].sum(axis=1),
        "H1 Value": pv[h1].sum(axis=1), "H2 Value": pv[h2].sum(axis=1), "Total Value": pv[fy_keys].sum(axis=1),
    })

    open_shown = open_q.sum(axis=1)
    missing_price = part[(part["unit_price_inr"].fillna(0) <= 0) & (open_shown > 0)]
    for (cc, sap), r in missing_price.iterrows():
        issues.add("No VLD price (open qty valued at 0)", customer_code=cc, sap_code=sap, customer=r["Customer"],
                   dom_export=r["Dom/Export"], open_qty_fy=float(open_q.loc[(cc, sap), fy_months].sum()),
                   open_qty_to_month_11=float(open_shown.loc[(cc, sap)]), price_status=r["price_status"])
    expired = part[part["price_status"].fillna("").str.contains("expired|other sales org|future|No rate|last invoice", case=False)
                   & (open_shown > 0)]
    for (cc, sap), r in expired.iterrows():
        issues.add("VLD price notes", customer_code=cc, sap_code=sap, customer=r["Customer"], note=r["price_status"],
                   vld_price=r["vld_price"], currency=r["currency"], valid_to=r["valid_to"])
    unmapped_sales = part[(part["class_source"] == "Not in Master") & (act_q.sum(axis=1) != 0)]
    for (cc, sap), r in unmapped_sales.iterrows():
        issues.add("Sales part not in Master (shown as 'Not in Master')", customer_code=cc, sap_code=sap,
                   customer=r["Customer"], description=r["Description"], actual_qty=float(act_q.loc[(cc, sap)].sum()),
                   actual_value_lacs=float(act_v.loc[(cc, sap)].sum()))

    return dict(part=part, pq=pq, pv=pv, periods=periods, summary=summary_cols, months=months, run_month=run_m,
                fy0=fy0, fy_end=fy_end, last_month=last_m, act_q=act_q, open_q=open_q)
