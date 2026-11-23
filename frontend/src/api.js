async function handle(res) {
  if (res.ok) return res.json();
  let msg = `${res.status} ${res.statusText}`;
  try {
    const j = await res.json();
    if (j.detail) msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
  } catch {
    /* not json */
  }
  throw new Error(msg);
}

export const api = {
  state: () => fetch("/api/state").then(handle),
  run: (id) => fetch(`/api/runs/${id}`).then(handle),
  saveSettings: (body) =>
    fetch("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(handle),
  uploadMaster: (slot, file) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetch(`/api/masters/${slot}`, { method: "POST", body: fd }).then(handle);
  },
  startRun: (fd) => fetch("/api/runs", { method: "POST", body: fd }).then(handle),
  fileUrl: (id, name) => `/api/runs/${encodeURIComponent(id)}/files/${encodeURIComponent(name)}`,
  zipUrl: (id) => `/api/runs/${encodeURIComponent(id)}/zip`,
  masterUrl: (slot) => `/api/masters/${slot}/file`,
};

export const fmt = {
  qty: (v) => (v == null ? "-" : Math.round(v).toLocaleString("en-IN")),
  lacs: (v) => (v == null ? "-" : v.toLocaleString("en-IN", { maximumFractionDigits: 1, minimumFractionDigits: 1 })),
  date: (s) => {
    if (!s) return "-";
    const d = new Date(s);
    return isNaN(d) ? s : d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
  },
  dateTime: (s) => {
    if (!s) return "-";
    const d = new Date(s);
    return isNaN(d)
      ? s
      : d.toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
  },
};
