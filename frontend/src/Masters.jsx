import React, { useState } from "react";
import { api, fmt } from "./api.js";

export default function Masters({ state, refresh }) {
  return (
    <div>
      <p className="muted">
        Permanent inputs are stored once and used by every run until you replace them. The previous version is kept
        in the data folder under <code>masters/&lt;slot&gt;/previous</code>.
      </p>
      {Object.entries(state.master_slots).map(([slot, meta]) => (
        <MasterCard key={slot} slot={slot} meta={meta} current={state.masters[slot]} refresh={refresh} />
      ))}
    </div>
  );
}

function MasterCard({ slot, meta, current, refresh }) {
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  async function upload() {
    setBusy(true);
    setMsg(null);
    try {
      const m = await api.uploadMaster(slot, file);
      setMsg({ ok: true, text: `Saved ${m.filename}` });
      setFile(null);
      refresh();
    } catch (e) {
      setMsg({ ok: false, text: e.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card">
      <h2>
        {meta.label} {meta.required ? <span className="badge failed">required</span> : <span className="badge">optional</span>}
      </h2>
      <p className="muted small">{meta.hint}</p>
      {current ? (
        <div className="current">
          <div>
            <strong>{current.filename}</strong>{" "}
            <span className="muted">uploaded {fmt.dateTime(current.uploaded_at)}</span>{" "}
            <a href={api.masterUrl(slot)}>download</a>
          </div>
          <div className="small muted">
            {Object.entries(current.info || {})
              .map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`)
              .join(" · ")}
          </div>
        </div>
      ) : (
        <p className="muted">Not uploaded yet.</p>
      )}
      <div className="row">
        <input type="file" accept=".xlsx,.xls,.xlsm" onChange={(e) => setFile(e.target.files[0] || null)} />
        <button className="primary" disabled={!file || busy} onClick={upload}>
          {busy ? "Checking…" : current ? "Replace" : "Upload"}
        </button>
      </div>
      {msg && <div className={msg.ok ? "alert ok" : "alert error"}>{msg.text}</div>}
    </section>
  );
}
