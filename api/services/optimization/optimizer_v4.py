"""
Capstone Gurobi Optimizer v13

Düzeltilen sorunlar (v6'ya göre):
  1. MONTHLY planning horizon — yıllık değil, aylık bazda çalışır.
     Her ay için ayrı optimizer çağrısı yapılır; kapasite 1 aylık iş günü × 8 saat.
  2. Idle penalty objective'e eklendi (SRS formülü: min Z = Σc_tu*x_tu + λΣot + μΣidle + MΣmiss).
  3. AA breakdown ticket'ları öncelikli constraint ile ayrıştırıldı:
     AA ticket'lar için ayrı coverage constraint + en yüksek penalty.
  4. Breakdown dengesizliği düzeltildi: workload balancing constraint eklendi,
     region mismatch nedeniyle boş kalan teknisyen sorunu giderildi.
  5. Escalator sabah penceresi constraint'i modele eklendi (08:00-10:00 arası başlamalı).
  6. required_technicians=1 vs 2 ayrımı doğru işleniyor.
  7. Haversine fallback travel time — lat/lon varsa gerçek mesafe hesabı.
  8. Breakdown daily_summary artık dolu.

Kullanım:
    python capstone_gurobi_optimizer_v10.py --mode maintenance --month 2026-01
    python capstone_gurobi_optimizer_v10.py --mode maintenance --month 2026-01 --precheck
    python capstone_gurobi_optimizer_v10.py --mode generate_breakdowns --breakdown-count 50
    python capstone_gurobi_optimizer_v10.py --mode breakdown

Dosya yapısı:
    data/
        technicians.xlsx
        units.xlsx
        breakdown_tickets.xlsx
    results/
"""

from __future__ import annotations

import argparse
import hashlib
import math
import random
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import pandas as pd


# =====================================================
# CONFIG
# =====================================================

REGULAR_DAILY_HOURS   = 8.0
WORKING_DAYS_PER_MONTH = 22          # 1 aylık planlama horizon (yaklaşık iş günü)
MONTHLY_CAPACITY_HOURS = REGULAR_DAILY_HOURS * WORKING_DAYS_PER_MONTH  # 176 saat

IDLE_WARNING_HOURS    = 1.0

LABOR_COST_PER_HOUR   = 100.0
TRAVEL_COST_PER_HOUR  =  50.0
OVERTIME_PENALTY      = 500.0
IDLE_PENALTY          =  10.0       # μ — SRS formülündeki eksik terim eklendi

MAINTENANCE_MISSED_PENALTY   = 1_000_000.0
BREAKDOWN_MISSED_PENALTY     = 5_000_000.0
AA_BREAKDOWN_MISSED_PENALTY  = 50_000_000.0   # AA için çok daha yüksek
SLA_VIOLATION_PENALTY        = 2_000_000.0

MAX_MAINTENANCE_OVERTIME     = 0.0   # Fazla mesai yok; kapasitesi dolunca unassigned
MAX_BREAKDOWN_OVERTIME       = 2.0   # Breakdown'da max 2 saat fazla mesai

TIME_LIMIT_SECONDS = 180
MIP_GAP            = 0.01

SHIFT_START_DEFAULT = "08:00"
SHIFT_END_DEFAULT   = "17:00"
LUNCH_START_DEFAULT = "12:00"
LUNCH_END_DEFAULT   = "13:00"

# Escalator sabah penceresi: bina kapalıyken (08:00-10:00) yapılmalı
ESCALATOR_WINDOW_START_MIN = 8 * 60   #  480 dk
ESCALATOR_WINDOW_END_MIN   = 10 * 60  #  600 dk

MAINTENANCE_TIME_MAP = {
    "A": 4.0,
    "B": 2.0,
    "C": 0.75,
}

DEFAULT_MAINTENANCE_PACKAGE      = "C"
DEFAULT_BREAKDOWN_SERVICE_TIME   = 1.0
DEFAULT_TRAVEL_TIME_HOURS        = 0.25  # Google Maps yoksa fallback

# İstanbul ilçe → bölge eşlemesi
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

# Callback SLA sınırları (saat)
CALLBACK_SLA_HOURS = {
    "AA": 1.0,
    "A":  4.0,
    "B":  8.0,
    "C": 24.0,
    "D": 48.0,
}


@dataclass
class SolverConfig:
    # Maintenance: aylık capacity
    working_days_per_month: int  = WORKING_DAYS_PER_MONTH
    max_maintenance_overtime: float = MAX_MAINTENANCE_OVERTIME

    # Breakdown: günlük dispatch
    max_breakdown_overtime: float = MAX_BREAKDOWN_OVERTIME
    max_breakdown_tickets_per_tech: Optional[int] = None   # None → otomatik dengeli

    # Genel
    allow_unknown_region_match: bool = True
    time_limit_seconds: int = TIME_LIMIT_SECONDS
    mip_gap: float = MIP_GAP
    default_travel_time_hours: float = DEFAULT_TRAVEL_TIME_HOURS
    maintenance_combine_rule: str = "sum"   # "sum" veya "max"
    lunch_start: str = LUNCH_START_DEFAULT
    lunch_end: str = LUNCH_END_DEFAULT


# =====================================================
# METİN / NORMALİZASYON YARDIMCILARI
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
    """
    Teknisyen/ünite yetkinliğini normalize eder.

    ÖNEMLİ: Eski versiyonda "Asansör + Yürüyen Merdiven" gibi ifadeler,
    içinde "merdiven" geçtiği için Escalator'a düşüyordu. Bu yüzden tüm
    Both teknisyenler yanlışlıkla Escalator görünüyordu. Önce iki ürünün
    birlikte geçip geçmediğini kontrol ediyoruz.
    """
    raw = "" if value is None else str(value).strip()
    text = clean_text(raw)
    compact = compact_key(raw)

    has_elevator = (
        "elevator" in text or "asansor" in text or "lift" in text
    )
    has_escalator = (
        "escalator" in text or "yuruyen" in text or "merdiven" in text or "walkway" in text
    )

    both_tokens = [
        "both", "hepsi", "tum", "tumu", "iki", "ikisi", "ikiside",
        "asansoryuruyen", "asansormerdiven", "elevatorescalator",
        "elevatorandescalator", "asansorveyuruyen", "asansorveyuruyenmerdiven",
    ]
    if any(tok in compact for tok in both_tokens) or (has_elevator and has_escalator):
        return "Both"
    if has_elevator:
        return "Elevator"
    if has_escalator:
        return "Escalator"
    return raw if raw else "Unknown"


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
    if "insan" in text or "person" in text or "kal" in text:
        return "AA"
    return "D"   # bilinmeyeni en düşük önceliğe at


def region_from_location(location: Any) -> str:
    text = clean_text(location)
    for district in ASIA_DISTRICTS:
        if re.search(rf"\b{re.escape(district)}\b", text):
            return "Asia"
    for district in EUROPE_DISTRICTS:
        if re.search(rf"\b{re.escape(district)}\b", text):
            return "Europe"
    return "Unknown"


def is_avm_like(*values: Any) -> bool:
    """
    Escalator morning window sadece AVM / shopping mall gibi yerlerde uygulanır.
    Diğer escalator üniteleri için sabah 10 kısıtı yoktur.

    Yeni veri formatı:
      - Excel'de `Konut Tipi` kolonu olabilir.
      - Bu kolonda `AVM` yazıyorsa ve unit_type Escalator ise morning_required=YES olur.
      - `Site`, `Hastane`, `Ofis`, `Konut` vb. değerler sabah kısıtı doğurmaz.
    """
    cleaned = [clean_text(v) for v in values if v is not None]
    text = " ".join(cleaned)

    # Direkt boolean/flag değerleri
    if any(v in {"1", "true", "yes", "evet", "y", "avm"} for v in cleaned):
        if any(v == "avm" for v in cleaned) or "avm" in text:
            return True

    avm_keywords = [
        "avm", "alisveris", "alisveris merkezi", "shopping", "mall",
        "plaza avm", "center avm", "centre avm", "outlet", "magaza merkezi"
    ]
    return any(k in text for k in avm_keywords)


def deterministic_region(value: Any, index: int) -> str:
    text = str(value) if value is not None else str(index)
    digest = hashlib.md5(text.encode("utf-8")).hexdigest()
    return "Asia" if int(digest, 16) % 2 == 0 else "Europe"


def stable_month_from_unit(unit_id: Any) -> int:
    """
    Gerçek bakım tarihleri yoksa demo plan için üniteleri 12 aya dengeli ve sabit dağıtır.
    Aynı unit_id her çalıştırmada aynı bakım ayına düşer.
    """
    text = str(unit_id) if unit_id is not None else ""
    digest = hashlib.md5(text.encode("utf-8")).hexdigest()
    return int(digest, 16) % 12 + 1


def add_six_months(month_no: int) -> int:
    """1-12 arasındaki bir aya 6 ay ekler ve yine 1-12 aralığında döndürür."""
    return ((int(month_no) - 1 + 6) % 12) + 1


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
    return None if pd.isna(dt) else dt


def parse_time_string(value: Any, default: time) -> time:
    if value is None or str(value).strip() == "":
        return default
    try:
        return pd.to_datetime(str(value)).time()
    except Exception:
        return default


# =====================================================
# HAVERSINE TRAVEL TIME FALLBACK
# =====================================================

def haversine_hours(lat1: float, lon1: float, lat2: float, lon2: float,
                    speed_kmh: float = 30.0) -> float:
    """
    İki nokta arasındaki kuş uçuşu mesafeyi şehir içi ortalama hızla saat cinsine çevirir.
    Google Maps yokken lat/lon varsa bu kullanılır.
    """
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    dist_km = 2 * R * math.asin(math.sqrt(a))
    return dist_km / speed_kmh


def get_travel_time(
    tech_lat: Optional[float], tech_lon: Optional[float],
    task_lat: Optional[float], task_lon: Optional[float],
    travel_time_matrix: Optional[Mapping],
    tech_id: str, task_id: str,
    default: float,
) -> float:
    """
    Öncelik sırası:
      1. travel_time_matrix (Google Maps veya önbellekten)
      2. Haversine hesabı (lat/lon varsa)
      3. Sabit fallback (default)
    """
    if travel_time_matrix:
        for key in [(tech_id, task_id), f"{tech_id}|{task_id}", f"{tech_id},{task_id}"]:
            if key in travel_time_matrix:
                try:
                    return float(travel_time_matrix[key])
                except Exception:
                    pass
        nested = travel_time_matrix.get(tech_id) if isinstance(travel_time_matrix, dict) else None
        if isinstance(nested, dict) and task_id in nested:
            try:
                return float(nested[task_id])
            except Exception:
                pass

    if (tech_lat and tech_lon and task_lat and task_lon and
            not any(math.isnan(v) for v in [tech_lat, tech_lon, task_lat, task_lon])):
        return haversine_hours(tech_lat, tech_lon, task_lat, task_lon)

    return default


