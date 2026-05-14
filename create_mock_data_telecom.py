"""
Telecom Network Analytics Mock Data Generator (12-Table Schema)
================================================================
Creates BigQuery tables matching ontology.yaml with deliberate incident patterns.

Tables (12):
  Fact Tables:
    - call_events: Individual call attempts with outcome and quality
    - network_measurements: Aggregated 15-min cell counters
    - handover_events: Cell-to-cell handover attempts
    - spectrum_interference_logs: Interference detection events
    
  Dimension Tables:
    - cells: Cell/sector master data
    - towers: Physical tower locations
    - regions: Geographic regions
    - network_clusters: Logical tower groupings
    - subscribers: Subscriber master data
    - devices: Device reference data
    
  Aggregate Tables:
    - network_kpi_targets: Monthly KPI targets
    - maintenance_work_orders: Maintenance records

Incident Patterns (8):
  1. ericsson_baseband_bug (Nov 15-18, 2025) - FirmwareBugIncident
  2. storm_arwen_scotland (Nov 27-30, 2025) - WeatherIncident
  3. christmas_congestion_2025 (Dec 25, 2025) - CongestionIncident
  4. 5g_interrat_ho_failure (Jan 10-12, 2026) - AlgorithmIncident
  5. pilot_pollution_canary_wharf (Feb 1-5, 2026) - InterferenceIncident
  6. samsung_s24_volte_bug (Feb 15-28, 2026) - DeviceIncident
  7. birmingham_power_outage (Feb 15, 2026) - PowerOutageIncident
  8. m25_fiber_cut (Mar 5, 2026) - BackhaulIncident

Usage:
    python create_mock_data_telecom.py
"""

import random
import uuid
from datetime import date, datetime, timedelta
from typing import List, Dict, Any
from google.cloud import bigquery

# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════
PROJECT = "acn-uki-ds-data-ai-project"
DATASET = "telecom_network_analytics"
LOCATION = "europe-west2"

random.seed(42)

# Date range
START_DATE = date(2025, 9, 1)
END_DATE = date(2026, 3, 31)

# ═══════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════
REGIONS = [
    {"id": "REG_LON", "name": "London", "type": "urban", "country": "GB", "market": "consumer", "density": "high"},
    {"id": "REG_SE", "name": "South East", "type": "suburban", "country": "GB", "market": "consumer", "density": "medium"},
    {"id": "REG_MID", "name": "Midlands", "type": "suburban", "country": "GB", "market": "consumer", "density": "medium"},
    {"id": "REG_NW", "name": "North West", "type": "urban", "country": "GB", "market": "consumer", "density": "high"},
    {"id": "REG_YKS", "name": "Yorkshire", "type": "suburban", "country": "GB", "market": "consumer", "density": "medium"},
    {"id": "REG_SCO", "name": "Scotland", "type": "mixed", "country": "GB", "market": "consumer", "density": "low"},
    {"id": "REG_NE", "name": "North East", "type": "suburban", "country": "GB", "market": "consumer", "density": "medium"},
    {"id": "REG_WAL", "name": "Wales", "type": "rural", "country": "GB", "market": "consumer", "density": "low"},
    {"id": "REG_SW", "name": "South West", "type": "rural", "country": "GB", "market": "consumer", "density": "low"},
]

CLUSTERS_PER_REGION = {
    "REG_LON": [
        {"id": "CLU_LON_001", "name": "London Central", "type": "urban_core", "team": "Metro Ops"},
        {"id": "CLU_LON_002", "name": "Canary Wharf", "type": "venue", "team": "Metro Ops"},
        {"id": "CLU_LON_003", "name": "London South", "type": "suburban", "team": "Metro Ops"},
    ],
    "REG_NW": [
        {"id": "CLU_NW_001", "name": "Manchester Central", "type": "urban_core", "team": "Northern Ops"},
        {"id": "CLU_NW_002", "name": "Liverpool", "type": "urban_core", "team": "Northern Ops"},
        {"id": "CLU_NW_003", "name": "M62 Corridor", "type": "highway", "team": "Transport Ops"},
    ],
    "REG_SCO": [
        {"id": "CLU_SCO_001", "name": "Glasgow Central", "type": "urban_core", "team": "Scotland Ops"},
        {"id": "CLU_SCO_002", "name": "Edinburgh", "type": "urban_core", "team": "Scotland Ops"},
        {"id": "CLU_SCO_003", "name": "Highlands", "type": "rural", "team": "Field Services"},
    ],
    "REG_MID": [
        {"id": "CLU_MID_001", "name": "Birmingham Central", "type": "urban_core", "team": "Central Ops"},
    ],
    "REG_SE": [
        {"id": "CLU_SE_001", "name": "M25 Ring", "type": "highway", "team": "Transport Ops"},
    ],
    "REG_YKS": [
        {"id": "CLU_YKS_001", "name": "Leeds Central", "type": "urban_core", "team": "Northern Ops"},
    ],
}

VENDORS = ["Ericsson", "Nokia", "Samsung", "Huawei"]
TECHNOLOGIES = ["2G", "3G", "4G", "5G"]
BANDS = ["700", "800", "1800", "2100", "2600", "3500"]
CELL_TYPES = ["macro", "micro", "pico", "indoor"]
TOWER_TYPES = ["greenfield", "rooftop", "monopole", "lattice"]

