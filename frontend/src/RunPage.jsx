import React, { useState } from "react";
import { api, fmt } from "./api.js";
import RunResult from "./RunResult.jsx";

function today() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

export default function RunPage({ state, refresh, goMasters }) {
  const [runDate, setRunDate] = useState(today());
  const [rate, setRate] = useState(state.settings.last_usd_inr ?? "");
  const [files, setFiles] = useState({});
  const [reuse, setReuse] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [formKey, setFormKey] = useState(0);

  const slots = Object.entries(state.run_slots);
  const last = state.last_inputs || {};
  const master = state.masters.master;
  const va31 = state.masters.va31;
  const ready =
    master &&
    rate !== "" &&
    Number(rate) > 0 &&
    slots.every(([k]) => files[k] || (reuse[k] && last[k]));

  async function submit(e) {
    e.preventDefault();
    setError("");
    setResult(null);
    const fd = new FormData();
    fd.append("run_date", runDate);
    fd.append("usd_inr", String(rate));
    const reuseList = [];
    for (const [k] of slots) {
      if (files[k]) fd.append(k, files[k]);
      else if (reuse[k]) reuseList.push(k);
    }
    fd.append("reuse", reuseList.join(","));
    setBusy(true);
    try {
      const rec = await api.startRun(fd);
      setResult(rec);
      setFiles({});
      setReuse({});
      setFormKey((n) => n + 1);
      refresh();
    } catch (err) {
      setError(err.message);
      refresh();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      {state.settings.open_items?.length > 0 && (
        <div className="alert note">
          <strong>Open item:</strong> {state.settings.open_items[0]}
        </div>
      )}
      <section className="card">
        <h2>Permanent inputs</h2>
        <div className="masters-strip">
          <MasterChip label="Master classification" meta={master} required />
          <MasterChip label="VA31 line items (for ZVA_SCH)" meta={va31} />
          <button className="link" onClick={goMasters}>
            Manage masters
          </button>
        </div>
      </section>

      <form className="card" onSubmit={submit}>
        <h2>Weekly inputs</h2>
        <div className="row">
          <label className="field">
            <span>Run date</span>
            <input type="date" value={runDate} onChange={(e) => setRunDate(e.target.value)} required />
          </label>
          <label className="field">
            <span>USD → INR rate for this run</span>
            <input
              type="number"
              step="0.01"
              min="1"
              placeholder="e.g. 88.50"
              value={rate}
              onChange={(e) => setRate(e.target.value)}
              required
            />
          </label>
        </div>

        <div className="slots">
          {slots.map(([k, meta]) => (
            <div key={k} className={files[k] || (reuse[k] && last[k]) ? "slot ok" : "slot"}>
              <div className="slot-head">
                <strong>{meta.label}</strong>
                <span className="muted small">{meta.hint}</span>
              </div>
              <input
                key={`${k}-${formKey}`}
                type="file"
                accept=".xlsx,.xls,.xlsm"
                onChange={(e) => {
                  const f = e.target.files[0];
                  setFiles((s) => ({ ...s, [k]: f }));
                  if (f) setReuse((s) => ({ ...s, [k]: false }));
                }}
              />
              {last[k] && !files[k] && (
                <label className="reuse">
                  <input
                    type="checkbox"
                    checked={!!reuse[k]}
                    onChange={(e) => setReuse((s) => ({ ...s, [k]: e.target.checked }))}
                  />
                  <span>
                    Use last run's file: <em>{last[k].filename}</em> ({fmt.date(last[k].run_date)})
                  </span>
                </label>
              )}
            </div>
          ))}
        </div>

        {!master && (
          <div className="alert error">
            Upload the Master classification file first.{" "}
            <button type="button" className="link" onClick={goMasters}>
              Go to Masters
            </button>
          </div>
        )}
        {error && <div className="alert error">{error}</div>}
        <div className="actions">
          <button className="primary" type="submit" disabled={!ready || busy}>
            {busy ? "Processing… (10–60 s)" : "Run"}
          </button>
          {!ready && !busy && (
            <span className="muted small">Needs the run date, USD rate and all four weekly files.</span>
          )}
        </div>
      </form>

      {result && <RunResult rec={result} />}
    </div>
  );
}

function MasterChip({ label, meta, required }) {
  return (
    <div className={meta ? "chip ok" : required ? "chip bad" : "chip"}>
      <span className="chip-label">{label}</span>
      {meta ? (
        <span>
          {meta.filename} <span className="muted">· {fmt.dateTime(meta.uploaded_at)}</span>
        </span>
      ) : (
        <span className="muted">{required ? "missing" : "not uploaded (ZVA_SCH will be empty)"}</span>
      )}
    </div>
  );
}
