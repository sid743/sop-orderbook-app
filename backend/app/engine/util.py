"""Small helpers shared by the engine: code normalisation, header detection, dates."""
from __future__ import annotations

import datetime as dt
import math
import re
from typing import Iterable, Optional

import pandas as pd


def norm_code(value) -> str:
    """Normalise a material / customer / location code to a comparable string.

    - floats that are whole numbers lose the ".0"
    - all-digit strings lose SAP leading zeros (000000000000396903 -> 396903)
    - whitespace trimmed, upper-cased
    """
    if value is None:
        return ""
    if isinstance(value, float):
        if math.isnan(value):
            return ""
        if value.is_integer():
            value = int(value)
    s = str(value).strip()
    if s.lower() in ("nan", "none", "nat"):
        return ""
    if s.isdigit():
        s = s.lstrip("0") or "0"
    return s.upper()


def excel_code(code: str):
    """Value to write into Excel for a material code: int when all digits, else text."""
    if code.isdigit() and len(code) < 16:
        return int(code)
    return code


def norm_status(value) -> str:
    s = str(value or "").strip().upper()
    s = s.replace("'", "").replace("’", "")
    s = re.sub(r"[\s\-]+", "_", s)
    return s


def norm_header(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def find_header_row(raw: pd.DataFrame, must_have: Iterable[str], max_rows: int = 15) -> Optional[int]:
    """Return the index of the first row (in a header=None frame) containing all labels."""
    wanted = [norm_header(w) for w in must_have]
    for i in range(min(max_rows, len(raw))):
        cells = [norm_header(v) for v in raw.iloc[i].tolist()]
        if all(any(w == c for c in cells) for w in wanted):
            return i
    return None


def frame_from_header(raw: pd.DataFrame, header_row: int) -> pd.DataFrame:
    """Turn a header=None frame into a frame using `header_row` as column names.

    Duplicate / blank headers get suffixes so nothing is silently dropped.
    """
    headers = []
    seen: dict[str, int] = {}
    for j, v in enumerate(raw.iloc[header_row].tolist()):
        if isinstance(v, (dt.datetime, pd.Timestamp)):
            name = pd.Timestamp(v)
        else:
            name = str(v).strip() if v is not None and str(v).strip() not in ("", "nan") else f"_col{j}"
        key = str(name)
        if key in seen:
            seen[key] += 1
            name = f"{name}.{seen[key]}" if not isinstance(name, pd.Timestamp) else name
        else:
            seen[key] = 0
        headers.append(name)
    df = raw.iloc[header_row + 1:].copy()
    df.columns = headers
    df = df.reset_index(drop=True)
    return df


def pick_col(df: pd.DataFrame, *candidates: str, required: bool = True) -> Optional[str]:
    """Find a column by any of the candidate names (case/space-insensitive)."""
    lookup = {norm_header(c): c for c in df.columns if not isinstance(c, pd.Timestamp)}
    for cand in candidates:
        key = norm_header(cand)
        if key in lookup:
            return lookup[key]
    # loose contains-match as a fallback
    for cand in candidates:
        key = norm_header(cand)
        for k, orig in lookup.items():
            if key and key in k:
                return orig
    if required:
        raise ValueError(f"Column not found. Expected one of: {', '.join(candidates)}")
    return None


def to_date(value) -> Optional[pd.Timestamp]:
    """Parse Excel dates, datetimes and dd.mm.yyyy / dd-mm-yyyy strings. None if not a date."""
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value.normalize()
    if isinstance(value, (dt.datetime, dt.date)):
        return pd.Timestamp(value).normalize()
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None
        # Excel serial date
        if 20000 < float(value) < 80000:
            return (pd.Timestamp("1899-12-30") + pd.Timedelta(days=float(value))).normalize()
        return None
    s = str(value).strip()
    if not s:
        return None
    for fmt in ("%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return pd.Timestamp(dt.datetime.strptime(s, fmt)).normalize()
        except ValueError:
            continue
    return None


def to_num(value) -> float:
    try:
        f = float(value)
        return 0.0 if math.isnan(f) else f
    except (TypeError, ValueError):
        return 0.0


def month_start(ts: pd.Timestamp) -> pd.Timestamp:
    return pd.Timestamp(year=ts.year, month=ts.month, day=1)


def add_months(ts: pd.Timestamp, n: int) -> pd.Timestamp:
    y = ts.year + (ts.month - 1 + n) // 12
    m = (ts.month - 1 + n) % 12 + 1
    return pd.Timestamp(year=y, month=m, day=1)


def month_end(ts: pd.Timestamp) -> pd.Timestamp:
    return add_months(month_start(ts), 1) - pd.Timedelta(days=1)


def fy_start(ts: pd.Timestamp) -> pd.Timestamp:
    """Indian financial year start (1 April) for the date."""
    year = ts.year if ts.month >= 4 else ts.year - 1
    return pd.Timestamp(year=year, month=4, day=1)


def fy_label(ts: pd.Timestamp) -> str:
    start = fy_start(ts)
    return f"FY{str(start.year + 1)[-2:]}"


def mat_sort_key(code: str):
    """Numbers before text, like Excel's ascending sort."""
    if code.isdigit():
        return (0, int(code), "")
    return (1, 0, code)


def read_raw_sheets(path: str) -> dict[str, pd.DataFrame]:
    """Read every sheet with header=None, all values kept as python objects."""
    engine = None
    if str(path).lower().endswith(".xls"):
        engine = "xlrd"
    return pd.read_excel(path, sheet_name=None, header=None, dtype=object, engine=engine)
