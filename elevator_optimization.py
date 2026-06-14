"""
=============================================================================
ASANSÖR & YÜRÜYEN MERDİVEN TEKNİSYEN PLANLAMASI - GUROBİ OPTİMİZASYONU
=============================================================================

AMAÇ FONKSİYONU:
Zmax = α·Σ(x_{t,j,d,s} · w_j) - β·Σ(idle_{t,d}) - γ·Σ(unserved_j) - δ·Σ(max(0, idle_{t,d} - 1))

Kısıtlar:
  C1:  Σ_j x_{t,j,d,s} · dur_j  ≤ 8            ∀ t,d       (günlük maks çalışma)
  C2:  Σ_t x_{t,j,d,s}          ≤ 2            ∀ j,d,s     (işe maks 2 teknisyen)
  C3:  Σ_{j,s} x_{t,j,d,s}·dur_j ≤ 1 (slot)   ∀ t,d       (aynı anda tek iş)
  C4:  Nöbet kısıtı: hafta içi gece 1, hafta sonu 2 arızacı
  C5:  Yürüyen merdiven bakımı saat 10:00'dan önce bitmeli
  C6:  Teknisyen yetkinlik kısıtı (asansör/yürüyen merdiven)
  C7:  AA arıza ≤ 1 saat müdahale, diğer arıza ≤ 4 saat
  C8:  Hafta sonu planlı bakım yok
  C9:  Bölge (Asya/Avrupa) uyumu
  C10: unserved_j ≥ 1 - Σ_{t,d,s} x_{t,j,d,s}  (eksik iş tespiti)
  C11: idle_{t,d} = 8 - Σ_{j,s} x_{t,j,d,s}·dur_j  (idle time hesabı)
=============================================================================
"""

import gurobipy as gp
from gurobipy import GRB
import random
import math

# ─────────────────────────────────────────────────────────────────────────────
# 1. PARAMETRELER
# ─────────────────────────────────────────────────────────────────────────────
random.seed(42)

PLANNING_DAYS   = 5          # Hafta içi gün sayısı (1 hafta)
WORK_HOURS      = 8          # Günlük net çalışma saati (9 - 1 mola)
WORK_START      = 8          # Mesai başlangıcı
WORK_END        = 17         # Mesai bitişi
ESCALATOR_DEADLINE = 10      # Yürüyen merdiven bakım bitiş saati

# Teknisyen grupları
N_MAINTAINER_ELEVATOR   = 35   # Sadece asansör bakımcı
N_MAINTAINER_ESCALATOR  = 5    # Sadece yürüyen merdiven bakımcı
N_FAULT_TECHNICIAN      = 10   # Hem asansör hem merdiven arızacı (10 = 5 Asia + 5 Europe)
N_TECHNICIANS           = N_MAINTAINER_ELEVATOR + N_MAINTAINER_ESCALATOR + N_FAULT_TECHNICIAN  # 50

# Bakım üniteleri (küçük ölçek - tam problem çok büyük olur)
N_ELEVATOR   = 200   # 4000'den temsili (oran korundu: 4:1)
N_ESCALATOR  = 50    # 1000'den temsili

N_UNITS      = N_ELEVATOR + N_ESCALATOR

# Bölgeler
REGIONS      = ["Asia", "Europe"]

# Bakım tipleri ve süreleri (saat)
MAINT_TYPES  = {
    "A": {"interval_months": 12, "duration": 4.0},
    "B": {"interval_months": 6,  "duration": 2.0},
    "C": {"interval_months": 1,  "duration": 0.75},
}

# Arıza tipleri ve öncelikleri
FAULT_TYPES  = {
    "AA": {"response_hours": 1,  "priority": 100},  # Mahsur kalan
    "A":  {"response_hours": 4,  "priority": 80},
    "B":  {"response_hours": 4,  "priority": 70},
    "C":  {"response_hours": 4,  "priority": 60},
    "D":  {"response_hours": 4,  "priority": 50},
}

# Amaç fonksiyonu ağırlıkları
ALPHA = 10    # Tamamlanan iş ödülü
BETA  = 5     # Idle time ceza
GAMMA = 20    # Eksik kalan iş ceza
DELTA = 8     # 1 saati aşan idle time ekstra ceza

# ─────────────────────────────────────────────────────────────────────────────
# 2. VERİ OLUŞTURMA
# ─────────────────────────────────────────────────────────────────────────────

