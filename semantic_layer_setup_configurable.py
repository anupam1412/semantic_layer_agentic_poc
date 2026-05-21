"""
Semantic Layer Setup — Configuration-Driven (Use-Case Agnostic)
===============================================================
Reads all ontology, domain layers, and data from YAML/JSON config files
and populates Neo4j + Vector Search.

This replaces the hardcoded semantic_layer_setup.py with a configuration-driven
approach. Same destination (full Neo4j), different source (config files).

Usage:
    # Load retail domain (default)
    python semantic_layer_setup_configurable.py
    
    # Load different domain
    python semantic_layer_setup_configurable.py --config-dir configs/healthcare
    
    # Dry run (validate configs without writing)
    python semantic_layer_setup_configurable.py --dry-run

Config Structure:
    configs/retail/
    ├── ontology.yaml         # Tables, KPIs, concepts, examples
    ├── domain_layers.yaml    # Event type schemas  
    ├── domain_data.yaml      # Actual domain events (10 layers)
    └── org_hierarchy.yaml    # Regions, stores, territories (optional)
"""

import os
import sys
import json
import logging
import argparse
from pathlib import Path
from typing import Dict, List, Any, Optional

import yaml

# Load environment variables from .env or _env
try:
    from dotenv import load_dotenv
    # Try _env first (project convention), then .env
    env_file = Path("_env") if Path("_env").exists() else Path(".env")
    if env_file.exists():
        load_dotenv(env_file)
        print(f"[SETUP] Loaded environment from {env_file}")
