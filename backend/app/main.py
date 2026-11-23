"""FastAPI app: permanent masters, weekly runs, downloads, and the built React UI."""
from __future__ import annotations

import datetime as dt
import io
import shutil
import tempfile
import threading
import traceback
import zipfile
from pathlib import Path
from typing import Optional

import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import storage
from .config import DATA_DIR, FRONTEND_DIST, MASTER_SLOTS, RUN_SLOTS
from .engine import pipeline
from .engine.readers import READERS

app = FastAPI(title="S&OP Order Book", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])
_run_lock = threading.Lock()
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _save_upload(upload: UploadFile) -> Path:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in (".xlsx", ".xlsm", ".xls"):
        raise HTTPException(400, f"{upload.filename}: please upload an Excel file (.xlsx / .xls).")
    tmp = Path(tempfile.mkdtemp()) / storage.safe_name(upload.filename)
    with tmp.open("wb") as f:
        shutil.copyfileobj(upload.file, f)
    return tmp


def _master_info(slot: str, path: Path) -> dict:
    df = READERS[slot](str(path))
    if slot == "master":
        return {"rows": int(len(df)), "mrc_rows": int(df["is_mrc"].sum()), "po_sop_rows": int((~df["is_mrc"]).sum()),
                "customer_codes": int(df["cust_code"].nunique()), "sap_codes": int(df["sap_code"].nunique())}
    return {"lines": int(len(df)), "sales_documents": int(df["sales_doc"].nunique()),
            "customers": int(df["cust_code"].nunique())}


# --------------------------------------------------------------------------- state & settings
@app.get("/api/health")
def health():
    return {"ok": True, "data_dir": str(DATA_DIR)}


@app.get("/api/state")
def state():
    last = storage.last_inputs()
    return {
        "settings": storage.load_settings(),
        "master_slots": MASTER_SLOTS,
        "run_slots": RUN_SLOTS,
        "masters": {s: storage.master_meta(s) for s in MASTER_SLOTS},
        "last_inputs": {k: {kk: vv for kk, vv in v.items() if kk != "path"} for k, v in last.items()},
        "runs": [_brief(r) for r in storage.list_runs()[:50]],
        "data_dir": str(DATA_DIR),
    }


def _brief(r: dict) -> dict:
    s = r.get("summary") or {}
    return {"id": r["id"], "status": r.get("status"), "run_date": r.get("run_date"), "created_at": r.get("created_at"),
            "usd_inr": r.get("usd_inr"), "error": r.get("error"), "totals": s.get("totals"),
            "issue_counts": s.get("issue_counts"), "inputs": {k: v["filename"] for k, v in (r.get("inputs") or {}).items()}}


@app.put("/api/settings")
def put_settings(body: dict):
    try:
        return storage.save_settings(body)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))


# --------------------------------------------------------------------------- masters
@app.post("/api/masters/{slot}")
def upload_master(slot: str, file: UploadFile = File(...)):
    if slot not in MASTER_SLOTS:
        raise HTTPException(404, "Unknown master slot")
    tmp = _save_upload(file)
    try:
        info = _master_info(slot, tmp)
    except ValueError as e:
        raise HTTPException(400, f"{MASTER_SLOTS[slot]['label']}: {e}")
    except Exception as e:
        raise HTTPException(400, f"{MASTER_SLOTS[slot]['label']}: could not be read ({e})")
    return storage.save_master(slot, tmp, file.filename, info)


@app.get("/api/masters/{slot}/file")
def download_master(slot: str):
    p = storage.master_file(slot)
    if not p:
        raise HTTPException(404, "Not uploaded yet")
    return FileResponse(p, filename=storage.master_meta(slot)["filename"], media_type=XLSX_MIME)