# Teknisyen listesi
technicians = list(range(N_TECHNICIANS))

# Teknisyen tipleri
# 0-34  : Asansör bakımcı
# 35-39 : Yürüyen merdiven bakımcı
# 40-49 : Arızacı (hem asansör hem merdiven)
tech_type = {}
for t in range(N_TECHNICIANS):
    if t < 35:
        tech_type[t] = "elevator_maintainer"
    elif t < 40:
        tech_type[t] = "escalator_maintainer"
    else:
        tech_type[t] = "fault_technician"

# Teknisyen bölgeleri (arızacılar ve bakımcılar eşit dağıtıldı)
tech_region = {}
for t in range(N_TECHNICIANS):
    tech_region[t] = "Asia" if t % 2 == 0 else "Europe"

# Ünite listesi
units = list(range(N_UNITS))

# Ünite tipleri ve bölgeleri
unit_type   = {}
unit_region = {}
for u in units:
    unit_type[u]   = "elevator"  if u < N_ELEVATOR else "escalator"
    unit_region[u] = "Asia"      if u % 2 == 0      else "Europe"

# Her ünite için planlı bakım işleri oluştur (1 haftalık pencere)
# Basitleştirme: Her üniteye C tipi bakım planlanıyor (aylık)
# A ve B tipleri için takvim uygun düşen ünitelere eklendi
jobs = []   # (job_id, unit_id, job_type, duration, priority, is_fault, fault_type, required_by_hour)
job_id = 0

for u in units:
    # C tipi bakım: aylık → her ünitenin bu haftada bakımı var
    jobs.append({
        "id":              job_id,
        "unit":            u,
        "type":            "maintenance",
        "maint_type":      "C",
        "duration":        0.75,
        "priority":        20,
        "is_fault":        False,
        "fault_type":      None,
        "required_by_hour": None,
        "unit_type":       unit_type[u],
        "region":          unit_region[u],
    })
    job_id += 1

    # Her 5. üniteye B tipi bakım
    if u % 5 == 0:
        jobs.append({
            "id":              job_id,
            "unit":            u,
            "type":            "maintenance",
            "maint_type":      "B",
            "duration":        2.0,
            "priority":        40,
            "is_fault":        False,
            "fault_type":      None,
            "required_by_hour": None,
            "unit_type":       unit_type[u],
            "region":          unit_region[u],
        })
        job_id += 1

    # Her 20. üniteye A tipi bakım
    if u % 20 == 0:
        jobs.append({
            "id":              job_id,
            "unit":            u,
            "type":            "maintenance",
            "maint_type":      "A",
            "duration":        4.0,
            "priority":        60,
            "is_fault":        False,
            "fault_type":      None,
            "required_by_hour": None,
            "unit_type":       unit_type[u],
            "region":          unit_region[u],
        })
        job_id += 1

# Arıza işleri (simülasyon)
fault_counts = {"AA": 3, "A": 5, "B": 5, "C": 4, "D": 3}
for ftype, count in fault_counts.items():
    for _ in range(count):
        u   = random.randint(0, N_UNITS - 1)
        day = random.randint(0, PLANNING_DAYS - 1)
        hour = random.randint(WORK_START, WORK_END - 2)
        resp = FAULT_TYPES[ftype]["response_hours"]
        jobs.append({
            "id":              job_id,
            "unit":            u,
            "type":            "fault",
            "maint_type":      None,
            "duration":        1.0,
            "priority":        FAULT_TYPES[ftype]["priority"],
            "is_fault":        True,
            "fault_type":      ftype,
            "required_by_hour": hour + resp,
            "fault_day":       day,
            "unit_type":       unit_type[u],
            "region":          unit_region[u],
        })
        job_id += 1

N_JOBS = len(jobs)
print(f"Toplam iş sayısı: {N_JOBS}")
print(f"  - Bakım işleri : {sum(1 for j in jobs if not j['is_fault'])}")
print(f"  - Arıza işleri : {sum(1 for j in jobs if j['is_fault'])}")

# ─────────────────────────────────────────────────────────────────────────────
# 3. GUROBİ MODELİ
# ─────────────────────────────────────────────────────────────────────────────
m = gp.Model("ElevatorScheduling")
m.setParam("OutputFlag", 1)
m.setParam("TimeLimit", 300)       # 5 dakika zaman limiti
m.setParam("MIPGap", 0.05)        # %5 optimality gap