DEVICE_MANUFACTURERS = ["Apple", "Samsung", "Google", "Huawei", "Xiaomi", "OnePlus", "Other"]
DEVICE_MODELS = {
    "Apple": ["iPhone 15 Pro", "iPhone 15", "iPhone 14", "iPhone SE"],
    "Samsung": ["Galaxy S24", "Galaxy S23", "Galaxy A54", "Galaxy Z Fold"],
    "Google": ["Pixel 8 Pro", "Pixel 8", "Pixel 7a"],
    "Huawei": ["P60 Pro", "Mate 60"],
    "Xiaomi": ["14 Pro", "13T"],
    "OnePlus": ["12", "11"],
    "Other": ["Generic 4G", "Generic 5G"],
}

CALL_OUTCOMES = ["completed", "dropped", "blocked", "setup_failure"]
DROP_REASONS = ["radio_link_failure", "handover_failure", "interference", "congestion", "equipment_fault"]
CALL_TYPES = ["voice", "video", "volte", "vonr"]

HO_TYPES = ["intra_frequency", "inter_frequency", "inter_rat", "emergency"]
HO_OUTCOMES = ["success", "failure", "ping_pong"]

INTERFERENCE_TYPES = ["co_channel", "adjacent_channel", "external", "intermod", "pilot_pollution"]

SUBSCRIPTION_TYPES = ["prepaid", "postpaid", "enterprise", "iot"]
SEGMENTS = ["consumer", "enterprise", "mvno", "wholesale"]
LOYALTY_TIERS = ["standard", "silver", "gold", "platinum"]

WO_TYPES = ["preventive", "corrective", "upgrade", "swap", "emergency"]
WO_STATUSES = ["planned", "in_progress", "completed", "cancelled"]

# ═══════════════════════════════════════════════════════════════════════════
# INCIDENT DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════════
INCIDENTS = {
    "ericsson_baseband_bug": {
        "start": date(2025, 11, 15),
        "end": date(2025, 11, 18),
        "regions": ["REG_LON", "REG_SE"],
        "vendor": "Ericsson",
        "drop_reason": "radio_link_failure",
        "cdr_multiplier": 4.5,
        "cssr_impact": -3.0,
        "rsrp_impact": -7,
    },
    "storm_arwen_scotland": {
        "start": date(2025, 11, 27),
        "end": date(2025, 11, 30),
        "regions": ["REG_SCO", "REG_NE"],
        "drop_reason": "equipment_fault",
        "cdr_multiplier": 8.0,
        "prb_impact": 40,
    },
    "christmas_congestion_2025": {
        "start": date(2025, 12, 25),
        "end": date(2025, 12, 25),
        "regions": ["REG_LON", "REG_SE", "REG_MID"],
        "cluster_types": ["urban_core"],
        "drop_reason": "congestion",
        "prb_target": 98,
        "cssr_impact": -4.5,
    },
    "5g_interrat_ho_failure": {
        "start": date(2026, 1, 10),
        "end": date(2026, 1, 12),
        "regions": ["REG_NW", "REG_YKS"],
        "vendor": "Samsung",
        "technology": "5G",
        "drop_reason": "handover_failure",
        "hosr_target": 82,
        "cdr_multiplier": 6.8,
    },
    "pilot_pollution_canary_wharf": {
        "start": date(2026, 2, 1),
        "end": date(2026, 2, 5),
        "clusters": ["CLU_LON_002"],
        "interference_type": "pilot_pollution",
        "sinr_target": 2,
        "hosr_target": 88,
    },
    "samsung_s24_volte_bug": {
        "start": date(2026, 2, 15),
        "end": date(2026, 2, 28),
        "device_model": "Galaxy S24",
        "drop_reason": None,  # setup_failure, not drop
        "cssr_impact": -7.0,
    },
    "birmingham_power_outage": {
        "start": date(2026, 2, 15),
        "end": date(2026, 2, 15),
        "clusters": ["CLU_MID_001"],
        "drop_reason": "equipment_fault",
        "cdr_multiplier": 100,  # Total outage
    },
    "m25_fiber_cut": {
        "start": date(2026, 3, 5),
        "end": date(2026, 3, 5),
        "clusters": ["CLU_SE_001"],
        "drop_reason": "equipment_fault",
        "throughput_impact": -70,
        "cdr_multiplier": 2.8,
    },
}

# ═══════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════
def rand_date(start: date, end: date) -> date:
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, max(delta, 0)))

def rand_ts(d: date, hour_range=(0, 23)) -> datetime:
    return datetime(d.year, d.month, d.day,
                   random.randint(hour_range[0], hour_range[1]),
                   random.randint(0, 59), random.randint(0, 59))

def gen_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12].upper()}"

def is_incident_active(d: date, incident_key: str) -> bool:
    inc = INCIDENTS.get(incident_key)
    if not inc:
        return False
    return inc["start"] <= d <= inc["end"]

def get_active_incidents(d: date, region_id: str = None, cluster_id: str = None, 
                         vendor: str = None, technology: str = None,
                         device_model: str = None) -> List[str]:
    """Return list of incident keys active on this date matching criteria."""
    active = []
    for key, inc in INCIDENTS.items():
        if not (inc["start"] <= d <= inc["end"]):
            continue
        
        # Check region match
        if "regions" in inc and region_id:
            if region_id not in inc["regions"]:
                continue
        
        # Check cluster match
        if "clusters" in inc and cluster_id:
            if cluster_id not in inc["clusters"]:
                continue
        
        # Check vendor match
        if "vendor" in inc and vendor:
            if vendor != inc["vendor"]:
                continue
        
        # Check technology match
        if "technology" in inc and technology:
            if inc["technology"] not in technology:
                continue
        
        # Check device model match
        if "device_model" in inc and device_model:
            if inc["device_model"] not in device_model:
                continue
        
        active.append(key)
    
    return active