# =====================================================
# VERİ OKUMA: TEKNİSYENLER
# =====================================================

def technicians_to_dataframe(records: Iterable[Mapping[str, Any]], config: SolverConfig) -> pd.DataFrame:
    raw = pd.DataFrame(list(records))
    if raw.empty:
        return pd.DataFrame()

    id_col         = find_col(raw, ["technician_id", "Technician ID", "id", "pk"])
    first_name_col = find_col(raw, ["Ad", "first_name", "name", "Name"])
    last_name_col  = find_col(raw, ["Soyad", "last_name", "surname"])
    role_col       = find_col(raw, [
        "role", "Görev Türü", "Gorev Turu", "task_role", "technician_role",
        "technician_type", "employee_type", "Çalışan Tipi", "Calisan Tipi",
        "Personel Tipi", "Personel Türü", "Tip", "type"
    ])
    skill_col      = find_col(raw, [
        "skill_type", "Skill Type", "Uzmanlık", "Uzmanlik", "skill", "expertise",
        "qualification", "competency", "yetkinlik", "Yetenek", "Beceri",
        "Baktığı Ürün", "Baktigi Urun", "Bakabildiği Ürün", "Bakabildigi Urun",
        "Ürün Yetkinliği", "Urun Yetkinligi", "Servis Ürünü", "Servis Urunu",
        "qualified_unit_type", "served_unit_type", "unit_type_skill"
    ])
    region_col     = find_col(raw, ["region", "Bölge", "Bolge"])
    hours_col      = find_col(raw, ["available_hours", "daily_capacity_hours", "capacity_hours", "hours"])
    shift_start_col= find_col(raw, ["shift_start", "start_time"])
    shift_end_col  = find_col(raw, ["shift_end", "end_time"])
    lat_col        = find_col(raw, ["latitude", "start_latitude", "lat"])
    lon_col        = find_col(raw, ["longitude", "start_longitude", "lon", "lng"])

    if id_col is None or role_col is None or skill_col is None:
        raise ValueError("Teknisyen verisi: technician_id, role, skill_type alanları zorunlu.")

    out = pd.DataFrame()
    out["technician_id"]   = raw[id_col].astype(str).str.strip()
    out["technician_name"] = raw[first_name_col].fillna("").astype(str).str.strip() if first_name_col else out["technician_id"]
    if last_name_col and last_name_col != first_name_col:
        out["technician_name"] = (out["technician_name"] + " " + raw[last_name_col].fillna("").astype(str).str.strip()).str.strip()

    out["role"]       = raw[role_col].apply(normalize_role)
    out["skill_type"] = raw[skill_col].apply(normalize_skill)

    # Proje iş kuralı: arızacılar hem asansör hem yürüyen merdiven arızasına bakabilir.
    # Excel'de skill kolonu yanlış/eksik okunsa bile Breakdown rolündeki kişileri Both kabul ediyoruz.
    out.loc[out["role"] == "Breakdown", "skill_type"] = "Both"

    if region_col is not None:
        out["region"] = raw[region_col].apply(normalize_region)
    else:
        out["region"] = ["Asia" if i % 2 == 0 else "Europe" for i in range(len(out))]

    # Aylık kapasite: Excel'de yıllık saat yazıyorsa düzelt
    if hours_col is not None:
        raw_hours = pd.to_numeric(raw[hours_col], errors="coerce")
        # 176 saatin üzerindeyse (yıllık gibi görünüyorsa) aylık kapasiteye sabitle
        out["available_hours"] = raw_hours.apply(
            lambda h: MONTHLY_CAPACITY_HOURS if (math.isnan(h) or h > MONTHLY_CAPACITY_HOURS) else h
        )
    else:
        out["available_hours"] = MONTHLY_CAPACITY_HOURS

    out["shift_start"] = (raw[shift_start_col].apply(lambda x: str(x) if str(x) != "nan" else SHIFT_START_DEFAULT)
                          if shift_start_col else SHIFT_START_DEFAULT)
    out["shift_end"]   = (raw[shift_end_col].apply(lambda x: str(x) if str(x) != "nan" else SHIFT_END_DEFAULT)
                          if shift_end_col else SHIFT_END_DEFAULT)

    out["latitude"]  = pd.to_numeric(raw[lat_col],  errors="coerce") if lat_col  else float("nan")
    out["longitude"] = pd.to_numeric(raw[lon_col],  errors="coerce") if lon_col  else float("nan")

    return out.dropna(subset=["technician_id"]).drop_duplicates("technician_id").reset_index(drop=True)


# =====================================================
# VERİ OKUMA: ÜNİTELER
# =====================================================

def units_to_dataframe(records: Iterable[Mapping[str, Any]]) -> pd.DataFrame:
    raw = pd.DataFrame(list(records))
    if raw.empty:
        return pd.DataFrame()

    unit_id_col   = find_col(raw, ["unit_id", "Unit Number", "unit_number", "id", "pk"])
    unit_name_col = find_col(raw, ["unit_name", "Unit Name", "name"])
    location_col  = find_col(raw, ["unit_location", "Unit Location", "location", "address"])
    unit_type_col = find_col(raw, ["unit_type", "Unit Type", "type"])
    company_col   = find_col(raw, ["unit_company", "Unit Company", "company"])
    is_avm_col   = find_col(raw, ["is_avm", "AVM", "mall", "is_mall"])
    # Konut Tipi / Building Type kolonundan AVM bilgisini yakala.
    # Örnek: Site, Hastane, AVM. Sadece AVM + Escalator ise 10:00 öncesi kuralı uygulanır.
    venue_col    = find_col(raw, [
        "Konut Tipi", "konut_tipi", "konut tipi", "KonutTipi",
        "venue_type", "building_type", "building type", "place_type", "location_type", "property_type",
        "Bina Tipi", "bina_tipi", "type_of_building"
    ])
    region_col    = find_col(raw, ["region", "Bölge", "Bolge"])
    lat_col       = find_col(raw, ["latitude", "lat"])
    lon_col       = find_col(raw, ["longitude", "lon", "lng"])
    last_a_col    = find_col(raw, ["last_A_maintenance_date", "last_a_date", "last_a"])
    last_b_col    = find_col(raw, ["last_B_maintenance_date", "last_b_date", "last_b"])
    last_c_col    = find_col(raw, ["last_C_maintenance_date", "last_c_date", "last_c"])

    if unit_id_col is None or unit_type_col is None:
        raise ValueError("Ünite verisi: unit_id ve unit_type alanları zorunlu.")

    out = pd.DataFrame()
    out["unit_id"]   = raw[unit_id_col].astype(str).str.strip()
    out["unit_name"] = raw[unit_name_col].fillna("").astype(str).str.strip() if unit_name_col else out["unit_id"]
    out["location"]  = raw[location_col].fillna("").astype(str).str.strip() if location_col else ""
    out["unit_type"] = raw[unit_type_col].apply(normalize_skill)
    out["company"]   = raw[company_col].fillna("").astype(str).str.strip() if company_col else ""
    out["is_avm"]    = raw[is_avm_col].fillna("").astype(str).str.strip() if is_avm_col else ""
    out["venue_type"] = raw[venue_col].fillna("").astype(str).str.strip() if venue_col else ""

    if region_col is not None:
        out["region"] = raw[region_col].apply(normalize_region)
    else:
        detected = out["location"].apply(region_from_location)
        out["region"] = [
            detected.iloc[i] if detected.iloc[i] != "Unknown" else deterministic_region(out.loc[i, "unit_id"], i)
            for i in range(len(out))
        ]

    out["latitude"]  = pd.to_numeric(raw[lat_col], errors="coerce") if lat_col else float("nan")
    out["longitude"] = pd.to_numeric(raw[lon_col], errors="coerce") if lon_col else float("nan")
    out["last_A_maintenance_date"] = raw[last_a_col].apply(parse_date) if last_a_col else None
    out["last_B_maintenance_date"] = raw[last_b_col].apply(parse_date) if last_b_col else None
    out["last_C_maintenance_date"] = raw[last_c_col].apply(parse_date) if last_c_col else None

    return out.dropna(subset=["unit_id"]).drop_duplicates("unit_id").reset_index(drop=True)


# =====================================================
# BAKIM GÖREVİ ÜRETME (AYLIK)
# =====================================================

def generate_maintenance_tasks_for_month(
    units: Iterable[Mapping[str, Any]] | pd.DataFrame,
    plan_month: str | None = None,       # "2026-01" formatında; None → bu ay
    config: SolverConfig = SolverConfig(),
) -> List[Dict[str, Any]]:
    """
    Bir ay için bakım OPERASYONLARINI üretir.

    v12 mantığı:
      - A/B/C bakım türleri ayrı operasyon olarak üretilir.
      - C bakımı her ay tüm aktif ünitelere gelir.
      - B bakımı her üniteye yılda 2 kez gelir.
      - A bakımı her üniteye yılda 1 kez gelir.
      - Tarih verisi olmadığı için A/B ayları unit_id hash'i yerine
        region + unit_type bazında dengeli dağıtılır. Böylece Ocak ayında
        tüm A/B tasklarının sadece Asia veya sadece Elevator tarafına yığılması engellenir.
      - Escalator morning_required sadece AVM/shopping mall ünitelerinde YES olur.
    """
    if isinstance(units, pd.DataFrame):
        units_df = units.copy()
    else:
        units_df = units_to_dataframe(units)

    if plan_month:
        ts = pd.to_datetime(plan_month, format="%Y-%m")
    else:
        ts = pd.Timestamp(datetime.today().replace(day=1))

    month_no = int(ts.month)
    year     = int(ts.year)

    # Dengeli demo cycle: her region + unit_type grubu kendi içinde 12 aya yayılır.
    units_df = units_df.copy().reset_index(drop=True)
    units_df["_cycle_order"] = (
        units_df.sort_values(["region", "unit_type", "unit_id"])
                .groupby(["region", "unit_type"], dropna=False)
                .cumcount()
                .reindex(units_df.index)
                .fillna(0)
                .astype(int)
    )
    units_df["_annual_a_month"] = (units_df["_cycle_order"] % 12) + 1
    units_df["_second_b_month"] = ((units_df["_annual_a_month"] - 1 + 6) % 12) + 1

    rows: List[Dict[str, Any]] = []

    def add_task(unit: Mapping[str, Any], maintenance_type: str, annual_a_month: int, second_b_month: int) -> None:
        unit_id = str(unit["unit_id"])
        task_id = f"M-{unit_id}-{year}-M{month_no:02d}-{maintenance_type}"
        avm_escalator = (
            unit.get("unit_type") == "Escalator"
            and is_avm_like(unit.get("unit_name"), unit.get("location"), unit.get("company"), unit.get("is_avm"), unit.get("venue_type"))
        )
        rows.append({
            "task_id":              task_id,
            "unit_id":              unit_id,
            "unit_name":            unit.get("unit_name", unit_id),
            "task_type":            "Maintenance",
            "maintenance_type":      maintenance_type,
            "maintenance_package":   maintenance_type,
            "unit_type":            unit.get("unit_type", "Unknown"),
            "region":               unit.get("region", "Unknown"),
            "service_time":         MAINTENANCE_TIME_MAP[maintenance_type],
            "required_technicians":  1,
            "planned_month":        month_no,
            "planned_year":         year,
            "demo_cycle_a_month":    annual_a_month,
            "demo_cycle_b_months":   f"{annual_a_month},{second_b_month}",
            "location":             unit.get("location", ""),
            "latitude":             unit.get("latitude", None),
            "longitude":            unit.get("longitude", None),
            "morning_required":      "YES" if avm_escalator else "NO",
            "operation_count_A":     1 if maintenance_type == "A" else 0,
            "operation_count_B":     1 if maintenance_type == "B" else 0,
            "operation_count_C":     1 if maintenance_type == "C" else 0,
            "avm_escalator":         "YES" if avm_escalator else "NO",
        })

    for _, unit in units_df.iterrows():
        annual_a_month = int(unit["_annual_a_month"])
        second_b_month = int(unit["_second_b_month"])

        # C her ay gelir.
        add_task(unit, "C", annual_a_month, second_b_month)

        # B yılda 2 kez gelir.
        if month_no == annual_a_month or month_no == second_b_month:
            add_task(unit, "B", annual_a_month, second_b_month)

        # A yılda 1 kez gelir.
        if month_no == annual_a_month:
            add_task(unit, "A", annual_a_month, second_b_month)

    return rows