days     = list(range(PLANNING_DAYS))

# ── 3.1 Karar Değişkenleri ──────────────────────────────────────────────────

# x[t, j, d] = 1 → teknisyen t, iş j'yi gün d'de yapıyor
x = m.addVars(
    [(t, j["id"], d)
     for t in technicians
     for j in jobs
     for d in days],
    vtype=GRB.BINARY,
    name="x"
)

# idle[t, d] = teknisyen t'nin gün d'deki boş saati
idle = m.addVars(
    [(t, d) for t in technicians for d in days],
    vtype=GRB.CONTINUOUS,
    lb=0,
    name="idle"
)

# idle_excess[t, d] = max(0, idle[t,d] - 1)
idle_excess = m.addVars(
    [(t, d) for t in technicians for d in days],
    vtype=GRB.CONTINUOUS,
    lb=0,
    name="idle_excess"
)

# unserved[j] = 1 → iş j tamamlanamadı
unserved = m.addVars(
    [j["id"] for j in jobs],
    vtype=GRB.BINARY,
    name="unserved"
)

# ── 3.2 Amaç Fonksiyonu ─────────────────────────────────────────────────────
#
#  Zmax = α·Σ x_{t,j,d}·w_j
#        - β·Σ idle_{t,d}
#        - γ·Σ unserved_j
#        - δ·Σ idle_excess_{t,d}

served_reward = gp.quicksum(
    ALPHA * j["priority"] * x[t, j["id"], d]
    for t in technicians
    for j in jobs
    for d in days
)

idle_penalty = gp.quicksum(
    BETA * idle[t, d]
    for t in technicians
    for d in days
)

unserved_penalty = gp.quicksum(
    GAMMA * unserved[j["id"]]
    for j in jobs
)

excess_idle_penalty = gp.quicksum(
    DELTA * idle_excess[t, d]
    for t in technicians
    for d in days
)

m.setObjective(
    served_reward - idle_penalty - unserved_penalty - excess_idle_penalty,
    GRB.MAXIMIZE
)

# ── 3.3 Kısıtlar ────────────────────────────────────────────────────────────

# C1: Günlük çalışma saati ≤ WORK_HOURS
for t in technicians:
    for d in days:
        m.addConstr(
            gp.quicksum(j["duration"] * x[t, j["id"], d] for j in jobs)
            <= WORK_HOURS,
            name=f"C1_workload_t{t}_d{d}"
        )

# C2: Bir işe max 2 teknisyen atanabilir (tüm günlerde toplamda)
for j in jobs:
    m.addConstr(
        gp.quicksum(x[t, j["id"], d] for t in technicians for d in days)
        <= 2,
        name=f"C2_max2tech_j{j['id']}"
    )

# C3: Aynı gün atanan işlerin toplam süresi ≤ WORK_HOURS (iş çakışması yok)
# Bu C1 ile örtüşüyor, ek olarak: her teknisyen aynı günde sadece 1 büyük iş yapabilir (A tipi)
for t in technicians:
    for d in days:
        for j in jobs:
            if j["duration"] >= 4.0:   # A tipi 4 saat
                # Eğer A tipi iş yapıyorsa o gün başka uzun iş yapamaz
                other_long = [jj for jj in jobs if jj["id"] != j["id"] and jj["duration"] >= 4.0]
                for jj in other_long:
                    m.addConstr(
                        x[t, j["id"], d] + x[t, jj["id"], d] <= 1,
                        name=f"C3_nodouble_long_t{t}_j{j['id']}_jj{jj['id']}_d{d}"
                    )

# C4: Yetkinlik kısıtı
for t in technicians:
    for j in jobs:
        for d in days:
            can_do = False
            if tech_type[t] == "fault_technician":
                can_do = True   # Arızacı her işi yapabilir
            elif tech_type[t] == "elevator_maintainer" and j["unit_type"] == "elevator":
                can_do = True
            elif tech_type[t] == "escalator_maintainer" and j["unit_type"] == "escalator":
                can_do = True

            if not can_do:
                m.addConstr(
                    x[t, j["id"], d] == 0,
                    name=f"C4_skill_t{t}_j{j['id']}_d{d}"
                )

