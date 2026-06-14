"""
Capstone Gurobi Optimizer v5

This file is backend-ready:
- Core solver functions do NOT print and do NOT write to Excel.
- Core solver functions return Python dictionaries/lists.
- Django/backend can take these returned rows and write them into Schedule tables.

Standalone Excel mode is kept only for local testing/demo until Django DB integration is ready.

Modes:
    python capstone_gurobi_optimizer_v5.py --mode maintenance --precheck
    python capstone_gurobi_optimizer_v5.py --mode maintenance
    python capstone_gurobi_optimizer_v5.py --mode generate_breakdowns --breakdown-count 10
    python capstone_gurobi_optimizer_v5.py --mode breakdown

Expected local folder structure:
    Capstone_Gurobi_Project/
        capstone_gurobi_optimizer_v5.py
        data/
            technicians.xlsx
            units.xlsx
            breakdown_tickets.xlsx   # optional, can be generated for demo
        results/
"""

from __future__ import annotations

import argparse
import hashlib
import math
import random
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import pandas as pd


# =====================================================
# CONFIG
# =====================================================

REGULAR_DAILY_HOURS = 8.0
DEFAULT_WORKING_DAYS = 250  # annual planning horizon: approx. 5 workdays x 50 weeks
DEFAULT_AVAILABLE_HOURS = REGULAR_DAILY_HOURS * DEFAULT_WORKING_DAYS
IDLE_WARNING_HOURS = 1.0

LABOR_COST_PER_HOUR = 100.0
OVERTIME_PENALTY = 500.0
MAINTENANCE_MISSED_PENALTY = 1_000_000.0
BREAKDOWN_MISSED_PENALTY = 5_000_000.0
AA_BREAKDOWN_MISSED_PENALTY = 50_000_000.0
SLA_VIOLATION_PENALTY = 2_000_000.0
TRAVEL_TIME_COST_PER_HOUR = 50.0

TIME_LIMIT_SECONDS = 180
MIP_GAP = 0.01

SHIFT_START_DEFAULT = "08:00"
SHIFT_END_DEFAULT = "17:00"
LUNCH_START_DEFAULT = "12:00"
LUNCH_END_DEFAULT = "13:00"
MAX_MAINTENANCE_OVERTIME_HOURS = 0.0  # if capacity is not enough, report unassigned instead of overloading technicians

MAINTENANCE_TIME_MAP = {
    "A": 4.0,
    "B": 2.0,
    "C": 0.75,
}

# Annual preventive maintenance rule:
# For each unit in one year:
#   A: 1 operation/year
#   B: 2 operations/year
#   C: 12 operations/year
# This equals 15 maintenance operations per unit/year.
# Because multiple operation types can be done in one visit, the optimizer creates
# monthly visit tasks/packages:
#   10 months: C
#   1 month: B+C
#   1 month: A+B+C
# Therefore, 5000 units create 75,000 operations but 60,000 visit tasks.
ANNUAL_A_COUNT_PER_UNIT = 1
ANNUAL_B_COUNT_PER_UNIT = 2
ANNUAL_C_COUNT_PER_UNIT = 12
ANNUAL_VISITS_PER_UNIT = 12

DEFAULT_MAINTENANCE_PACKAGE = "C"
DEFAULT_BREAKDOWN_SERVICE_TIME = 1.0
DEFAULT_TRAVEL_TIME_HOURS = 0.25  # demo fallback until Google Maps travel matrix is connected

ASIA_DISTRICTS = {
    "adalar", "atasehir", "beykoz", "cekmekoy", "kadikoy", "kartal",
    "maltepe", "pendik", "sancaktepe", "sultanbeyli", "sile", "tuzla",
    "umraniye", "uskudar",
}

EUROPE_DISTRICTS = {
    "arnavutkoy", "avcilar", "bagcilar", "bahcelievler", "bakirkoy",
    "basaksehir", "bayrampasa", "besiktas", "beylikduzu", "beyoglu",
    "buyukcekmece", "catalca", "esenler", "esenyurt", "eyup", "eyupsultan",
    "fatih", "gaziosmanpasa", "gungoren", "kagithane", "kucukcekmece",
    "sariyer", "silivri", "sultangazi", "sisli", "zeytinburnu",
}


@dataclass
class SolverConfig:
    available_hours_default: float = DEFAULT_AVAILABLE_HOURS
    maintenance_combine_rule: str = "sum"  # "sum" or "max"
    allow_unknown_region_match: bool = True
    time_limit_seconds: int = TIME_LIMIT_SECONDS
    mip_gap: float = MIP_GAP
    default_travel_time_hours: float = DEFAULT_TRAVEL_TIME_HOURS
    working_days: int = DEFAULT_WORKING_DAYS
    max_maintenance_overtime_hours: float = MAX_MAINTENANCE_OVERTIME_HOURS
    # Breakdown is an instant/daily dispatch problem, not a monthly plan.
    # When None, the solver spreads tickets as evenly as possible across breakdown technicians.
    max_breakdown_tickets_per_tech: Optional[int] = None
    lunch_start: str = LUNCH_START_DEFAULT
    lunch_end: str = LUNCH_END_DEFAULT


# =====================================================
# TEXT / NORMALIZATION HELPERS
# =====================================================


def clean_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    text = str(value).strip()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    table = str.maketrans({
        "ı": "i", "İ": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g",
        "ü": "u", "Ü": "u", "ö": "o", "Ö": "o", "ç": "c", "Ç": "c",
    })
    return text.translate(table).lower()


def compact_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", clean_text(value))


def find_col(df: pd.DataFrame, candidates: Iterable[str]) -> Optional[str]:
    normalized = {compact_key(col): col for col in df.columns}
    for candidate in candidates:
        key = compact_key(candidate)
        if key in normalized:
            return normalized[key]
    return None


def normalize_skill(value: Any) -> str:
    text = clean_text(value)
    if any(k in text for k in ["both", "hepsi", "iki", "asansor&yuruyen", "elevator&escalator"]):
        return "Both"
    if "escalator" in text or "yuruyen" in text or "merdiven" in text:
        return "Escalator"
    if "elevator" in text or "asansor" in text:
        return "Elevator"
    return str(value).strip() if str(value).strip() else "Unknown"


def normalize_role(value: Any) -> str:
    text = clean_text(value)
    if any(k in text for k in ["both", "hepsi", "iki"]):
        return "Both"
    if "breakdown" in text or "failure" in text or "ariza" in text or "arizaci" in text:
        return "Breakdown"
    if "maintenance" in text or "bakim" in text or "bakimci" in text:
        return "Maintenance"
    return str(value).strip() if str(value).strip() else "Unknown"


def normalize_region(value: Any) -> str:
    text = clean_text(value)
    if text in {"asia", "asya", "asian", "anadolu"}:
        return "Asia"
    if text in {"europe", "avrupa", "eu"}:
        return "Europe"
    return "Unknown"


def normalize_failure_type(value: Any) -> str:
    text = clean_text(value).upper()
    if text in {"AA", "A", "B", "C", "D"}:
        return text
    if "INSAN" in text or "PERSON" in text or "KAL" in text:
        return "AA"
    if text in {"NORMAL", "OTHER", "DIGER", "OTHER_FAILURE"}:
        return "NORMAL"
    return str(value).strip().upper() if str(value).strip() else "NORMAL"


def region_from_location(location: Any) -> str:
    text = clean_text(location)
    for district in ASIA_DISTRICTS:
        if re.search(rf"\b{re.escape(district)}\b", text):
            return "Asia"
    for district in EUROPE_DISTRICTS:
        if re.search(rf"\b{re.escape(district)}\b", text):
            return "Europe"
    return "Unknown"


def deterministic_region(value: Any, index: int) -> str:
    """Fallback only for Excel demo files that do not contain region data."""
    text = str(value) if value is not None else str(index)
    digest = hashlib.md5(text.encode("utf-8")).hexdigest()
    return "Asia" if int(digest, 16) % 2 == 0 else "Europe"


def normalize_package(value: Any) -> str:
    text = str(value).upper().strip().replace(" ", "")
    if not text:
        return DEFAULT_MAINTENANCE_PACKAGE
    parts = []
    for p in re.split(r"[+/,;|-]", text):
        p = p.strip()
        if p in MAINTENANCE_TIME_MAP:
            parts.append(p)
    if not parts and text in MAINTENANCE_TIME_MAP:
        parts = [text]
    return "+".join(sorted(set(parts))) if parts else DEFAULT_MAINTENANCE_PACKAGE