# =====================================================
# UYUM KONTROL YARDIMCILARI
# =====================================================

def skills_match(tech_skill: str, unit_type: str) -> bool:
    return tech_skill == "Both" or tech_skill == unit_type or unit_type == "Unknown"


def regions_match(tech_region: str, task_region: str, config: SolverConfig) -> bool:
    if config.allow_unknown_region_match and (tech_region == "Unknown" or task_region == "Unknown"):
        return True
    return tech_region == task_region


# =====================================================
# CORE SOLVER: BAKIM (AYLIK)
# =====================================================

def _task_priority_for_daily_scheduler(row: Mapping[str, Any]) -> Tuple[int, int, str]:
    """Daily scheduler sort key: escalator morning jobs first, then larger packages."""
    package = str(row.get("maintenance_package", DEFAULT_MAINTENANCE_PACKAGE))
    parts = set(package.split("+"))
    package_priority = 0
    if "A" in parts:
        package_priority = -3
    elif "B" in parts:
        package_priority = -2
    else:
        package_priority = -1
    morning_priority = 0 if row.get("morning_required") == "YES" else 1
    return (morning_priority, package_priority, str(row.get("region", "")))


def _build_candidate_techs_for_task(
    techs: pd.DataFrame,
    task_row: Mapping[str, Any],
    config: SolverConfig,
) -> List[str]:
    """Returns maintenance technician IDs that can process the task based on role/skill/region."""
    unit_type = str(task_row.get("unit_type", "Unknown"))
    region = str(task_row.get("region", "Unknown"))
    candidates: List[str] = []
    for _, trow in techs.iterrows():
        if not skills_match(str(trow.get("skill_type")), unit_type):
            continue
        if not regions_match(str(trow.get("region")), region, config):
            continue
        candidates.append(str(trow.get("technician_id")))
    return candidates


def _simulate_daily_append(
    slot: Dict[str, Any],
    travel_min: int,
    service_min: int,
    morning_required: bool,
    lunch_start: int,
    lunch_end: int,
    shift_end: int,
) -> Optional[Dict[str, Any]]:
    """
    Try to append one task at the end of a technician-day route.

    Important: lunch is NOT counted as work time, but it can pause/shift the route.
    If a maintenance service crosses 12:00-13:00, the service is paused and end time
    is extended by the lunch duration. This allows long packages like A+B+C to fit
    into a normal 08:00-17:00 day when total actual work <= 8 hours.
    """
    cur = int(slot["current_min"])
    used = int(slot["used_min"])
    daily_cap = int(REGULAR_DAILY_HOURS * 60)

    if used + travel_min + service_min > daily_cap:
        return None

    travel_start = cur

    # If the route would start during lunch, wait until lunch ends.
    if lunch_start <= travel_start < lunch_end:
        travel_start = lunch_end

    # If travel would cross lunch, leave after lunch instead.
    if travel_start < lunch_start and travel_start + travel_min > lunch_start:
        travel_start = lunch_end

    service_start = travel_start + travel_min
    service_end = service_start + service_min
    lunch_used = False

    # If maintenance service crosses lunch, pause for lunch and resume afterwards.
    if service_start < lunch_end and service_end > lunch_start:
        service_end += (lunch_end - lunch_start)
        lunch_used = True

    # Escalator morning window: must start by 10:00.
    if morning_required and service_start > ESCALATOR_WINDOW_END_MIN:
        return None

    if service_end > shift_end:
        return None

    return {
        "travel_start": travel_start,
        "service_start": service_start,
        "service_end": service_end,
        "used_after": used + travel_min + service_min,
        "lunch_used": lunch_used,
    }