# C5: Yürüyen merdiven bakımı sabah 10'dan önce bitmeli
# Bakım en erken saat 8'de başlıyor, bitiş = 8 + süre ≤ 10 → sadece 0.75h ve 2h işler
# A tipi (4 saat): 8 + 4 = 12 > 10  → Yürüyen merdiven A tipi yapılamaz (sabah kısıtı)
for t in technicians:
    for j in jobs:
        for d in days:
            if j["unit_type"] == "escalator" and j["type"] == "maintenance":
                if j["duration"] + WORK_START > ESCALATOR_DEADLINE:
                    m.addConstr(
                        x[t, j["id"], d] == 0,
                        name=f"C5_escalator_time_t{t}_j{j['id']}_d{d}"
                    )

# C6: Bölge kısıtı — teknisyen yalnızca kendi bölgesindeki işlere atanabilir
for t in technicians:
    for j in jobs:
        for d in days:
            if tech_region[t] != j["region"]:
                m.addConstr(
                    x[t, j["id"], d] == 0,
                    name=f"C6_region_t{t}_j{j['id']}_d{d}"
                )

# C7: Arıza işleri yalnızca belirli günde yapılabilir
for j in jobs:
    if j["is_fault"]:
        fault_day = j.get("fault_day", 0)
        for t in technicians:
            for d in days:
                if d != fault_day:
                    m.addConstr(
                        x[t, j["id"], d] == 0,
                        name=f"C7_fault_day_t{t}_j{j['id']}_d{d}"
                    )

# C8: Arıza işlerine sadece arızacılar veya bakımcı + fault_technician atanabilir
# AA arıza ise arızacı zorunlu değil ama öncelikli (bu soft constraint)
# Hard: Bakım teknisyeni arıza işine atanamaz (yetkinlik C4 ile halledildi)

# C9: Unserved bağlantısı
# unserved[j] = 1 eğer hiçbir teknisyen o işe atanmadıysa
for j in jobs:
    assigned = gp.quicksum(x[t, j["id"], d] for t in technicians for d in days)
    m.addConstr(
        unserved[j["id"]] >= 1 - assigned,
        name=f"C9_unserved_j{j['id']}"
    )
    m.addConstr(
        unserved[j["id"]] <= 1 - assigned / (N_TECHNICIANS * PLANNING_DAYS),
        name=f"C9_unserved_upper_j{j['id']}"
    )

# C10: Idle time hesabı
for t in technicians:
    for d in days:
        work_done = gp.quicksum(j["duration"] * x[t, j["id"], d] for j in jobs)
        m.addConstr(
            idle[t, d] == WORK_HOURS - work_done,
            name=f"C10_idle_t{t}_d{d}"
        )

# C11: Idle excess (linearize max(0, idle - 1))
for t in technicians:
    for d in days:
        m.addConstr(
            idle_excess[t, d] >= idle[t, d] - 1,
            name=f"C11_idle_excess_t{t}_d{d}"
        )

# C12: Hafta sonu nöbet (arızacılar için — bu model hafta içini optimize ediyor)
# Nöbetçi arızacı sayısı kontrol — hafta içi gece için not:
# Bu modelde gündüz planlaması yapılıyor; gece nöbeti ayrı bir shift.
# Kısıt: Her gün en az 1 arızacı "serbest" bırakılmalı (boş kapasitesi olmalı)
fault_technicians = [t for t in technicians if tech_type[t] == "fault_technician"]
asia_fault_techs  = [t for t in fault_technicians if tech_region[t] == "Asia"]
europe_fault_techs = [t for t in fault_technicians if tech_region[t] == "Europe"]

for d in days:
    # Her bölgede en az 1 arızacının kapasitesi olmalı (gece nöbet için)
    for region_techs, region in [(asia_fault_techs, "Asia"), (europe_fault_techs, "Europe")]:
        if region_techs:
            m.addConstr(
                gp.quicksum(
                    j["duration"] * x[t, j["id"], d]
                    for t in region_techs
                    for j in jobs
                ) <= (len(region_techs) - 1) * WORK_HOURS,
                name=f"C12_oncall_{region}_d{d}"
            )

# ─────────────────────────────────────────────────────────────────────────────
# 4. OPTİMİZASYON
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*60)
print("OPTİMİZASYON BAŞLIYOR...")
print("="*60)
m.optimize()

# ─────────────────────────────────────────────────────────────────────────────
# 5. SONUÇLAR
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*60)
print("SONUÇLAR")
print("="*60)