def package_service_time(package: str, rule: str = "sum") -> float:
    parts = [p for p in normalize_package(package).split("+") if p]
    durations = [MAINTENANCE_TIME_MAP[p] for p in parts if p in MAINTENANCE_TIME_MAP]
    if not durations:
        return MAINTENANCE_TIME_MAP[DEFAULT_MAINTENANCE_PACKAGE]
    if rule == "max":
        return max(durations)
    return sum(durations)


def parse_date(value: Any) -> Optional[pd.Timestamp]:
    if value is None or str(value).strip() == "":
        return None
    try:
        dt = pd.to_datetime(value, errors="coerce")
    except Exception:
        return None
    if pd.isna(dt):
        return None
    return dt


def parse_time_string(value: Any, default: time) -> time:
    if value is None or str(value).strip() == "":
        return default
    try:
        return pd.to_datetime(str(value)).time()
    except Exception:
        return default


# =====================================================
# BACKEND-READY INPUT NORMALIZATION
# =====================================================


def technicians_to_dataframe(records: Iterable[Mapping[str, Any]], config: SolverConfig) -> pd.DataFrame:
    raw = pd.DataFrame(list(records))
    if raw.empty:
        return pd.DataFrame(columns=[
            "technician_id", "technician_name", "role", "skill_type", "region", "available_hours",
            "shift_start", "shift_end", "latitude", "longitude", "current_latitude", "current_longitude",
        ])

    id_col = find_col(raw, ["technician_id", "Technician ID", "id", "pk"])
    first_name_col = find_col(raw, ["Ad", "first_name", "name", "Name"])
    last_name_col = find_col(raw, ["Soyad", "last_name", "surname"])
    role_col = find_col(raw, ["role", "Görev Türü", "Gorev Turu", "task_role"])
    skill_col = find_col(raw, ["skill_type", "Uzmanlık", "Uzmanlik", "skill", "expertise"])
    region_col = find_col(raw, ["region", "Bölge", "Bolge"])
    hours_col = find_col(raw, ["available_hours", "daily_capacity_hours", "capacity_hours", "hours"])
    shift_start_col = find_col(raw, ["shift_start", "start_time"])
    shift_end_col = find_col(raw, ["shift_end", "end_time"])
    lat_col = find_col(raw, ["latitude", "start_latitude", "lat"])
    lon_col = find_col(raw, ["longitude", "start_longitude", "lon", "lng"])
    current_lat_col = find_col(raw, ["current_latitude", "current_lat", "last_latitude"])
    current_lon_col = find_col(raw, ["current_longitude", "current_lon", "current_lng", "last_longitude"])

    if id_col is None or role_col is None or skill_col is None:
        raise ValueError("Technician data must include technician_id, role and skill_type fields.")

    out = pd.DataFrame()
    out["technician_id"] = raw[id_col].astype(str).str.strip()

    if first_name_col is not None:
        out["technician_name"] = raw[first_name_col].fillna("").astype(str).str.strip()
    else:
        out["technician_name"] = out["technician_id"]
    if last_name_col is not None and last_name_col != first_name_col:
        out["technician_name"] = (out["technician_name"] + " " + raw[last_name_col].fillna("").astype(str).str.strip()).str.strip()

    out["role"] = raw[role_col].apply(normalize_role)
    out["skill_type"] = raw[skill_col].apply(normalize_skill)

    if region_col is not None:
        out["region"] = raw[region_col].apply(normalize_region)
    else:
        # Fallback for demo Excel only: alternate regions so both maintenance and breakdown techs are distributed.
        out["region"] = ["Asia" if i % 2 == 0 else "Europe" for i in range(len(out))]

    if hours_col is not None:
        out["available_hours"] = pd.to_numeric(raw[hours_col], errors="coerce").fillna(config.available_hours_default)
    else:
        out["available_hours"] = config.available_hours_default

    out["shift_start"] = raw[shift_start_col].apply(lambda x: str(x) if str(x) != "nan" else SHIFT_START_DEFAULT) if shift_start_col else SHIFT_START_DEFAULT
    out["shift_end"] = raw[shift_end_col].apply(lambda x: str(x) if str(x) != "nan" else SHIFT_END_DEFAULT) if shift_end_col else SHIFT_END_DEFAULT

    out["latitude"] = pd.to_numeric(raw[lat_col], errors="coerce") if lat_col else None
    out["longitude"] = pd.to_numeric(raw[lon_col], errors="coerce") if lon_col else None
    out["current_latitude"] = pd.to_numeric(raw[current_lat_col], errors="coerce") if current_lat_col else out["latitude"]
    out["current_longitude"] = pd.to_numeric(raw[current_lon_col], errors="coerce") if current_lon_col else out["longitude"]

    out = out.dropna(subset=["technician_id"]).drop_duplicates("technician_id").reset_index(drop=True)
    return out


def units_to_dataframe(records: Iterable[Mapping[str, Any]]) -> pd.DataFrame:
    raw = pd.DataFrame(list(records))
    if raw.empty:
        return pd.DataFrame(columns=[
            "unit_id", "unit_name", "unit_type", "region", "location", "company", "latitude", "longitude",
            "last_A_maintenance_date", "last_B_maintenance_date", "last_C_maintenance_date",
        ])

    unit_id_col = find_col(raw, ["unit_id", "Unit Number", "unit_number", "id", "pk"])
    unit_name_col = find_col(raw, ["unit_name", "Unit Name", "name"])
    location_col = find_col(raw, ["unit_location", "Unit Location", "location", "address"])
    unit_type_col = find_col(raw, ["unit_type", "Unit Type", "type"])
    company_col = find_col(raw, ["unit_company", "Unit Company", "company"])
    region_col = find_col(raw, ["region", "Bölge", "Bolge"])
    lat_col = find_col(raw, ["latitude", "lat"])
    lon_col = find_col(raw, ["longitude", "lon", "lng"])
    last_a_col = find_col(raw, ["last_A_maintenance_date", "last_a_date", "last_a", "son_a_bakim"])
    last_b_col = find_col(raw, ["last_B_maintenance_date", "last_b_date", "last_b", "son_b_bakim"])
    last_c_col = find_col(raw, ["last_C_maintenance_date", "last_c_date", "last_c", "son_c_bakim"])

    if unit_id_col is None or unit_type_col is None:
        raise ValueError("Unit data must include unit_id/unit_number and unit_type fields.")

    out = pd.DataFrame()
    out["unit_id"] = raw[unit_id_col].astype(str).str.strip()
    out["unit_name"] = raw[unit_name_col].fillna("").astype(str).str.strip() if unit_name_col else out["unit_id"]
    out["location"] = raw[location_col].fillna("").astype(str).str.strip() if location_col else ""
    out["unit_type"] = raw[unit_type_col].apply(normalize_skill)
    out["company"] = raw[company_col].fillna("").astype(str).str.strip() if company_col else ""

    if region_col is not None:
        out["region"] = raw[region_col].apply(normalize_region)
    else:
        detected_region = out["location"].apply(region_from_location)
        out["region"] = [
            detected_region.iloc[i] if detected_region.iloc[i] != "Unknown" else deterministic_region(out.loc[i, "unit_id"], i)
            for i in range(len(out))
        ]

    out["latitude"] = pd.to_numeric(raw[lat_col], errors="coerce") if lat_col else None
    out["longitude"] = pd.to_numeric(raw[lon_col], errors="coerce") if lon_col else None
    out["last_A_maintenance_date"] = raw[last_a_col].apply(parse_date) if last_a_col else None
    out["last_B_maintenance_date"] = raw[last_b_col].apply(parse_date) if last_b_col else None
    out["last_C_maintenance_date"] = raw[last_c_col].apply(parse_date) if last_c_col else None

    out = out.dropna(subset=["unit_id"]).drop_duplicates("unit_id").reset_index(drop=True)
    return out