def solve_maintenance(
    technician_records: Iterable[Mapping[str, Any]],
    task_records:       Iterable[Mapping[str, Any]],
    travel_time_matrix: Optional[Mapping] = None,
    config:             SolverConfig = SolverConfig(),
) -> Dict[str, Any]:
    """
    v8 day-based maintenance planner.

    Main fix vs v8:
      - The planner no longer assigns tasks only against monthly total capacity.
      - Each assignment is placed directly into a specific technician-day route.
      - Every technician-day respects 08:00-17:00 shift, 12:00-13:00 lunch,
        and 8 hours of actual work capacity.
      - Escalator morning tasks must start by 10:00.
      - Assignments, Daily_Summary and Daily_Timeline now describe the same plan.

    Note for backend:
      This function still returns dict/list output. Excel writing is only CLI/demo.
      For 20,000+ monthly tasks, this fast daily construction planner is used because
      an exact x[technician, task, day] MIP would be too large for local/demo runs.
    """
    techs = technicians_to_dataframe(technician_records, config)
    techs = techs[techs["role"].isin(["Maintenance", "Both"])].copy().reset_index(drop=True)

    tasks = pd.DataFrame(list(task_records))
    if tasks.empty:
        return _empty_result("NO_TASKS", "Bakım görevi bulunamadı.")
    tasks = tasks[tasks["task_type"].isin(["Maintenance", "Both"])].copy().reset_index(drop=True)

    if techs.empty:
        return _empty_result(
            "NO_MAINTENANCE_TECHNICIANS",
            "Bakım teknisyeni bulunamadı.",
            unassigned=tasks.to_dict("records"),
        )

    # Ensure numeric fields are present and clean.
    tasks["service_time"] = pd.to_numeric(tasks["service_time"], errors="coerce").fillna(
        tasks.get("maintenance_package", DEFAULT_MAINTENANCE_PACKAGE).apply(
            lambda x: package_service_time(x, config.maintenance_combine_rule)
        ) if "maintenance_package" in tasks.columns else MAINTENANCE_TIME_MAP[DEFAULT_MAINTENANCE_PACKAGE]
    )
    if "required_technicians" not in tasks.columns:
        tasks["required_technicians"] = 1
    tasks["required_technicians"] = pd.to_numeric(tasks["required_technicians"], errors="coerce").fillna(1).astype(int)

    T = techs["technician_id"].astype(str).tolist()
    tech_info = techs.set_index("technician_id")

    # Shift/lunch settings.
    lunch_start = _time_to_minutes(config.lunch_start, LUNCH_START_DEFAULT)
    lunch_end = _time_to_minutes(config.lunch_end, LUNCH_END_DEFAULT)

    # State for every technician-day.
    slots: Dict[Tuple[str, int], Dict[str, Any]] = {}
    for t in T:
        shift_start = _time_to_minutes(tech_info.loc[t].get("shift_start"), SHIFT_START_DEFAULT)
        shift_end = _time_to_minutes(tech_info.loc[t].get("shift_end"), SHIFT_END_DEFAULT)
        for d in range(1, config.working_days_per_month + 1):
            slots[(t, d)] = {
                "technician_id": t,
                "work_day": d,
                "shift_start": shift_start,
                "shift_end": shift_end,
                "current_min": shift_start,
                "used_min": 0,
                "route_order": 1,
                "tasks": [],
            }

    # Sort tasks before scheduling. This is a construction heuristic that respects daily constraints.
    task_rows = tasks.to_dict("records")
    task_rows.sort(key=_task_priority_for_daily_scheduler)

    assignments: List[Dict[str, Any]] = []
    unassigned: List[Dict[str, Any]] = []
    feasible_pair_count = 0

    # Cache candidate technician lists by task attributes for speed.
    candidate_cache: Dict[Tuple[str, str], List[str]] = {}

    for task in task_rows:
        task_id = str(task.get("task_id"))
        required = int(task.get("required_technicians", 1))
        service_time = float(task.get("service_time", 0.0) or 0.0)
        service_min = int(round(service_time * 60))
        morning_required = task.get("morning_required") == "YES"
        unit_type = str(task.get("unit_type", "Unknown"))
        region = str(task.get("region", "Unknown"))
        cache_key = (region, unit_type)

        if cache_key not in candidate_cache:
            candidate_cache[cache_key] = _build_candidate_techs_for_task(techs, task, config)
        candidates = candidate_cache[cache_key]
        feasible_pair_count += len(candidates)

        if len(candidates) < required:
            row = dict(task)
            row.update({
                "unmet_technician_requirement": required,
                "reason": "Uygun bakım teknisyeni yok (rol/yetenek/bölge uyuşmazlığı)",
            })
            unassigned.append(row)
            continue

        selected: List[Tuple[str, int, Dict[str, Any], float]] = []
        blocked_techs: set = set()

        # required_technicians=2 ise aynı task'a iki farklı teknisyen seçilir.
        for req_idx in range(required):
            best: Optional[Tuple[Tuple, str, int, Dict[str, Any], float]] = None
            for t in candidates:
                if t in blocked_techs:
                    continue
                trow = tech_info.loc[t]
                travel_h = get_travel_time(
                    _safe_float(trow.get("latitude")), _safe_float(trow.get("longitude")),
                    _safe_float(task.get("latitude")), _safe_float(task.get("longitude")),
                    travel_time_matrix, t, task_id, config.default_travel_time_hours,
                )
                travel_min = int(round(travel_h * 60))

                for d in range(1, config.working_days_per_month + 1):
                    slot = slots[(t, d)]
                    sim = _simulate_daily_append(
                        slot=slot,
                        travel_min=travel_min,
                        service_min=service_min,
                        morning_required=morning_required,
                        lunch_start=lunch_start,
                        lunch_end=lunch_end,
                        shift_end=int(slot["shift_end"]),
                    )
                    if sim is None:
                        continue

                    # Score v12: önce teknisyenler arası yükü dengeler, sonra günü iyi doldurur.
                    # Eski skor en erken günü fazla önceliklendirdiği için bazı teknisyenler dolarken
                    # bazıları boş kalabiliyordu.
                    monthly_used = sum(slots[(t, dd)]["used_min"] for dd in range(1, config.working_days_per_month + 1))
                    remaining_after = int(REGULAR_DAILY_HOURS * 60) - sim["used_after"]
                    score = (
                        monthly_used,           # önce en az yüklenmiş uygun teknisyen
                        d,                      # sonra en erken gün
                        remaining_after,        # sonra günü daha iyi dolduran seçenek
                        travel_min,             # sonra daha düşük yol süresi
                        str(t),
                    )
                    if best is None or score < best[0]:
                        best = (score, t, d, sim, travel_h)

            if best is None:
                break
            _, chosen_t, chosen_d, chosen_sim, chosen_travel_h = best
            selected.append((chosen_t, chosen_d, chosen_sim, chosen_travel_h))
            blocked_techs.add(chosen_t)

        if len(selected) < required:
            row = dict(task)
            row.update({
                "unmet_technician_requirement": required - len(selected),
                "reason": "Günlük kapasite, shift veya escalator morning window nedeniyle atanamadı",
            })
            unassigned.append(row)
            continue

        for t, d, sim, travel_h in selected:
            slot = slots[(t, d)]
            trow = tech_info.loc[t]
            route_order = int(slot["route_order"])
            row = {
                "technician_id": t,
                "technician_name": trow.get("technician_name", t),
                "task_id": task_id,
                "unit_id": task.get("unit_id"),
                "unit_name": task.get("unit_name"),
                "task_type": "Maintenance",
                "maintenance_package": task.get("maintenance_package", DEFAULT_MAINTENANCE_PACKAGE),
                "unit_type": task.get("unit_type"),
                "region": task.get("region"),
                "service_time": float(service_time),
                "travel_time": float(travel_h),
                "total_time": float(service_time) + float(travel_h),
                "morning_required": task.get("morning_required", "NO"),
                "work_day": d,
                "route_order": route_order,
                "estimated_travel_start_time": _minutes_to_hhmm(int(sim["travel_start"])),
                "estimated_start_time": _minutes_to_hhmm(int(sim["service_start"])),
                "estimated_end_time": _minutes_to_hhmm(int(sim["service_end"])),
                "lunch_break": "YES" if sim.get("lunch_used") else "NO",
                "time_window_warning": "NO",
                "schedule_status": "scheduled",
                "status": "assigned",
            }
            assignments.append(row)
            slot["tasks"].append(row)
            slot["used_min"] = int(sim["used_after"])
            slot["current_min"] = int(sim["service_end"])
            slot["route_order"] = route_order + 1

    # Daily summary from actual scheduled slots.
    daily_summary: List[Dict[str, Any]] = []
    for (t, d), slot in sorted(slots.items(), key=lambda kv: (str(kv[0][0]), int(kv[0][1]))):
        if not slot["tasks"]:
            continue
        used_h = float(slot["used_min"]) / 60.0
        idle_h = max(0.0, REGULAR_DAILY_HOURS - used_h)
        daily_summary.append({
            "technician_id": t,
            "technician_name": tech_info.loc[t].get("technician_name", t),
            "work_day": d,
            "assigned_task_count": len(slot["tasks"]),
            "used_work_hours": round(used_h, 4),
            "idle_time_hours": round(idle_h, 4),
            "idle_warning": "YES" if idle_h > IDLE_WARNING_HOURS else "NO",
            "day_start": _minutes_to_hhmm(int(slot["shift_start"])),
            "day_end": _minutes_to_hhmm(int(slot["shift_end"])),
        })

    # Technician summary from actual scheduled assignments.
    by_tech: Dict[str, List[Dict[str, Any]]] = {t: [] for t in T}
    for row in assignments:
        by_tech[row["technician_id"]].append(row)

    technician_summary: List[Dict[str, Any]] = []
    for t in T:
        rows = by_tech[t]
        svc_s = sum(float(r.get("service_time", 0) or 0) for r in rows)
        trv_s = sum(float(r.get("travel_time", 0) or 0) for r in rows)
        total_used = svc_s + trv_s
        available = REGULAR_DAILY_HOURS * config.working_days_per_month
        idle_h = max(0.0, available - total_used)
        technician_summary.append({
            "technician_id": t,
            "technician_name": tech_info.loc[t].get("technician_name", t),
            "role": tech_info.loc[t].get("role"),
            "skill_type": tech_info.loc[t].get("skill_type"),
            "region": tech_info.loc[t].get("region"),
            "assigned_task_count": len(rows),
            "scheduled_days": len({r.get("work_day") for r in rows}),
            "total_service_time": round(svc_s, 4),
            "total_travel_time": round(trv_s, 4),
            "total_work_time": round(total_used, 4),
            "available_hours": round(available, 4),
            "overtime_hours": 0.0,
            "idle_hours": round(idle_h, 4),
            "idle_warning": "YES" if idle_h > IDLE_WARNING_HOURS else "NO",
        })

    return {
        "assignments": assignments,
        "technician_summary": technician_summary,
        "daily_summary": daily_summary,
        "unassigned_tasks": unassigned,
        "meta": {
            "status": "OK",
            "mode": "maintenance",
            "solver": "fast_day_based_scheduler_v12",
            "objective_value": None,
            "technicians_used": sum(1 for r in technician_summary if r["assigned_task_count"] > 0),
            "total_assignments": len(assignments),
            "unassigned_count": len(unassigned),
            "feasible_pairs": feasible_pair_count,
            "working_days_per_month": config.working_days_per_month,
            "daily_capacity_hours": REGULAR_DAILY_HOURS,
            "monthly_capacity_hours": REGULAR_DAILY_HOURS * config.working_days_per_month,
            "note": "Maintenance operations A/B/C are scheduled directly by technician-day. Excel CLI/demo output only; backend should store assignments in Schedule.",
        },
    }



# =====================================================
# CORE SOLVER: ARIZA (BREAKDOWN) — GÜNLÜK DISPATCH
# =====================================================

def breakdown_tickets_to_dataframe(
    ticket_records: Iterable[Mapping[str, Any]],
    unit_records:   Optional[Iterable[Mapping[str, Any]]] = None,
) -> pd.DataFrame:
    raw = pd.DataFrame(list(ticket_records))
    if raw.empty:
        return pd.DataFrame()

    ticket_id_col = find_col(raw, ["ticket_id", "id", "pk"])
    unit_id_col   = find_col(raw, ["unit_id", "Unit Number", "unit_number"])
    unit_type_col = find_col(raw, ["unit_type", "Unit Type", "type"])
    region_col    = find_col(raw, ["region", "Bölge", "Bolge"])
    failure_col   = find_col(raw, ["failure_type", "Failure Type", "Arıza Tipi"])
    created_col   = find_col(raw, ["created_at", "created_time", "reported_at", "date"])
    response_col  = find_col(raw, ["response_limit_hours", "response_limit", "sla_hours"])
    service_col   = find_col(raw, ["service_time", "duration", "repair_time"])
    status_col    = find_col(raw, ["status"])

    if ticket_id_col is None or unit_id_col is None:
        raise ValueError("Breakdown verisi: ticket_id ve unit_id zorunlu.")

    out = pd.DataFrame()
    out["ticket_id"]    = raw[ticket_id_col].astype(str).str.strip()
    out["unit_id"]      = raw[unit_id_col].astype(str).str.strip()
    out["failure_type"] = raw[failure_col].apply(normalize_failure_type) if failure_col else "D"
    out["created_at"]   = raw[created_col].apply(parse_date) if created_col else pd.Timestamp.now()
    out["status"]       = raw[status_col].fillna("open").astype(str).str.lower().str.strip() if status_col else "open"
    out["task_type"]    = "Breakdown"

    # SLA sınırını failure_type'tan otomatik hesapla
    if response_col:
        out["response_limit_hours"] = pd.to_numeric(raw[response_col], errors="coerce")
    else:
        out["response_limit_hours"] = out["failure_type"].map(CALLBACK_SLA_HOURS).fillna(4.0)
    out["response_limit_hours"] = out["response_limit_hours"].fillna(
        out["failure_type"].map(CALLBACK_SLA_HOURS).fillna(4.0)
    )

    out["service_time"] = (pd.to_numeric(raw[service_col], errors="coerce").fillna(DEFAULT_BREAKDOWN_SERVICE_TIME)
                           if service_col else DEFAULT_BREAKDOWN_SERVICE_TIME)

    units_df = units_to_dataframe(unit_records or [])
    if not units_df.empty:
        out = out.merge(
            units_df[["unit_id", "unit_name", "unit_type", "region", "location", "latitude", "longitude"]],
            on="unit_id", how="left"
        )
    else:
        out["unit_name"] = out["unit_id"]
        out["unit_type"] = raw[unit_type_col].apply(normalize_skill) if unit_type_col else "Unknown"
        out["region"]    = raw[region_col].apply(normalize_region)   if region_col    else "Unknown"
        out["location"]  = ""
        out["latitude"]  = float("nan")
        out["longitude"] = float("nan")

    out["unit_type"] = out["unit_type"].fillna("Unknown")
    out["region"]    = out["region"].fillna("Unknown")
    return out[out["status"].isin(["open", "pending", "new"])].reset_index(drop=True)