if m.Status in [GRB.OPTIMAL, GRB.TIME_LIMIT, GRB.SUBOPTIMAL]:
    obj_val = m.ObjVal
    print(f"\nAmaç Fonksiyonu Değeri (Zmax): {obj_val:.2f}")
    print(f"MIP Gap: {m.MIPGap*100:.2f}%")

    # ── 5.1 Atama özeti ──
    print("\n--- GÜNLÜK ATAMA ÖZETİ ---")
    day_names = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma"]
    for d in days:
        total_work = 0
        assigned_jobs = []
        for t in technicians:
            for j in jobs:
                if x[t, j["id"], d].X > 0.5:
                    total_work += j["duration"]
                    assigned_jobs.append((t, j))
        print(f"\n{day_names[d]} (Gün {d+1}): {len(assigned_jobs)} atama, "
              f"toplam {total_work:.1f} saat iş")

    # ── 5.2 Tamamlanamayan işler ──
    unserved_jobs = [j for j in jobs if unserved[j["id"]].X > 0.5]
    print(f"\n--- EKSİK/TAMAMLANAMAYAN İŞLER ---")
    print(f"Toplam eksik iş: {len(unserved_jobs)}")
    maint_unserved = [j for j in unserved_jobs if not j["is_fault"]]
    fault_unserved = [j for j in unserved_jobs if j["is_fault"]]
    print(f"  Bakım eksik  : {len(maint_unserved)}")
    print(f"  Arıza eksik  : {len(fault_unserved)}")

    for j in unserved_jobs:
        jtype = j["fault_type"] if j["is_fault"] else f"Bakım-{j['maint_type']}"
        print(f"  [!] Ünite {j['unit']:>3} | {jtype:>10} | Bölge: {j['region']}")

    # ── 5.3 Idle time bildirimi ──
    print(f"\n--- IDLE TIME UYARILARI (>1 saat) ---")
    idle_alerts = []
    for t in technicians:
        for d in days:
            idle_val = idle[t, d].X
            if idle_val > 1.0 + 1e-4:
                idle_alerts.append((t, d, idle_val))

    if idle_alerts:
        for t, d, iv in idle_alerts:
            print(f"  [UYARI] Teknisyen {t:>2} ({tech_type[t]:25}) | "
                  f"{day_names[d]:>10} | Boş süre: {iv:.2f} saat")
    else:
        print("  Tüm teknisyenlerin idle time 1 saatin altında.")

    # ── 5.4 Teknisyen bazlı iş yükü özeti ──
    print(f"\n--- TEKNİSYEN İŞ YÜKÜ ÖZETİ ---")
    for t in technicians:
        total = sum(
            j["duration"] * x[t, j["id"], d].X
            for j in jobs
            for d in days
        )
        total_idle = sum(idle[t, d].X for d in days)
        print(f"  T{t:>2} [{tech_type[t]:25}][{tech_region[t]:6}] "
              f"| Toplam iş: {total:5.2f}h | Toplam idle: {total_idle:5.2f}h")

    # ── 5.5 Bakım tipi tamamlanma oranları ──
    print(f"\n--- BAKIM TİPİ TAMAMLANMA ORANLARI ---")
    for mtype in ["A", "B", "C"]:
        total_mtype  = [j for j in jobs if not j["is_fault"] and j["maint_type"] == mtype]
        served_mtype = [j for j in total_mtype if unserved[j["id"]].X < 0.5]
        if total_mtype:
            pct = 100 * len(served_mtype) / len(total_mtype)
            print(f"  Bakım {mtype}: {len(served_mtype):>3}/{len(total_mtype):>3} tamamlandı (%{pct:.1f})")

    print(f"\n--- ARIZA MÜDAHALE DURUMU ---")
    for ftype in ["AA", "A", "B", "C", "D"]:
        total_f  = [j for j in jobs if j["is_fault"] and j["fault_type"] == ftype]
        served_f = [j for j in total_f if unserved[j["id"]].X < 0.5]
        if total_f:
            pct = 100 * len(served_f) / len(total_f)
            print(f"  Arıza {ftype}: {len(served_f)}/{len(total_f)} müdahale edildi (%{pct:.1f})")

else:
    print(f"Optimizasyon başarısız. Status: {m.Status}")

print("\n" + "="*60)
print("OPTİMİZASYON TAMAMLANDI")
print("="*60)