# ═══════════════════════════════════════════════════════════════════════════
# SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════
SCHEMAS = {
    "regions": [
        bigquery.SchemaField("region_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("region_name", "STRING"),
        bigquery.SchemaField("region_type", "STRING"),
        bigquery.SchemaField("country", "STRING"),
        bigquery.SchemaField("market", "STRING"),
        bigquery.SchemaField("population_density", "STRING"),
    ],
    "network_clusters": [
        bigquery.SchemaField("cluster_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("cluster_name", "STRING"),
        bigquery.SchemaField("region_id", "STRING"),
        bigquery.SchemaField("cluster_type", "STRING"),
        bigquery.SchemaField("responsible_team", "STRING"),
        bigquery.SchemaField("tower_count", "INT64"),
    ],
    "towers": [
        bigquery.SchemaField("tower_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("tower_name", "STRING"),
        bigquery.SchemaField("latitude", "FLOAT64"),
        bigquery.SchemaField("longitude", "FLOAT64"),
        bigquery.SchemaField("height_m", "FLOAT64"),
        bigquery.SchemaField("tower_type", "STRING"),
        bigquery.SchemaField("region_id", "STRING"),
        bigquery.SchemaField("cluster_id", "STRING"),
        bigquery.SchemaField("power_source", "STRING"),
        bigquery.SchemaField("has_backup_power", "BOOL"),
        bigquery.SchemaField("maintenance_zone", "STRING"),
        bigquery.SchemaField("commissioned_date", "DATE"),
        bigquery.SchemaField("is_active", "BOOL"),
    ],
    "cells": [
        bigquery.SchemaField("cell_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("cell_name", "STRING"),
        bigquery.SchemaField("tower_id", "STRING"),
        bigquery.SchemaField("technology", "STRING"),
        bigquery.SchemaField("band_mhz", "STRING"),
        bigquery.SchemaField("azimuth_deg", "INT64"),
        bigquery.SchemaField("tilt_deg", "FLOAT64"),
        bigquery.SchemaField("max_tx_power_dbm", "FLOAT64"),
        bigquery.SchemaField("designed_capacity", "INT64"),
        bigquery.SchemaField("cell_type", "STRING"),
        bigquery.SchemaField("vendor", "STRING"),
        bigquery.SchemaField("region_id", "STRING"),
        bigquery.SchemaField("commissioned_date", "DATE"),
        bigquery.SchemaField("is_active", "BOOL"),
    ],
    "subscribers": [
        bigquery.SchemaField("subscriber_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("msisdn_hash", "STRING"),
        bigquery.SchemaField("subscription_type", "STRING"),
        bigquery.SchemaField("tariff_plan", "STRING"),
        bigquery.SchemaField("segment", "STRING"),
        bigquery.SchemaField("loyalty_tier", "STRING"),
        bigquery.SchemaField("home_region_id", "STRING"),
        bigquery.SchemaField("churn_risk_score", "FLOAT64"),
        bigquery.SchemaField("activation_date", "DATE"),
        bigquery.SchemaField("is_active", "BOOL"),
    ],
    "devices": [
        bigquery.SchemaField("device_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("imei_hash", "STRING"),
        bigquery.SchemaField("manufacturer", "STRING"),
        bigquery.SchemaField("model", "STRING"),
        bigquery.SchemaField("device_type", "STRING"),
        bigquery.SchemaField("technology_support", "STRING"),
        bigquery.SchemaField("volte_capable", "BOOL"),
        bigquery.SchemaField("vonr_capable", "BOOL"),
        bigquery.SchemaField("known_issue_flag", "BOOL"),
        bigquery.SchemaField("os_version", "STRING"),
    ],
    "call_events": [
        bigquery.SchemaField("call_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("subscriber_id", "STRING"),
        bigquery.SchemaField("cell_id", "STRING"),
        bigquery.SchemaField("tower_id", "STRING"),
        bigquery.SchemaField("device_id", "STRING"),
        bigquery.SchemaField("region_id", "STRING"),
        bigquery.SchemaField("call_start_ts", "TIMESTAMP"),
        bigquery.SchemaField("call_end_ts", "TIMESTAMP"),
        bigquery.SchemaField("call_date", "DATE"),
        bigquery.SchemaField("call_duration_sec", "INT64"),
        bigquery.SchemaField("call_outcome", "STRING"),
        bigquery.SchemaField("drop_reason", "STRING"),
        bigquery.SchemaField("technology", "STRING"),
        bigquery.SchemaField("call_type", "STRING"),
        bigquery.SchemaField("rsrp_start_dbm", "FLOAT64"),
        bigquery.SchemaField("rsrp_end_dbm", "FLOAT64"),
        bigquery.SchemaField("sinr_start_db", "FLOAT64"),
        bigquery.SchemaField("sinr_end_db", "FLOAT64"),
        bigquery.SchemaField("handover_count", "INT64"),
        bigquery.SchemaField("handover_success", "BOOL"),
    ],
    "network_measurements": [
        bigquery.SchemaField("measurement_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("cell_id", "STRING"),
        bigquery.SchemaField("tower_id", "STRING"),
        bigquery.SchemaField("measurement_ts", "TIMESTAMP"),
        bigquery.SchemaField("measurement_date", "DATE"),
        bigquery.SchemaField("technology", "STRING"),
        bigquery.SchemaField("call_attempts", "INT64"),
        bigquery.SchemaField("call_drops", "INT64"),
        bigquery.SchemaField("call_setups_success", "INT64"),
        bigquery.SchemaField("call_setups_fail", "INT64"),
        bigquery.SchemaField("handover_attempts", "INT64"),
        bigquery.SchemaField("handover_success", "INT64"),
        bigquery.SchemaField("handover_fail", "INT64"),
        bigquery.SchemaField("avg_rsrp_dbm", "FLOAT64"),
        bigquery.SchemaField("avg_sinr_db", "FLOAT64"),
        bigquery.SchemaField("avg_throughput_mbps", "FLOAT64"),
        bigquery.SchemaField("prb_utilisation_pct", "FLOAT64"),
        bigquery.SchemaField("active_ues", "INT64"),
        bigquery.SchemaField("interference_level_db", "FLOAT64"),
        bigquery.SchemaField("rrc_connected_users", "INT64"),
    ],
    "handover_events": [
        bigquery.SchemaField("ho_event_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("call_id", "STRING"),
        bigquery.SchemaField("source_cell_id", "STRING"),
        bigquery.SchemaField("target_cell_id", "STRING"),
        bigquery.SchemaField("subscriber_id", "STRING"),
        bigquery.SchemaField("ho_timestamp", "TIMESTAMP"),
        bigquery.SchemaField("ho_date", "DATE"),
        bigquery.SchemaField("ho_type", "STRING"),
        bigquery.SchemaField("ho_outcome", "STRING"),
        bigquery.SchemaField("rsrp_trigger_dbm", "FLOAT64"),
        bigquery.SchemaField("sinr_trigger_db", "FLOAT64"),
        bigquery.SchemaField("ho_duration_ms", "INT64"),
        bigquery.SchemaField("technology", "STRING"),
    ],
    "spectrum_interference_logs": [
        bigquery.SchemaField("interference_log_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("cell_id", "STRING"),
        bigquery.SchemaField("detected_ts", "TIMESTAMP"),
        bigquery.SchemaField("detected_date", "DATE"),
        bigquery.SchemaField("interference_type", "STRING"),
        bigquery.SchemaField("interfering_cell_id", "STRING"),
        bigquery.SchemaField("interference_level_db", "FLOAT64"),
        bigquery.SchemaField("affected_frequency_mhz", "FLOAT64"),
        bigquery.SchemaField("band", "STRING"),
        bigquery.SchemaField("duration_minutes", "INT64"),
        bigquery.SchemaField("is_resolved", "BOOL"),
    ],
    "network_kpi_targets": [
        bigquery.SchemaField("target_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("region_id", "STRING"),
        bigquery.SchemaField("technology", "STRING"),
        bigquery.SchemaField("target_month", "DATE"),
        bigquery.SchemaField("target_cdr", "FLOAT64"),
        bigquery.SchemaField("target_cssr", "FLOAT64"),
        bigquery.SchemaField("target_hosr", "FLOAT64"),
        bigquery.SchemaField("target_throughput", "FLOAT64"),
        bigquery.SchemaField("target_availability", "FLOAT64"),
    ],
    "maintenance_work_orders": [
        bigquery.SchemaField("wo_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("tower_id", "STRING"),
        bigquery.SchemaField("cell_id", "STRING"),
        bigquery.SchemaField("wo_type", "STRING"),
        bigquery.SchemaField("status", "STRING"),
        bigquery.SchemaField("scheduled_date", "DATE"),
        bigquery.SchemaField("completed_date", "DATE"),
        bigquery.SchemaField("description", "STRING"),
        bigquery.SchemaField("vendor_engineer", "STRING"),
        bigquery.SchemaField("caused_outage", "BOOL"),
    ],
}

# ═══════════════════════════════════════════════════════════════════════════
# DATA GENERATION
# ═══════════════════════════════════════════════════════════════════════════
def generate_data():
    """Generate all mock data."""
    data = {}
    
    # ─── Regions ───
    print("Generating regions...")
    data["regions"] = [
        {
            "region_id": r["id"],
            "region_name": r["name"],
            "region_type": r["type"],
            "country": r["country"],
            "market": r["market"],
            "population_density": r["density"],
        }
        for r in REGIONS
    ]
    print(f"  {len(data['regions'])} regions")
    
    # ─── Network Clusters ───
    print("Generating clusters...")
    data["network_clusters"] = []
    all_clusters = []
    for region_id, clusters in CLUSTERS_PER_REGION.items():
        for c in clusters:
            cluster = {
                "cluster_id": c["id"],
                "cluster_name": c["name"],
                "region_id": region_id,
                "cluster_type": c["type"],
                "responsible_team": c["team"],
                "tower_count": random.randint(10, 50),
            }
            data["network_clusters"].append(cluster)
            all_clusters.append(cluster)
    print(f"  {len(data['network_clusters'])} clusters")
    
    # ─── Towers ───
    print("Generating towers...")
    data["towers"] = []
    all_towers = []
    tower_counter = 1
    
    for cluster in all_clusters:
        num_towers = cluster["tower_count"]
        for i in range(num_towers):
            tower = {
                "tower_id": f"TWR_{tower_counter:05d}",
                "tower_name": f"{cluster['cluster_name']} Tower {i+1}",
                "latitude": round(random.uniform(50.0, 58.5), 6),
                "longitude": round(random.uniform(-5.5, 1.5), 6),
                "height_m": round(random.uniform(15, 80), 1),
                "tower_type": random.choice(TOWER_TYPES),
                "region_id": cluster["region_id"],
                "cluster_id": cluster["cluster_id"],
                "power_source": random.choice(["grid", "generator", "solar", "hybrid"]),
                "has_backup_power": random.random() > 0.2,
                "maintenance_zone": random.choice(["zone_a", "zone_b", "zone_c"]),
                "commissioned_date": rand_date(date(2015, 1, 1), date(2024, 12, 31)).isoformat(),
                "is_active": True,
            }
            data["towers"].append(tower)
            all_towers.append(tower)
            tower_counter += 1
    
    print(f"  {len(data['towers'])} towers")
    
    # ─── Cells ───
    print("Generating cells...")
    data["cells"] = []
    all_cells = []
    cell_counter = 1
    
    for tower in all_towers:
        # Each tower has 3-9 cells (sectors * technologies)
        num_cells = random.randint(3, 9)
        for i in range(num_cells):
            tech = random.choices(TECHNOLOGIES, weights=[5, 10, 50, 35])[0]
            vendor = random.choices(VENDORS, weights=[40, 30, 20, 10])[0]
            
            # Urban areas have more 5G
            if tower["cluster_id"] in ["CLU_LON_001", "CLU_LON_002", "CLU_NW_001"]:
                tech = random.choices(TECHNOLOGIES, weights=[2, 5, 40, 53])[0]
            
            cell = {
                "cell_id": f"CELL_{cell_counter:06d}",
                "cell_name": f"{tower['tower_name']} Cell {i+1}",
                "tower_id": tower["tower_id"],
                "technology": tech,
                "band_mhz": random.choice(BANDS),
                "azimuth_deg": random.choice([0, 120, 240]),
                "tilt_deg": round(random.uniform(2, 10), 1),
                "max_tx_power_dbm": round(random.uniform(40, 46), 1),
                "designed_capacity": random.choice([500, 1000, 2000]),
                "cell_type": random.choice(CELL_TYPES),
                "vendor": vendor,
                "region_id": tower["region_id"],
                "commissioned_date": tower["commissioned_date"],
                "is_active": True,
            }
            data["cells"].append(cell)
            all_cells.append(cell)
            cell_counter += 1
    
    print(f"  {len(data['cells'])} cells")
    
    # Build lookups
    cell_by_id = {c["cell_id"]: c for c in all_cells}
    tower_by_id = {t["tower_id"]: t for t in all_towers}
    cells_by_region = {}
    for c in all_cells:
        cells_by_region.setdefault(c["region_id"], []).append(c)
    cells_by_cluster = {}
    for c in all_cells:
        t = tower_by_id[c["tower_id"]]
        cells_by_cluster.setdefault(t["cluster_id"], []).append(c)
    
    # ─── Devices ───
    print("Generating devices...")
    data["devices"] = []
    all_devices = []
    device_counter = 1
    
    for _ in range(5000):
        manufacturer = random.choices(
            DEVICE_MANUFACTURERS, 
            weights=[35, 30, 10, 5, 10, 5, 5]
        )[0]
        model = random.choice(DEVICE_MODELS[manufacturer])
        
        # Samsung S24 devices get known_issue_flag for the bug incident
        known_issue = (model == "Galaxy S24")
        
        tech_support = "4G"
        if "Pro" in model or "15" in model or "S24" in model or "S23" in model or "Pixel 8" in model:
            tech_support = "5G"
        
        device = {
            "device_id": f"DEV_{device_counter:06d}",
            "imei_hash": uuid.uuid4().hex[:16],
            "manufacturer": manufacturer,
            "model": model,
            "device_type": "smartphone",
            "technology_support": tech_support,
            "volte_capable": random.random() > 0.1,
            "vonr_capable": tech_support == "5G" and random.random() > 0.3,
            "known_issue_flag": known_issue,
            "os_version": f"v{random.randint(10, 17)}.{random.randint(0, 5)}",
        }
        data["devices"].append(device)
        all_devices.append(device)
        device_counter += 1
    
    print(f"  {len(data['devices'])} devices")
    
    # ─── Subscribers ───
    print("Generating subscribers...")
    data["subscribers"] = []
    all_subscribers = []
    
    for i in range(20000):
        region = random.choice(REGIONS)
        sub = {
            "subscriber_id": f"SUB_{i+1:06d}",
            "msisdn_hash": uuid.uuid4().hex[:16],
            "subscription_type": random.choices(SUBSCRIPTION_TYPES, weights=[20, 50, 20, 10])[0],
            "tariff_plan": random.choice(["basic", "standard", "premium", "unlimited"]),
            "segment": random.choices(SEGMENTS, weights=[70, 20, 5, 5])[0],
            "loyalty_tier": random.choices(LOYALTY_TIERS, weights=[50, 30, 15, 5])[0],
            "home_region_id": region["id"],
            "churn_risk_score": round(random.uniform(0, 1), 3),
            "activation_date": rand_date(date(2020, 1, 1), date(2025, 8, 31)).isoformat(),
            "is_active": random.random() > 0.05,
        }
        data["subscribers"].append(sub)
        all_subscribers.append(sub)
    
    print(f"  {len(data['subscribers'])} subscribers")
    
    # ─── Call Events ───
    print("Generating call events...")
    data["call_events"] = []
    
    current_date = START_DATE
    while current_date <= END_DATE:
        # Base calls per day: ~50000
        daily_calls = random.randint(45000, 55000)
        
        # Christmas congestion: 3.4x traffic
        if current_date == date(2025, 12, 25):
            daily_calls = int(daily_calls * 3.4)
        
        for _ in range(daily_calls):
            subscriber = random.choice(all_subscribers)
            region_id = subscriber["home_region_id"]
            
            # 80% calls in home region, 20% roaming
            if random.random() > 0.8:
                region_id = random.choice(REGIONS)["id"]
            
            available_cells = cells_by_region.get(region_id, all_cells[:100])
            cell = random.choice(available_cells)
            tower = tower_by_id[cell["tower_id"]]
            device = random.choice(all_devices)
            
            ts = rand_ts(current_date)
            
            # Determine call outcome based on incidents
            active_incidents = get_active_incidents(
                current_date, 
                region_id=region_id,
                cluster_id=tower["cluster_id"],
                vendor=cell["vendor"],
                technology=cell["technology"],
                device_model=device["model"]
            )
            
            # Base drop rate: 1%
            drop_prob = 0.01
            setup_fail_prob = 0.005
            drop_reason = None
            
            for inc_key in active_incidents:
                inc = INCIDENTS[inc_key]
                
                if "cdr_multiplier" in inc:
                    drop_prob = 0.01 * inc["cdr_multiplier"]
                
                if "cssr_impact" in inc:
                    setup_fail_prob += abs(inc["cssr_impact"]) / 100
                
                if "drop_reason" in inc and inc["drop_reason"]:
                    drop_reason = inc["drop_reason"]
            
            # Samsung S24 VoLTE bug
            if "samsung_s24_volte_bug" in active_incidents and device["model"] == "Galaxy S24":
                setup_fail_prob = 0.08
            
            # Determine outcome
            outcome = "completed"
            if random.random() < setup_fail_prob:
                outcome = "setup_failure"
                drop_reason = None
            elif random.random() < drop_prob:
                outcome = "dropped"
                if not drop_reason:
                    drop_reason = random.choice(DROP_REASONS)
            
            # Call duration
            duration = 0 if outcome != "completed" else random.randint(10, 600)
            if outcome == "dropped":
                duration = random.randint(5, 120)
            
            # Signal quality
            rsrp_start = round(random.gauss(-85, 10), 1)
            sinr_start = round(random.gauss(15, 5), 1)
            
            # Apply incident impacts
            for inc_key in active_incidents:
                inc = INCIDENTS[inc_key]
                if "rsrp_impact" in inc:
                    rsrp_start += inc["rsrp_impact"]
                if "sinr_target" in inc:
                    sinr_start = inc["sinr_target"] + random.gauss(0, 1)
            
            call = {
                "call_id": gen_id("CALL"),
                "subscriber_id": subscriber["subscriber_id"],
                "cell_id": cell["cell_id"],
                "tower_id": tower["tower_id"],
                "device_id": device["device_id"],
                "region_id": region_id,
                "call_start_ts": ts.isoformat(),
                "call_end_ts": (ts + timedelta(seconds=duration)).isoformat(),
                "call_date": current_date.isoformat(),
                "call_duration_sec": duration,
                "call_outcome": outcome,
                "drop_reason": drop_reason,
                "technology": cell["technology"],
                "call_type": random.choice(CALL_TYPES),
                "rsrp_start_dbm": rsrp_start,
                "rsrp_end_dbm": rsrp_start + random.gauss(0, 3) if duration > 0 else None,
                "sinr_start_db": sinr_start,
                "sinr_end_db": sinr_start + random.gauss(0, 2) if duration > 0 else None,
                "handover_count": random.randint(0, 5) if duration > 60 else 0,
                "handover_success": outcome == "completed",
            }
            data["call_events"].append(call)
        
        current_date += timedelta(days=1)
        if current_date.day == 1:
            print(f"    Processed {current_date.strftime('%Y-%m')}...")
    
    print(f"  {len(data['call_events'])} call events")
    
    # ─── Network Measurements (15-min aggregates) ───
    print("Generating network measurements...")
    data["network_measurements"] = []
    
    current_date = START_DATE
    while current_date <= END_DATE:
        for hour in range(24):
            for quarter in [0, 15, 30, 45]:
                ts = datetime(current_date.year, current_date.month, current_date.day, hour, quarter)
                
                # Sample ~10% of cells per interval
                sampled_cells = random.sample(all_cells, min(500, len(all_cells)))
                
                for cell in sampled_cells:
                    tower = tower_by_id[cell["tower_id"]]
                    
                    active_incidents = get_active_incidents(
                        current_date,
                        region_id=cell["region_id"],
                        cluster_id=tower["cluster_id"],
                        vendor=cell["vendor"],
                        technology=cell["technology"]
                    )
                    
                    # Base metrics
                    call_attempts = random.randint(50, 200)
                    base_cssr = 0.99
                    base_cdr = 0.01
                    base_hosr = 0.98
                    base_prb = random.uniform(30, 60)
                    base_rsrp = random.gauss(-85, 8)
                    base_sinr = random.gauss(15, 4)
                    base_throughput = random.gauss(50, 15)
                    
                    # Apply incident impacts
                    for inc_key in active_incidents:
                        inc = INCIDENTS[inc_key]
                        if "cdr_multiplier" in inc:
                            base_cdr *= inc["cdr_multiplier"]
                        if "cssr_impact" in inc:
                            base_cssr += inc["cssr_impact"] / 100
                        if "hosr_target" in inc:
                            base_hosr = inc["hosr_target"] / 100
                        if "prb_target" in inc:
                            base_prb = inc["prb_target"]
                        if "prb_impact" in inc:
                            base_prb += inc["prb_impact"]
                        if "rsrp_impact" in inc:
                            base_rsrp += inc["rsrp_impact"]
                        if "sinr_target" in inc:
                            base_sinr = inc["sinr_target"]
                        if "throughput_impact" in inc:
                            base_throughput *= (1 + inc["throughput_impact"] / 100)
                    
                    # Clamp values
                    base_cssr = max(0.8, min(1.0, base_cssr))
                    base_cdr = max(0, min(0.5, base_cdr))
                    base_hosr = max(0.7, min(1.0, base_hosr))
                    base_prb = max(0, min(100, base_prb))
                    base_throughput = max(1, base_throughput)
                    
                    call_setups_success = int(call_attempts * base_cssr)
                    call_setups_fail = call_attempts - call_setups_success
                    call_drops = int(call_setups_success * base_cdr)
                    
                    ho_attempts = random.randint(10, 50)
                    ho_success = int(ho_attempts * base_hosr)
                    
                    measurement = {
                        "measurement_id": gen_id("MEAS"),
                        "cell_id": cell["cell_id"],
                        "tower_id": cell["tower_id"],
                        "measurement_ts": ts.isoformat(),
                        "measurement_date": current_date.isoformat(),
                        "technology": cell["technology"],
                        "call_attempts": call_attempts,
                        "call_drops": call_drops,
                        "call_setups_success": call_setups_success,
                        "call_setups_fail": call_setups_fail,
                        "handover_attempts": ho_attempts,
                        "handover_success": ho_success,
                        "handover_fail": ho_attempts - ho_success,
                        "avg_rsrp_dbm": round(base_rsrp, 1),
                        "avg_sinr_db": round(base_sinr, 1),
                        "avg_throughput_mbps": round(base_throughput, 2),
                        "prb_utilisation_pct": round(base_prb, 1),
                        "active_ues": random.randint(20, 200),
                        "interference_level_db": round(random.gauss(-115, 5), 1),
                        "rrc_connected_users": random.randint(10, 150),
                    }
                    data["network_measurements"].append(measurement)
        
        current_date += timedelta(days=1)
    
    print(f"  {len(data['network_measurements'])} measurements")
    
    # ─── Handover Events ───
    print("Generating handover events...")
    data["handover_events"] = []
    
    # Generate handovers from call events with handovers
    calls_with_ho = [c for c in data["call_events"] if c["handover_count"] > 0]
    for call in random.sample(calls_with_ho, min(50000, len(calls_with_ho))):
        cell = cell_by_id.get(call["cell_id"])
        if not cell:
            continue
        
        tower = tower_by_id.get(cell["tower_id"])
        if not tower:
            continue
        
        # Get neighbor cells
        cluster_cells = cells_by_cluster.get(tower["cluster_id"], [])
        if len(cluster_cells) < 2:
            continue
        
        call_date = date.fromisoformat(call["call_date"])
        active_incidents = get_active_incidents(
            call_date,
            cluster_id=tower["cluster_id"],
            vendor=cell["vendor"],
            technology=cell["technology"]
        )
        
        ho_success_rate = 0.98
        for inc_key in active_incidents:
            if "hosr_target" in INCIDENTS[inc_key]:
                ho_success_rate = INCIDENTS[inc_key]["hosr_target"] / 100
        
        for i in range(call["handover_count"]):
            target_cell = random.choice([c for c in cluster_cells if c["cell_id"] != call["cell_id"]])
            
            outcome = "success" if random.random() < ho_success_rate else random.choice(["failure", "ping_pong"])
            
            ho = {
                "ho_event_id": gen_id("HO"),
                "call_id": call["call_id"],
                "source_cell_id": call["cell_id"],
                "target_cell_id": target_cell["cell_id"],
                "subscriber_id": call["subscriber_id"],
                "ho_timestamp": call["call_start_ts"],
                "ho_date": call["call_date"],
                "ho_type": random.choice(HO_TYPES),
                "ho_outcome": outcome,
                "rsrp_trigger_dbm": round(random.gauss(-100, 5), 1),
                "sinr_trigger_db": round(random.gauss(5, 3), 1),
                "ho_duration_ms": random.randint(50, 500),
                "technology": cell["technology"],
            }
            data["handover_events"].append(ho)
    
    print(f"  {len(data['handover_events'])} handover events")
    
    # ─── Spectrum Interference Logs ───
    print("Generating interference logs...")
    data["spectrum_interference_logs"] = []
    
    # Generate interference events, especially during pilot pollution incident
    current_date = START_DATE
    while current_date <= END_DATE:
        # Base: 10-20 interference events per day
        num_events = random.randint(10, 20)
        
        # Pilot pollution incident: many more in Canary Wharf
        if is_incident_active(current_date, "pilot_pollution_canary_wharf"):
            num_events += 50
        
        for _ in range(num_events):
            cell = random.choice(all_cells)
            tower = tower_by_id[cell["tower_id"]]
            
            int_type = random.choice(INTERFERENCE_TYPES)
            
            # During pilot pollution incident, force type in affected cluster
            if is_incident_active(current_date, "pilot_pollution_canary_wharf"):
                if tower["cluster_id"] == "CLU_LON_002":
                    int_type = "pilot_pollution"
            
            log = {
                "interference_log_id": gen_id("INT"),
                "cell_id": cell["cell_id"],
                "detected_ts": rand_ts(current_date).isoformat(),
                "detected_date": current_date.isoformat(),
                "interference_type": int_type,
                "interfering_cell_id": random.choice(all_cells)["cell_id"] if random.random() > 0.3 else None,
                "interference_level_db": round(random.gauss(-95, 10), 1),
                "affected_frequency_mhz": float(random.choice(BANDS)),
                "band": random.choice(BANDS),
                "duration_minutes": random.randint(5, 120),
                "is_resolved": random.random() > 0.1,
            }
            data["spectrum_interference_logs"].append(log)
        
        current_date += timedelta(days=1)
    
    print(f"  {len(data['spectrum_interference_logs'])} interference logs")
    
    # ─── KPI Targets ───
    print("Generating KPI targets...")
    data["network_kpi_targets"] = []
    
    for region in REGIONS:
        for tech in ["4G", "5G"]:
            current_month = date(2025, 9, 1)
            while current_month <= date(2026, 3, 1):
                target = {
                    "target_id": gen_id("TGT"),
                    "region_id": region["id"],
                    "technology": tech,
                    "target_month": current_month.isoformat(),
                    "target_cdr": 1.0 if tech == "4G" else 1.5,
                    "target_cssr": 99.0,
                    "target_hosr": 98.0 if tech == "4G" else 97.0,
                    "target_throughput": 30.0 if tech == "4G" else 100.0,
                    "target_availability": 99.9,
                }
                data["network_kpi_targets"].append(target)
                
                # Next month
                if current_month.month == 12:
                    current_month = date(current_month.year + 1, 1, 1)
                else:
                    current_month = date(current_month.year, current_month.month + 1, 1)
    
    print(f"  {len(data['network_kpi_targets'])} KPI targets")
    
    # ─── Maintenance Work Orders ───
    print("Generating work orders...")
    data["maintenance_work_orders"] = []
    
    # Regular preventive maintenance
    for tower in random.sample(all_towers, min(200, len(all_towers))):
        wo = {
            "wo_id": gen_id("WO"),
            "tower_id": tower["tower_id"],
            "cell_id": None,
            "wo_type": "preventive",
            "status": "completed",
            "scheduled_date": rand_date(START_DATE, END_DATE).isoformat(),
            "completed_date": rand_date(START_DATE, END_DATE).isoformat(),
            "description": "Scheduled preventive maintenance",
            "vendor_engineer": random.choice(["Ericsson Field Eng", "Nokia Field Eng", "Samsung Field Eng"]),
            "caused_outage": False,
        }
        data["maintenance_work_orders"].append(wo)
    
    # Corrective maintenance for incidents
    for inc_key, inc in INCIDENTS.items():
        if "clusters" in inc:
            for cluster_id in inc["clusters"]:
                cluster_towers = [t for t in all_towers if t["cluster_id"] == cluster_id]
                for tower in random.sample(cluster_towers, min(5, len(cluster_towers))):
                    wo = {
                        "wo_id": gen_id("WO"),
                        "tower_id": tower["tower_id"],
                        "cell_id": None,
                        "wo_type": "emergency" if "power" in inc_key or "fiber" in inc_key else "corrective",
                        "status": "completed",
                        "scheduled_date": inc["start"].isoformat(),
                        "completed_date": inc["end"].isoformat(),
                        "description": f"Corrective action for {inc_key}",
                        "vendor_engineer": random.choice(["Ericsson Field Eng", "Nokia Field Eng"]),
                        "caused_outage": True,
                    }
                    data["maintenance_work_orders"].append(wo)
    
    print(f"  {len(data['maintenance_work_orders'])} work orders")
    
    return data

# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════
def main():
    print("=" * 70)
    print("TELECOM NETWORK ANALYTICS - MOCK DATA GENERATOR")
    print("=" * 70)
    
    # Initialize BigQuery client
    client = bigquery.Client(project=PROJECT, location=LOCATION)
    
    # Create dataset
    ds = bigquery.Dataset(f"{PROJECT}.{DATASET}")
    ds.location = LOCATION
    client.create_dataset(ds, exists_ok=True)
    print(f"\nDataset '{DATASET}' ready")
    
    # Create tables
    print("\nCreating tables...")
    for table_name, schema in SCHEMAS.items():
        table_ref = f"{PROJECT}.{DATASET}.{table_name}"
        table = bigquery.Table(table_ref, schema=schema)
        client.delete_table(table_ref, not_found_ok=True)
        client.create_table(table)
        print(f"  ✓ {table_name}")
    
    # Generate data
    print("\n" + "=" * 70)
    print("GENERATING DATA")
    print("=" * 70)
    data = generate_data()
    
    # Load data
    print("\n" + "=" * 70)
    print("LOADING DATA TO BIGQUERY")
    print("=" * 70)
    
    for table_name, rows in data.items():
        if not rows:
            continue
        
        table_ref = f"{PROJECT}.{DATASET}.{table_name}"
        
        # Load in batches
        batch_size = 10000
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            errors = client.insert_rows_json(table_ref, batch)
            if errors:
                print(f"  ✗ {table_name}: {len(errors)} errors")
                print(f"    First error: {errors[0]}")
            else:
                print(f"  ✓ {table_name}: loaded {min(i + batch_size, len(rows))}/{len(rows)} rows")
    
    print("\n" + "=" * 70)
    print("COMPLETE!")
    print("=" * 70)
    print(f"\nDataset: {PROJECT}.{DATASET}")
    print("Tables created:")
    for table_name in SCHEMAS.keys():
        count = len(data.get(table_name, []))
        print(f"  - {table_name}: {count:,} rows")

if __name__ == "__main__":
    main()