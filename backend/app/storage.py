"""File-system storage: settings, permanent master files and run history (no database needed)."""
from __future__ import annotations

import copy
import datetime as dt
import json
import re
import shutil
from pathlib import Path
from typing import Optional

from .config import DATA_DIR, DEFAULT_SETTINGS, MASTER_SLOTS, RUN_SLOTS
from .engine.util import norm_status


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def safe_name(name: str) -> str:
    name = Path(name or "file.xlsx").name
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip() or "file.xlsx"


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return copy.deepcopy(default)


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


# --------------------------------------------------------------------------- settings
def settings_path() -> Path:
    return DATA_DIR / "settings.json"


def _migrate(saved: dict) -> dict:
    """Bring settings saved by an older version up to date (runs on every load until saved again)."""
    version = int(saved.get("settings_version", 1) or 1)
    if version < 2 and isinstance(saved.get("status_zone"), dict):
        # v1 turned spaces into underscores, so "In Process" and IN_PROCESS shared one key and
        # "Matl' Acquisition" was stored as MATL_ACQUISITION. Team decision 24-Nov-2026:
        # IN_PROCESS (Domestic MRC) = Firm, "In Process" (Export MRC) = Plan.
        sz = {norm_status(k): v for k, v in saved["status_zone"].items()}
        if "MATL_ACQUISITION" in sz:
            sz["MATL ACQUISITION"] = sz.pop("MATL_ACQUISITION")
        sz["IN_PROCESS"] = "Firm"
        sz["IN PROCESS"] = "Plan"
        for k, v in DEFAULT_SETTINGS["status_zone"].items():
            sz.setdefault(k, v)
        saved = dict(saved, status_zone=sz)
    if version < 2:
        saved["open_items"] = [t for t in saved.get("open_items", []) if "IN_PROCESS" not in t]
    saved["settings_version"] = DEFAULT_SETTINGS["settings_version"]
    return saved


def load_settings() -> dict:
    saved = _migrate(_read_json(settings_path(), {}))
    merged = copy.deepcopy(DEFAULT_SETTINGS)
    for k, v in saved.items():
        if k == "status_zone" and isinstance(v, dict):
            merged["status_zone"] = {norm_status(a): b for a, b in v.items()}
        else:
            merged[k] = v
    return merged


def save_settings(new: dict) -> dict:
    cur = load_settings()
    allowed = set(DEFAULT_SETTINGS)
    for k, v in new.items():
        if k in allowed:
            cur[k] = v
    zones = {}
    for k, v in cur["status_zone"].items():
        key = norm_status(k)
        if not key:
            continue
        val = str(v).strip().capitalize()
        if val not in ("Firm", "Plan", "Ignore"):
            raise ValueError(f"Status '{k}': zone must be Firm, Plan or Ignore.")
        zones[key] = val
    cur["status_zone"] = zones
    cur["max_date_columns"] = int(cur["max_date_columns"])
    cur["plan_horizon_months"] = int(cur["plan_horizon_months"])
    if cur["max_date_columns"] < 12:
        raise ValueError("Max MD61 date columns should be at least 12.")
    _write_json(settings_path(), cur)
    return cur


# --------------------------------------------------------------------------- masters
def master_dir(slot: str) -> Path:
    return DATA_DIR / "masters" / slot


def master_meta(slot: str) -> Optional[dict]:
    meta = _read_json(master_dir(slot) / "meta.json", None)
    if meta and (master_dir(slot) / meta["stored_as"]).exists():
        return meta
    return None


def master_file(slot: str) -> Optional[Path]:
    meta = master_meta(slot)
    return master_dir(slot) / meta["stored_as"] if meta else None


def save_master(slot: str, tmp_file: Path, filename: str, info: dict) -> dict:
    if slot not in MASTER_SLOTS:
        raise KeyError(slot)
    d = master_dir(slot)
    old = master_meta(slot)
    if old:  # keep the previous version for reference
        hist = d / "previous"
        hist.mkdir(parents=True, exist_ok=True)
        src = d / old["stored_as"]
        if src.exists():
            shutil.move(str(src), str(hist / f"{old['uploaded_at'].replace(':', '')}__{old['filename']}"))
    d.mkdir(parents=True, exist_ok=True)
    stored = safe_name(filename)
    shutil.move(str(tmp_file), str(d / stored))
    meta = {"slot": slot, "filename": filename, "stored_as": stored, "uploaded_at": _now(), "info": info}
    _write_json(d / "meta.json", meta)
    return meta


# --------------------------------------------------------------------------- runs
def runs_dir() -> Path:
    return DATA_DIR / "runs"


def new_run_id(run_date: str) -> str:
    stamp = dt.datetime.now().strftime("%H%M%S")
    base = f"{run_date}_{stamp}"
    rid, i = base, 2
    while (runs_dir() / rid).exists():
        rid = f"{base}-{i}"
        i += 1
    return rid


def run_path(run_id: str) -> Path:
    if not re.fullmatch(r"[\w\-]+", run_id):
        raise KeyError(run_id)
    return runs_dir() / run_id


def save_run(run_id: str, record: dict) -> None:
    _write_json(run_path(run_id) / "run.json", record)


def load_run(run_id: str) -> Optional[dict]:
    rec = _read_json(run_path(run_id) / "run.json", None)
    return rec


def list_runs() -> list[dict]:
    out = []
    if not runs_dir().exists():
        return out
    for p in runs_dir().iterdir():
        rec = _read_json(p / "run.json", None)
        if rec:
            out.append(rec)
    out.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return out


def last_successful_run(exclude: str = "") -> Optional[dict]:
    for r in list_runs():
        if r.get("status") == "done" and r.get("id") != exclude:
            return r
    return None


def last_inputs() -> dict:
    """Latest stored file for every weekly slot (for 'reuse last file')."""
    found = {}
    for r in list_runs():
        if r.get("status") != "done":
            continue
        for slot, meta in (r.get("inputs") or {}).items():
            if slot in RUN_SLOTS and slot not in found:
                p = run_path(r["id"]) / "inputs" / meta["stored_as"]
                if p.exists():
                    found[slot] = {"filename": meta["filename"], "run_id": r["id"], "run_date": r.get("run_date"),
                                   "path": str(p)}
    return found
