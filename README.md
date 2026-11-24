# S&OP Order Book app

FastAPI + React app for the weekly S&OP cycle:

**Inputs → MD61 Firm + MD61 Plan (ZPIRDAILY uploads) → ZVA_SCH (VA31 upload) → Order book (3 sheets) + run report**

## Start it (Windows, Command Prompt)

Needs Python 3.10 or newer (python.org, tick "Add python.exe to PATH").

```
cd /d "C:\Users\Sid\steel1\P04_S&OP\sop-orderbook-app"
run_app.bat
```

The first start creates `.venv` and installs the packages (needs internet, about a minute). After that it opens
http://127.0.0.1:8000 in the browser. Close the command window to stop the app.

Manual start, if you prefer:

```
cd /d "C:\Users\Sid\steel1\P04_S&OP\sop-orderbook-app"
python -m venv .venv
.venv\Scripts\python -m pip install -r backend\requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

The React UI is already built (`frontend\dist`), so Node.js is not needed to use the app.

## Weekly use

1. **Masters tab** (once, and whenever they change): upload
   - `1.Master` classification file (required)
   - `6.VA31 Line item` (optional; needed for ZVA_SCH)
2. **New run tab**: run date, USD→INR rate for this run, and the four weekly files:
   `2.MRC schedule`, `3.PO & S&OP`, `4.VLD sap pricing`, `5.Sales register`.
   Any of them can be reused from the last run with the tick box.
3. Download the outputs (or all as .zip). Every run is kept under **Run history** with its inputs.

Outputs per run:

| File | What it is |
|---|---|
| `7.ZPIRDaily(MD61) - Firm - dd.mm.yyyy.xlsx` | MD61 upload, requirement plan `F<customer code>` |
| `8.ZPIRDaily(MD61) - Plan - dd.mm.yyyy.xlsx` | MD61 upload, requirement plan `P<customer code>` |
| `9.ZVA_SCH(ddmmyyyy).xlsx` | VA31 firm schedule upload (Ref, item, part, date dd.mm.yyyy, qty, MRC ID) |
| `Order Book FYxx - dd.mm.yyyy.xlsx` | 1. Order book summary, 2. Part family order book, 3. Part level order book |
| `Run report - dd.mm.yyyy.xlsx` | Totals by source, MD61 checks, one sheet per exception type, firm-zone changes vs the last run |

## Rules built in

Taken from the Master `Notes` / `process` sheets and the 19-Nov upload files.

- **CAT (MRC)**: `Item ID` + delivery location (`Deliver To` / `Delivery To`) → Master `MRC CODE` + `Location` → SAP code and customer code.
  Qty = Ordered − MAX(Shipped, Received). Date = Ship Date. Quantities for different MRC revisions of one SAP code are added.
- **Zone by MRC status** (Settings tab; spelling matters, case does not):
  Firm = Pending, Open, ACCEPTED, SUPPLIER_REQ_CHANGE, **IN_PROCESS** (with underscore, Domestic MRC).
  Plan = Tradeoff, Planned, **In Process** (with a space, Export MRC), Matl' Acquisition.
  Team decision 24-Nov-2026. Settings saved by the first version are converted automatically on first load.
- **Other customers**: `Open PO FIRM ZONE` sheet = Firm (Best Ex Works date); `S&OP plan zone` sheet = Plan
  (month quantity on the 1st of the month). Material → Master (PO/S&OP rows) for the SAP code.
- **Past dues**: dates before the 1st of the run month go to the 1st of the run month (as in the 19-Nov Firm file).
- **Horizon**: run month + 13 months (Nov-26 run → Dec-27, as in the 19-Nov Plan file). Later dates are not uploaded
  and are listed in the run report. Change it in Settings.
- **97-column rule**: each MD61 file uses the exact dates. If there are more than 97 date columns, months are
  turned monthly (1st of the month) from the last month backwards until the file fits.
- **ZVA_SCH**: firm quantities on the same dates as the MD61 Firm file, matched to VA31 by Sold-To Party + Material.
  Parts with no VA31 line, or with several line items for the same part (most of Terex), are left out and listed.
- **Price**: VLD PR00 record valid on the run date (else the latest record); domestic customers use the domestic
  sales org, export customers the export org. USD × the run's USD/INR rate → INR. Parts without a VLD record are
  valued at 0 and listed. Settings has an optional switch to use the last invoice price instead.
- **Order book** (INR lacs): month columns from 1 April of the FY to run month + 11 (Nov-26 run → Oct-27).
  Months before the run month = actual sales register. The run month has two columns: invoiced 1st–run date
  (e.g. "Nov-26 01-24") and open for the rest of the month (e.g. "Nov-26 25-30"); the open column also carries
  past-due orders not yet invoiced. Later months = open Firm + Plan × price; months after March are marked
  "Open FY28". The FY totals (Actual YTD, Firm/PO FY27, Estimate/plan FY27, H1, H2, FCST FY27) cover April–March only.
  A firm PO and an S&OP quantity in the same month are both real demand and are both counted.
  Classification (New Terms, Segment, EXIM, Customer, Family, Model) from the Master; sales parts not in the Master
  appear as "Not in Master".
- CM / cost columns are not included (agreed: skip for now).

## Open items

- **Plan prefix**: the process sheet says Plan starts with "B"; the 19-Nov Plan file and MD79 use "P". The app uses P
  (Settings).
- **97 columns**: the app counts date columns only. If SAP counts the 4 key columns too, set the limit to 93.
- **VLD coverage**: the 21-Nov VLD file has no price records for most CAT MRC parts, so their open orders show 0
  value unless the last-invoice switch is on or a VLD download with those prices is used.
- **ZVA_SCH dates**: the 20-Nov ZVA_SCH file had January 2027 dates written as `..01.2026`. The app writes the real year.

## Folders

```
sop-orderbook-app\
  run_app.bat            start script
  backend\app\           FastAPI app (main.py) and engine\ (readers, demand, outputs, excel, pipeline)
  frontend\              React source (src\) and built UI (dist\)
  data\                  created on first start: settings.json, masters\, runs\<run id>\inputs + outputs
```

Set `SOP_DATA_DIR` to keep the data folder somewhere else.

## Changing the UI (optional, needs Node.js)

```
cd frontend
npm install
npm run dev        (UI on http://localhost:5173, talks to the API on :8000)
npm run build      (writes frontend\dist, which the API serves)
```

## Azure App Service (Linux)

The root `requirements.txt` is for Azure only (adds gunicorn). Startup command:

```
gunicorn --chdir backend -w 1 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000 --timeout 600 app.main:app
```

Keep one worker: runs and history are stored as files and a run holds an in-process lock. Set the app setting
`SOP_DATA_DIR=/home/sopdata` so masters and run history live on the persistent `/home` share. The app has no login
of its own; restrict access (IP rule or App Service Authentication) before sharing the URL.

## API

`GET /api/state` · `PUT /api/settings` · `POST /api/masters/{master|va31}` · `POST /api/runs` (multipart: run_date,
usd_inr, reuse, mrc, po_sop, vld, sales) · `GET /api/runs/{id}` · `GET /api/runs/{id}/files/{name}` ·
`GET /api/runs/{id}/zip`. Interactive docs at http://127.0.0.1:8000/docs.