def solve_breakdown(
    technician_records: Iterable[Mapping[str, Any]],
    ticket_records:     Iterable[Mapping[str, Any]],
    unit_records:       Optional[Iterable[Mapping[str, Any]]] = None,
    travel_time_matrix: Optional[Mapping] = None,
    config:             SolverConfig = SolverConfig(),
) -> Dict[str, Any]:
    """
    Günlük arıza dispatch solver'ı.

    Düzeltmeler v5'e göre:
      - AA ticket'lar ayrı öncelik constraint'i ile ayrıştırıldı:
        AA ticket başka ticket atanmadan önce dolu olmalı (büyük penalty).
      - Workload balancing: min/max ticket farkını minimize eden soft constraint eklendi.
      - Region mismatch'ten boş kalan teknisyen sorunu: Unknown region her iki tarafa eşleşir.
      - Idle penalty objective'e eklendi.
      - Daily summary artık dolu.
    """
    try:
        import gurobipy as gp
        from gurobipy import GRB
    except ModuleNotFoundError as exc:
        raise RuntimeError("gurobipy kurulu değil.") from exc

    techs   = technicians_to_dataframe(technician_records, config)
    techs   = techs[techs["role"].isin(["Breakdown", "Both"])].copy().reset_index(drop=True)
    tickets = breakdown_tickets_to_dataframe(ticket_records, unit_records)

    if tickets.empty:
        return _empty_result("NO_OPEN_BREAKDOWNS", "Açık arıza bileti yok.")
    if techs.empty:
        return _empty_result("NO_BREAKDOWN_TECHNICIANS", "Arıza teknisyeni bulunamadı.",
                             unassigned=tickets.to_dict("records"))

    T = techs["technician_id"].astype(str).tolist()
    B = tickets["ticket_id"].astype(str).tolist()

    tech_info   = techs.set_index("technician_id")
    ticket_info = tickets.set_index("ticket_id")

    feasible_pairs: List[Tuple[str, str]] = []
    travel: Dict[Tuple[str, str], float]  = {}
    sla_risk: Dict[Tuple[str, str], int]  = {}

    for t in T:
        trow = tech_info.loc[t]
        for b in B:
            brow = ticket_info.loc[b]
            if not regions_match(str(trow["region"]), str(brow["region"]), config):
                continue
            if not skills_match(str(trow["skill_type"]), str(brow["unit_type"])):
                continue
            tt = get_travel_time(
                _safe_float(trow.get("latitude")), _safe_float(trow.get("longitude")),
                _safe_float(brow.get("latitude")), _safe_float(brow.get("longitude")),
                travel_time_matrix, t, b, config.default_travel_time_hours,
            )
            feasible_pairs.append((t, b))
            travel[(t, b)]   = tt
            sla_risk[(t, b)] = 1 if tt > float(brow["response_limit_hours"]) else 0

    feasible_by_ticket: Dict[str, List[str]] = {b: [] for b in B}
    feasible_by_tech:   Dict[str, List[str]] = {t: [] for t in T}
    for t, b in feasible_pairs:
        feasible_by_ticket[b].append(t)
        feasible_by_tech[t].append(b)

    svc   = ticket_info["service_time"].astype(float).to_dict()
    avail = {str(t): min(float(v), REGULAR_DAILY_HOURS) for t, v in tech_info["available_hours"].astype(float).to_dict().items()}

    # Dengeli dağılım: ticket/technisyen oranından soft cap
    max_tpt = config.max_breakdown_tickets_per_tech
    if max_tpt is None:
        max_tpt = max(1, math.ceil(len(B) / max(1, len(T))))

    # ---------- model ----------
    model = gp.Model("breakdown_dispatch")
    model.Params.OutputFlag = 0
    model.Params.TimeLimit  = config.time_limit_seconds
    model.Params.MIPGap     = config.mip_gap

    x        = model.addVars(feasible_pairs, vtype=GRB.BINARY,     name="x")
    overtime = model.addVars(T, lb=0, ub=config.max_breakdown_overtime, vtype=GRB.CONTINUOUS, name="ot")
    idle     = model.addVars(T, lb=0, vtype=GRB.CONTINUOUS,        name="idle")
    miss     = model.addVars(B, vtype=GRB.BINARY,                  name="miss")

    # Balancing: her teknisyen için ticket sayısı değişkeni
    n_assigned = model.addVars(T, lb=0, vtype=GRB.INTEGER, name="n")
    max_load   = model.addVar(lb=0, vtype=GRB.INTEGER, name="max_load")
    min_load   = model.addVar(lb=0, vtype=GRB.INTEGER, name="min_load")

    for t in T:
        count = gp.quicksum(x[t, b] for b in feasible_by_tech[t])
        model.addConstr(n_assigned[t] == count,    name=f"n_{t}")
        model.addConstr(max_load >= n_assigned[t], name=f"maxload_{t}")
        model.addConstr(min_load <= n_assigned[t], name=f"minload_{t}")

    # Kapsama: her ticket tam olarak 1 teknisyene atanır veya miss olur
    for b in B:
        assigned = gp.quicksum(x[t, b] for t in feasible_by_ticket[b])
        model.addConstr(assigned + miss[b] == 1, name=f"cov_{b}")

    # Kapasite + idle
    for t in T:
        total = gp.quicksum((svc[b] + travel[(t, b)]) * x[t, b] for b in feasible_by_tech[t])
        model.addConstr(total <= avail[t] + overtime[t], name=f"cap_{t}")
        model.addConstr(idle[t] >= avail[t] - total,     name=f"idle_{t}")
        # Soft max ticket cap
        model.addConstr(n_assigned[t] <= max_tpt,        name=f"maxtpt_{t}")

    # AA öncelik: AA ticket miss'i diğerlerinden çok daha pahalı (zaten penalty ile)
    # Ek olarak: AA ticket'lar için feasible teknisyen varsa mutlaka atanmalı (soft: çok büyük penalty)
    aa_tickets = [b for b in B if str(ticket_info.loc[b, "failure_type"]) == "AA"]
    for b in aa_tickets:
        if feasible_by_ticket[b]:
            # Eğer en az 1 feasible teknisyen varsa miss'i 0'a zorla (hard constraint)
            model.addConstr(miss[b] == 0, name=f"aa_must_assign_{b}")

    # Missed cost: AA çok daha yüksek
    missed_cost = gp.quicksum(
        (AA_BREAKDOWN_MISSED_PENALTY if str(ticket_info.loc[b, "failure_type"]) == "AA"
         else BREAKDOWN_MISSED_PENALTY) * miss[b]
        for b in B
    )
    sla_cost = gp.quicksum(SLA_VIOLATION_PENALTY * sla_risk[(t, b)] * x[t, b] for t, b in feasible_pairs)
    balance_cost = 500.0 * (max_load - min_load)   # yük dengeleme penalty

    obj = (
        gp.quicksum(LABOR_COST_PER_HOUR   * svc[b]         * x[t, b] for t, b in feasible_pairs)
        + gp.quicksum(TRAVEL_COST_PER_HOUR * travel[(t, b)] * x[t, b] for t, b in feasible_pairs)
        + gp.quicksum(OVERTIME_PENALTY    * overtime[t]               for t in T)
        + gp.quicksum(IDLE_PENALTY        * idle[t]                   for t in T)
        + missed_cost
        + sla_cost
        + balance_cost
    )
    model.setObjective(obj, GRB.MINIMIZE)
    model.optimize()

    if model.status not in {GRB.OPTIMAL, GRB.SUBOPTIMAL, GRB.TIME_LIMIT} or model.SolCount == 0:
        return _empty_result(f"GUROBI_{model.status}", "Breakdown modeli çözüm üretemedi.",
                             unassigned=tickets.to_dict("records"))

    # ---------- sonuçları topla ----------
    assignments: List[Dict[str, Any]] = []
    for t, b in feasible_pairs:
        if x[t, b].X > 0.5:
            brow = ticket_info.loc[b]
            trow = tech_info.loc[t]
            limit = float(brow.get("response_limit_hours", 4.0))
            tt    = float(travel[(t, b)])
            assignments.append({
                "ticket_id":             b,
                "unit_id":               brow.get("unit_id"),
                "unit_name":             brow.get("unit_name"),
                "technician_id":         t,
                "technician_name":       trow.get("technician_name", t),
                "task_type":             "Breakdown",
                "failure_type":          brow.get("failure_type"),
                "unit_type":             brow.get("unit_type"),
                "region":                brow.get("region"),
                "service_time":          float(svc[b]),
                "estimated_travel_time": tt,
                "response_limit_hours":  limit,
                "sla_status":            "OK" if tt <= limit else "RISK",
                "assigned_at":           datetime.now().isoformat(timespec="seconds"),
                "status":                "assigned",
            })

    tech_summary  = _build_tech_summary_breakdown(T, tech_info, assignments, avail, overtime, idle)
    daily_summary = _build_daily_schedule_breakdown(assignments, techs, config)

    unassigned: List[Dict[str, Any]] = []
    for b in B:
        if miss[b].X > 0.5:
            brow = ticket_info.loc[b]
            reason = ("Uygun arıza teknisyeni yok (rol/yetenek/bölge uyuşmazlığı)"
                      if not feasible_by_ticket[b] else
                      "Arıza kapasitesi yetersiz veya max ticket sınırına ulaşıldı")
            unassigned.append({
                "ticket_id":           b,
                "unit_id":             brow.get("unit_id"),
                "unit_name":           brow.get("unit_name"),
                "task_type":           "Breakdown",
                "failure_type":        brow.get("failure_type"),
                "unit_type":           brow.get("unit_type"),
                "region":              brow.get("region"),
                "response_limit_hours":float(brow.get("response_limit_hours", 4.0)),
                "reason":              reason,
            })

    return {
        "assignments":        assignments,
        "technician_summary": tech_summary,
        "daily_summary":      daily_summary,
        "unassigned_tasks":   unassigned,
        "meta": {
            "status":            "OK",
            "mode":              "breakdown",
            "gurobi_status":     int(model.status),
            "objective_value":   round(float(model.ObjVal), 2),
            "total_assignments": len(assignments),
            "unassigned_count":  len(unassigned),
            "aa_tickets":        len(aa_tickets),
            "sla_risk_count":    sum(1 for r in assignments if r["sla_status"] == "RISK"),
            "load_balance":      int(max_load.X - min_load.X),
            "feasible_pairs":    len(feasible_pairs),
        },
    }


# =====================================================
# POST-PROCESSING: GÜNLÜK ÇİZELGE
# =====================================================

def _time_to_minutes(value: Any, default: str) -> int:
    t = parse_time_string(value, pd.to_datetime(default).time())
    return t.hour * 60 + t.minute


def _minutes_to_hhmm(minutes: int) -> str:
    minutes = max(0, minutes) % (24 * 60)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _safe_float(v: Any) -> float:
    try:
        f = float(v)
        return float("nan") if math.isnan(f) else f
    except (TypeError, ValueError):
        return float("nan")


