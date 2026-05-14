"""
Semantic Layer Setup — Telecom v6 Ontology Support
===================================================
Configuration-driven setup for Neo4j knowledge graph with full support for:
  - Retail domain (original 10 layers)
  - Telecom v6 domain (topology, events, ontology layer)

Usage:
    # Load telecom domain
    python semantic_layer_setup_configurable.py --config-dir configs/telecom
    
    # Load retail domain
    python semantic_layer_setup_configurable.py --config-dir configs/retail
    
    # Dry run (validate configs without writing)
    python semantic_layer_setup_configurable.py --config-dir configs/telecom --dry-run
    
    # Clear and reload
    python semantic_layer_setup_configurable.py --config-dir configs/telecom --clear

Config Structure (Telecom v6):
    configs/telecom/
    ├── ontology.yaml      # meta, tables, joins, neo4j_schema, business, examples
    └── domain_data.yaml   # regions, clusters, towers, cells, equipment, events, relationships
"""

import os
import sys
import re
import json
import logging
import argparse
from pathlib import Path
from typing import Dict, List, Any, Optional

import yaml

from dotenv import load_dotenv
load_dotenv(".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("telecom_setup")

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class TelecomSemanticLayerSetup:
    """Configuration-driven semantic layer setup for Telecom v6 ontology."""
    
    def __init__(self, config_dir: str, dry_run: bool = False, clear: bool = False):
        self.config_dir = Path(config_dir)
        self.dry_run = dry_run
        self.clear = clear
        
        # Config data
        self.ontology: Dict = {}
        self.domain_data: Dict = {}
        
        # Variable substitution map
        self.variables: Dict[str, str] = {}
        
        # Stats tracking
        self.stats = {
            # Schema
            "tables": 0, "joins": 0,
            # KPIs
            "kpis": 0, "kpi_drivers": 0,
            # Ontology layer
            "ont_entities": 0, "ont_concepts": 0, "ont_events": 0,
            "triggers_edges": 0, "causes_edges": 0,
            # KG instance layer
            "regions": 0, "clusters": 0, "towers": 0, "cells": 0,
            "equipment": 0, "subscribers": 0, "events": 0,
            # Relationships
            "neighbours": 0, "interferes_with": 0, "served_by": 0,
            "equipped_with": 0, "powered_by": 0, "impacted_by": 0,
            "event_cascades": 0, "event_ont_links": 0,
            # Examples
            "sql_examples": 0, "cypher_examples": 0,
        }
        
        # Lazy-loaded knowledge graph
        self._kg = None
    
    @property
    def kg(self):
        """Lazy load KnowledgeGraph."""
        if self._kg is None and not self.dry_run:
            from knowledge_graph import KnowledgeGraph
            self._kg = KnowledgeGraph()
        return self._kg
    
    # ═══════════════════════════════════════════════════════════════════════════
    # CONFIG LOADING
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _resolve_variables(self, text: str) -> str:
        """Replace ${VAR} placeholders with actual values."""
        def replacer(match):
            var_name = match.group(1)
            # Try uppercase first (env var style), then lowercase
            return self.variables.get(var_name, 
                   self.variables.get(var_name.lower(), 
                   self.variables.get(var_name.upper(), match.group(0))))
        return re.sub(r'\$\{([^}]+)\}', replacer, str(text))
    
    def _resolve_dict(self, d: Any) -> Any:
        """Recursively resolve variables in a dict/list structure."""
        if isinstance(d, dict):
            return {k: self._resolve_dict(v) for k, v in d.items()}
        elif isinstance(d, list):
            return [self._resolve_dict(item) for item in d]
        elif isinstance(d, str):
            return self._resolve_variables(d)
        return d
    
    def load_configs(self) -> "TelecomSemanticLayerSetup":
        """Load all config files from config_dir."""
        log.info(f"Loading configs from {self.config_dir}")
        
        # ── Load ontology.yaml (required) ──
        ontology_path = self.config_dir / "ontology.yaml"
        if not ontology_path.exists():
            raise FileNotFoundError(f"Required file not found: {ontology_path}")
        
        with open(ontology_path, 'r', encoding='utf-8') as f:
            raw_ontology = yaml.safe_load(f)
        
        # Extract variables from meta section
        meta = raw_ontology.get("meta", {})
        bq = meta.get("bigquery", {})
        
        # Build variables from env vars and config
        self.variables = {
            # From environment
            "BIGQUERY_PROJECT": os.getenv("GCP_PROJECT", bq.get("project", "")),
            "BIGQUERY_DATASET": os.getenv("BQ_DATASET", bq.get("dataset", "")),
            "NEO4J_HOST": os.getenv("NEO4J_HOST", "localhost"),
            # Lowercase versions for compatibility
            "bigquery_project": os.getenv("GCP_PROJECT", bq.get("project", "")),
            "bigquery_dataset": os.getenv("BQ_DATASET", bq.get("dataset", "")),
        }
        
        # Also reference meta.bigquery.project/dataset
        self.variables["meta.bigquery.project"] = self.variables["BIGQUERY_PROJECT"]
        self.variables["meta.bigquery.dataset"] = self.variables["BIGQUERY_DATASET"]
        
        # Resolve variables and store
        self.ontology = self._resolve_dict(raw_ontology)
        
        # Log what we loaded
        tables = self.ontology.get("tables", [])
        business = self.ontology.get("business", {})
        log.info(f"  Loaded ontology.yaml:")
        log.info(f"    - {len(tables)} tables")
        log.info(f"    - {len(business.get('entities', []))} entities")
        log.info(f"    - {len(business.get('kpis', []))} KPIs")
        log.info(f"    - {len(business.get('concepts', []))} concepts")
        log.info(f"    - {len(business.get('event_types', []))} event types")
        
        # ── Load domain_data.yaml (optional but expected for telecom) ──
        domain_data_path = self.config_dir / "domain_data.yaml"
        if domain_data_path.exists():
            with open(domain_data_path, 'r', encoding='utf-8') as f:
                self.domain_data = self._resolve_dict(yaml.safe_load(f) or {})
            
            log.info(f"  Loaded domain_data.yaml:")
            log.info(f"    - {len(self.domain_data.get('regions', []))} regions")
            log.info(f"    - {len(self.domain_data.get('clusters', []))} clusters")
            log.info(f"    - {len(self.domain_data.get('towers', []))} towers")
            log.info(f"    - {len(self.domain_data.get('cells', []))} cells")
            log.info(f"    - {len(self.domain_data.get('equipment', []))} equipment")
            log.info(f"    - {len(self.domain_data.get('subscribers', []))} subscribers")
            log.info(f"    - {len(self.domain_data.get('events', []))} events")
        else:
            log.warning(f"  domain_data.yaml not found at {domain_data_path}")
        
        return self
    
    def _resolve_table_fqn(self, name_or_fqn: str) -> str:
        """Resolve a table name to its FQN."""
        if "." in name_or_fqn:
            return name_or_fqn
        
        # Look up in tables list
        for table in self.ontology.get("tables", []):
            if table.get("name") == name_or_fqn:
                return table.get("fqn", "")
        
        # Construct FQN from variables
        project = self.variables.get("BIGQUERY_PROJECT", "")
        dataset = self.variables.get("BIGQUERY_DATASET", "")
        if project and dataset:
            return f"{project}.{dataset}.{name_or_fqn}"
        return name_or_fqn
    
    # ═══════════════════════════════════════════════════════════════════════════
    # SETUP METHODS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def run_setup(self):
        """Run the full setup process."""
        log.info("=" * 70)
        log.info("TELECOM SEMANTIC LAYER SETUP")
        log.info("=" * 70)
        
        if self.dry_run:
            log.info("DRY RUN MODE - No changes will be made to Neo4j")
        
        if self.clear and not self.dry_run:
            log.warning("Clearing all existing Neo4j data...")
            self.kg.clear_all()
        
        # Phase 1: Schema Layer
        self._setup_schema()
        
        # Phase 2: KPIs and Driver Trees
        self._setup_kpis()
        
        # Phase 3: Ontology Layer (OntEntity, OntConcept, OntEvent)
        self._setup_ontology_layer()
        
        # Phase 4: KG Instance Layer (topology)
        self._setup_kg_instances()
        
        # Phase 5: KG Relationships
        self._setup_kg_relationships()
        
        # Phase 6: Link Events to Ontology
        self._setup_event_ontology_links()
        
        # Phase 7: Query Examples
        self._setup_examples()
        
        # Summary
        self._print_summary()
        
        # Close connection
        if not self.dry_run and self._kg:
            self._kg.close()
        
        return self.stats
    
    # ═══════════════════════════════════════════════════════════════════════════
    # PHASE 1: SCHEMA LAYER
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _setup_schema(self):
        """Setup tables and joins."""
        log.info("\n[Phase 1] Schema Layer...")
        
        tables = self.ontology.get("tables", [])
        for table in tables:
            fqn = table.get("fqn", "")
            if not fqn:
                continue
            
            if self.dry_run:
                log.debug(f"  [DRY RUN] Would create table: {table.get('name')}")
            else:
                self.kg.upsert_table(
                    fqn=fqn,
                    name=table.get("name", ""),
                    desc=table.get("description", ""),
                    dataset=self.variables.get("BIGQUERY_DATASET", ""),
                    columns=table.get("columns", []),
                    layer=table.get("layer", ""),
                )
            self.stats["tables"] += 1
        
        # Joins
        joins = self.ontology.get("joins", [])
        for join in joins:
            from_fqn = self._resolve_table_fqn(join.get("from", ""))
            to_fqn = self._resolve_table_fqn(join.get("to", ""))
            
            if from_fqn and to_fqn and not self.dry_run:
                self.kg.upsert_relationship(
                    from_fqn, to_fqn,
                    join.get("type", "MANY_TO_ONE"),
                    join.get("condition", ""),
                )
            self.stats["joins"] += 1
        
        log.info(f"  Created {self.stats['tables']} tables, {self.stats['joins']} joins")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # PHASE 2: KPIs AND DRIVER TREES
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _setup_kpis(self):
        """Setup KPIs and driver tree edges."""
        log.info("\n[Phase 2] KPIs and Driver Trees...")
        
        business = self.ontology.get("business", {})
        kpis = business.get("kpis", [])
        
        # Get schema mapping for KPI table dependencies
        schema_mapping = self.ontology.get("schema_mapping", {})
        kpi_table_deps = {
            dep.get("kpi"): dep 
            for dep in schema_mapping.get("kpi_table_dependencies", [])
        }
        
        for kpi in kpis:
            name = kpi.get("name", "")
            if not name:
                continue
            
            # Get table FQNs from schema_mapping or dimensions
            table_fqns = []
            if name in kpi_table_deps:
                dep = kpi_table_deps[name]
                primary = dep.get("primary", "")
                if primary:
                    table_fqns.append(self._resolve_table_fqn(primary))
                for join_table in dep.get("joins", []):
                    table_fqns.append(self._resolve_table_fqn(join_table))
            
            if not self.dry_run:
                self.kg.upsert_kpi(
                    name=name,
                    expression=kpi.get("expression", ""),
                    table_fqns=table_fqns,
                    description=kpi.get("description", ""),
                    display_name=kpi.get("display_name", ""),
                    unit=kpi.get("unit", ""),
                    grain=kpi.get("grain", "daily"),
                    direction=kpi.get("direction", "lower_is_better"),
                    thresholds=kpi.get("thresholds"),
                    dimensions=kpi.get("dimensions"),
                    synonyms=kpi.get("synonyms"),
                )
            self.stats["kpis"] += 1
        
        # KPI Driver Tree
        driver_tree = business.get("kpi_driver_tree", [])
        for edge in driver_tree:
            if not self.dry_run:
                self.kg.upsert_kpi_driver(
                    parent_kpi=edge.get("parent", ""),
                    child_kpi=edge.get("child", ""),
                    direction=edge.get("direction", ""),
                    plain_english=edge.get("plain_english", ""),
                )
            self.stats["kpi_drivers"] += 1
        
        log.info(f"  Created {self.stats['kpis']} KPIs, {self.stats['kpi_drivers']} driver edges")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # PHASE 3: ONTOLOGY LAYER
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _setup_ontology_layer(self):
        """Setup OntEntity, OntConcept, OntEvent nodes and their relationships."""
        log.info("\n[Phase 3] Ontology Layer...")
        
        business = self.ontology.get("business", {})
        
        # ── OntEntity nodes ──
        entities = business.get("entities", [])
        for entity in entities:
            entity_id = entity.get("id", "")
            if not entity_id:
                continue
            
            if not self.dry_run:
                self.kg.upsert_ont_entity(
                    entity_id=entity_id,
                    display_name=entity.get("display_name", ""),
                    synonyms=entity.get("synonyms", []),
                    primary_kpi=entity.get("primary_kpi", ""),
                    hierarchy_level=entity.get("hierarchy_level", 0),
                    attributes=entity.get("attributes", []),
                )
            self.stats["ont_entities"] += 1
        
        # ── OntConcept nodes (must be created before TRIGGERS edges) ──
        concepts = business.get("concepts", [])
        for concept in concepts:
            concept_id = concept.get("id", "")
            if not concept_id:
                continue
            
            if not self.dry_run:
                self.kg.upsert_ont_concept(
                    concept_id=concept_id,
                    display_name=concept.get("display_name", ""),
                    synonyms=concept.get("synonyms", []),
                    kpis=concept.get("kpis", []),
                    entities=concept.get("entities", []),
                )
            self.stats["ont_concepts"] += 1
        
        # ── CAUSES edges between OntConcepts ──
        for concept in concepts:
            concept_id = concept.get("id", "")
            for cause_def in concept.get("causes", []):
                target_concept = cause_def.get("concept", "")
                if target_concept and not self.dry_run:
                    self.kg.upsert_ont_causes(
                        source_concept_id=concept_id,
                        target_concept_id=target_concept,
                        strength=cause_def.get("strength", "moderate"),
                        time_lag=cause_def.get("time_lag", ""),
                        plain_english=cause_def.get("plain_english", ""),
                    )
                    self.stats["causes_edges"] += 1
        
        # ── OntEvent nodes with TRIGGERS edges ──
        event_types = business.get("event_types", [])
        for event_type in event_types:
            event_type_id = event_type.get("id", "")
            if not event_type_id:
                continue
            
            triggers_concepts = event_type.get("triggers_concepts", [])
            
            if not self.dry_run:
                self.kg.upsert_ont_event(
                    event_type_id=event_type_id,
                    display_name=event_type.get("display_name", ""),
                    domain=event_type.get("domain", ""),
                    severity_scale=event_type.get("severity_scale", "medium"),
                    typical_duration_days=event_type.get("typical_duration_days", 1),
                    triggers_concepts=triggers_concepts,
                )
            self.stats["ont_events"] += 1
            self.stats["triggers_edges"] += len(triggers_concepts)
        
        log.info(f"  Created {self.stats['ont_entities']} OntEntity nodes")
        log.info(f"  Created {self.stats['ont_concepts']} OntConcept nodes, {self.stats['causes_edges']} CAUSES edges")
        log.info(f"  Created {self.stats['ont_events']} OntEvent nodes, {self.stats['triggers_edges']} TRIGGERS edges")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # PHASE 4: KG INSTANCE LAYER (Topology)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _setup_kg_instances(self):
        """Setup KG instance nodes from domain_data."""
        log.info("\n[Phase 4] KG Instance Layer (Topology)...")
        
        if not self.domain_data:
            log.info("  No domain_data.yaml loaded, skipping")
            return
        
        # ── Regions ──
        for region in self.domain_data.get("regions", []):
            if not self.dry_run:
                self.kg.upsert_kg_region(
                    region_id=region.get("region_id", ""),
                    region_name=region.get("region_name", ""),
                    region_type=region.get("region_type", "urban"),
                    country=region.get("country", "UK"),
                    market=region.get("market", "consumer"),
                    population_density=region.get("population_density", "medium"),
                )
            self.stats["regions"] += 1
        
        # ── Clusters ──
        for cluster in self.domain_data.get("clusters", []):
            if not self.dry_run:
                self.kg.upsert_kg_cluster(
                    cluster_id=cluster.get("cluster_id", ""),
                    cluster_name=cluster.get("cluster_name", ""),
                    region_id=cluster.get("region_id", ""),
                    cluster_type=cluster.get("cluster_type", "urban_core"),
                    tower_count=cluster.get("tower_count", 0),
                )
            self.stats["clusters"] += 1
        
        # ── Towers ──
        for tower in self.domain_data.get("towers", []):
            if not self.dry_run:
                self.kg.upsert_kg_tower(
                    tower_id=tower.get("tower_id", ""),
                    tower_name=tower.get("tower_name", ""),
                    region_id=tower.get("region_id", ""),
                    cluster_id=tower.get("cluster_id", ""),
                    latitude=tower.get("latitude", 0.0),
                    longitude=tower.get("longitude", 0.0),
                    height_m=tower.get("height_m", 30.0),
                    tower_type=tower.get("tower_type", "greenfield"),
                    power_source=tower.get("power_source", "grid"),
                    has_backup_power=tower.get("has_backup_power", True),
                    is_active=tower.get("is_active", True),
                )
            self.stats["towers"] += 1
        
        # ── Cells ──
        for cell in self.domain_data.get("cells", []):
            if not self.dry_run:
                self.kg.upsert_kg_cell(
                    cell_id=cell.get("cell_id", ""),
                    cell_name=cell.get("cell_name", ""),
                    tower_id=cell.get("tower_id", ""),
                    region_id=cell.get("region_id", ""),
                    technology=cell.get("technology", "4G"),
                    band_mhz=str(cell.get("band_mhz", "1800")),
                    sector=cell.get("sector", "A"),
                    azimuth_deg=cell.get("azimuth_deg", 0),
                    tilt_deg=cell.get("tilt_deg", 4.0),
                    tx_power_dbm=cell.get("tx_power_dbm", 43.0),
                    designed_capacity=cell.get("designed_capacity", 500),
                    cell_type=cell.get("cell_type", "macro"),
                    vendor=cell.get("vendor", "Ericsson"),
                    pci=cell.get("pci", 0),
                    is_active=cell.get("is_active", True),
                )
            self.stats["cells"] += 1
        
        # ── Equipment ──
        for equipment in self.domain_data.get("equipment", []):
            if not self.dry_run:
                self.kg.upsert_kg_equipment(
                    equipment_id=equipment.get("equipment_id", ""),
                    equipment_type=equipment.get("equipment_type", "RRU"),
                    vendor=equipment.get("vendor", ""),
                    model=equipment.get("model", ""),
                    firmware_version=equipment.get("firmware_version", ""),
                    install_date=equipment.get("install_date", ""),
                    status=equipment.get("status", "active"),
                )
            self.stats["equipment"] += 1
        
        # ── Subscribers ──
        for subscriber in self.domain_data.get("subscribers", []):
            if not self.dry_run:
                self.kg.upsert_kg_subscriber(
                    subscriber_id=subscriber.get("subscriber_id", ""),
                    subscription_type=subscriber.get("subscription_type", "postpaid"),
                    segment=subscriber.get("segment", "consumer"),
                    loyalty_tier=subscriber.get("loyalty_tier", "standard"),
                    home_region_id=subscriber.get("home_region_id", ""),
                    churn_risk_score=subscriber.get("churn_risk_score", 0.0),
                    is_active=subscriber.get("is_active", True),
                )
            self.stats["subscribers"] += 1
        
        # ── Events ──
        for event in self.domain_data.get("events", []):
            if not self.dry_run:
                self.kg.upsert_kg_event(
                    event_id=event.get("event_id", ""),
                    event_type=event.get("event_type", ""),
                    severity=event.get("severity", "medium"),
                    start_date=event.get("start_date", ""),
                    end_date=event.get("end_date"),
                    is_resolved=event.get("is_resolved", False),
                    source=event.get("source", "nms_alarm"),
                    description=event.get("description", ""),
                    subscribers_affected=event.get("subscribers_affected", 0),
                    cells_affected=event.get("cells_affected", 0),
                )
            self.stats["events"] += 1
        
        log.info(f"  Created {self.stats['regions']} regions, {self.stats['clusters']} clusters")
        log.info(f"  Created {self.stats['towers']} towers, {self.stats['cells']} cells")
        log.info(f"  Created {self.stats['equipment']} equipment, {self.stats['subscribers']} subscribers")
        log.info(f"  Created {self.stats['events']} events")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # PHASE 5: KG RELATIONSHIPS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _setup_kg_relationships(self):
        """Setup KG relationships from domain_data."""
        log.info("\n[Phase 5] KG Relationships...")
        
        if not self.domain_data:
            log.info("  No domain_data.yaml loaded, skipping")
            return
        
        # ── NEIGHBOURS ──
        for neighbour in self.domain_data.get("neighbours", []):
            if not self.dry_run:
                self.kg.upsert_neighbours(
                    source_cell_id=neighbour.get("source_cell_id", ""),
                    target_cell_id=neighbour.get("target_cell_id", ""),
                    ho_direction=neighbour.get("ho_direction", "bidirectional"),
                    ho_offset_db=neighbour.get("ho_offset_db", 3),
                    is_active_neighbour=neighbour.get("is_active_neighbour", True),
                )
            self.stats["neighbours"] += 1
        
        # ── INTERFERES_WITH ──
        for interference in self.domain_data.get("interferes_with", []):
            if not self.dry_run:
                self.kg.upsert_interferes_with(
                    source_cell_id=interference.get("source_cell_id", ""),
                    target_cell_id=interference.get("target_cell_id", ""),
                    interference_type=interference.get("interference_type", "co_channel"),
                    interference_db=interference.get("interference_db", 0.0),
                    detected_date=interference.get("detected_date", ""),
                    is_active=interference.get("is_active", True),
                )
            self.stats["interferes_with"] += 1
        
        # ── SERVED_BY ──
        for served in self.domain_data.get("served_by", []):
            if not self.dry_run:
                self.kg.upsert_served_by(
                    subscriber_id=served.get("subscriber_id", ""),
                    cell_id=served.get("cell_id", ""),
                    relationship_type=served.get("relationship_type", "home"),
                    pct_calls=served.get("pct_calls", 0),
                    pct_data=served.get("pct_data", 0),
                )
            self.stats["served_by"] += 1
        
        # ── EQUIPPED_WITH ──
        for equipped in self.domain_data.get("equipped_with", []):
            if not self.dry_run:
                self.kg.upsert_equipped_with(
                    cell_id=equipped.get("cell_id", ""),
                    equipment_id=equipped.get("equipment_id", ""),
                    equipment_role=equipped.get("equipment_role", "primary_radio"),
                )
            self.stats["equipped_with"] += 1
        
        # ── POWERED_BY ──
        for powered in self.domain_data.get("powered_by", []):
            if not self.dry_run:
                self.kg.upsert_powered_by(
                    tower_id=powered.get("tower_id", ""),
                    equipment_id=powered.get("equipment_id", ""),
                    power_type=powered.get("power_type", "primary"),
                    capacity_kw=powered.get("capacity_kw", 10.0),
                    backup_hours=powered.get("backup_hours", 8),
                )
            self.stats["powered_by"] += 1
        
        # ── IMPACTED_BY (from events.impacted_entities) ──
        for event in self.domain_data.get("events", []):
            event_id = event.get("event_id", "")
            for impacted in event.get("impacted_entities", []):
                if not self.dry_run:
                    self.kg.upsert_impacted_by(
                        entity_type=impacted.get("entity_type", ""),
                        entity_id=impacted.get("entity_id", ""),
                        event_id=event_id,
                    )
                self.stats["impacted_by"] += 1
        
        # ── EVENT_CASCADES (CAUSED_BY between events) ──
        for cascade in self.domain_data.get("event_cascades", []):
            if not self.dry_run:
                self.kg.upsert_event_caused_by(
                    source_event_id=cascade.get("source_event_id", ""),
                    target_event_id=cascade.get("target_event_id", ""),
                    mechanism=cascade.get("mechanism", ""),
                    lag_minutes=cascade.get("lag_minutes", 0),
                )
            self.stats["event_cascades"] += 1
        
        log.info(f"  Created {self.stats['neighbours']} NEIGHBOURS edges")
        log.info(f"  Created {self.stats['interferes_with']} INTERFERES_WITH edges")
        log.info(f"  Created {self.stats['served_by']} SERVED_BY edges")
        log.info(f"  Created {self.stats['equipped_with']} EQUIPPED_WITH edges")
        log.info(f"  Created {self.stats['powered_by']} POWERED_BY edges")
        log.info(f"  Created {self.stats['impacted_by']} IMPACTED_BY edges")
        log.info(f"  Created {self.stats['event_cascades']} CAUSED_BY (cascade) edges")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # PHASE 6: LINK EVENTS TO ONTOLOGY
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _setup_event_ontology_links(self):
        """Link KGEvent instances to OntEvent types via EVENT_INSTANCE_OF."""
        log.info("\n[Phase 6] Event-Ontology Links...")
        
        if not self.domain_data:
            log.info("  No domain_data.yaml loaded, skipping")
            return
        
        for event in self.domain_data.get("events", []):
            event_id = event.get("event_id", "")
            event_type = event.get("event_type", "")
            
            if event_id and event_type and not self.dry_run:
                self.kg.link_event_to_ont_event(event_id, event_type)
                self.stats["event_ont_links"] += 1
        
        log.info(f"  Created {self.stats['event_ont_links']} EVENT_INSTANCE_OF edges")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # PHASE 7: QUERY EXAMPLES
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _setup_examples(self):
        """Setup SQL and Cypher query examples."""
        log.info("\n[Phase 7] Query Examples...")
        
        examples = self.ontology.get("examples", {})
        
        # SQL examples - store as QueryExample nodes
        for example in examples.get("sql", []):
            example_id = example.get("id", "")
            question = example.get("question", "")
            sql = example.get("sql", "")
            category = example.get("category", "LOOKUP")
            
            if example_id and sql and not self.dry_run:
                self._upsert_sql_example(
                    example_id=example_id,
                    question=question,
                    sql=sql,
                    category=category,
                )
            self.stats["sql_examples"] += 1
        
        # Cypher examples - store as CypherExample nodes
        for example in examples.get("cypher", []):
            example_id = example.get("id", "")
            intent = example.get("intent", "")
            cypher = example.get("cypher", "")
            
            if example_id and cypher and not self.dry_run:
                self._upsert_cypher_example(
                    example_id=example_id,
                    intent=intent,
                    cypher=cypher,
                )
            self.stats["cypher_examples"] += 1
        
        log.info(f"  Created {self.stats['sql_examples']} SQL examples")
        log.info(f"  Created {self.stats['cypher_examples']} Cypher examples")
    
    def _upsert_sql_example(self, example_id: str, question: str, sql: str, category: str):
        """Store a SQL example in Neo4j."""
        with self.kg.driver.session() as s:
            s.run("""
                MERGE (e:QueryExample:SQLExample {example_id: $example_id})
                SET e.question = $question,
                    e.sql = $sql,
                    e.category = $category,
                    e.type = 'sql'
            """, example_id=example_id, question=question, sql=sql, category=category)
    
    def _upsert_cypher_example(self, example_id: str, intent: str, cypher: str):
        """Store a Cypher example in Neo4j."""
        with self.kg.driver.session() as s:
            s.run("""
                MERGE (e:QueryExample:CypherExample {example_id: $example_id})
                SET e.intent = $intent,
                    e.cypher = $cypher,
                    e.type = 'cypher'
            """, example_id=example_id, intent=intent, cypher=cypher)
    
    # ═══════════════════════════════════════════════════════════════════════════
    # SUMMARY
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _print_summary(self):
        """Print setup summary."""
        log.info("\n" + "=" * 70)
        log.info("SETUP COMPLETE")
        log.info("=" * 70)
        
        log.info("\nSchema Layer:")
        log.info(f"  Tables:       {self.stats['tables']}")
        log.info(f"  Joins:        {self.stats['joins']}")
        
        log.info("\nKPI Layer:")
        log.info(f"  KPIs:         {self.stats['kpis']}")
        log.info(f"  Driver Edges: {self.stats['kpi_drivers']}")
        
        log.info("\nOntology Layer:")
        log.info(f"  OntEntity:    {self.stats['ont_entities']}")
        log.info(f"  OntConcept:   {self.stats['ont_concepts']}")
        log.info(f"  OntEvent:     {self.stats['ont_events']}")
        log.info(f"  CAUSES edges: {self.stats['causes_edges']}")
        log.info(f"  TRIGGERS edges: {self.stats['triggers_edges']}")
        
        log.info("\nKG Instance Layer:")
        log.info(f"  Regions:      {self.stats['regions']}")
        log.info(f"  Clusters:     {self.stats['clusters']}")
        log.info(f"  Towers:       {self.stats['towers']}")
        log.info(f"  Cells:        {self.stats['cells']}")
        log.info(f"  Equipment:    {self.stats['equipment']}")
        log.info(f"  Subscribers:  {self.stats['subscribers']}")
        log.info(f"  Events:       {self.stats['events']}")
        
        log.info("\nRelationships:")
        log.info(f"  NEIGHBOURS:       {self.stats['neighbours']}")
        log.info(f"  INTERFERES_WITH:  {self.stats['interferes_with']}")
        log.info(f"  SERVED_BY:        {self.stats['served_by']}")
        log.info(f"  EQUIPPED_WITH:    {self.stats['equipped_with']}")
        log.info(f"  POWERED_BY:       {self.stats['powered_by']}")
        log.info(f"  IMPACTED_BY:      {self.stats['impacted_by']}")
        log.info(f"  EVENT_INSTANCE_OF: {self.stats['event_ont_links']}")
        
        log.info("\nExamples:")
        log.info(f"  SQL:          {self.stats['sql_examples']}")
        log.info(f"  Cypher:       {self.stats['cypher_examples']}")
        
        total_nodes = (
            self.stats['tables'] + self.stats['kpis'] + 
            self.stats['ont_entities'] + self.stats['ont_concepts'] + self.stats['ont_events'] +
            self.stats['regions'] + self.stats['clusters'] + self.stats['towers'] +
            self.stats['cells'] + self.stats['equipment'] + self.stats['subscribers'] +
            self.stats['events']
        )
        total_edges = (
            self.stats['joins'] + self.stats['kpi_drivers'] +
            self.stats['causes_edges'] + self.stats['triggers_edges'] +
            self.stats['neighbours'] + self.stats['interferes_with'] +
            self.stats['served_by'] + self.stats['equipped_with'] +
            self.stats['powered_by'] + self.stats['impacted_by'] +
            self.stats['event_ont_links']
        )
        
        log.info(f"\nTOTAL: {total_nodes} nodes, {total_edges} edges")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Telecom Semantic Layer Setup",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config-dir", "-c",
        default="configs/telecom",
        help="Path to config directory (default: configs/telecom)",
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Validate configs without writing to Neo4j",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear all existing Neo4j data before setup",
    )
    
    args = parser.parse_args()
    
    setup = TelecomSemanticLayerSetup(
        config_dir=args.config_dir,
        dry_run=args.dry_run,
        clear=args.clear,
    )
    
    setup.load_configs()
    setup.run_setup()


if __name__ == "__main__":
    main()