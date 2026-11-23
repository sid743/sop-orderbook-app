import React from "react";
import { api, fmt } from "./api.js";

const FILE_LABELS = {
  md61_firm: "MD61 upload – Firm (ZPIRDAILY)",
  md61_plan: "MD61 upload – Plan (ZPIRDAILY)",
  zva_sch: "ZVA_SCH – VA31 firm schedule upload",
  order_book: "Order book (3 sheets)",
  report: "Run report – exceptions & checks",
};

export default function RunResult({ rec }) {
  if (rec.status === "failed") {
    return (
      <section className="card">
        <h2>Run {rec.id} failed</h2>
        <div className="alert error">{rec.error}</div>
      </section>
    );
  }
  const s = rec.summary;
  if (!s) return null;
  const t = s.totals;
  const issues = Object.entries(s.issue_counts || {}).sort((a, b) => b[1] - a[1]);
  return (
    <section className="card">
      <div className="result-head">
        <h2>
          Run {fmt.date(s.run_date)} <span className="muted small">({rec.id})</span>
        </h2>
        <a className="button" href={api.zipUrl(rec.id)}>
          Download all (.zip)
        </a>
      </div>
      <p className="muted small">
        USD/INR {s.usd_inr} · {s.fy} · demand window {fmt.date(s.horizon[0])} – {fmt.date(s.horizon[1])} ·{" "}
        {s.seconds}s{s.compared_with ? ` · firm zone compared with ${s.compared_with}` : ""}
      </p>

      <div className="kpis">
        <Kpi label="Firm qty (MD61 F)" value={fmt.qty(t.firm_qty)} />
        <Kpi label="Plan qty (MD61 P)" value={fmt.qty(t.plan_qty)} />
        <Kpi label={`FCST ${s.fy} (₹ lacs)`} value={fmt.lacs(t.ob_total_lacs)} strong />
        <Kpi label="Actual YTD (₹ lacs)" value={fmt.lacs(t.ob_actual_lacs)} />
        <Kpi label="Firm/PO (₹ lacs)" value={fmt.lacs(t.ob_firm_lacs)} />
        <Kpi label="Estimate/plan (₹ lacs)" value={fmt.lacs(t.ob_plan_lacs)} />
      </div>

      <div className="grid2">
        <div>
          <h3>Files</h3>
          <ul className="files">
            {Object.entries(s.files).map(([k, name]) => (
              <li key={k}>
                <a href={api.fileUrl(rec.id, name)}>{name}</a>
                <span className="muted small"> — {FILE_LABELS[k] || k}</span>
              </li>
            ))}
          </ul>
          <h3>MD61 files</h3>
          <table className="tbl">
            <thead>
              <tr>
                <th>File</th>
                <th className="num">Rows</th>
                <th className="num">Date cols</th>
                <th className="num">Qty</th>
                <th>Turned monthly (97 rule)</th>
              </tr>
            </thead>
            <tbody>
              {["Firm", "Plan"].map((z) => {
                const m = s.md61[z];
                return (
                  <tr key={z} className={m.too_many_columns ? "warn" : ""}>
                    <td>{z}</td>
                    <td className="num">{m.rows}</td>
                    <td className="num">{m.columns}</td>
                    <td className="num">{fmt.qty(m.qty)}</td>
                    <td className="small">{m.collapsed_months.length ? m.collapsed_months.join(", ") : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <h3>Quantity by source</h3>
          <table className="tbl">
            <tbody>
              {s.by_source.map((r) => (
                <tr key={r.source + r.zone}>
                  <td>{r.source}</td>
                  <td>{r.zone}</td>
                  <td className="num">{fmt.qty(r.qty)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div>
          <h3>Exceptions ({issues.length} categories)</h3>
          {issues.length === 0 ? (
            <p className="muted">None.</p>
          ) : (
            <table className="tbl">
              <tbody>
                {issues.map(([k, n]) => (
                  <tr key={k} className={/excluded|No VLD|left out|not in Master/i.test(k) ? "warn" : ""}>
                    <td>{k}</td>
                    <td className="num">{n}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="muted small">Details: one sheet per category in the run report.</p>
          {s.notes?.length > 0 && (
            <div className="alert note">
              {s.notes.map((n) => (
                <div key={n}>{n}</div>
              ))}
            </div>
          )}
          <h3>FCST by customer group (₹ lacs)</h3>
          <table className="tbl">
            <tbody>
              {Object.entries(s.by_new_terms_lacs).map(([k, v]) => (
                <tr key={k}>
                  <td>{k}</td>
                  <td className="num">{fmt.lacs(v)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <details className="small">
        <summary>Inputs used</summary>
        <ul>
          {Object.entries(rec.masters || {}).map(([k, v]) => (
            <li key={k}>
              {k}: {v || "—"} (permanent)
            </li>
          ))}
          {Object.entries(rec.inputs || {}).map(([k, v]) => (
            <li key={k}>
              {k}: <a href={api.fileUrl(rec.id, v.stored_as)}>{v.filename}</a>
              {v.reused_from ? ` (reused from ${v.reused_from})` : ""}
            </li>
          ))}
        </ul>
      </details>
    </section>
  );
}

function Kpi({ label, value, strong }) {
  return (
    <div className={strong ? "kpi strong" : "kpi"}>
      <div className="kpi-value">{value}</div>
      <div className="kpi-label">{label}</div>
    </div>
  );
}