def task_records_to_dataframe(records: Iterable[Mapping[str, Any]], config: SolverConfig) -> pd.DataFrame:
    raw = pd.DataFrame(list(records))
    if raw.empty:
        return pd.DataFrame(columns=[
            "task_id", "unit_id", "unit_name", "task_type", "unit_type", "region", "maintenance_package",
            "service_time", "required_technicians", "planned_date",
        ])

    task_id_col = find_col(raw, ["task_id", "id", "pk"])
    unit_id_col = find_col(raw, ["unit_id", "Unit Number", "unit_number"])
    unit_name_col = find_col(raw, ["unit_name", "Unit Name", "name"])
    task_type_col = find_col(raw, ["task_type", "Task Type", "Görev Türü", "Gorev Turu"])
    unit_type_col = find_col(raw, ["unit_type", "Unit Type", "type"])
    region_col = find_col(raw, ["region", "Bölge", "Bolge"])
    package_col = find_col(raw, ["maintenance_package", "maintenance_type", "Maintenance Type", "Bakım Tipi", "Bakim Tipi"])
    service_col = find_col(raw, ["service_time", "Service Time", "duration", "Süre", "Sure"])
    required_col = find_col(raw, ["required_technicians", "Required Technicians", "required"])
    planned_date_col = find_col(raw, ["planned_date", "date", "due_date"])

    if unit_id_col is None or unit_type_col is None:
        raise ValueError("Task data must include unit_id and unit_type fields.")

    out = pd.DataFrame()
    out["unit_id"] = raw[unit_id_col].astype(str).str.strip()
    out["task_id"] = raw[task_id_col].astype(str).str.strip() if task_id_col else "M-" + out["unit_id"].astype(str)
    out["unit_name"] = raw[unit_name_col].fillna("").astype(str).str.strip() if unit_name_col else out["unit_id"]
    out["task_type"] = raw[task_type_col].apply(normalize_role) if task_type_col else "Maintenance"
    out["unit_type"] = raw[unit_type_col].apply(normalize_skill)
    out["region"] = raw[region_col].apply(normalize_region) if region_col else "Unknown"
    out["maintenance_package"] = raw[package_col].apply(normalize_package) if package_col else DEFAULT_MAINTENANCE_PACKAGE

    if service_col:
        out["service_time"] = pd.to_numeric(raw[service_col], errors="coerce")
    else:
        out["service_time"] = out["maintenance_package"].apply(lambda p: package_service_time(p, config.maintenance_combine_rule))
    out["service_time"] = out["service_time"].fillna(out["maintenance_package"].apply(lambda p: package_service_time(p, config.maintenance_combine_rule)))

    out["required_technicians"] = pd.to_numeric(raw[required_col], errors="coerce").fillna(1).astype(int) if required_col else 1
    out["planned_date"] = raw[planned_date_col].apply(parse_date) if planned_date_col else None

    if out["task_id"].duplicated().any():
        out["task_id"] = out["task_id"].astype(str) + "_" + out.index.astype(str)
    return out.reset_index(drop=True)


# =====================================================
# MAINTENANCE TASK GENERATION
# =====================================================


def generate_maintenance_tasks_from_units(
    units: Iterable[Mapping[str, Any]] | pd.DataFrame,
    plan_start: Optional[str | datetime] = None,
    plan_end: Optional[str | datetime] = None,
    config: SolverConfig = SolverConfig(),
    fallback_package: str = DEFAULT_MAINTENANCE_PACKAGE,
    demo_due_pattern: bool = False,
) -> List[Dict[str, Any]]:
    """
    Creates maintenance visit tasks from unit records.

    v5 annual logic:
    - Every unit has 15 maintenance operations per year:
        A: 1/year
        B: 2/year
        C: 12/year
    - However, if A/B/C fall in the same month, they are done in one visit.
    - Therefore, every unit creates 12 visit tasks per year:
        10 x C
        1 x B+C
        1 x A+B+C
    - Operation count for 5000 units is still 75,000/year:
        5000 A + 10000 B + 60000 C.
      The optimization assigns visit packages, not separate duplicate trips.

    Backend usage:
    - Prefer creating Task objects in Django and pass them directly to solve_maintenance_from_records.
    - Use this helper only if backend wants Python to generate annual due maintenance tasks from Unit records.

    demo_due_pattern remains as a small legacy fallback for local demos, but the normal v5 behavior is annual.
    """
    if isinstance(units, pd.DataFrame):
        units_df = units.copy()
    else:
        units_df = units_to_dataframe(units)

    start = parse_date(plan_start) or pd.Timestamp(datetime.today().date().replace(month=1, day=1))

    rows: List[Dict[str, Any]] = []

    # Legacy/small demo mode, kept only for quick tests.
    if demo_due_pattern:
        for i, unit in units_df.iterrows():
            if i % 12 == 0:
                package = "A+B+C"
            elif i % 6 == 0:
                package = "B+C"
            else:
                package = fallback_package
            task_id = f"M-{unit['unit_id']}-{package}"
            rows.append({
                "task_id": task_id,
                "unit_id": unit["unit_id"],
                "unit_name": unit.get("unit_name", unit["unit_id"]),
                "task_type": "Maintenance",
                "unit_type": unit.get("unit_type", "Unknown"),
                "region": unit.get("region", "Unknown"),
                "maintenance_package": package,
                "service_time": package_service_time(package, config.maintenance_combine_rule),
                "required_technicians": 1,
                "planned_date": str(start.date()),
                "planned_month": 1,
                "operation_count_A": 1 if "A" in package.split("+") else 0,
                "operation_count_B": 1 if "B" in package.split("+") else 0,
                "operation_count_C": 1 if "C" in package.split("+") else 0,
                "location": unit.get("location", ""),
                "latitude": unit.get("latitude", None),
                "longitude": unit.get("longitude", None),
                "morning_required": "YES" if unit.get("unit_type") == "Escalator" else "NO",
            })
        return rows

    # Annual package pattern. C is monthly. B is in months 6 and 12. A is in month 12.
    # Month 12 becomes A+B+C, month 6 becomes B+C, other months become C.
    for _, unit in units_df.iterrows():
        for month_no in range(1, 13):
            due = ["C"]
            if month_no in {6, 12}:
                due.append("B")
            if month_no == 12:
                due.append("A")

            package = "+".join(sorted(set(due)))
            planned_date = start + pd.DateOffset(months=month_no - 1)
            task_id = f"M-{unit['unit_id']}-Y{planned_date.year}-M{month_no:02d}-{package}"
            parts = set(package.split("+"))

            rows.append({
                "task_id": task_id,
                "unit_id": unit["unit_id"],
                "unit_name": unit.get("unit_name", unit["unit_id"]),
                "task_type": "Maintenance",
                "unit_type": unit.get("unit_type", "Unknown"),
                "region": unit.get("region", "Unknown"),
                "maintenance_package": package,
                "service_time": package_service_time(package, config.maintenance_combine_rule),
                "required_technicians": 1,
                "planned_date": str(planned_date.date()),
                "planned_month": month_no,
                "operation_count_A": 1 if "A" in parts else 0,
                "operation_count_B": 1 if "B" in parts else 0,
                "operation_count_C": 1 if "C" in parts else 0,
                "location": unit.get("location", ""),
                "latitude": unit.get("latitude", None),
                "longitude": unit.get("longitude", None),
                "morning_required": "YES" if unit.get("unit_type") == "Escalator" else "NO",
            })

    return rows


# =====================================================
# FEASIBILITY / TRAVEL
# =====================================================


def skills_match(tech_skill: str, unit_type: str) -> bool:
    return tech_skill == "Both" or tech_skill == unit_type or unit_type == "Unknown"


def regions_match(tech_region: str, task_region: str, config: SolverConfig) -> bool:
    if config.allow_unknown_region_match and (tech_region == "Unknown" or task_region == "Unknown"):
        return True
    return tech_region == task_region


def lookup_travel_time(
    travel_time_matrix: Optional[Mapping[Any, float]],
    technician_id: str,
    target_id: str,
    default: float,
) -> float:
    if not travel_time_matrix:
        return default
    keys = [
        (technician_id, target_id),
        f"{technician_id}|{target_id}",
        f"{technician_id},{target_id}",
    ]
    for key in keys:
        if key in travel_time_matrix:
            try:
                return float(travel_time_matrix[key])
            except Exception:
                return default
    nested = travel_time_matrix.get(technician_id) if isinstance(travel_time_matrix, dict) else None
    if isinstance(nested, dict) and target_id in nested:
        try:
            return float(nested[target_id])
        except Exception:
            return default
    return default


# =====================================================
# CORE SOLVER: MAINTENANCE
# =====================================================


