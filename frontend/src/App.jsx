import React, { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import RunPage from "./RunPage.jsx";
import History from "./History.jsx";
import Masters from "./Masters.jsx";
import Settings from "./Settings.jsx";

const TABS = [
  ["run", "New run"],
  ["history", "Run history"],
  ["masters", "Masters"],
  ["settings", "Settings"],
];

export default function App() {
  const [tab, setTab] = useState("run");
  const [state, setState] = useState(null);
  const [error, setError] = useState("");

  const refresh = useCallback(() => {
    return api
      .state()
      .then((s) => {
        setState(s);
        setError("");
        return s;
      })
      .catch((e) => setError(`Cannot reach the server: ${e.message}`));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const masterMissing = state && !state.masters.master;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <strong>S&amp;OP Order Book</strong>
          <span className="muted">MRC / PO / S&amp;OP → MD61 Firm &amp; Plan → ZVA_SCH → Order book</span>
        </div>
        <nav className="tabs">
          {TABS.map(([k, label]) => (
            <button key={k} className={tab === k ? "tab active" : "tab"} onClick={() => setTab(k)}>
              {label}
              {k === "masters" && masterMissing ? <span className="dot" title="Master file missing" /> : null}
            </button>
          ))}
        </nav>
      </header>
      <main className="content">
        {error && <div className="alert error">{error}</div>}
        {!state && !error && <p className="muted">Loading…</p>}
        {state && tab === "run" && <RunPage state={state} refresh={refresh} goMasters={() => setTab("masters")} />}
        {state && tab === "history" && <History state={state} />}
        {state && tab === "masters" && <Masters state={state} refresh={refresh} />}
        {state && tab === "settings" && <Settings state={state} refresh={refresh} />}
      </main>
      {state && <footer className="footer muted">Data folder: {state.data_dir}</footer>}
    </div>
  );
}