# --------------------------------------------------------------------------- runs
@app.post("/api/runs")
def create_run(
    run_date: str = Form(...),
    usd_inr: float = Form(...),
    reuse: str = Form(""),
    mrc: Optional[UploadFile] = File(None),
    po_sop: Optional[UploadFile] = File(None),
    vld: Optional[UploadFile] = File(None),
    sales: Optional[UploadFile] = File(None),
):
    try:
        rd = pd.Timestamp(dt.date.fromisoformat(run_date))
    except ValueError:
        raise HTTPException(400, "Run date must be YYYY-MM-DD.")
    if not (1 <= usd_inr <= 1000):
        raise HTTPException(400, "Enter the USD/INR rate for this run (e.g. 88.50).")
    if not storage.master_file("master"):
        raise HTTPException(400, "Upload the Master classification file first (Masters tab).")
    uploads = {"mrc": mrc, "po_sop": po_sop, "vld": vld, "sales": sales}
    reuse_slots = {s.strip() for s in reuse.split(",") if s.strip()}
    last = storage.last_inputs()
    missing = [RUN_SLOTS[s]["label"] for s, u in uploads.items()
               if (u is None or not u.filename) and not (s in reuse_slots and s in last)]
    if missing:
        raise HTTPException(400, "Missing input file(s): " + ", ".join(missing))

    if not _run_lock.acquire(blocking=False):
        raise HTTPException(409, "Another run is in progress. Try again in a minute.")
    try:
        rid = storage.new_run_id(rd.strftime("%Y-%m-%d"))
        rdir = storage.run_path(rid)
        (rdir / "inputs").mkdir(parents=True, exist_ok=True)
        inputs_meta, paths = {}, {}
        for slot, up in uploads.items():
            if up is not None and up.filename:
                tmp = _save_upload(up)
                stored = f"{slot}__{storage.safe_name(up.filename)}"
                shutil.move(str(tmp), str(rdir / "inputs" / stored))
                inputs_meta[slot] = {"filename": up.filename, "stored_as": stored, "reused_from": None}
            else:
                src = Path(last[slot]["path"])
                stored = f"{slot}__{storage.safe_name(last[slot]['filename'])}"
                shutil.copy2(src, rdir / "inputs" / stored)
                inputs_meta[slot] = {"filename": last[slot]["filename"], "stored_as": stored,
                                     "reused_from": last[slot]["run_id"]}
            paths[slot] = str(rdir / "inputs" / stored)
        for slot in MASTER_SLOTS:
            meta = storage.master_meta(slot)
            paths[slot] = str(storage.master_file(slot)) if meta else None
        masters_used = {s: (storage.master_meta(s) or {}).get("filename") for s in MASTER_SLOTS}

        settings = storage.load_settings()
        prev = storage.last_successful_run()
        prev_firm, prev_label = None, ""
        if prev:
            snap = storage.run_path(prev["id"]) / "outputs" / "_firm_snapshot.csv"
            if snap.exists():
                prev_firm = pd.read_csv(snap, dtype={"cust_code": str, "sap_code": str})
                prev_label = f"{prev['run_date']} ({prev['id']})"
        record = {"id": rid, "status": "running", "run_date": rd.strftime("%Y-%m-%d"), "usd_inr": usd_inr,
                  "created_at": dt.datetime.now().isoformat(timespec="seconds"), "inputs": inputs_meta,
                  "masters": masters_used, "settings": settings}
        storage.save_run(rid, record)
        try:
            summary = pipeline.run(paths, rd, usd_inr, settings, str(rdir / "outputs"), prev_firm, prev_label)
            record.update(status="done", summary=summary)
            storage.save_run(rid, record)
            settings["last_usd_inr"] = usd_inr
            storage.save_settings(settings)
            return record
        except pipeline.InputError as e:
            record.update(status="failed", error=str(e))
            storage.save_run(rid, record)
            raise HTTPException(400, str(e))
        except Exception as e:
            (rdir / "error.txt").write_text(traceback.format_exc(), encoding="utf-8")
            record.update(status="failed", error=f"{type(e).__name__}: {e}")
            storage.save_run(rid, record)
            raise HTTPException(500, f"Run failed: {type(e).__name__}: {e} (details in {rdir / 'error.txt'})")
    finally:
        _run_lock.release()


@app.get("/api/runs")
def runs():
    return [_brief(r) for r in storage.list_runs()]


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str):
    try:
        rec = storage.load_run(run_id)
    except KeyError:
        rec = None
    if not rec:
        raise HTTPException(404, "Run not found")
    return rec


@app.get("/api/runs/{run_id}/files/{name}")
def run_file(run_id: str, name: str):
    rec = run_detail(run_id)
    files = (rec.get("summary") or {}).get("files") or {}
    inputs = rec.get("inputs") or {}
    if name in files.values():
        p = storage.run_path(run_id) / "outputs" / name
        dl = name
    elif name in {v["stored_as"] for v in inputs.values()}:
        p = storage.run_path(run_id) / "inputs" / name
        dl = name.split("__", 1)[-1]
    else:
        raise HTTPException(404, "File not found")
    if not p.exists():
        raise HTTPException(404, "File missing on disk")
    return FileResponse(p, filename=dl, media_type=XLSX_MIME)


@app.get("/api/runs/{run_id}/zip")
def run_zip(run_id: str):
    rec = run_detail(run_id)
    files = (rec.get("summary") or {}).get("files") or {}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in files.values():
            p = storage.run_path(run_id) / "outputs" / name
            if p.exists():
                z.write(p, arcname=name)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="SOP outputs {rec["run_date"]}.zip"'})


# --------------------------------------------------------------------------- UI
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        target = FRONTEND_DIST / path
        if path and target.is_file():
            return FileResponse(target)
        return FileResponse(FRONTEND_DIST / "index.html")
else:
    @app.get("/")
    def no_ui():
        return JSONResponse({"message": "API is running. Build the UI with 'npm run build' in frontend/."})
