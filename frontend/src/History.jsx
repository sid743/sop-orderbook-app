import React, { useState } from "react";
import { api, fmt } from "./api.js";
import RunResult from "./RunResult.jsx";

export default function History({ state }) {
  const [open, setOpen] = useState(null);
  const [error, setError] = useState("");

  async function show(id) {
    setError("");
    try {
      setOpen(await api.run(id));
    } catch (e) {
      setError(e.message);
    }
  }

  if (!state.runs.length) return <p className="muted">No runs yet.</p>;
  return (
    <div>
      <section className="card">
        <h2>Run history</h2>
        <table className="tbl clickable">
          <thead>
            <tr>
              <th>Run date</th>
              <th>Created</th>
              <th>Status</th>
              <th className="num">USD/INR</th>
              <th className="num">Firm qty</th>
              <th className="num">Plan qty</th>
              <th className="num">FCST ₹ lacs</th>
              <th className="num">Exception rows</th>
            </tr>
          </thead>
          <tbody>
            {state.runs.map((r) => {
              const issues = Object.values(r.issue_counts || {}).reduce((a, b) => a + b, 0);
              return (
                <tr key={r.id} onClick={() => show(r.id)} className={open?.id === r.id ? "selected" : ""}>
                  <td>{fmt.date(r.run_date)}</td>
                  <td>{fmt.dateTime(r.created_at)}</td>
                  <td>
                    <span className={`badge ${r.status}`}>{r.status}</span>
                    {r.error ? <span className="muted small"> {r.error.slice(0, 80)}</span> : null}
                  </td>
                  <td className="num">{r.usd_inr}</td>
                  <td className="num">{fmt.qty(r.totals?.firm_qty)}</td>
                  <td className="num">{fmt.qty(r.totals?.plan_qty)}</td>
                  <td className="num">{fmt.lacs(r.totals?.ob_total_lacs)}</td>
                  <td className="num">{r.status === "done" ? issues : "-"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
      {error && <div className="alert error">{error}</div>}
      {open && <RunResult rec={open} />}
    </div>
  );
}