def _build_daily_schedule(
    assignments: List[Dict[str, Any]],
    technicians_df: pd.DataFrame,
    config: SolverConfig,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Aylık atamayı günlük çizelgeye dönüştürür.

    Sıralama mantığı:
      1. Escalator sabah penceresi gerektiren task'lar güne ilk konur (morning_required=YES)
      2. Aynı bölgedeki task'lar kümelenir (seyahat süresi minimize)
      3. Büyük servis süreli task'lar öne alınır (günü verimli doldurur)

    Escalator sabah kontrolü:
      morning_required=YES olan task'lar 08:00-10:00 arasında başlamalı.
      Başlayamazsa time_window_warning=YES işaretlenir.
    """
    if not assignments:
        return assignments, []

    tech_shift = technicians_df.set_index("technician_id")[["shift_start", "shift_end"]].to_dict("index")
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in assignments:
        grouped.setdefault(row["technician_id"], []).append(row)

    lunch_start = _time_to_minutes(config.lunch_start, LUNCH_START_DEFAULT)
    lunch_end   = _time_to_minutes(config.lunch_end,   LUNCH_END_DEFAULT)
    daily_cap   = int(REGULAR_DAILY_HOURS * 60)

    final_rows: List[Dict[str, Any]] = []
    daily_summary: List[Dict[str, Any]] = []

    for tech_id, rows in grouped.items():
        # Sıralama: önce escalator (morning_required=YES), sonra bölge, sonra büyük iş
        rows_sorted = sorted(
            rows,
            key=lambda r: (
                0 if r.get("morning_required") == "YES" else 1,
                str(r.get("region", "")),
                -float(r.get("service_time", 0)),
            ),
        )

        shift_s = _time_to_minutes(tech_shift.get(tech_id, {}).get("shift_start"), SHIFT_START_DEFAULT)
        shift_e = _time_to_minutes(tech_shift.get(tech_id, {}).get("shift_end"),   SHIFT_END_DEFAULT)

        day         = 1
        route_order = 1
        cur         = shift_s
        used_min    = 0
        day_rows: List[Dict[str, Any]] = []

        def close_day() -> None:
            nonlocal day_rows, used_min, day, route_order, cur
            if day_rows:
                idle_h = max(0.0, (daily_cap - used_min) / 60.0)
                daily_summary.append({
                    "technician_id":      tech_id,
                    "work_day":           day,
                    "assigned_task_count":len(day_rows),
                    "used_work_hours":    round(used_min / 60.0, 4),
                    "idle_time_hours":    round(idle_h, 4),
                    "idle_warning":       "YES" if idle_h > IDLE_WARNING_HOURS else "NO",
                    "day_start":          _minutes_to_hhmm(shift_s),
                    "day_end":            _minutes_to_hhmm(shift_e),
                })
            day         += 1
            route_order  = 1
            cur          = shift_s
            used_min     = 0
            day_rows     = []

        for orig in rows_sorted:
            travel_min  = int(round(float(orig.get("travel_time", 0) or 0) * 60))
            service_min = int(round(float(orig.get("service_time", 0) or 0) * 60))
            task_min    = travel_min + service_min

            if task_min > daily_cap:
                row = dict(orig)
                row.update({
                    "work_day": None, "route_order": None,
                    "estimated_travel_start_time": None,
                    "estimated_start_time": None,
                    "estimated_end_time": None,
                    "lunch_break": "NO",
                    "time_window_warning": "YES",
                    "schedule_status": "task_longer_than_daily_capacity",
                })
                final_rows.append(row)
                continue

            if day_rows and used_min + task_min > daily_cap:
                close_day()

            if day > config.working_days_per_month:
                row = dict(orig)
                row.update({
                    "work_day": None, "route_order": None,
                    "estimated_travel_start_time": None,
                    "estimated_start_time": None,
                    "estimated_end_time": None,
                    "lunch_break": "NO",
                    "time_window_warning": "YES",
                    "schedule_status": "no_remaining_work_day_in_month",
                })
                final_rows.append(row)
                continue

            # Öğle paydosunu aşıyorsa öğleden sonraya kaydır
            travel_start = cur
            svc_start    = cur + travel_min
            svc_end      = svc_start + service_min
            lunch_used   = False

            if svc_start < lunch_end and svc_end > lunch_start:
                travel_start = max(cur, lunch_end)
                svc_start    = travel_start + travel_min
                svc_end      = svc_start + service_min
                lunch_used   = True

            if day_rows and svc_end > shift_e:
                close_day()
                travel_start = cur
                svc_start    = cur + travel_min
                svc_end      = svc_start + service_min
                lunch_used   = False
                if svc_start < lunch_end and svc_end > lunch_start:
                    travel_start = max(cur, lunch_end)
                    svc_start    = travel_start + travel_min
                    svc_end      = svc_start + service_min
                    lunch_used   = True

            # Escalator sabah penceresi kontrolü
            is_escalator_morning = orig.get("morning_required") == "YES"
            tw_warning = "YES" if (is_escalator_morning and svc_start > ESCALATOR_WINDOW_END_MIN) else "NO"

            row = dict(orig)
            row.update({
                "work_day":                    day,
                "route_order":                 route_order,
                "estimated_travel_start_time": _minutes_to_hhmm(travel_start),
                "estimated_start_time":        _minutes_to_hhmm(svc_start),
                "estimated_end_time":          _minutes_to_hhmm(svc_end),
                "lunch_break":                 "YES" if lunch_used else "NO",
                "time_window_warning":         tw_warning,
                "schedule_status":             "scheduled",
            })
            final_rows.append(row)
            day_rows.append(row)
            used_min    += task_min
            cur          = svc_end
            route_order += 1

        close_day()

    final_rows.sort(key=lambda r: (
        999 if r.get("work_day") is None else int(r.get("work_day")),
        str(r.get("technician_id", "")),
        999 if r.get("route_order") is None else int(r.get("route_order")),
    ))
    return final_rows, daily_summary


def _build_daily_schedule_breakdown(
    assignments: List[Dict[str, Any]],
    technicians_df: pd.DataFrame,
    config: SolverConfig,
) -> List[Dict[str, Any]]:
    """Breakdown günlük çizelgesi — her teknisyen için tek gün."""
    if not assignments:
        return []

    tech_shift = technicians_df.set_index("technician_id")[["shift_start", "shift_end"]].to_dict("index")
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in assignments:
        grouped.setdefault(row["technician_id"], []).append(row)

    lunch_start = _time_to_minutes(config.lunch_start, LUNCH_START_DEFAULT)
    lunch_end   = _time_to_minutes(config.lunch_end,   LUNCH_END_DEFAULT)

    daily_summary: List[Dict[str, Any]] = []

    for tech_id, rows in grouped.items():
        # AA önce gelsin
        rows_sorted = sorted(rows, key=lambda r: (
            0 if r.get("failure_type") == "AA" else 1,
            r.get("response_limit_hours", 4.0),
        ))

        shift_s = _time_to_minutes(tech_shift.get(tech_id, {}).get("shift_start"), SHIFT_START_DEFAULT)
        shift_e = _time_to_minutes(tech_shift.get(tech_id, {}).get("shift_end"),   SHIFT_END_DEFAULT)
        cur     = shift_s
        used    = 0

        for i, row in enumerate(rows_sorted):
            travel_min  = int(round(float(row.get("estimated_travel_time", 0) or 0) * 60))
            service_min = int(round(float(row.get("service_time", 0) or 0) * 60))
            travel_s = cur
            svc_s    = cur + travel_min
            svc_e    = svc_s + service_min
            if svc_s < lunch_end and svc_e > lunch_start:
                travel_s = max(cur, lunch_end)
                svc_s    = travel_s + travel_min
                svc_e    = svc_s + service_min
            row["dispatch_order"]                = i + 1
            row["estimated_dispatch_start_time"] = _minutes_to_hhmm(travel_s)
            row["estimated_arrival_time"]        = _minutes_to_hhmm(svc_s)
            row["estimated_completion_time"]     = _minutes_to_hhmm(svc_e)
            used += travel_min + service_min
            cur   = svc_e

        idle_h = max(0.0, ((shift_e - shift_s) - used) / 60.0)
        daily_summary.append({
            "technician_id":      tech_id,
            "work_day":           1,
            "assigned_ticket_count": len(rows),
            "used_work_hours":    round(used / 60.0, 4),
            "idle_time_hours":    round(idle_h, 4),
            "idle_warning":       "YES" if idle_h > IDLE_WARNING_HOURS else "NO",
            "day_start":          _minutes_to_hhmm(shift_s),
            "day_end":            _minutes_to_hhmm(shift_e),
        })

    return daily_summary


# =====================================================
# ÖZET YARDIMCILARI
# =====================================================

def _build_tech_summary(
    T, tech_info, assignments, avail, overtime_vars, idle_vars
) -> List[Dict[str, Any]]:
    by_tech: Dict[str, List] = {t: [] for t in T}
    for row in assignments:
        by_tech[row["technician_id"]].append(row)

    summary = []
    for t in T:
        rows  = by_tech[t]
        svc_s = sum(float(r["service_time"]) for r in rows)
        trv_s = sum(float(r["travel_time"])   for r in rows)
        summary.append({
            "technician_id":       t,
            "technician_name":     tech_info.loc[t].get("technician_name", t),
            "role":                tech_info.loc[t].get("role"),
            "skill_type":          tech_info.loc[t].get("skill_type"),
            "region":              tech_info.loc[t].get("region"),
            "assigned_task_count": len(rows),
            "total_service_time":  round(svc_s, 4),
            "total_travel_time":   round(trv_s, 4),
            "total_work_time":     round(svc_s + trv_s, 4),
            "available_hours":     float(avail[t]),
            "overtime_hours":      round(float(overtime_vars[t].X), 4),
            "idle_hours":          round(float(idle_vars[t].X), 4),
            "idle_warning":        "YES" if idle_vars[t].X > IDLE_WARNING_HOURS else "NO",
        })
    return summary


def _build_tech_summary_breakdown(
    T, tech_info, assignments, avail, overtime_vars, idle_vars
) -> List[Dict[str, Any]]:
    by_tech: Dict[str, List] = {t: [] for t in T}
    for row in assignments:
        by_tech[row["technician_id"]].append(row)

    summary = []
    for t in T:
        rows  = by_tech[t]
        svc_s = sum(float(r["service_time"])          for r in rows)
        trv_s = sum(float(r["estimated_travel_time"]) for r in rows)
        summary.append({
            "technician_id":        t,
            "technician_name":      tech_info.loc[t].get("technician_name", t),
            "role":                 tech_info.loc[t].get("role"),
            "skill_type":           tech_info.loc[t].get("skill_type"),
            "region":               tech_info.loc[t].get("region"),
            "assigned_ticket_count":len(rows),
            "aa_tickets":           sum(1 for r in rows if r.get("failure_type") == "AA"),
            "total_service_time":   round(svc_s, 4),
            "total_travel_time":    round(trv_s, 4),
            "total_work_time":      round(svc_s + trv_s, 4),
            "available_hours":      float(avail[t]),
            "overtime_hours":       round(float(overtime_vars[t].X), 4),
            "idle_hours":           round(float(idle_vars[t].X), 4),
            "idle_warning":         "YES" if idle_vars[t].X > IDLE_WARNING_HOURS else "NO",
        })
    return summary


def _empty_result(status: str, message: str, unassigned: List = None) -> Dict[str, Any]:
    return {
        "assignments":        [],
        "technician_summary": [],
        "daily_summary":      [],
        "unassigned_tasks":   unassigned or [],
        "meta":               {"status": status, "message": message},
    }


# =====================================================
# PRECHECK
# =====================================================

def maintenance_precheck(
    technicians_df: pd.DataFrame,
    units_df:       pd.DataFrame,
    tasks:          List[Dict[str, Any]],
) -> Dict[str, Any]:
    tasks_df = pd.DataFrame(tasks)
    svc_total = round(float(tasks_df["service_time"].sum()), 2) if not tasks_df.empty else 0.0
    trv_est   = round(len(tasks_df) * DEFAULT_TRAVEL_TIME_HOURS, 2) if not tasks_df.empty else 0.0

    maint_mask = technicians_df["role"].isin(["Maintenance", "Both"]) if not technicians_df.empty else pd.Series(dtype=bool)
    br_mask    = technicians_df["role"].isin(["Breakdown", "Both"]) if not technicians_df.empty else pd.Series(dtype=bool)

    cap = round(float(technicians_df.loc[maint_mask, "available_hours"].sum()), 2) if not technicians_df.empty else 0.0

    return {
        "technicians_total":          len(technicians_df),
        "maintenance_technicians":    int(maint_mask.sum()) if not technicians_df.empty else 0,
        "breakdown_technicians":      int(br_mask.sum()) if not technicians_df.empty else 0,
        "units_total":                len(units_df),
        "monthly_capacity_per_tech":  MONTHLY_CAPACITY_HOURS,
        "tasks_generated":            len(tasks_df),
        "package_counts":             tasks_df["maintenance_package"].value_counts().to_dict() if not tasks_df.empty else {},
        "operation_count_A":          int(tasks_df["operation_count_A"].sum()) if "operation_count_A" in tasks_df else 0,
        "operation_count_B":          int(tasks_df["operation_count_B"].sum()) if "operation_count_B" in tasks_df else 0,
        "operation_count_C":          int(tasks_df["operation_count_C"].sum()) if "operation_count_C" in tasks_df else 0,
        "morning_required_tasks":     int((tasks_df.get("morning_required", pd.Series(dtype=str)) == "YES").sum()) if not tasks_df.empty else 0,
        "avm_escalator_tasks":        int((tasks_df.get("avm_escalator", pd.Series(dtype=str)) == "YES").sum()) if not tasks_df.empty else 0,
        "total_service_hours":        svc_total,
        "estimated_travel_hours":     trv_est,
        "total_required_hours":       round(svc_total + trv_est, 2),
        "total_capacity_hours":       cap,
        "capacity_surplus_hours":     round(cap - svc_total - trv_est, 2),
        "tech_skill_dist_all":        technicians_df["skill_type"].value_counts().to_dict() if not technicians_df.empty else {},
        "maintenance_skill_dist":     technicians_df.loc[maint_mask, "skill_type"].value_counts().to_dict() if not technicians_df.empty else {},
        "breakdown_skill_dist":       technicians_df.loc[br_mask, "skill_type"].value_counts().to_dict() if not technicians_df.empty else {},
        "role_skill_crosscheck":      technicians_df.groupby(["role", "skill_type"]).size().to_dict() if not technicians_df.empty else {},
        "tech_region_dist":           technicians_df["region"].value_counts().to_dict() if not technicians_df.empty else {},
        "unit_type_dist":             units_df["unit_type"].value_counts().to_dict() if not units_df.empty else {},
        "unit_region_dist":           units_df["region"].value_counts().to_dict() if not units_df.empty else {},
    }

# =====================================================
# EXCEL YARDIMCILARI (YEREL TEST)
# =====================================================

def read_excel_records(path: Path) -> List[Dict[str, Any]]:
    all_sheets = pd.read_excel(path, sheet_name=None)
    df = pd.concat(all_sheets.values(), ignore_index=True)
    return df.to_dict("records")


def build_daily_timeline_rows(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Output'u okunabilir hale getiren timeline üretir.
    Travel, Maintenance/Breakdown Service ve Lunch Break ayrı ayrı satır olur.
    """
    rows: List[Dict[str, Any]] = []
    assignments = result.get("assignments", []) or []
    mode = (result.get("meta", {}) or {}).get("mode", "")

    seen_lunch = set()

    for a in assignments:
        if a.get("task_type") == "Maintenance" or mode == "maintenance":
            tech = a.get("technician_name") or a.get("technician_id")
            tech_id = a.get("technician_id")
            day = a.get("work_day")
            route_order = a.get("route_order")
            unit_id = a.get("unit_id")
            unit_name = a.get("unit_name")

            # Lunch ayrı satır olarak gösterilsin.
            if a.get("lunch_break") == "YES" and day is not None:
                key = (tech_id, day)
                if key not in seen_lunch:
                    seen_lunch.add(key)
                    rows.append({
                        "technician_id": tech_id,
                        "technician_name": tech,
                        "work_day": day,
                        "route_order": route_order,
                        "time_start": LUNCH_START_DEFAULT,
                        "time_end": LUNCH_END_DEFAULT,
                        "activity_type": "Lunch Break",
                        "unit_id": "",
                        "unit_name": "",
                        "detail": "Lunch break",
                        "duration_hours": 1.0,
                        "region": a.get("region"),
                        "status": "scheduled",
                    })

            if a.get("estimated_travel_start_time") and a.get("estimated_start_time"):
                rows.append({
                    "technician_id": tech_id,
                    "technician_name": tech,
                    "work_day": day,
                    "route_order": route_order,
                    "time_start": a.get("estimated_travel_start_time"),
                    "time_end": a.get("estimated_start_time"),
                    "activity_type": "Travel",
                    "unit_id": unit_id,
                    "unit_name": unit_name,
                    "detail": f"Travel to unit {unit_id}",
                    "duration_hours": a.get("travel_time"),
                    "region": a.get("region"),
                    "status": a.get("schedule_status", a.get("status")),
                })

            if a.get("estimated_start_time") and a.get("estimated_end_time"):
                rows.append({
                    "technician_id": tech_id,
                    "technician_name": tech,
                    "work_day": day,
                    "route_order": route_order,
                    "time_start": a.get("estimated_start_time"),
                    "time_end": a.get("estimated_end_time"),
                    "activity_type": "Maintenance",
                    "unit_id": unit_id,
                    "unit_name": unit_name,
                    "detail": f"{a.get('maintenance_package')} maintenance",
                    "duration_hours": a.get("service_time"),
                    "region": a.get("region"),
                    "status": a.get("schedule_status", a.get("status")),
                    "time_window_warning": a.get("time_window_warning"),
                })

        else:
            # Breakdown timeline
            tech = a.get("technician_name") or a.get("technician_id")
            tech_id = a.get("technician_id")
            ticket_id = a.get("ticket_id")
            unit_id = a.get("unit_id")
            unit_name = a.get("unit_name")
            order = a.get("dispatch_order")

            if a.get("estimated_dispatch_start_time") and a.get("estimated_arrival_time"):
                rows.append({
                    "technician_id": tech_id,
                    "technician_name": tech,
                    "work_day": 1,
                    "route_order": order,
                    "time_start": a.get("estimated_dispatch_start_time"),
                    "time_end": a.get("estimated_arrival_time"),
                    "activity_type": "Travel",
                    "ticket_id": ticket_id,
                    "unit_id": unit_id,
                    "unit_name": unit_name,
                    "detail": f"Travel to breakdown {ticket_id}",
                    "duration_hours": a.get("estimated_travel_time"),
                    "region": a.get("region"),
                    "status": a.get("status"),
                    "sla_status": a.get("sla_status"),
                })

            if a.get("estimated_arrival_time") and a.get("estimated_completion_time"):
                rows.append({
                    "technician_id": tech_id,
                    "technician_name": tech,
                    "work_day": 1,
                    "route_order": order,
                    "time_start": a.get("estimated_arrival_time"),
                    "time_end": a.get("estimated_completion_time"),
                    "activity_type": "Breakdown Service",
                    "ticket_id": ticket_id,
                    "unit_id": unit_id,
                    "unit_name": unit_name,
                    "detail": f"{a.get('failure_type')} breakdown service",
                    "duration_hours": a.get("service_time"),
                    "region": a.get("region"),
                    "status": a.get("status"),
                    "sla_status": a.get("sla_status"),
                })

    def sort_key(r: Dict[str, Any]):
        return (
            999 if r.get("work_day") in [None, ""] else int(r.get("work_day")),
            str(r.get("technician_name", "")),
            999 if r.get("route_order") in [None, ""] else int(r.get("route_order")),
            str(r.get("time_start", "")),
            str(r.get("activity_type", "")),
        )
    return sorted(rows, key=sort_key)


def build_unassigned_summary_rows(unassigned: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Unassigned taskları 20.000 satır basmak yerine okunabilir özet haline getirir.
    Backend yine result["unassigned_tasks"] listesini kullanabilir; bu sadece Excel çıktısı için.
    """
    if not unassigned:
        return []
    df = pd.DataFrame(unassigned)
    if df.empty:
        return []

    # Farklı versiyonlardaki kolon adlarını normalize et.
    if "maintenance_package" not in df.columns and "maintenance_type" in df.columns:
        df["maintenance_package"] = df["maintenance_type"]
    if "maintenance_package" not in df.columns:
        df["maintenance_package"] = df.get("task_type", "Unknown")
    if "region" not in df.columns:
        df["region"] = "Unknown"
    if "unit_type" not in df.columns:
        df["unit_type"] = "Unknown"
    if "reason" not in df.columns:
        df["reason"] = "Unknown"
    if "service_time" not in df.columns:
        df["service_time"] = 0.0
    if "travel_time" not in df.columns:
        df["travel_time"] = DEFAULT_TRAVEL_TIME_HOURS

    df["service_time"] = pd.to_numeric(df["service_time"], errors="coerce").fillna(0.0)
    df["travel_time"] = pd.to_numeric(df["travel_time"], errors="coerce").fillna(DEFAULT_TRAVEL_TIME_HOURS)
    df["required_hours_est"] = df["service_time"] + df["travel_time"]

    group_cols = ["maintenance_package", "region", "unit_type", "reason"]
    out = (
        df.groupby(group_cols, dropna=False)
          .agg(unassigned_count=("reason", "size"), required_hours_est=("required_hours_est", "sum"))
          .reset_index()
          .sort_values(["unassigned_count", "required_hours_est"], ascending=False)
    )
    out["required_hours_est"] = out["required_hours_est"].round(2)
    return out.to_dict("records")


def sample_unassigned_rows(unassigned: List[Dict[str, Any]], max_rows: Optional[int] = None) -> List[Dict[str, Any]]:
    """Excel için unassigned listesini döndürür. v12'de full liste basılır."""
    if not unassigned:
        return []
    if max_rows is None:
        return list(unassigned)
    return list(unassigned[:max_rows])


def export_result_to_excel(result: Dict[str, Any], output_file: Path) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        adf = pd.DataFrame(result.get("assignments", []))
        if not adf.empty:
            sort_cols = [c for c in ["work_day", "technician_id", "route_order", "dispatch_order"]
                         if c in adf.columns]
            if sort_cols:
                adf = adf.sort_values(sort_cols, na_position="last")

        timeline_df = pd.DataFrame(build_daily_timeline_rows(result))
        if not timeline_df.empty:
            sort_cols = [c for c in ["work_day", "time_start", "technician_name", "route_order", "activity_type"]
                         if c in timeline_df.columns]
            timeline_df = timeline_df.sort_values(sort_cols, na_position="last")

        adf.to_excel(writer, sheet_name="Assignments", index=False)
        timeline_df.to_excel(writer, sheet_name="Daily_Timeline", index=False)
        pd.DataFrame(result.get("technician_summary", [])).to_excel(writer, sheet_name="Technician_Summary", index=False)
        pd.DataFrame(result.get("daily_summary", [])).to_excel(writer, sheet_name="Daily_Summary", index=False)

        unassigned = result.get("unassigned_tasks", []) or []
        pd.DataFrame(build_unassigned_summary_rows(unassigned)).to_excel(writer, sheet_name="Unassigned_Summary", index=False)
        pd.DataFrame(sample_unassigned_rows(unassigned, max_rows=None)).to_excel(writer, sheet_name="Unassigned_Tasks", index=False)

        meta = dict(result.get("meta", {}) or {})
        meta["unassigned_full_list_note"] = "v12: Excel'de tüm unassigned tasklar Unassigned_Tasks sheetine basılıyor."
        pd.DataFrame([meta]).to_excel(writer, sheet_name="Meta", index=False)


def generate_demo_breakdown_tickets(
    unit_records: Iterable[Mapping[str, Any]],
    count: int = 50,
    aa_count: int = 5,
    seed: int = 42,
) -> List[Dict[str, Any]]:
    units_df = units_to_dataframe(unit_records)
    if units_df.empty:
        return []

    rng          = random.Random(seed)
    desired      = min(count, len(units_df))
    shuffled     = units_df.sample(frac=1, random_state=seed).reset_index(drop=True)

    avail_regions = [r for r in ["Asia", "Europe"] if (shuffled["region"] == r).any()]
    if len(avail_regions) == 2:
        quotas = {"Asia": desired // 2 + desired % 2, "Europe": desired // 2}
    elif len(avail_regions) == 1:
        quotas = {avail_regions[0]: desired}
    else:
        quotas = {"Unknown": desired}

    selected: List[Dict] = []
    used_ids:  set = set()
    used_names: set = set()

    def try_add(pool, quota, avoid_dup_name=True) -> int:
        added = 0
        for _, row in pool.iterrows():
            if added >= quota:
                break
            uid  = str(row.get("unit_id"))
            name = str(row.get("unit_name", "")).strip().lower()
            if uid in used_ids:
                continue
            if avoid_dup_name and name and name in used_names:
                continue
            selected.append(row.to_dict())
            used_ids.add(uid)
            if name:
                used_names.add(name)
            added += 1
        return added

    missing = 0
    for region, quota in quotas.items():
        pool  = shuffled if region == "Unknown" else shuffled[shuffled["region"] == region]
        added = try_add(pool, quota, avoid_dup_name=True)
        missing += quota - added
    if missing > 0:
        try_add(shuffled, missing, avoid_dup_name=False)
    if len(selected) < desired:
        try_add(shuffled, desired - len(selected), avoid_dup_name=False)

    sel_df = pd.DataFrame(selected).drop_duplicates("unit_id").head(desired).reset_index(drop=True)

    failure_types = ["AA"] * min(aa_count, desired)
    normal_cycle  = ["A", "B", "C", "D"]
    failure_types += [normal_cycle[i % 4] for i in range(desired - len(failure_types))]
    rng.shuffle(failure_types)

    rows: List[Dict[str, Any]] = []
    now = datetime.now().replace(microsecond=0)
    for i, (_, unit) in enumerate(sel_df.iterrows(), 1):
        ft = failure_types[i - 1]
        rows.append({
            "ticket_id":            f"BD-{now.strftime('%Y%m%d')}-{i:03d}",
            "unit_id":              unit["unit_id"],
            "unit_name":            unit.get("unit_name"),
            "unit_type":            unit.get("unit_type"),
            "region":               unit.get("region"),
            "failure_type":         ft,
            "created_at":           now.isoformat(sep=" "),
            "response_limit_hours": CALLBACK_SLA_HOURS.get(ft, 4.0),
            "service_time":         DEFAULT_BREAKDOWN_SERVICE_TIME,
            "status":               "open",
        })
    return rows


# =====================================================
# CLI
# =====================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="Capstone Gurobi Optimizer v13")
    parser.add_argument("--mode", choices=["maintenance", "breakdown", "generate_breakdowns"], default="maintenance")
    parser.add_argument("--technicians", default="data/technicians.xlsx")
    parser.add_argument("--units",       default="data/units.xlsx")
    parser.add_argument("--breakdowns",  default="data/breakdown_tickets.xlsx")
    parser.add_argument("--output",      default="results/optimization_result_v11.xlsx")
    parser.add_argument("--month",       default=None,
                        help="Bakım planı ayı: YYYY-MM formatında (örn: 2026-01). None ise bu ay.")
    parser.add_argument("--precheck",    action="store_true")
    parser.add_argument("--combine-rule",choices=["sum", "max"], default="sum")
    parser.add_argument("--breakdown-count", type=int, default=50)
    parser.add_argument("--aa-count",        type=int, default=5)
    parser.add_argument("--max-breakdown-tickets-per-tech", type=int, default=None)
    parser.add_argument("--seed",            type=int, default=42)
    parser.add_argument("--unit-limit",      type=int, default=None,
                        help="Demo/test için ilk N üniteyi kullanır. Full 20k yerine hızlı test sağlar.")
    parser.add_argument("--region-filter",   default="All", choices=["All", "Asia", "Europe"],
                        help="Demo/test için sadece seçilen bölgedeki üniteleri kullanır.")
    parser.add_argument("--unit-type-filter", default="All", choices=["All", "Elevator", "Escalator"],
                        help="Demo/test için sadece seçilen unit type kullanılır.")
    args = parser.parse_args()

    config = SolverConfig(
        maintenance_combine_rule=args.combine_rule,
        max_breakdown_tickets_per_tech=args.max_breakdown_tickets_per_tech,
    )

    tech_file = Path(args.technicians)
    unit_file = Path(args.units)
    bd_file   = Path(args.breakdowns)
    out_file  = Path(args.output)

    if not tech_file.exists():
        raise FileNotFoundError(f"Teknisyen dosyası bulunamadı: {tech_file}")
    if not unit_file.exists():
        raise FileNotFoundError(f"Ünite dosyası bulunamadı: {unit_file}")

    tech_records = read_excel_records(tech_file)
    unit_records = read_excel_records(unit_file)
    techs_df     = technicians_to_dataframe(tech_records, config)
    units_df     = units_to_dataframe(unit_records)

    # Demo/test hızlandırma filtreleri. Production backend entegrasyonunda kullanılmaz;
    # backend zaten solver'a ilgili Unit/Task kayıtlarını verir.
    if args.region_filter != "All":
        units_df = units_df[units_df["region"] == args.region_filter].copy()
    if args.unit_type_filter != "All":
        units_df = units_df[units_df["unit_type"] == args.unit_type_filter].copy()
    if args.unit_limit is not None:
        units_df = units_df.head(args.unit_limit).copy()
    unit_records = units_df.to_dict("records")

    # ---- generate_breakdowns ----
    if args.mode == "generate_breakdowns":
        tickets = generate_demo_breakdown_tickets(unit_records, args.breakdown_count, args.aa_count, args.seed)
        bd_file.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(tickets).to_excel(bd_file, index=False)
        print(f"Demo breakdown bileti oluşturuldu: {bd_file}")
        print(f"Toplam: {len(tickets)}  |  AA: {sum(1 for t in tickets if t['failure_type'] == 'AA')}")
        return

    # ---- maintenance ----
    if args.mode == "maintenance":
        tasks = generate_maintenance_tasks_for_month(units_df, plan_month=args.month, config=config)
        if args.precheck:
            pc = maintenance_precheck(techs_df, units_df, tasks)
            print("\n=== PRECHECK ===")
            for k, v in pc.items():
                print(f"  {k}: {v}")
            print("\nPrecheck tamamlandı. Gurobi başlatılmadı.")
            return
        result = solve_maintenance(tech_records, tasks, config=config)
        export_result_to_excel(result, out_file)
        m = result["meta"]
        print(f"\nBakım optimizasyonu tamamlandı → {out_file}")
        print(f"  Durum          : {m.get('status')}")
        print(f"  Atama          : {m.get('total_assignments')}")
        print(f"  Atanmayan      : {m.get('unassigned_count')}")
        print(f"  Aylık kapasite : {m.get('monthly_capacity_hours')} saat/teknisyen")
        print(f"  Objective      : {m.get('objective_value')}")
        return

    # ---- breakdown ----
    if args.mode == "breakdown":
        if not bd_file.exists():
            raise FileNotFoundError(
                f"Breakdown dosyası bulunamadı: {bd_file}. "
                "Önce --mode generate_breakdowns çalıştırın."
            )
        ticket_records = read_excel_records(bd_file)
        if args.precheck:
            tdf = breakdown_tickets_to_dataframe(ticket_records, unit_records)
            print("\n=== PRECHECK (BREAKDOWN) ===")
            print(f"  Toplam teknisyen   : {len(techs_df)}")
            print(f"  Arıza teknisyeni   : {techs_df['role'].isin(['Breakdown','Both']).sum()}")
            print(f"  Açık bilet         : {len(tdf)}")
            print(f"  Failure dağılımı   : {tdf['failure_type'].value_counts().to_dict()}")
            print(f"  Bölge dağılımı     : {tdf['region'].value_counts().to_dict()}")
            print("\nPrecheck tamamlandı. Gurobi başlatılmadı.")
            return
        result = solve_breakdown(tech_records, ticket_records, unit_records=unit_records, config=config)
        export_result_to_excel(result, out_file)
        m = result["meta"]
        print(f"\nArıza dispatch tamamlandı → {out_file}")
        print(f"  Durum       : {m.get('status')}")
        print(f"  Atama       : {m.get('total_assignments')}")
        print(f"  Atanmayan   : {m.get('unassigned_count')}")
        print(f"  AA bilet    : {m.get('aa_tickets')}")
        print(f"  SLA riski   : {m.get('sla_risk_count')}")
        print(f"  Yük dengesi : {m.get('load_balance')} (max-min ticket farkı)")
        return


if __name__ == "__main__":
    main()

def solve_maintenance_from_records(
    technician_records,
    task_records,
    travel_time_matrix=None,
    config=SolverConfig(),
):
    return solve_maintenance(
        technician_records=technician_records,
        task_records=task_records,
        travel_time_matrix=travel_time_matrix,
        config=config,
    )


def solve_breakdown_from_records(
    technician_records,
    ticket_records,
    unit_records=None,
    travel_time_matrix=None,
    config=SolverConfig(),
):
    return solve_breakdown(
        technician_records=technician_records,
        ticket_records=ticket_records,
        unit_records=unit_records,
        travel_time_matrix=travel_time_matrix,
        config=config,
    )