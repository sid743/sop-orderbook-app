import React, { useState } from "react";
import { api } from "./api.js";

export default function Settings({ state, refresh }) {
  const [s, setS] = useState(() => JSON.parse(JSON.stringify(state.settings)));
  const [newStatus, setNewStatus] = useState("");
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  const set = (k, v) => setS((x) => ({ ...x, [k]: v }));
  const setZone = (k, v) => setS((x) => ({ ...x, status_zone: { ...x.status_zone, [k]: v } }));

  async function save() {
    setBusy(true);
    setMsg(null);
    try {
      const saved = await api.saveSettings(s);
      setS(saved);
      setMsg({ ok: true, text: "Settings saved. They apply from the next run." });
      refresh();
    } catch (e) {
      setMsg({ ok: false, text: e.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      {s.open_items?.length > 0 && (
        <div className="alert note">
          <strong>Open items</strong>
          <ul>
            {s.open_items.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
          <button type="button" className="small-btn" onClick={() => set("open_items", [])}>
            Mark resolved (removes this note when you save)
          </button>
        </div>
      )}

      <section className="card">
        <h2>MRC status → zone</h2>
        <p className="muted small">
          Firm goes to the F-plan MD61 file, ZVA_SCH and Firm/PO in the order book. Plan goes to the P-plan MD61 file
          and Estimate/plan. Ignore drops the line. A status not listed here is left out and shown in the run report.
          Spelling matters, case does not: <code>IN_PROCESS</code> (with underscore, Domestic MRC) and{" "}
          <code>IN PROCESS</code> (with a space, Export MRC) are separate statuses.
        </p>
        <table className="tbl narrow">
          <tbody>
            {Object.entries(s.status_zone).map(([k, v]) => (
              <tr key={k} className={k === "IN_PROCESS" ? "highlight" : ""}>
                <td>
                  <code>{k}</code>
                </td>
                <td>
                  <select value={v} onChange={(e) => setZone(k, e.target.value)}>
                    <option>Firm</option>
                    <option>Plan</option>
                    <option>Ignore</option>
                  </select>
                </td>
              </tr>
            ))}
            <tr>
              <td>
                <input placeholder="NEW_STATUS" value={newStatus} onChange={(e) => setNewStatus(e.target.value)} />
              </td>
              <td>
                <button
                  type="button"
                  disabled={!newStatus.trim()}
                  onClick={() => {
                    setZone(newStatus.trim().toUpperCase().replace(/['’]/g, "").replace(/\s+/g, " "), "Plan");
                    setNewStatus("");
                  }}
                >
                  Add
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <section className="card">
        <h2>MD61 upload files</h2>
        <div className="row wrap">
          <Num label="Max date columns per file" v={s.max_date_columns} on={(v) => set("max_date_columns", v)}
               help="Notes: max 97. If SAP counts the 4 key columns too, set 93." />
          <Num label="Horizon (months after run month)" v={s.plan_horizon_months}
               on={(v) => set("plan_horizon_months", v)} help="13 = run month + 13 (Nov-26 run → Dec-27)." />
          <Txt label="Firm requirement plan prefix" v={s.firm_prefix} on={(v) => set("firm_prefix", v)} />
          <Txt label="Plan requirement plan prefix" v={s.plan_prefix} on={(v) => set("plan_prefix", v)}
               help="19-Nov file and MD79 use P (process sheet says B)." />
          <Txt label="Version No" v={s.version_no} on={(v) => set("version_no", v)} />
          <Txt label="Active flag" v={s.active_flag} on={(v) => set("active_flag", v)} />
        </div>
        <label className="check">
          <input
            type="checkbox"
            checked={!!s.past_due_to_month_start}
            onChange={(e) => set("past_due_to_month_start", e.target.checked)}
          />
          Move past-due dates (before the run month) to the 1st of the run month
        </label>
      </section>

      <section className="card">
        <h2>Pricing</h2>
        <p className="muted small">
          Price = VLD PR00 record valid on the run date (else the latest record). USD prices × the run's USD/INR rate.
        </p>
        <label className="check">
          <input
            type="checkbox"
            checked={!!s.price_fallback_sales}
            onChange={(e) => set("price_fallback_sales", e.target.checked)}
          />
          When a part has no VLD record, use its last invoice price from the sales register
        </label>
        <p className="muted small">
          Off = VLD only (parts without a VLD record are valued at 0 and listed in the run report). The 21-Nov VLD file
          has no records for most CAT MRC parts.
        </p>
      </section>

      {msg && <div className={msg.ok ? "alert ok" : "alert error"}>{msg.text}</div>}
      <div className="actions">
        <button className="primary" onClick={save} disabled={busy}>
          {busy ? "Saving…" : "Save settings"}
        </button>
      </div>
    </div>
  );
}

function Num({ label, v, on, help }) {
  return (
    <label className="field">
      <span>{label}</span>
      <input type="number" value={v} onChange={(e) => on(e.target.value === "" ? "" : Number(e.target.value))} />
      {help && <small className="muted">{help}</small>}
    </label>
  );
}

function Txt({ label, v, on, help }) {
  return (
    <label className="field">
      <span>{label}</span>
      <input value={v} onChange={(e) => on(e.target.value)} />
      {help && <small className="muted">{help}</small>}
    </label>
  );
}
