"""Paths and default settings."""
from __future__ import annotations

import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
ROOT_DIR = BACKEND_DIR.parent
DATA_DIR = Path(os.environ.get("SOP_DATA_DIR", ROOT_DIR / "data")).resolve()
FRONTEND_DIST = Path(os.environ.get("SOP_FRONTEND_DIST", ROOT_DIR / "frontend" / "dist")).resolve()

# Permanent inputs: uploaded once, replaced when they change.
MASTER_SLOTS = {
    "master": {"label": "Master classification file", "required": True,
               "hint": "1.Master - sheet 'Masters' (MRC CODE, SAP CODE, Location, Customer Code, New Terms ...)"},
    "va31": {"label": "VA31 line items", "required": False,
             "hint": "6.VA31 Line item - Sales Document, Item (SD), Sold-To Party, Material. Needed for ZVA_SCH."},
}

# Weekly inputs: uploaded every run (or reused from the last run).
RUN_SLOTS = {
    "mrc": {"label": "MRC schedule (CAT)", "hint": "2.MRC schedule - Export + Domestic sheets"},
    "po_sop": {"label": "PO & S&OP", "hint": "3.PO & S&OP - 'Open PO FIRM ZONE' + 'S&OP plan zone' sheets"},
    "vld": {"label": "VLD SAP pricing", "hint": "4.VLD sap pricing - V/LD PR00 list, Domestic + Export sales orgs"},
    "sales": {"label": "Sales register", "hint": "5.Sales register - 1 April to run date"},
}

DEFAULT_SETTINGS = {
    # MRC status -> zone. Firm / Plan / Ignore.
    "status_zone": {
        "PENDING": "Firm",
        "OPEN": "Firm",
        "ACCEPTED": "Firm",
        "SUPPLIER_REQ_CHANGE": "Firm",
        "PLANNED": "Plan",
        "TRADEOFF": "Plan",
        "IN_PROCESS": "Plan",
        "MATL_ACQUISITION": "Plan",
    },
    "max_date_columns": 97,          # Notes: max 97 columns, go monthly from the last month
    "plan_horizon_months": 13,       # demand kept up to the end of run month + N (19-Nov file ran to Dec-2027)
    "past_due_to_month_start": True,  # dates before the run month go to the 1st of the run month
    "firm_prefix": "F",
    "plan_prefix": "P",
    "version_no": "00",
    "active_flag": "X",
    "price_fallback_sales": False,   # VLD only (agreed); switch on to use last invoice price when VLD has none
    "last_usd_inr": None,
    "open_items": [
        "Ask the team: should MRC status IN_PROCESS be Firm or Plan? It is set to Plan for now "
        "(Notes sheet says Plan; the 19-Nov MD61 Firm file had it in Firm). Change it under Status -> zone.",
    ],
}