def solve_maintenance_from_records(
    technician_records: Iterable[Mapping[str, Any]],
    task_records: Iterable[Mapping[str, Any]],
    travel_time_matrix: Optional[Mapping[Any, float]] = None,
    config: SolverConfig = SolverConfig(),
) -> Dict[str, Any]:
    """
    Backend-ready maintenance solver.

    Input:
        technician_records: Django Technician queryset converted to list(dict)
        task_records: Django Task queryset converted to list(dict), preferably already due maintenance tasks
        travel_time_matrix: optional Google Maps precomputed travel time in HOURS

    Output:
        dict with assignments, technician_summary, unassigned_tasks, meta

    Important:
        This function does not print and does not write files.
    """
    try:
        import gurobipy as gp
        from gurobipy import GRB
    except ModuleNotFoundError as exc:
        raise RuntimeError("gurobipy is not installed in this Python environment.") from exc

    technicians = technicians_to_dataframe(technician_records, config)
    tasks = task_records_to_dataframe(task_records, config)

    technicians = technicians[technicians["role"].isin(["Maintenance", "Both"])].copy()
    tasks = tasks[tasks["task_type"].isin(["Maintenance", "Both"])].copy()

    if technicians.empty:
        return {
            "assignments": [],
            "technician_summary": [],
            "unassigned_tasks": tasks.to_dict("records"),
            "meta": {"status": "NO_MAINTENANCE_TECHNICIANS", "message": "No maintenance technicians found."},
        }

    T = technicians["technician_id"].astype(str).tolist()
    K = tasks["task_id"].astype(str).tolist()

    tech_info = technicians.set_index("technician_id")
    task_info = tasks.set_index("task_id")

    feasible_pairs: List[Tuple[str, str]] = []
    travel_time: Dict[Tuple[str, str], float] = {}

    for t in T:
        for k in K:
            if not regions_match(str(tech_info.loc[t, "region"]), str(task_info.loc[k, "region"]), config):
                continue
            if not skills_match(str(tech_info.loc[t, "skill_type"]), str(task_info.loc[k, "unit_type"])):
                continue
            feasible_pairs.append((t, k))
            travel_time[(t, k)] = lookup_travel_time(travel_time_matrix, t, k, config.default_travel_time_hours)

    feasible_by_task: Dict[str, List[str]] = {k: [] for k in K}
    feasible_by_tech: Dict[str, List[str]] = {t: [] for t in T}
    for t, k in feasible_pairs:
        feasible_by_task[k].append(t)
        feasible_by_tech[t].append(k)

    service_time = task_info["service_time"].astype(float).to_dict()
    required = task_info["required_technicians"].astype(int).to_dict()
    available_hours = tech_info["available_hours"].astype(float).to_dict()

    model = gp.Model("maintenance_planning")
    model.Params.OutputFlag = 0
    model.Params.TimeLimit = config.time_limit_seconds
    model.Params.MIPGap = config.mip_gap

    x = model.addVars(feasible_pairs, vtype=GRB.BINARY, name="assign")
    overtime = model.addVars(T, lb=0, ub=config.max_maintenance_overtime_hours, vtype=GRB.CONTINUOUS, name="overtime")
    miss = model.addVars(K, lb=0, vtype=GRB.CONTINUOUS, name="miss")

    for k in K:
        assigned = gp.quicksum(x[t, k] for t in feasible_by_task[k])
        model.addConstr(assigned + miss[k] == required[k], name=f"coverage_{k}")
        model.addConstr(assigned <= 2, name=f"max_two_techs_{k}")

    for t in T:
        total_time = gp.quicksum((service_time[k] + travel_time[(t, k)]) * x[t, k] for k in feasible_by_tech[t])
        model.addConstr(total_time <= available_hours[t] + overtime[t], name=f"capacity_{t}")

    objective = (
        gp.quicksum(LABOR_COST_PER_HOUR * service_time[k] * x[t, k] for t, k in feasible_pairs)
        + gp.quicksum(TRAVEL_TIME_COST_PER_HOUR * travel_time[(t, k)] * x[t, k] for t, k in feasible_pairs)
        + gp.quicksum(OVERTIME_PENALTY * overtime[t] for t in T)
        + gp.quicksum(MAINTENANCE_MISSED_PENALTY * miss[k] for k in K)
    )
    model.setObjective(objective, GRB.MINIMIZE)
    model.optimize()

    if model.status not in {GRB.OPTIMAL, GRB.SUBOPTIMAL, GRB.TIME_LIMIT}:
        return {
            "assignments": [],
            "technician_summary": [],
            "unassigned_tasks": tasks.to_dict("records"),
            "meta": {"status": f"GUROBI_STATUS_{model.status}", "message": "Maintenance model did not return a usable solution."},
        }

    assignments: List[Dict[str, Any]] = []
    for t, k in feasible_pairs:
        if x[t, k].X > 0.5:
            row = task_info.loc[k]
            tech = tech_info.loc[t]
            assignments.append({
                "technician_id": t,
                "technician_name": tech.get("technician_name", t),
                "task_id": k,
                "unit_id": row.get("unit_id"),
                "unit_name": row.get("unit_name"),
                "task_type": "Maintenance",
                "maintenance_package": row.get("maintenance_package", DEFAULT_MAINTENANCE_PACKAGE),
                "unit_type": row.get("unit_type"),
                "region": row.get("region"),
                "service_time": float(row.get("service_time", 0)),
                "travel_time": float(travel_time[(t, k)]),
                "total_time": float(row.get("service_time", 0)) + float(travel_time[(t, k)]),
                "route_order": None,
                "estimated_start_time": None,
                "estimated_end_time": None,
                "time_window_warning": "NO",
                "status": "assigned",
            })

    # Post-process: create a simple sequential route order per technician.
    # This is not a full routing MIP yet; Google Maps route sequencing can replace this later.
    assignments, daily_summary = add_work_days_and_times(assignments, technicians, config)

    assigned_by_tech: Dict[str, List[Dict[str, Any]]] = {t: [] for t in T}
    for row in assignments:
        assigned_by_tech[row["technician_id"]].append(row)

    technician_summary: List[Dict[str, Any]] = []
    for t in T:
        rows = assigned_by_tech[t]
        service_sum = sum(float(r["service_time"]) for r in rows)
        travel_sum = sum(float(r["travel_time"]) for r in rows)
        total_sum = service_sum + travel_sum
        idle = max(0.0, available_hours[t] - total_sum)
        technician_summary.append({
            "technician_id": t,
            "technician_name": tech_info.loc[t].get("technician_name", t),
            "role": tech_info.loc[t].get("role"),
            "skill_type": tech_info.loc[t].get("skill_type"),
            "region": tech_info.loc[t].get("region"),
            "assigned_task_count": len(rows),
            "total_service_time": round(service_sum, 4),
            "total_travel_time": round(travel_sum, 4),
            "total_work_time": round(total_sum, 4),
            "available_hours": float(available_hours[t]),
            "overtime": round(float(overtime[t].X), 4),
            "idle_time": round(idle, 4),
            "idle_warning": "YES" if rows and idle > IDLE_WARNING_HOURS else "NO",
        })

    unassigned_tasks: List[Dict[str, Any]] = []
    for k in K:
        if miss[k].X > 1e-6:
            row = task_info.loc[k]
            reason = "No feasible maintenance technician or insufficient maintenance capacity"
            if not feasible_by_task[k]:
                reason = "No feasible maintenance technician due to role/skill/region mismatch"
            unassigned_tasks.append({
                "task_id": k,
                "unit_id": row.get("unit_id"),
                "unit_name": row.get("unit_name"),
                "task_type": "Maintenance",
                "maintenance_package": row.get("maintenance_package"),
                "unit_type": row.get("unit_type"),
                "region": row.get("region"),
                "service_time": float(row.get("service_time", 0)),
                "unmet_technician_requirement": round(float(miss[k].X), 4),
                "reason": reason,
            })

    return {
        "assignments": assignments,
        "technician_summary": technician_summary,
        "daily_summary": daily_summary,
        "unassigned_tasks": unassigned_tasks,
        "meta": {
            "status": "OK",
            "mode": "maintenance",
            "gurobi_status": int(model.status),
            "objective_value": float(model.ObjVal) if model.SolCount > 0 else None,
            "technicians_used": len([r for r in technician_summary if r["assigned_task_count"] > 0]),
            "total_assignments": len(assignments),
            "unassigned_count": len(unassigned_tasks),
            "feasible_pairs": len(feasible_pairs),
        },
    }


# =====================================================
# CORE SOLVER: BREAKDOWN
# =====================================================