except ImportError:
    print("[SETUP] Warning: python-dotenv not installed, using system env vars")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("setup")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class ConfigurableSemanticLayerSetup:
    """Configuration-driven semantic layer setup for Neo4j."""
    
    def __init__(self, config_dir: str, dry_run: bool = False):
        self.config_dir = Path(config_dir)
        self.dry_run = dry_run
        
        # Config data
        self.ontology: Dict = {}
        self.domain_layers: Dict = {}
        self.domain_data: Dict = {}
        self.org_hierarchy: Dict = {}
        
        # Variable substitution map
        self.variables: Dict[str, str] = {}
        
        # Stats
        self.stats = {
            "tables": 0, "joins": 0, "fks": 0,
            "kpis": 0, "driver_edges": 0,
            "concepts": 0, "affects_edges": 0,
            "examples": 0,
            "regions": 0, "stores": 0, "territories": 0,
            "location_entities": 0,
            "suppliers": 0, "supply_incidents": 0,
            "account_managers": 0, "contracts": 0, "churn_risks": 0,
            "competitor_actions": 0, "market_conditions": 0, "policy_changes": 0,
            "loyalty_tiers": 0, "redemption_rules": 0, "campaigns": 0,
            "pricing_decisions": 0, "discount_policies": 0,
            "categories": 0, "brands": 0,
        }
        
        # Lazy-loaded stores
        self._kg = None
        self._vs = None
        self._bq = None
    
    @property
    def kg(self):
        if self._kg is None and not self.dry_run:
            from knowledge_graph import KnowledgeGraph
            self._kg = KnowledgeGraph()
        return self._kg
    
    @property
    def vs(self):
        if self._vs is None and not self.dry_run:
            from vector_search import VectorSearch
            # Pass Neo4j driver to vector search (uses Neo4j native vector indexes)
            self._vs = VectorSearch(neo4j_driver=self.kg.driver)
        return self._vs
    
    @property
    def bq(self):
        if self._bq is None and not self.dry_run:
            from google.cloud import bigquery
            project = self.variables.get("bigquery_project", "")
            self._bq = bigquery.Client(project=project, location="europe-west2")
        return self._bq
    
    # ═══════════════════════════════════════════════════════════════════════
    # CONFIG LOADING
    # ═══════════════════════════════════════════════════════════════════════
    
    def _resolve_variables(self, text: str) -> str:
        """Replace ${var} placeholders with actual values.
        Handles: ${VAR}, ${meta.bigquery.project}, ${meta.bigquery.dataset}
        """
        import re
        def replacer(match):
            var_name = match.group(1)
            # Handle nested meta.bigquery.* references
            if var_name.startswith("meta."):
                return self.variables.get(var_name, match.group(0))
            # Handle regular variables
            return self.variables.get(var_name, match.group(0))
        # Match ${...} patterns including dots for nested refs
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
    
    def load_configs(self):
        """Load all config files from config_dir."""
        log.info(f"Loading configs from {self.config_dir}")
        
        # Load ontology (required)
        ontology_path = self.config_dir / "ontology.yaml"
        if not ontology_path.exists():
            raise FileNotFoundError(f"Required file not found: {ontology_path}")
        
        with open(ontology_path, 'r', encoding='utf-8') as f:
            raw_ontology = yaml.safe_load(f)
        
        # Extract variables from meta section
        meta = raw_ontology.get("meta", {})
        
        # Get bigquery settings (handle nested structure)
        bq_meta = meta.get("bigquery", {})
        
        # Resolve env vars in bigquery project/dataset
        bq_project_raw = bq_meta.get("project", "") or ""
        bq_dataset_raw = bq_meta.get("dataset", "") or ""
        
        # Expand env vars like ${BIGQUERY_PROJECT}
        import re
        def expand_env(s):
            def env_replacer(m):
                var = m.group(1)
                # Try multiple env var names as fallbacks
                val = os.getenv(var) or os.getenv(f"BQ_{var.replace('BIGQUERY_', '')}") or ""
                return val if val else m.group(0)
            return re.sub(r'\$\{(\w+)\}', env_replacer, str(s))
        
        bq_project = expand_env(bq_project_raw) or os.getenv("BQ_PROJECT") or os.getenv("BIGQUERY_PROJECT") or ""
        bq_dataset = expand_env(bq_dataset_raw) or os.getenv("BQ_DATASET") or os.getenv("BIGQUERY_DATASET") or ""
        
        # Build variables dict for placeholder expansion
        self.variables = {
            # Support ${meta.bigquery.project} and ${meta.bigquery.dataset}
            "meta.bigquery.project": bq_project,
            "meta.bigquery.dataset": bq_dataset,
            # Also support flat names
            "bigquery_project": bq_project,
            "bigquery_dataset": bq_dataset,
            "BIGQUERY_PROJECT": bq_project,
            "BIGQUERY_DATASET": bq_dataset,
            # Combined prefix
            "P": f"{bq_project}.{bq_dataset}" if bq_project and bq_dataset else "",
        }
        
        log.info(f"  Resolved BigQuery: {bq_project}.{bq_dataset}")
        
        # Resolve variables and store
        self.ontology = self._resolve_dict(raw_ontology)
        
        # Count concepts from both old format (root) and new format (business.concepts)
        root_concepts = self.ontology.get('concepts', [])
        business_concepts = self.ontology.get('business', {}).get('concepts', [])
        concept_count = len(root_concepts) or len(business_concepts)
        
        log.info(f"  Loaded ontology: {len(self.ontology.get('tables', []))} tables, "
                f"{len(self.ontology.get('kpis', []))} KPIs, "
                f"{concept_count} concepts")
        
        # Load domain layers schema (optional)
        domain_layers_path = self.config_dir / "domain_layers.yaml"
        if domain_layers_path.exists():
            with open(domain_layers_path, 'r', encoding='utf-8') as f:
                self.domain_layers = yaml.safe_load(f)
            log.info(f"  Loaded domain layers: {len(self.domain_layers.get('layers', []))} layer types")
        
        # Load domain data (optional)
        domain_data_path = self.config_dir / "domain_data.yaml"
        if domain_data_path.exists():
            with open(domain_data_path, 'r', encoding='utf-8') as f:
                self.domain_data = self._resolve_dict(yaml.safe_load(f))
            log.info(f"  Loaded domain data: {sum(len(v) for k, v in self.domain_data.items() if isinstance(v, list))} events")
        
        # Load org hierarchy (optional)
        org_path = self.config_dir / "org_hierarchy.yaml"
        if org_path.exists():
            with open(org_path, 'r', encoding='utf-8') as f:
                self.org_hierarchy = self._resolve_dict(yaml.safe_load(f))
            log.info(f"  Loaded org hierarchy: {len(self.org_hierarchy.get('regions', []))} regions, "
                    f"{len(self.org_hierarchy.get('stores', []))} stores")
        
        return self
    
    # ═══════════════════════════════════════════════════════════════════════
    # LAYER 1: SCHEMA (Tables, Joins, FKs)
    # ═══════════════════════════════════════════════════════════════════════
    
    def setup_layer1_schema(self):
        """Populate tables, relationships, and foreign keys."""
        log.info("Layer 1: Schema...")
        
        tables = self.ontology.get("tables", [])
        dataset = self.variables.get("bigquery_dataset", "")
        
        # Option A: Auto-discover from BigQuery if tables list is empty or has "auto_discover: true"
        if self.ontology.get("meta", {}).get("auto_discover_schema", False):
            self._auto_discover_schema()
        else:
            # Option B: Use tables from config
            for table in tables:
                if self.dry_run:
                    log.info(f"  [DRY RUN] Would create table: {table['name']}")
                else:
                    self.kg.upsert_table(
                        fqn=table["fqn"],
                        name=table["name"],
                        desc=table.get("description", ""),
                        dataset=dataset,
                        columns=table.get("columns", []),
                    )
                self.stats["tables"] += 1
        
        # Relationships
        joins = self.ontology.get("joins", [])
        for join in joins:
            from_fqn = self._resolve_table_fqn(join["from"])
            to_fqn = self._resolve_table_fqn(join["to"])
            if from_fqn and to_fqn:
                if not self.dry_run:
                    self.kg.upsert_relationship(
                        from_fqn, to_fqn,
                        join.get("type", "ONE_TO_MANY"),
                        join.get("condition", ""),
                    )
                self.stats["joins"] += 1
        
        # Foreign keys
        fks = self.ontology.get("foreign_keys", [])
        for fk in fks:
            if not self.dry_run:
                self.kg.upsert_fk(fk["from"], fk["to"])
            self.stats["fks"] += 1
        
        log.info(f"  Layer 1 complete: {self.stats['tables']} tables, "
                f"{self.stats['joins']} joins, {self.stats['fks']} FKs")
    
    def _auto_discover_schema(self):
        """Auto-discover tables from BigQuery."""
        if self.dry_run:
            log.info("  [DRY RUN] Would auto-discover tables from BigQuery")
            return
        
        project = self.variables.get("bigquery_project", "")
        dataset = self.variables.get("bigquery_dataset", "")
        P = f"{project}.{dataset}"
        
        for tref in self.bq.list_tables(self.bq.dataset(dataset, project=project)):
            t = self.bq.get_table(tref)
            cols = [
                {"name": f.name, "type": f.field_type, "description": f.description or ""}
                for f in t.schema
            ]
            self.kg.upsert_table(f"{P}.{t.table_id}", t.table_id, t.description or "", dataset, cols)
            self.stats["tables"] += 1
            log.info(f"    Auto-discovered: {t.table_id} ({len(cols)} columns)")
    
    def _resolve_table_fqn(self, name_or_fqn: str) -> Optional[str]:
        """Resolve a table name to its FQN."""
        # If it already looks like an FQN (has dots), return as-is
        if "." in name_or_fqn:
            return name_or_fqn
        
        # Otherwise, look up in tables list
        for table in self.ontology.get("tables", []):
            if table["name"] == name_or_fqn:
                return table["fqn"]
        
        # Fall back to constructing FQN
        P = self.variables.get("P", "")
        return f"{P}.{name_or_fqn}" if P else name_or_fqn
    
    # ═══════════════════════════════════════════════════════════════════════
    # LAYER 2: ORG HIERARCHY
    # ═══════════════════════════════════════════════════════════════════════
    
    def setup_layer2_org_hierarchy(self):
        """Populate regions, stores, territories."""
        log.info("Layer 2: Org hierarchy...")
        
        if not self.org_hierarchy:
            log.info("  No org_hierarchy.yaml found, skipping")
            return
        
        # Regions
        for region in self.org_hierarchy.get("regions", []):
            if not self.dry_run:
                self.kg.upsert_region(
                    region["name"],
                    region.get("country", "GB"),
                    region.get("head", ""),
                    region.get("store_count", 0),
                )
            self.stats["regions"] += 1
        
        # Stores
        for store in self.org_hierarchy.get("stores", []):
            if not self.dry_run:
                self.kg.upsert_store_node(
                    store["store_id"],
                    store["name"],
                    store["region"],
                    store.get("type", "standard"),
                    store.get("capacity", 0),
                    store.get("opened", ""),
                    store.get("manager_name", ""),
                    store.get("manager_since", ""),
                    store.get("manager_experience", 0),
                )
            self.stats["stores"] += 1
        
        # Territories
        for territory in self.org_hierarchy.get("territories", []):
            if not self.dry_run:
                self.kg.upsert_territory(
                    territory["name"],
                    territory["region"],
                    territory.get("annual_target", 0),
                )
            self.stats["territories"] += 1
        
        log.info(f"  Layer 2 complete: {self.stats['regions']} regions, "
                f"{self.stats['stores']} stores, {self.stats['territories']} territories")
    

    # ═══════════════════════════════════════════════════════════════════════
    # LAYER 2B: LOCATION ENTITIES
    # ═══════════════════════════════════════════════════════════════════════
    
    def setup_layer2b_location_entities(self):
        """Create LocationEntity nodes for entity resolution in queries.
        
        Reads location_entities from ontology.yaml and creates nodes in Neo4j
        that help the agent resolve location names to the correct table/column.
        """
        log.info("  Layer 2b: Location entities...")
        
        location_entities = self.ontology.get("location_entities", [])
        if not location_entities:
            log.info("    No location_entities in ontology, skipping")
            return
        
        for loc in location_entities:
            name = loc.get("name", "")
            loc_type = loc.get("type", "unknown")
            table = loc.get("table", "")
            column = loc.get("column", "")
            
            if not name:
                log.warning(f"    Skipping location entity with no name: {loc}")
                continue
            
            if not self.dry_run:
                self.kg.upsert_location_entity(
                    name=name,
                    loc_type=loc_type,
                    table=table,
                    column=column,
                )
            self.stats["location_entities"] += 1
        
        log.info(f"    Created {self.stats['location_entities']} location entities")
    
    # ═══════════════════════════════════════════════════════════════════════
    # LAYER 3: KPIs + DRIVER TREES
    # ═══════════════════════════════════════════════════════════════════════
    
    def setup_layer3_kpis(self):
        """Populate KPIs and driver tree edges.
        
        Supports two formats:
        
        OLD FORMAT:
            kpis:
              - name: revenue
                expression: "SUM(amount)"
                tables: [orders]
        
        NEW FORMAT:
            business:
              kpis:
                - name: call_drop_rate
                  display_name: "Call Drop Rate"
                  expression: "..."
                  dimensions: [cell_id, region_id]
        """
        log.info("Layer 3: KPIs + driver trees...")
        
        # Try new format first (business.kpis), fall back to old (kpis at root)
        business_section = self.ontology.get("business", {})
        kpis = business_section.get("kpis", []) or self.ontology.get("kpis", [])
        
        for kpi in kpis:
            # Resolve table names to FQNs (may not exist in new format)
            table_fqns = [self._resolve_table_fqn(t) for t in kpi.get("tables", [])]
            table_fqns = [f for f in table_fqns if f]
            
            # Use display_name as description if no description field
            description = kpi.get("description", kpi.get("display_name", ""))
            
            if not self.dry_run:
                self.kg.upsert_kpi(
                    name=kpi["name"],
                    expression=kpi.get("expression", ""),
                    table_fqns=table_fqns,
                    description=description,
                    grain=kpi.get("grain", "monthly"),
                    thresholds=kpi.get("thresholds"),
                    dimensions=kpi.get("dimensions"),
                )
            self.stats["kpis"] += 1
        
        # Driver tree edges
        driver_edges = self.ontology.get("kpi_driver_tree", [])
        for edge in driver_edges:
            if not self.dry_run:
                self.kg.upsert_kpi_driver(edge["parent"], edge["child"])
            self.stats["driver_edges"] += 1
        
        log.info(f"  Layer 3 complete: {self.stats['kpis']} KPIs, "
                f"{self.stats['driver_edges']} driver edges")
    
    # ═══════════════════════════════════════════════════════════════════════
    # LAYER 4: CAUSAL REASONING (Concepts + AFFECTS)
    # ═══════════════════════════════════════════════════════════════════════
    
    def setup_layer4_causal(self):
        """Populate business concepts and AFFECTS edges.
        
        Supports two ontology formats:
        
        OLD FORMAT (retail-style):
            concepts:
              - name: revenue_decline
                maps_to_tables: [orders]
            affects_edges:
              - from: supply_disruption
                to: revenue_decline
        
        NEW FORMAT (telecom-style):
            business:
              concepts:
                - id: call_drop_degradation
                  display_name: "Call Drop Degradation"
                  caused_by:
                    - { concept: equipment_failure, plain_english: "..." }
                  causes:
                    - { concept: subscriber_experience_degradation, ... }
        """
        log.info("Layer 4: Causal reasoning...")
        
        # ─── Detect format and get concepts ───
        business_section = self.ontology.get("business", {})
        
        # Try new format first (business.concepts), fall back to old (concepts at root)
        concepts = business_section.get("concepts", []) or self.ontology.get("concepts", [])
        
        if not concepts:
            log.warning("  No concepts found in ontology")
            return
        
        # Detect format by checking first concept's structure
        is_new_format = concepts and "id" in concepts[0] and ("caused_by" in concepts[0] or "causes" in concepts[0])
        
        if is_new_format:
            log.info(f"  Detected NEW format (business.concepts with caused_by/causes)")
        else:
            log.info(f"  Detected OLD format (concepts with maps_to_tables)")
        
        # ─── Create concepts ───
        for concept in concepts:
            if is_new_format:
                # NEW FORMAT: id, display_name, synonyms, kpis, entities, caused_by, causes
                concept_name = concept.get("id", "")
                description = concept.get("display_name", concept_name)
                synonyms = concept.get("synonyms", [])
                kpis = concept.get("kpis", [])
                table_fqns = []
                
                # Build calculation hint from caused_by concepts
                caused_by_list = concept.get("caused_by", [])
                calc_hint = ""
                if caused_by_list:
                    calc_hint = f"Can be caused by: {', '.join(c.get('concept', '') for c in caused_by_list[:3])}"
            else:
                # OLD FORMAT: name, description, maps_to_tables, maps_to_kpis, synonyms
                concept_name = concept.get("name", "")
                description = concept.get("description", "")
                synonyms = concept.get("synonyms", [])
                kpis = concept.get("maps_to_kpis", [])
                table_fqns = [self._resolve_table_fqn(t) for t in concept.get("maps_to_tables", [])]
                table_fqns = [f for f in table_fqns if f]
                calc_hint = concept.get("calculation_hint", "")
            
            if not concept_name:
                continue
                
            if not self.dry_run:
                self.kg.upsert_concept(
                    concept=concept_name,
                    description=description,
                    maps_to_tables=table_fqns,
                    maps_to_kpis=kpis,
                    synonyms=synonyms,
                    calculation_hint=calc_hint,
                )
            self.stats["concepts"] += 1
        
        # ─── Create AFFECTS edges ───
        affects_count = 0
        
        if is_new_format:
            # Extract AFFECTS edges from caused_by/causes within each concept
            for concept in concepts:
                concept_name = concept.get("id", "")
                if not concept_name:
                    continue
                
                # caused_by: source AFFECTS this concept
                for edge in concept.get("caused_by", []):
                    source = edge.get("concept", "")
                    mechanism = edge.get("plain_english", edge.get("mechanism", ""))
                    
                    if source and not self.dry_run:
                        self.kg.upsert_affects(
                            source=source,
                            target=concept_name,
                            mechanism=mechanism,
                        )
                        affects_count += 1
                
                # causes: this concept AFFECTS target
                for edge in concept.get("causes", []):
                    target = edge.get("concept", "")
                    mechanism = edge.get("plain_english", edge.get("mechanism", ""))
                    
                    if target and not self.dry_run:
                        self.kg.upsert_affects(
                            source=concept_name,
                            target=target,
                            mechanism=mechanism,
                        )
                        affects_count += 1
        else:
            # OLD FORMAT: Read from separate affects_edges section
            affects_edges = self.ontology.get("affects_edges", [])
            for edge in affects_edges:
                if not self.dry_run:
                    self.kg.upsert_affects(
                        edge["from"],
                        edge["to"],
                        edge.get("mechanism", ""),
                    )
                affects_count += 1
        
        self.stats["affects_edges"] = affects_count
        
        log.info(f"  Layer 4 complete: {self.stats['concepts']} concepts, "
                f"{affects_count} AFFECTS edges (deduplicated by Neo4j MERGE)")
    
    # ═══════════════════════════════════════════════════════════════════════
    # LAYER 5: PRODUCT TAXONOMY
    # ═══════════════════════════════════════════════════════════════════════
    
    def setup_layer5_taxonomy(self):
        """Populate categories, subcategories, brands."""
        log.info("Layer 5: Product taxonomy...")
        
        taxonomy = self.ontology.get("taxonomy", {})
        
        # Categories
        for category in taxonomy.get("categories", []):
            if not self.dry_run:
                self.kg.upsert_category(category["name"])
                self.stats["categories"] += 1
                
                # Subcategories
                for sub in category.get("subcategories", []):
                    self.kg.upsert_category(sub, parent_category=category["name"])
                    self.stats["categories"] += 1
                
                # Brands for this category
                for brand in category.get("brands", []):
                    self.kg.upsert_brand(
                        brand["name"],
                        category["name"],
                        brand.get("tier", "mid"),
                    )
                    self.stats["brands"] += 1
        
        # Competes-with relationships
        for comp in taxonomy.get("competes_with", []):
            if not self.dry_run:
                self.kg.upsert_competes_with(comp["a"], comp["b"])
        
        log.info(f"  Layer 5 complete: {self.stats['categories']} categories, "
                f"{self.stats['brands']} brands")
    
    # ═══════════════════════════════════════════════════════════════════════
    # LAYERS 6-10: DOMAIN DATA
    # ═══════════════════════════════════════════════════════════════════════
    
    def setup_domain_layers(self):
        """Populate all domain event layers from domain_data.yaml."""
        if not self.domain_data:
            log.info("No domain_data.yaml found, skipping layers 6-10")
            return
        
        # Layer 6: Supply Chain
        self._setup_supply_chain()
        
        # Layer 7: Customer Relationships
        self._setup_customer_relationships()
        
        # Layer 8: Temporal Context
        self._setup_temporal_context()
        
        # Layer 9: Business Rules
        self._setup_business_rules()
        
        # Layer 10: Loyalty Program
        self._setup_loyalty_program()
    
    def _setup_supply_chain(self):
        """Layer 6: Suppliers and supply incidents."""
        log.info("Layer 6: Supply chain...")
        
        for supplier in self.domain_data.get("suppliers", []):
            if not self.dry_run:
                self.kg.upsert_supplier(
                    supplier["name"],
                    supplier.get("location", ""),
                    supplier.get("lead_time_weeks", 4),
                    supplier.get("supplies_brands", []),
                )
            self.stats["suppliers"] += 1
        
        for incident in self.domain_data.get("supply_incidents", []):
            if not self.dry_run:
                self.kg.upsert_supply_incident(
                    incident["supplier"],
                    incident["incident_type"],
                    incident["date"],
                    incident.get("description", ""),
                    incident.get("duration_weeks", 0),
                )
            self.stats["supply_incidents"] += 1
        
        for alt in self.domain_data.get("alternate_suppliers", []):
            if not self.dry_run:
                self.kg.upsert_alternate_supplier(alt["primary"], alt["alternate"])
        
        log.info(f"  Layer 6 complete: {self.stats['suppliers']} suppliers, "
                f"{self.stats['supply_incidents']} incidents")
    
    def _setup_customer_relationships(self):
        """Layer 7: Account managers, contracts, churn risks."""
        log.info("Layer 7: Customer relationships...")
        
        for am in self.domain_data.get("account_managers", []):
            if not self.dry_run:
                self.kg.upsert_account_manager(
                    am["name"],
                    am.get("segment", ""),
                    am.get("left_date"),
                    am.get("accounts", 0),
                )
            self.stats["account_managers"] += 1
        
        for contract in self.domain_data.get("contracts", []):
            if not self.dry_run:
                self.kg.upsert_contract(
                    contract["segment"],
                    contract.get("type", "standard"),
                    contract.get("tier", ""),
                    contract.get("expiry", ""),
                )
            self.stats["contracts"] += 1
        
        for risk in self.domain_data.get("churn_risks", []):
            if not self.dry_run:
                self.kg.upsert_churn_risk(
                    risk["segment"],
                    risk["risk_score"],
                    risk.get("reason", ""),
                )
            self.stats["churn_risks"] += 1
        
        log.info(f"  Layer 7 complete: {self.stats['account_managers']} managers, "
                f"{self.stats['contracts']} contracts, {self.stats['churn_risks']} risks")
    
    def _setup_temporal_context(self):
        """Layer 8: Competitor actions, market conditions, policy changes."""
        log.info("Layer 8: Temporal context...")
        
        for action in self.domain_data.get("competitor_actions", []):
            if not self.dry_run:
                self.kg.upsert_competitor_action(
                    action["competitor"],
                    action["action_type"],
                    action["date"],
                    action.get("description", ""),
                    action.get("impact", ""),
                    action.get("region"),
                )
            self.stats["competitor_actions"] += 1
        
        for condition in self.domain_data.get("market_conditions", []):
            if not self.dry_run:
                self.kg.upsert_market_condition(
                    condition["name"],
                    condition.get("description", ""),
                    condition["date"],
                    condition.get("severity", "moderate"),
                )
            self.stats["market_conditions"] += 1
        
        for policy in self.domain_data.get("policy_changes", []):
            if not self.dry_run:
                self.kg.upsert_policy_change(
                    policy["name"],
                    policy.get("description", ""),
                    policy["date"],
                    policy.get("location"),
                    policy.get("impact", ""),
                )
            self.stats["policy_changes"] += 1
        
        log.info(f"  Layer 8 complete: {self.stats['competitor_actions']} competitor actions, "
                f"{self.stats['market_conditions']} conditions, {self.stats['policy_changes']} policies")
    
    def _setup_business_rules(self):
        """Layer 9: Discount policies, pricing decisions, segment rules."""
        log.info("Layer 9: Business rules...")
        
        for policy in self.domain_data.get("discount_policies", []):
            if not self.dry_run:
                self.kg.upsert_discount_policy(
                    policy["category"],
                    policy.get("max_pct", 25),
                    policy.get("store_type"),
                    policy.get("approved_by", ""),
                )
            self.stats["discount_policies"] += 1
        
        for decision in self.domain_data.get("pricing_decisions", []):
            if not self.dry_run:
                self.kg.upsert_pricing_decision(
                    decision["category"],
                    decision["action"],
                    decision.get("reason", ""),
                    decision["date"],
                    decision.get("scope", "all"),
                )
            self.stats["pricing_decisions"] += 1
        
        for rule in self.domain_data.get("segment_rules", []):
            if not self.dry_run:
                self.kg.upsert_segment_rule(
                    rule["segment"],
                    rule["metric"],
                    rule["condition"],
                    rule.get("description", ""),
                )
        
        log.info(f"  Layer 9 complete: {self.stats['discount_policies']} discount policies, "
                f"{self.stats['pricing_decisions']} pricing decisions")
    
    def _setup_loyalty_program(self):
        """Layer 10: Loyalty tiers, redemption rules, campaigns."""
        log.info("Layer 10: Loyalty program...")
        
        for tier in self.domain_data.get("loyalty_tiers", []):
            if not self.dry_run:
                self.kg.upsert_loyalty_tier(
                    tier["name"],
                    tier.get("min_annual_spend", 0),
                    tier.get("points_multiplier", 1.0),
                )
            self.stats["loyalty_tiers"] += 1
        
        for rule in self.domain_data.get("redemption_rules", []):
            if not self.dry_run:
                self.kg.upsert_redemption_rule(
                    rule["name"],
                    rule["rule_type"],
                    rule.get("old_value", ""),
                    rule.get("new_value", ""),
                    rule["effective_date"],
                    rule.get("description", ""),
                )
            self.stats["redemption_rules"] += 1
        
        for campaign in self.domain_data.get("loyalty_campaigns", []):
            if not self.dry_run:
                self.kg.upsert_loyalty_campaign(
                    campaign["name"],
                    campaign["campaign_type"],
                    campaign["start_date"],
                    campaign["end_date"],
                    campaign.get("target_tiers", []),
                    campaign.get("points_multiplier"),
                    campaign.get("description", ""),
                )
            self.stats["campaigns"] += 1
        
        log.info(f"  Layer 10 complete: {self.stats['loyalty_tiers']} tiers, "
                f"{self.stats['redemption_rules']} rules, {self.stats['campaigns']} campaigns")
    
    # ═══════════════════════════════════════════════════════════════════════
    # EXAMPLES + VECTOR SEARCH INDEXING
    # ═══════════════════════════════════════════════════════════════════════
    
    def setup_examples(self):
        """Populate few-shot SQL examples.
        
        Supports two formats:
        
        OLD FORMAT:
            examples:
              - question: "..."
                sql: "..."
                tables: [table1, table2]
        
        NEW FORMAT:
            examples:
              sql:
                - id: example_1
                  category: LOOKUP
                  question: "..."
                  sql: "..."
              cypher:
                - id: cypher_1
                  question: "..."
                  cypher: "..."
        """
        log.info("Setting up examples...")
        
        examples_section = self.ontology.get("examples", [])
        
        # Detect format
        if isinstance(examples_section, dict):
            # NEW FORMAT: examples.sql and examples.cypher
            sql_examples = examples_section.get("sql", [])
            cypher_examples = examples_section.get("cypher", [])
            
            for ex in sql_examples:
                if not self.dry_run:
                    self.kg.upsert_example(
                        ex.get("question", ""),
                        ex.get("sql", ""),
                        [],  # No tables field in new format
                        ex.get("category", ""),
                    )
                self.stats["examples"] += 1
            
            # Handle cypher examples if the method exists
            for ex in cypher_examples:
                if not self.dry_run and hasattr(self.kg, 'upsert_cypher_example'):
                    self.kg.upsert_cypher_example(
                        ex.get("question", ""),
                        ex.get("cypher", ""),
                        ex.get("category", ""),
                    )
                self.stats["examples"] += 1
        else:
            # OLD FORMAT: list of examples at root
            for ex in examples_section:
                if isinstance(ex, dict):
                    table_fqns = [self._resolve_table_fqn(t) for t in ex.get("tables", [])]
                    table_fqns = [f for f in table_fqns if f]
                    
                    if not self.dry_run:
                        self.kg.upsert_example(
                            ex["question"],
                            ex["sql"],
                            table_fqns,
                            ex.get("category", ""),
                        )
                    self.stats["examples"] += 1
        
        log.info(f"  {self.stats['examples']} examples created")
    
    def setup_vector_indexes(self):
        """Create vector search indexes."""
        if self.dry_run:
            log.info("Vector indexing: [DRY RUN] skipped")
            return
        
        log.info("Creating vector search indexes...")
        
        try:
            self.vs.create_indexes()
            log.info("  Vector indexes created/verified")
        except Exception as e:
            log.warning(f"  Vector index creation skipped: {e}")
    
    # ═══════════════════════════════════════════════════════════════════════
    # MAIN SETUP
    # ═══════════════════════════════════════════════════════════════════════
    
    def run(self):
        """Execute full semantic layer setup."""
        log.info("=" * 60)
        log.info("SEMANTIC LAYER SETUP (Configuration-Driven)")
        log.info("=" * 60)
        
        self.load_configs()
        
        self.setup_layer1_schema()
        self.setup_layer2_org_hierarchy()
        self.setup_layer2b_location_entities()
        self.setup_layer3_kpis()
        self.setup_layer4_causal()
        self.setup_layer5_taxonomy()
        self.setup_domain_layers()
        self.setup_examples()
        self.setup_vector_indexes()
        
        log.info("=" * 60)
        log.info("SETUP COMPLETE")
        log.info("=" * 60)
        
        return self.stats


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Configuration-driven semantic layer setup for Neo4j"
    )
    parser.add_argument(
        "--config-dir", "-c",
        default="configs/retail",
        help="Directory containing ontology.yaml and other config files"
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Validate configs without writing to Neo4j"
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear all Neo4j data before setup"
    )
    args = parser.parse_args()
    
    setup = ConfigurableSemanticLayerSetup(args.config_dir, args.dry_run)
    
    # Clear Neo4j if requested
    if args.clear and not args.dry_run:
        log.info("Clearing all Neo4j data...")
        with setup.kg.driver.session() as s:
            s.run("MATCH (n) DETACH DELETE n")
        log.info("  Neo4j cleared.")
    
    stats = setup.run()
    
    print("\n" + "=" * 40)
    print("STATISTICS")
    print("=" * 40)
    for key, value in stats.items():
        if value > 0:
            print(f"  {key}: {value}")


if __name__ == "__main__":
    main()