def breakdown_tickets_to_dataframe(
    ticket_records: Iterable[Mapping[str, Any]],
    unit_records: Optional[Iterable[Mapping[str, Any]]] = None,
) -> pd.DataFrame:
    raw = pd.DataFrame(list(ticket_records))
    if raw.empty:
        return pd.DataFrame(columns=[
            "ticket_id", "unit_id", "unit_name", "task_type", "unit_type", "region", "failure_type",
            "created_at", "response_limit_hours", "service_time", "status",
        ])

    ticket_id_col = find_col(raw, ["ticket_id", "id", "pk"])
    unit_id_col = find_col(raw, ["unit_id", "Unit Number", "unit_number"])
    unit_type_col = find_col(raw, ["unit_type", "Unit Type", "type"])
    region_col = find_col(raw, ["region", "Bölge", "Bolge"])
    failure_col = find_col(raw, ["failure_type", "Failure Type", "Arıza Tipi", "Ariza Tipi"])
    created_col = find_col(raw, ["created_at", "created_time", "reported_at", "date"])
    response_col = find_col(raw, ["response_limit_hours", "response_limit", "sla_hours"])
    service_col = find_col(raw, ["service_time", "duration", "repair_time"])
    status_col = find_col(raw, ["status"])

    if ticket_id_col is None or unit_id_col is None:
        raise ValueError("Breakdown ticket data must include ticket_id and unit_id.")

    out = pd.DataFrame()
    out["ticket_id"] = raw[ticket_id_col].astype(str).str.strip()
    out["unit_id"] = raw[unit_id_col].astype(str).str.strip()
    out["failure_type"] = raw[failure_col].apply(normalize_failure_type) if failure_col else "NORMAL"
    out["created_at"] = raw[created_col].apply(parse_date) if created_col else pd.Timestamp.now()
    out["status"] = raw[status_col].fillna("open").astype(str).str.lower().str.strip() if status_col else "open"
    out["task_type"] = "Breakdown"

    if response_col:
        out["response_limit_hours"] = pd.to_numeric(raw[response_col], errors="coerce")
    else:
        out["response_limit_hours"] = out["failure_type"].apply(lambda f: 1.0 if f == "AA" else 4.0)
    out["response_limit_hours"] = out["response_limit_hours"].fillna(out["failure_type"].apply(lambda f: 1.0 if f == "AA" else 4.0))

    out["service_time"] = pd.to_numeric(raw[service_col], errors="coerce").fillna(DEFAULT_BREAKDOWN_SERVICE_TIME) if service_col else DEFAULT_BREAKDOWN_SERVICE_TIME

    units_df = units_to_dataframe(unit_records or [])
    if not units_df.empty:
        out = out.merge(units_df[["unit_id", "unit_name", "unit_type", "region", "location", "latitude", "longitude"]], on="unit_id", how="left")
    else:
        out["unit_name"] = out["unit_id"]
        out["unit_type"] = raw[unit_type_col].apply(normalize_skill) if unit_type_col else "Unknown"
        out["region"] = raw[region_col].apply(normalize_region) if region_col else "Unknown"
        out["location"] = ""
        out["latitude"] = None
        out["longitude"] = None

    # If ticket has its own unit_type/region, prefer that over missing joined values.
    if unit_type_col:
        ticket_unit_type = raw[unit_type_col].apply(normalize_skill)
        out["unit_type"] = out["unit_type"].fillna(ticket_unit_type)
    if region_col:
        ticket_region = raw[region_col].apply(normalize_region)
        out["region"] = out["region"].fillna(ticket_region)

    out["unit_type"] = out["unit_type"].fillna("Unknown")
    out["region"] = out["region"].fillna("Unknown")
    return out[out["status"].isin(["open", "pending", "new"])].reset_index(drop=True)


def solve_breakdown_from_records(
    technician_records: Iterable[Mapping[str, Any]],
    ticket_records: Iterable[Mapping[str, Any]],
    unit_records: Optional[Iterable[Mapping[str, Any]]] = None,
    travel_time_matrix: Optional[Mapping[Any, float]] = None,
    config: SolverConfig = SolverConfig(),
) -> Dict[str, Any]:
    """
    Backend-ready breakdown dispatch solver.

    This solver only uses Breakdown technicians. It does not change maintenance schedules.
    AA tickets have 1-hour response limit. Other tickets have 4-hour limit unless provided otherwise.

    Output rows can be written by backend to Schedule/BreakdownAssignment table.
    """
    try:
        import gurobipy as gp
        from gurobipy import GRB
    except ModuleNotFoundError as exc:
        raise RuntimeError("gurobipy is not installed in this Python environment.") from exc

    technicians = technicians_to_dataframe(technician_records, config)
    tickets = breakdown_tickets_to_dataframe(ticket_records, unit_records)

    technicians = technicians[technicians["role"].isin(["Breakdown", "Both"])].copy()

    if tickets.empty:
        return {
            "assignments": [],
            "technician_summary": [],
            "unassigned_tasks": [],
            "meta": {"status": "NO_OPEN_BREAKDOWNS", "message": "No open breakdown tickets found."},
        }
    if technicians.empty:
        return {
            "assignments": [],
            "technician_summary": [],
            "daily_summary": [],
            "unassigned_tasks": tickets.to_dict("records"),
            "meta": {"status": "NO_BREAKDOWN_TECHNICIANS", "message": "No breakdown technicians found."},
        }

    T = technicians["technician_id"].astype(str).tolist()
    B = tickets["ticket_id"].astype(str).tolist()

    tech_info = technicians.set_index("technician_id")
    ticket_info = tickets.set_index("ticket_id")

    feasible_pairs: List[Tuple[str, str]] = []
    travel_time: Dict[Tuple[str, str], float] = {}
    sla_violation_candidate: Dict[Tuple[str, str], int] = {}

    for t in T:
        for b in B:
            if not regions_match(str(tech_info.loc[t, "region"]), str(ticket_info.loc[b, "region"]), config):
                continue
            if not skills_match(str(tech_info.loc[t, "skill_type"]), str(ticket_info.loc[b, "unit_type"])):
                continue
            tt = lookup_travel_time(travel_time_matrix, t, b, config.default_travel_time_hours)
            feasible_pairs.append((t, b))
            travel_time[(t, b)] = tt
            sla_violation_candidate[(t, b)] = 1 if tt > float(ticket_info.loc[b, "response_limit_hours"]) else 0

    feasible_by_ticket: Dict[str, List[str]] = {b: [] for b in B}
    feasible_by_tech: Dict[str, List[str]] = {t: [] for t in T}
    for t, b in feasible_pairs:
        feasible_by_ticket[b].append(t)
        feasible_by_tech[t].append(b)

    service_time = ticket_info["service_time"].astype(float).to_dict()

    # Breakdown dispatch is handled as an instant/daily problem.
    # Do not use the 20-day/monthly capacity here; cap each breakdown technician at one daily shift.
    available_hours = {
        str(t): min(float(v), REGULAR_DAILY_HOURS)
        for t, v in tech_info["available_hours"].astype(float).to_dict().items()
    }

    # Prevent the model from dumping all breakdown tickets on the first feasible technician.
    # If not set manually, distribute tickets as evenly as possible across breakdown technicians.
    max_tickets_per_tech = config.max_breakdown_tickets_per_tech
    if max_tickets_per_tech is None:
        max_tickets_per_tech = max(1, math.ceil(len(B) / max(1, len(T))))

    model = gp.Model("breakdown_dispatch")
    model.Params.OutputFlag = 0
    model.Params.TimeLimit = config.time_limit_seconds
    model.Params.MIPGap = config.mip_gap

    x = model.addVars(feasible_pairs, vtype=GRB.BINARY, name="assign")
    overtime = model.addVars(T, lb=0, ub=config.max_maintenance_overtime_hours, vtype=GRB.CONTINUOUS, name="overtime")
    miss = model.addVars(B, lb=0, vtype=GRB.BINARY, name="miss")

    for b in B:
        assigned = gp.quicksum(x[t, b] for t in feasible_by_ticket[b])
        model.addConstr(assigned + miss[b] == 1, name=f"coverage_{b}")

    for t in T:
        total_time = gp.quicksum((service_time[b] + travel_time[(t, b)]) * x[t, b] for b in feasible_by_tech[t])
        assigned_count = gp.quicksum(x[t, b] for b in feasible_by_tech[t])
        model.addConstr(total_time <= available_hours[t] + overtime[t], name=f"capacity_{t}")
        model.addConstr(assigned_count <= max_tickets_per_tech, name=f"max_breakdown_tickets_{t}")

    missed_cost = gp.quicksum(
        (AA_BREAKDOWN_MISSED_PENALTY if str(ticket_info.loc[b, "failure_type"]) == "AA" else BREAKDOWN_MISSED_PENALTY) * miss[b]
        for b in B
    )
    sla_cost = gp.quicksum(SLA_VIOLATION_PENALTY * sla_violation_candidate[(t, b)] * x[t, b] for t, b in feasible_pairs)
    objective = (
        gp.quicksum(LABOR_COST_PER_HOUR * service_time[b] * x[t, b] for t, b in feasible_pairs)
        + gp.quicksum(TRAVEL_TIME_COST_PER_HOUR * travel_time[(t, b)] * x[t, b] for t, b in feasible_pairs)
        + gp.quicksum(OVERTIME_PENALTY * overtime[t] for t in T)
        + missed_cost
        + sla_cost
    )
    model.setObjective(objective, GRB.MINIMIZE)
    model.optimize()

    if model.status not in {GRB.OPTIMAL, GRB.SUBOPTIMAL, GRB.TIME_LIMIT}:
        return {
            "assignments": [],
            "technician_summary": [],
            "daily_summary": [],
            "unassigned_tasks": tickets.to_dict("records"),
            "meta": {"status": f"GUROBI_STATUS_{model.status}", "message": "Breakdown model did not return a usable solution."},
        }

    assignments: List[Dict[str, Any]] = []
    for t, b in feasible_pairs:
        if x[t, b].X > 0.5:
            ticket = ticket_info.loc[b]
            tech = tech_info.loc[t]
            limit = float(ticket.get("response_limit_hours", 4.0))
            tt = float(travel_time[(t, b)])
            assignments.append({
                "ticket_id": b,
                "unit_id": ticket.get("unit_id"),
                "unit_name": ticket.get("unit_name"),
                "technician_id": t,
                "technician_name": tech.get("technician_name", t),
                "task_type": "Breakdown",
                "failure_type": ticket.get("failure_type"),
                "unit_type": ticket.get("unit_type"),
                "region": ticket.get("region"),
                "service_time": float(ticket.get("service_time", DEFAULT_BREAKDOWN_SERVICE_TIME)),
                "estimated_travel_time": tt,
                "response_limit_hours": limit,
                "sla_status": "OK" if tt <= limit else "RISK",
                "assigned_at": datetime.now().isoformat(timespec="seconds"),
                "status": "assigned",
            })

    assigned_by_tech: Dict[str, List[Dict[str, Any]]] = {t: [] for t in T}
    for row in assignments:
        assigned_by_tech[row["technician_id"]].append(row)

    technician_summary: List[Dict[str, Any]] = []
    for t in T:
        rows = assigned_by_tech[t]
        service_sum = sum(float(r["service_time"]) for r in rows)
        travel_sum = sum(float(r["estimated_travel_time"]) for r in rows)
        total_sum = service_sum + travel_sum
        idle = max(0.0, available_hours[t] - total_sum)
        technician_summary.append({
            "technician_id": t,
            "technician_name": tech_info.loc[t].get("technician_name", t),
            "role": tech_info.loc[t].get("role"),
            "skill_type": tech_info.loc[t].get("skill_type"),
            "region": tech_info.loc[t].get("region"),
            "assigned_ticket_count": len(rows),
            "total_service_time": round(service_sum, 4),
            "total_travel_time": round(travel_sum, 4),
            "total_work_time": round(total_sum, 4),
            "available_hours": float(available_hours[t]),
            "overtime": round(float(overtime[t].X), 4),
            "idle_time": round(idle, 4),
            "idle_warning": "YES" if rows and idle > IDLE_WARNING_HOURS else "NO",
        })

    unassigned_tasks: List[Dict[str, Any]] = []
    for b in B:
        if miss[b].X > 0.5:
            ticket = ticket_info.loc[b]
            reason = "No available breakdown technician or insufficient breakdown capacity"
            if not feasible_by_ticket[b]:
                reason = "No feasible breakdown technician due to role/skill/region mismatch"
            unassigned_tasks.append({
                "ticket_id": b,
                "unit_id": ticket.get("unit_id"),
                "unit_name": ticket.get("unit_name"),
                "task_type": "Breakdown",
                "failure_type": ticket.get("failure_type"),
                "unit_type": ticket.get("unit_type"),
                "region": ticket.get("region"),
                "response_limit_hours": float(ticket.get("response_limit_hours", 4.0)),
                "reason": reason,
            })

    return {
        "assignments": assignments,
        "technician_summary": technician_summary,
        "daily_summary": [],
        "unassigned_tasks": unassigned_tasks,
        "meta": {
            "status": "OK",
            "mode": "breakdown",
            "gurobi_status": int(model.status),
            "objective_value": float(model.ObjVal) if model.SolCount > 0 else None,
            "total_assignments": len(assignments),
            "unassigned_count": len(unassigned_tasks),
            "sla_risk_count": len([r for r in assignments if r["sla_status"] == "RISK"]),
            "feasible_pairs": len(feasible_pairs),
        },
    }


# =====================================================
# ROUTE ORDER POST-PROCESSING
# =====================================================


def _time_to_minutes(value: Any, default: str) -> int:
    t = parse_time_string(value, pd.to_datetime(default).time())
    return t.hour * 60 + t.minute


def _minutes_to_hhmm(minutes: int) -> str:
    minutes = minutes % (24 * 60)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _place_task_in_day(
    current_min: int,
    travel_min: int,
    service_min: int,
    lunch_start_min: int,
    lunch_end_min: int,
) -> Tuple[int, int, int, bool]:
    """Return travel_start, service_start, service_end, lunch_inserted."""
    travel_start = current_min
    service_start = current_min + travel_min
    service_end = service_start + service_min
    lunch_inserted = False

    # If the task would overlap lunch, take lunch before starting the service.
    if service_start < lunch_end_min and service_end > lunch_start_min:
        travel_start = max(current_min, lunch_end_min)
        service_start = travel_start + travel_min
        service_end = service_start + service_min
        lunch_inserted = True

    return travel_start, service_start, service_end, lunch_inserted


def add_work_days_and_times(
    assignments: List[Dict[str, Any]],
    technicians_df: pd.DataFrame,
    config: SolverConfig,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Post-process monthly assignment into daily schedules.

    Important: This is a scheduling layer, not the final routing MIP.
    It prevents the misleading v2 output where one technician appears to work
    continuously after 17:00. Each technician now has separate work days,
    08:00-17:00 shift, 12:00-13:00 lunch, and 8 net working hours.
    """
    if not assignments:
        return assignments, []

    tech_shift = technicians_df.set_index("technician_id")[["shift_start", "shift_end"]].to_dict("index")
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in assignments:
        grouped.setdefault(row["technician_id"], []).append(row)

    final_rows: List[Dict[str, Any]] = []
    daily_summary: List[Dict[str, Any]] = []

    lunch_start_min = _time_to_minutes(config.lunch_start, LUNCH_START_DEFAULT)
    lunch_end_min = _time_to_minutes(config.lunch_end, LUNCH_END_DEFAULT)
    daily_capacity_min = int(round(REGULAR_DAILY_HOURS * 60))

    for tech_id, rows in grouped.items():
        rows_sorted = sorted(
            rows,
            key=lambda r: (
                0 if r.get("unit_type") == "Escalator" else 1,
                str(r.get("region", "")),
                str(r.get("unit_name", "")),
                -float(r.get("service_time", 0)),
            ),
        )
        shift_start_min = _time_to_minutes(tech_shift.get(tech_id, {}).get("shift_start"), SHIFT_START_DEFAULT)
        shift_end_min = _time_to_minutes(tech_shift.get(tech_id, {}).get("shift_end"), SHIFT_END_DEFAULT)

        day = 1
        route_order = 1
        current_min = shift_start_min
        used_work_min = 0
        day_rows: List[Dict[str, Any]] = []

        def close_day() -> None:
            nonlocal day_rows, used_work_min, day, route_order, current_min
            if not day_rows:
                return
            idle_hours = max(0.0, (daily_capacity_min - used_work_min) / 60.0)
            daily_summary.append({
                "technician_id": tech_id,
                "work_day": day,
                "assigned_task_count": len(day_rows),
                "used_work_hours": round(used_work_min / 60.0, 4),
                "idle_time": round(idle_hours, 4),
                "idle_warning": "YES" if idle_hours > IDLE_WARNING_HOURS else "NO",
                "day_start": _minutes_to_hhmm(shift_start_min),
                "day_end": _minutes_to_hhmm(shift_end_min),
            })
            day += 1
            route_order = 1
            current_min = shift_start_min
            used_work_min = 0
            day_rows = []

        for original in rows_sorted:
            travel_min = int(round(float(original.get("travel_time", 0) or 0) * 60))
            service_min = int(round(float(original.get("service_time", 0) or 0) * 60))
            task_work_min = travel_min + service_min

            if task_work_min > daily_capacity_min:
                row = dict(original)
                row.update({
                    "work_day": None,
                    "route_order": None,
                    "estimated_travel_start_time": None,
                    "estimated_start_time": None,
                    "estimated_end_time": None,
                    "lunch_break": "NO",
                    "time_window_warning": "YES",
                    "schedule_status": "unscheduled_task_longer_than_daily_capacity",
                })
                final_rows.append(row)
                continue

            # Move to next day if daily capacity would be exceeded.
            if day_rows and used_work_min + task_work_min > daily_capacity_min:
                close_day()

            if day > config.working_days:
                row = dict(original)
                row.update({
                    "work_day": None,
                    "route_order": None,
                    "estimated_travel_start_time": None,
                    "estimated_start_time": None,
                    "estimated_end_time": None,
                    "lunch_break": "NO",
                    "time_window_warning": "YES",
                    "schedule_status": "unscheduled_no_remaining_work_day",
                })
                final_rows.append(row)
                continue

            travel_start, service_start, service_end, lunch_inserted = _place_task_in_day(
                current_min=current_min,
                travel_min=travel_min,
                service_min=service_min,
                lunch_start_min=lunch_start_min,
                lunch_end_min=lunch_end_min,
            )

            # If shift end would be exceeded after lunch handling, try next day.
            if day_rows and service_end > shift_end_min:
                close_day()
                travel_start, service_start, service_end, lunch_inserted = _place_task_in_day(
                    current_min=current_min,
                    travel_min=travel_min,
                    service_min=service_min,
                    lunch_start_min=lunch_start_min,
                    lunch_end_min=lunch_end_min,
                )

            row = dict(original)
            row["work_day"] = day
            row["route_order"] = route_order
            row["estimated_travel_start_time"] = _minutes_to_hhmm(travel_start)
            row["estimated_start_time"] = _minutes_to_hhmm(service_start)
            row["estimated_end_time"] = _minutes_to_hhmm(service_end)
            row["lunch_break"] = "YES" if lunch_inserted else "NO"
            row["schedule_status"] = "scheduled"
            row["time_window_warning"] = "YES" if row.get("unit_type") == "Escalator" and service_start >= 10 * 60 else "NO"
            final_rows.append(row)
            day_rows.append(row)
            used_work_min += task_work_min
            current_min = service_end
            route_order += 1

        close_day()

    final_rows = sorted(final_rows, key=lambda r: (
        999 if r.get("work_day") is None else int(r.get("work_day")),
        str(r.get("technician_id", "")),
        999 if r.get("route_order") is None else int(r.get("route_order")),
    ))
    return final_rows, daily_summary

# =====================================================
# EXCEL ADAPTERS FOR LOCAL TESTING ONLY
# =====================================================


def read_excel_records(path: Path) -> List[Dict[str, Any]]:
    all_sheets = pd.read_excel(path, sheet_name=None)
    df = pd.concat(all_sheets.values(), ignore_index=True)
    return df.to_dict("records")


def export_result_to_excel(result: Dict[str, Any], output_file: Path) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        assignments_df = pd.DataFrame(result.get("assignments", []))
        if not assignments_df.empty and {"work_day", "technician_id", "route_order"}.issubset(assignments_df.columns):
            assignments_df = assignments_df.sort_values(["work_day", "technician_id", "route_order"], na_position="last")
        assignments_df.to_excel(writer, sheet_name="Assignments", index=False)
        pd.DataFrame(result.get("technician_summary", [])).to_excel(writer, sheet_name="Technician_Summary", index=False)
        pd.DataFrame(result.get("daily_summary", [])).to_excel(writer, sheet_name="Daily_Summary", index=False)
        pd.DataFrame(result.get("unassigned_tasks", [])).to_excel(writer, sheet_name="Unassigned_Tasks", index=False)
        meta_df = pd.DataFrame([result.get("meta", {})])
        meta_df.to_excel(writer, sheet_name="Meta", index=False)


def maintenance_precheck(technicians: pd.DataFrame, units: pd.DataFrame, tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
    tasks_df = pd.DataFrame(tasks)
    op_a = int(tasks_df.get("operation_count_A", pd.Series(dtype=int)).sum()) if not tasks_df.empty else 0
    op_b = int(tasks_df.get("operation_count_B", pd.Series(dtype=int)).sum()) if not tasks_df.empty else 0
    op_c = int(tasks_df.get("operation_count_C", pd.Series(dtype=int)).sum()) if not tasks_df.empty else 0
    total_service = round(float(tasks_df["service_time"].sum()), 4) if not tasks_df.empty else 0.0
    total_travel = round(float(len(tasks_df) * DEFAULT_TRAVEL_TIME_HOURS), 4) if not tasks_df.empty else 0.0
    capacity = round(float(technicians.loc[technicians["role"].isin(["Maintenance", "Both"]), "available_hours"].sum()), 4) if not technicians.empty else 0.0
    return {
        "technicians_total": len(technicians),
        "maintenance_technicians": int(technicians["role"].isin(["Maintenance", "Both"]).sum()),
        "breakdown_technicians": int(technicians["role"].isin(["Breakdown", "Both"]).sum()),
        "units_total": len(units),
        "maintenance_visit_tasks_generated": len(tasks),
        "maintenance_operations_generated_total": op_a + op_b + op_c,
        "maintenance_operations_A": op_a,
        "maintenance_operations_B": op_b,
        "maintenance_operations_C": op_c,
        "maintenance_package_counts": tasks_df["maintenance_package"].value_counts(dropna=False).to_dict() if not tasks_df.empty else {},
        "planned_month_counts": tasks_df["planned_month"].value_counts(dropna=False).sort_index().to_dict() if not tasks_df.empty and "planned_month" in tasks_df.columns else {},
        "technician_roles": technicians["role"].value_counts(dropna=False).to_dict() if not technicians.empty else {},
        "technician_skills": technicians["skill_type"].value_counts(dropna=False).to_dict() if not technicians.empty else {},
        "technician_regions": technicians["region"].value_counts(dropna=False).to_dict() if not technicians.empty else {},
        "unit_types": units["unit_type"].value_counts(dropna=False).to_dict() if not units.empty else {},
        "unit_regions": units["region"].value_counts(dropna=False).to_dict() if not units.empty else {},
        "total_service_hours": total_service,
        "default_travel_time_per_visit_task_hours": DEFAULT_TRAVEL_TIME_HOURS,
        "estimated_total_travel_hours": total_travel,
        "estimated_total_service_plus_default_travel_hours": round(total_service + total_travel, 4),
        "total_maintenance_capacity_hours": capacity,
        "capacity_gap_hours_before_travel": round(capacity - total_service, 4),
        "capacity_gap_hours_after_default_travel": round(capacity - total_service - total_travel, 4),
    }


def generate_demo_breakdown_tickets(
    unit_records: Iterable[Mapping[str, Any]],
    count: int = 50,
    aa_count: int = 5,
    seed: int = 42,
) -> List[Dict[str, Any]]:
    """
    Demo helper only. Backend should normally create tickets from user/admin input or call center integration.

    v4 behavior:
    - Chooses unique unit IDs.
    - Tries not to create two breakdowns in the same visible place/building name.
    - Balances demo tickets between Asia and Europe when possible.
    - Shuffles units before selecting, so demo tickets are not always from the first rows of the Excel.
    - Spreads normal failure types A/B/C/D instead of randomly repeating the same type too much.
    """
    units_df = units_to_dataframe(unit_records)
    if units_df.empty:
        return []

    rng = random.Random(seed)
    desired_count = min(count, len(units_df))

    shuffled = units_df.sample(frac=1, random_state=seed).reset_index(drop=True)

    # Region quotas: for 10 tickets, normally 5 Asia + 5 Europe if both sides have enough units.
    available_regions = [r for r in ["Asia", "Europe"] if (shuffled["region"] == r).any()]
    if len(available_regions) == 2:
        quotas = {"Asia": desired_count // 2 + desired_count % 2, "Europe": desired_count // 2}
    elif len(available_regions) == 1:
        quotas = {available_regions[0]: desired_count}
    else:
        quotas = {"Unknown": desired_count}

    selected_rows: List[Mapping[str, Any]] = []
    selected_unit_ids: set = set()
    selected_place_names: set = set()

    def try_add_rows(pool: pd.DataFrame, quota: int, avoid_same_place: bool = True) -> int:
        added = 0
        for _, row in pool.iterrows():
            if added >= quota:
                break
            unit_id = str(row.get("unit_id"))
            place_name = str(row.get("unit_name", "")).strip().lower()
            if unit_id in selected_unit_ids:
                continue
            if avoid_same_place and place_name and place_name in selected_place_names:
                continue
            selected_rows.append(row.to_dict())
            selected_unit_ids.add(unit_id)
            if place_name:
                selected_place_names.add(place_name)
            added += 1
        return added

    # First pass: satisfy each region quota while avoiding repeated place/building names.
    missing_total = 0
    for region, quota in quotas.items():
        if region == "Unknown":
            pool = shuffled
        else:
            pool = shuffled[shuffled["region"] == region]
        added = try_add_rows(pool, quota, avoid_same_place=True)
        missing_total += quota - added

    # Second pass: if unique place names are not enough, allow same place name but still no same unit ID.
    if missing_total > 0:
        try_add_rows(shuffled, missing_total, avoid_same_place=False)

    # Final safety: if we still have fewer than desired_count, fill from any remaining unique unit.
    if len(selected_rows) < desired_count:
        remaining = desired_count - len(selected_rows)
        try_add_rows(shuffled, remaining, avoid_same_place=False)

    selected_df = pd.DataFrame(selected_rows).drop_duplicates(subset=["unit_id"]).head(desired_count).reset_index(drop=True)

    failure_types = ["AA"] * min(aa_count, desired_count)
    normal_needed = desired_count - len(failure_types)
    normal_cycle = ["A", "B", "C", "D"]
    failure_types.extend(normal_cycle[i % len(normal_cycle)] for i in range(normal_needed))
    rng.shuffle(failure_types)

    rows: List[Dict[str, Any]] = []
    now = datetime.now().replace(microsecond=0)
    for i, (_, unit) in enumerate(selected_df.iterrows(), start=1):
        failure = failure_types[i - 1]
        rows.append({
            "ticket_id": f"BD-{now.strftime('%Y%m%d')}-{i:03d}",
            "unit_id": unit["unit_id"],
            "unit_name": unit.get("unit_name"),
            "unit_type": unit.get("unit_type"),
            "region": unit.get("region"),
            "failure_type": failure,
            "created_at": now.isoformat(sep=" "),
            "response_limit_hours": 1.0 if failure == "AA" else 4.0,
            "service_time": DEFAULT_BREAKDOWN_SERVICE_TIME,
            "status": "open",
        })
    return rows

# =====================================================
# DJANGO INTEGRATION EXAMPLE
# =====================================================

DJANGO_INTEGRATION_EXAMPLE = r'''
# Example usage inside Django service layer:

from optimizer.capstone_gurobi_optimizer_v3 import solve_maintenance_from_records, solve_breakdown_from_records


def run_maintenance_optimization(plan_start, plan_end):
    technicians = list(Technician.objects.filter(is_active=True).values(
        "id", "name", "role", "skill_type", "region", "daily_capacity_hours",
        "shift_start", "shift_end", "latitude", "longitude",
    ))

    tasks = list(Task.objects.filter(status="pending", task_type="Maintenance").values(
        "id", "unit_id", "unit__name", "unit__unit_type", "unit__region",
        "maintenance_package", "service_time", "required_technicians", "planned_date",
    ))

    # optional: travel times from Google Maps / cached travel_matrix table
    travel_time_matrix = build_travel_time_matrix(technicians, tasks)

    result = solve_maintenance_from_records(technicians, tasks, travel_time_matrix=travel_time_matrix)

    for row in result["assignments"]:
        Schedule.objects.create(
            technician_id=row["technician_id"],
            task_id=row["task_id"],
            unit_id=row["unit_id"],
            route_order=row["route_order"],
            estimated_start_time=row["estimated_start_time"],
            estimated_end_time=row["estimated_end_time"],
            status=row["status"],
        )

    return result
'''


# =====================================================
# CLI
# =====================================================


def print_precheck_dict(data: Dict[str, Any]) -> None:
    print("\nPRECHECK")
    print("-" * 60)
    for key, value in data.items():
        print(f"{key}: {value}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["maintenance", "breakdown", "generate_breakdowns"], default="maintenance")
    parser.add_argument("--technicians", default="data/technicians.xlsx")
    parser.add_argument("--units", default="data/units.xlsx")
    parser.add_argument("--breakdowns", default="data/breakdown_tickets.xlsx")
    parser.add_argument("--output", default="results/optimization_result_v5.xlsx")
    parser.add_argument("--plan-start", default=None)
    parser.add_argument("--plan-end", default=None)
    parser.add_argument("--precheck", action="store_true")
    parser.add_argument("--demo-due-pattern", action="store_true", help="Standalone demo only: legacy small demo: creates one deterministic A/B/C package per unit instead of annual tasks.")
    parser.add_argument("--combine-rule", choices=["sum", "max"], default="sum")
    parser.add_argument("--breakdown-count", type=int, default=50)
    parser.add_argument("--aa-count", type=int, default=5)
    parser.add_argument("--max-breakdown-tickets-per-tech", type=int, default=None)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    config = SolverConfig(
        maintenance_combine_rule=args.combine_rule,
        max_breakdown_tickets_per_tech=args.max_breakdown_tickets_per_tech,
    )
    technician_file = Path(args.technicians)
    unit_file = Path(args.units)
    breakdown_file = Path(args.breakdowns)
    output_file = Path(args.output)

    if not technician_file.exists():
        raise FileNotFoundError(f"Technician file not found: {technician_file}")
    if not unit_file.exists():
        raise FileNotFoundError(f"Unit file not found: {unit_file}")

    technician_records = read_excel_records(technician_file)
    unit_records = read_excel_records(unit_file)
    technicians_df = technicians_to_dataframe(technician_records, config)
    units_df = units_to_dataframe(unit_records)

    if args.mode == "generate_breakdowns":
        tickets = generate_demo_breakdown_tickets(
            unit_records=unit_records,
            count=args.breakdown_count,
            aa_count=args.aa_count,
            seed=args.seed,
        )
        breakdown_file.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(tickets).to_excel(breakdown_file, index=False)
        print(f"Generated demo breakdown tickets: {breakdown_file}")
        print(f"Ticket count: {len(tickets)}")
        print(f"AA count: {len([t for t in tickets if t['failure_type'] == 'AA'])}")
        return

    if args.mode == "maintenance":
        maintenance_tasks = generate_maintenance_tasks_from_units(
            units_df,
            plan_start=args.plan_start,
            plan_end=args.plan_end,
            config=config,
            demo_due_pattern=args.demo_due_pattern,
        )
        if args.precheck:
            print_precheck_dict(maintenance_precheck(technicians_df, units_df, maintenance_tasks))
            print("\nPrecheck completed. Gurobi was not started.")
            return
        result = solve_maintenance_from_records(technician_records, maintenance_tasks, config=config)
        export_result_to_excel(result, output_file)
        print(f"Maintenance optimization completed. Output: {output_file}")
        print(f"Assignments: {len(result['assignments'])}")
        print(f"Unassigned tasks: {len(result['unassigned_tasks'])}")
        print(f"Meta: {result['meta']}")
        return

    if args.mode == "breakdown":
        if not breakdown_file.exists():
            raise FileNotFoundError(
                f"Breakdown ticket file not found: {breakdown_file}. First run --mode generate_breakdowns or provide real tickets."
            )
        ticket_records = read_excel_records(breakdown_file)
        if args.precheck:
            tickets_df = breakdown_tickets_to_dataframe(ticket_records, unit_records)
            print_precheck_dict({
                "technicians_total": len(technicians_df),
                "breakdown_technicians": int(technicians_df["role"].isin(["Breakdown", "Both"]).sum()),
                "open_breakdown_tickets": len(tickets_df),
                "failure_type_counts": tickets_df["failure_type"].value_counts(dropna=False).to_dict() if not tickets_df.empty else {},
                "ticket_regions": tickets_df["region"].value_counts(dropna=False).to_dict() if not tickets_df.empty else {},
                "ticket_unit_types": tickets_df["unit_type"].value_counts(dropna=False).to_dict() if not tickets_df.empty else {},
            })
            print("\nPrecheck completed. Gurobi was not started.")
            return
        result = solve_breakdown_from_records(technician_records, ticket_records, unit_records=unit_records, config=config)
        export_result_to_excel(result, output_file)
        print(f"Breakdown optimization completed. Output: {output_file}")
        print(f"Assignments: {len(result['assignments'])}")
        print(f"Unassigned tickets: {len(result['unassigned_tasks'])}")
        print(f"Meta: {result['meta']}")
        return


if __name__ == "__main__":
    main()
