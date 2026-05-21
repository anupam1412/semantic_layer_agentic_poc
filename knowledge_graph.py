"""
Neo4j Knowledge Graph — 10 Domain Layers + Location Entities
=============================================================
Changes from previous version:
  - upsert_redemption_rule: CREATE → MERGE (idempotent)
  - upsert_account_manager: fixed conditional SET for left_date
  - get_domain_context_for_question: deduplicated promotion_targeting
  - all_tables / all_concepts / get_all_kpis: added error handling
  - Added dotenv loading for environment variables
  - get_causal_chain: auto-resolves KPI names to concept names
  - NEW: LocationEntity nodes + get_location_hints() for entity resolution
"""

import os, json, logging
from pathlib import Path
from neo4j import GraphDatabase

# Load environment variables from .env or _env
try:
    from dotenv import load_dotenv
    # Try _env first (project convention), then .env
    env_file = Path("_env") if Path("_env").exists() else Path(".env")
    if env_file.exists():
        load_dotenv(env_file)
except ImportError:
    pass  # dotenv not installed, rely on system env vars

log = logging.getLogger("agentic_sl.kg")


class KnowledgeGraph:
    def __init__(self, uri=None, user=None, password=None):
        self.driver = GraphDatabase.driver(
            uri or os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            auth=(
                user or os.getenv("NEO4J_USER", "neo4j"),
                password or os.getenv("NEO4J_PASSWORD", "password"),
            ),
        )
        self._init_constraints()

    def _init_constraints(self):
        constraints = [
            "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Table) REQUIRE n.fqn IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Column) REQUIRE n.fqn IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (n:KPI) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (n:BusinessConcept) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (n:QueryExample) REQUIRE n.question IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Region) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Store) REQUIRE n.store_id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Category) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Supplier) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (n:LoyaltyTier) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Dimension) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (n:LocationEntity) REQUIRE n.name IS UNIQUE",  # NEW
        ]
        with self.driver.session() as s:
            for c in constraints:
                try:
                    s.run(c)
                except Exception:
                    pass
        log.info("Neo4j constraints initialized.")

    def close(self):
        self.driver.close()

    # ═══ Layer 1: Schema ═══

    def upsert_table(self, fqn, name, desc, dataset, columns):
        with self.driver.session() as s:
            s.run(
                "MERGE (t:Table {fqn:$f}) SET t.name=$n, t.description=$d, t.dataset=$ds",
                f=fqn, n=name, d=desc, ds=dataset,
            )
            s.run("MATCH (t:Table {fqn:$f})-[:HAS_COLUMN]->(c) DETACH DELETE c", f=fqn)
            for col in columns:
                s.run(
                    "MATCH (t:Table {fqn:$f}) "
                    "CREATE (c:Column {fqn:$cf, name:$n, data_type:$dt, "
                    "description:$d, is_pk:$pk}) "
                    "CREATE (t)-[:HAS_COLUMN]->(c)",
                    f=fqn,
                    cf=f"{fqn}.{col['name']}",
                    n=col["name"],
                    dt=col.get("type", "STRING"),
                    d=col.get("description", ""),
                    pk=col.get("is_pk", False),
                )

    def upsert_relationship(self, t1, t2, rtype, jcond):
        with self.driver.session() as s:
            s.run(
                "MATCH (a:Table {fqn:$a}),(b:Table {fqn:$b}) "
                "MERGE (a)-[r:RELATES_TO]->(b) SET r.type=$t, r.join_condition=$j",
                a=t1, b=t2, t=rtype, j=jcond,
            )

    def upsert_fk(self, from_col, to_col):
        with self.driver.session() as s:
            s.run(
                "MATCH (c1:Column {fqn:$f}),(c2:Column {fqn:$t}) "
                "MERGE (c1)-[:FOREIGN_KEY]->(c2)",
                f=from_col, t=to_col,
            )

    # ═══ Layer 2: Org Hierarchy ═══

    def upsert_region(self, name, country="GB", head="", store_count=0):
        with self.driver.session() as s:
            s.run(
                "MERGE (r:Region {name:$n}) SET r.country=$c, r.head=$h, r.store_count=$sc",
                n=name, c=country, h=head, sc=store_count,
            )

    def upsert_store_node(
        self, store_id, name, region, store_type, capacity, opened,
        manager_name="", manager_since="", manager_experience=0,
    ):
        with self.driver.session() as s:
            s.run(
                "MERGE (st:Store {store_id:$sid}) "
                "SET st.name=$n, st.type=$t, st.capacity_sqft=$c, st.opened=$o",
                sid=store_id, n=name, t=store_type, c=capacity, o=opened,
            )
            s.run(
                "MATCH (r:Region {name:$r}),(st:Store {store_id:$sid}) "
                "MERGE (r)-[:CONTAINS]->(st)",
                r=region, sid=store_id,
            )
            if manager_name:
                s.run(
                    "MERGE (m:Manager {name:$mn}) "
                    "SET m.since=$ms, m.experience_years=$me "
                    "WITH m MATCH (st:Store {store_id:$sid}) "
                    "MERGE (st)-[:MANAGED_BY]->(m)",
                    mn=manager_name, ms=manager_since, me=manager_experience,
                    sid=store_id,
                )

    def upsert_territory(self, name, region, annual_target=0):
        with self.driver.session() as s:
            s.run(
                "MERGE (t:Territory {name:$n}) SET t.annual_target=$at",
                n=name, at=annual_target,
            )
            s.run(
                "MATCH (r:Region {name:$r}),(t:Territory {name:$n}) "
                "MERGE (r)-[:HAS_TERRITORY]->(t)",
                r=region, n=name,
            )

    # ═══ Layer 2b: Location Entities (NEW) ═══

    def upsert_location_entity(self, name, loc_type, table, column):
        """Create a LocationEntity node for entity resolution in queries.
        
        Args:
            name: Location name (e.g., "Canary Wharf")
            loc_type: Entity type (e.g., "cluster", "region")
            table: BigQuery table name (e.g., "network_clusters")
            column: Column to filter on (e.g., "cluster_name")
        """
        with self.driver.session() as s:
            s.run(
                "MERGE (l:LocationEntity {name: $name}) "
                "SET l.type = $type, l.table = $table, l.column = $column, "
                "    l.name_lower = toLower($name)",
                name=name, type=loc_type, table=table, column=column,
            )

    def get_location_hints(self, question: str) -> list:
        """Find location entities mentioned in the question.
        
        Returns list of hints for SQL generation, e.g.:
          ["'Canary Wharf' is a cluster — filter using: network_clusters.cluster_name = 'Canary Wharf'"]
        """
        q_lower = question.lower()
        
        with self.driver.session() as s:
            # Find all location entities where name appears in the question
            result = s.run(
                """
                MATCH (l:LocationEntity)
                WHERE $question CONTAINS l.name_lower
                RETURN l.name AS name, l.type AS type, l.table AS table, l.column AS column
                """,
                question=q_lower
            )
            
            hints = []
            for record in result:
                name = record["name"]
                loc_type = record["type"]
                table = record["table"]
                column = record["column"]
                hints.append(
                    f"'{name}' is a {loc_type} — filter using: {table}.{column} = '{name}'"
                )
            
            return hints

    # ═══ Layer 3: KPI Definitions ═══

    def upsert_kpi(
        self, name, expression, table_fqns, description="", grain="monthly",
        thresholds=None, dimensions=None,
    ):
        with self.driver.session() as s:
            s.run(
                "MERGE (k:KPI {name:$n}) "
                "SET k.expression=$e, k.description=$d, k.grain=$g",
                n=name, e=expression, d=description, g=grain,
            )
            s.run("MATCH (k:KPI {name:$n})-[r:COMPUTED_FROM]->() DELETE r", n=name)
            for fqn in table_fqns:
                s.run(
                    "MATCH (k:KPI {name:$n}),(t:Table {fqn:$f}) "
                    "MERGE (k)-[:COMPUTED_FROM]->(t)",
                    n=name, f=fqn,
                )
            if thresholds:
                s.run(
                    "MATCH (k:KPI {name:$n})-[:HAS_THRESHOLD]->(th) DETACH DELETE th",
                    n=name,
                )
                for level, condition in thresholds.items():
                    s.run(
                        "MATCH (k:KPI {name:$n}) "
                        "CREATE (th:Threshold {level:$l, condition:$c}) "
                        "CREATE (k)-[:HAS_THRESHOLD]->(th)",
                        n=name, l=level, c=condition,
                    )
            if dimensions:
                s.run("MATCH (k:KPI {name:$n})-[r:SLICED_BY]->() DELETE r", n=name)
                for dim in dimensions:
                    s.run("MERGE (d:Dimension {name:$d})", d=dim)
                    s.run(
                        "MATCH (k:KPI {name:$n}),(d:Dimension {name:$d}) "
                        "MERGE (k)-[:SLICED_BY]->(d)",
                        n=name, d=dim,
                    )

    def upsert_kpi_driver(self, parent_kpi, child_kpi):
        with self.driver.session() as s:
            s.run(
                "MATCH (p:KPI {name:$p}),(c:KPI {name:$c}) "
                "MERGE (p)-[:DRIVEN_BY]->(c)",
                p=parent_kpi, c=child_kpi,
            )

    def get_kpi(self, name):
        with self.driver.session() as s:
            r = s.run(
                "MATCH (k:KPI {name:$n}) "
                "OPTIONAL MATCH (k)-[:COMPUTED_FROM]->(t:Table) "
                "OPTIONAL MATCH (k)-[:HAS_THRESHOLD]->(th:Threshold) "
                "OPTIONAL MATCH (k)-[:SLICED_BY]->(d:Dimension) "
                "RETURN k, collect(DISTINCT t.fqn) AS tables, "
                "  collect(DISTINCT {level:th.level, condition:th.condition}) AS thresholds, "
                "  collect(DISTINCT d.name) AS dimensions",
                n=name,
            ).single()
            if not r:
                return None
            k = r["k"]
            return {
                "name": k["name"],
                "expression": k.get("expression", ""),
                "description": k.get("description", ""),
                "grain": k.get("grain", ""),
                "tables": [t for t in r["tables"] if t],
                "thresholds": {
                    t["level"]: t["condition"]
                    for t in r["thresholds"]
                    if t.get("level")
                },
                "dimensions": [d for d in r["dimensions"] if d],
            }

    def get_kpi_driver_tree(self, kpi_name, depth=3):
        tree = {"kpi": kpi_name, "drivers": []}
        with self.driver.session() as s:
            for d in range(1, min(depth, 5) + 1):
                for r in s.run(
                    f"MATCH (p:KPI {{name:$n}})-[:DRIVEN_BY*{d}]->(c:KPI) "
                    f"RETURN DISTINCT c.name AS name, c.description AS desc, "
                    f"{d} AS depth",
                    n=kpi_name,
                ):
                    if not any(x["name"] == r["name"] for x in tree["drivers"]):
                        tree["drivers"].append({
                            "name": r["name"],
                            "description": r["desc"] or "",
                            "depth": r["depth"],
                        })
        return tree

    # ═══ Layer 4: Causal Reasoning ═══

    def upsert_concept(
        self, concept, description, maps_to_tables, maps_to_kpis=None,
        synonyms=None, calculation_hint="",
    ):
        with self.driver.session() as s:
            s.run(
                "MERGE (b:BusinessConcept {name:$n}) "
                "SET b.description=$d, b.synonyms=$s, b.calculation_hint=$ch",
                n=concept, d=description, s=synonyms or [], ch=calculation_hint,
            )
            s.run(
                "MATCH (b:BusinessConcept {name:$n})-[r:MAPS_TO]->() DELETE r",
                n=concept,
            )
            for fqn in maps_to_tables:
                s.run(
                    "MATCH (b:BusinessConcept {name:$n}),(t:Table {fqn:$f}) "
                    "MERGE (b)-[:MAPS_TO]->(t)",
                    n=concept, f=fqn,
                )
            s.run(
                "MATCH (b:BusinessConcept {name:$n})-[r:MEASURES]->() DELETE r",
                n=concept,
            )
            for kpi_name in (maps_to_kpis or []):
                s.run(
                    "MATCH (b:BusinessConcept {name:$n}),(k:KPI {name:$k}) "
                    "MERGE (b)-[:MEASURES]->(k)",
                    n=concept, k=kpi_name,
                )

    def upsert_affects(self, source, target, mechanism=""):
        with self.driver.session() as s:
            s.run(
                "MATCH (a:BusinessConcept {name:$s}),(b:BusinessConcept {name:$t}) "
                "MERGE (a)-[r:AFFECTS]->(b) SET r.mechanism=$m",
                s=source, t=target, m=mechanism,
            )

    def get_causal_chain(self, concept_name, depth=3):
        """Get causal chain for a concept.
        
        Accepts any of:
        - A BusinessConcept name (e.g., 'call_drop_degradation')
        - A KPI name (e.g., 'call_drop_rate')
        - A display name (e.g., 'Call Drop Rate') - auto-normalized
        """
        depth = min(max(int(depth), 1), 10)
        
        # Normalize: "Call Drop Rate" → "call_drop_rate"
        normalized = concept_name.lower().replace(" ", "_").replace("-", "_")
        
        # Extract key terms for matching: "call_drop_rate" → ["call", "drop"]
        key_terms = [t for t in normalized.replace("_", " ").split() 
                     if t not in ("rate", "ratio", "percentage", "pct", "count", "total", "avg", "average")]
        
        with self.driver.session() as s:
            resolved_name = None
            
            # 1. Try exact concept name match
            result = s.run(
                "MATCH (c:BusinessConcept {name: $n}) RETURN c.name AS name LIMIT 1",
                n=concept_name
            )
            record = result.single()
            if record:
                resolved_name = record["name"]
            
            # 2. Try normalized concept name
            if not resolved_name:
                result = s.run(
                    "MATCH (c:BusinessConcept {name: $n}) RETURN c.name AS name LIMIT 1",
                    n=normalized
                )
                record = result.single()
                if record:
                    resolved_name = record["name"]
            
            # 3. Try KPI lookup - prefer concept with similar name
            if not resolved_name and key_terms:
                result = s.run(
                    """
                    MATCH (c:BusinessConcept)-[:MEASURES]->(k:KPI)
                    WHERE k.name = $kpi_name OR k.name = $kpi_normalized
                    WITH c, k,
                         REDUCE(score = 0, term IN $terms | 
                           score + CASE WHEN toLower(c.name) CONTAINS term THEN 10 ELSE 0 END +
                           CASE WHEN toLower(c.description) CONTAINS term THEN 5 ELSE 0 END
                         ) AS match_score
                    RETURN c.name AS name, match_score
                    ORDER BY match_score DESC
                    LIMIT 1
                    """,
                    kpi_name=concept_name,
                    kpi_normalized=normalized,
                    terms=key_terms
                )
                record = result.single()
                if record:
                    resolved_name = record["name"]
            
            # 4. Fallback: any concept that MEASURES the KPI
            if not resolved_name:
                result = s.run(
                    "MATCH (c:BusinessConcept)-[:MEASURES]->(k:KPI {name: $n}) "
                    "RETURN c.name AS name LIMIT 1",
                    n=normalized
                )
                record = result.single()
                if record:
                    resolved_name = record["name"]
            
            # 5. Fuzzy match on concept synonyms
            if not resolved_name:
                search_term = concept_name.lower().replace("_", " ")
                result = s.run(
                    "MATCH (c:BusinessConcept) "
                    "WHERE toLower(c.name) CONTAINS $n OR $n CONTAINS toLower(c.name) "
                    "   OR ANY(syn IN c.synonyms WHERE toLower(syn) CONTAINS $n OR $n CONTAINS toLower(syn)) "
                    "RETURN c.name AS name LIMIT 1",
                    n=search_term
                )
                record = result.single()
                if record:
                    resolved_name = record["name"]
            
            # Use resolved name or fall back to original
            target_name = resolved_name or concept_name
            
            # Now get the causal chain
            causes = []
            for d in range(1, depth + 1):
                for r in s.run(
                    f"MATCH (c:BusinessConcept)-[:AFFECTS*{d}]->"
                    f"(t:BusinessConcept {{name:$n}}) "
                    f"RETURN DISTINCT c.name AS concept, c.description AS desc",
                    n=target_name,
                ):
                    if not any(x["concept"] == r["concept"] for x in causes):
                        causes.append({
                            "concept": r["concept"],
                            "description": r["desc"] or "",
                        })
            effects = []
            for d in range(1, depth + 1):
                for r in s.run(
                    f"MATCH (s:BusinessConcept {{name:$n}})-[:AFFECTS*{d}]->"
                    f"(e:BusinessConcept) "
                    f"RETURN DISTINCT e.name AS concept, e.description AS desc",
                    n=target_name,
                ):
                    if not any(x["concept"] == r["concept"] for x in effects):
                        effects.append({
                            "concept": r["concept"],
                            "description": r["desc"] or "",
                        })
            return {"concept": target_name, "caused_by": causes, "affects": effects}

    def get_causal_map(self):
        with self.driver.session() as s:
            return [
                {"source": r["s"], "target": r["t"], "mechanism": r["m"] or ""}
                for r in s.run(
                    "MATCH (a:BusinessConcept)-[r:AFFECTS]->(b:BusinessConcept) "
                    "RETURN a.name AS s, b.name AS t, r.mechanism AS m"
                )
            ]

    # ═══ Layer 5: Product Taxonomy ═══

    def upsert_category(self, name, parent_category=None):
        with self.driver.session() as s:
            s.run("MERGE (c:Category {name:$n})", n=name)
            if parent_category:
                s.run(
                    "MATCH (p:Category {name:$p}),(c:Category {name:$n}) "
                    "MERGE (p)-[:HAS_SUB]->(c)",
                    p=parent_category, n=name,
                )

    def upsert_brand(self, name, category, price_tier="standard"):
        with self.driver.session() as s:
            s.run("MERGE (b:Brand {name:$n}) SET b.price_tier=$pt", n=name, pt=price_tier)
            s.run(
                "MATCH (c:Category {name:$c}),(b:Brand {name:$n}) "
                "MERGE (c)-[:HAS_BRAND]->(b)",
                c=category, n=name,
            )

    def upsert_competes_with(self, sub1, sub2):
        with self.driver.session() as s:
            s.run(
                "MATCH (a:Category {name:$a}),(b:Category {name:$b}) "
                "MERGE (a)-[:COMPETES_WITH]->(b)",
                a=sub1, b=sub2,
            )

    def upsert_promo_targets_category(self, promo_name, category_name):
        with self.driver.session() as s:
            s.run(
                "MERGE (p:Promotion {name:$pn}) "
                "WITH p MATCH (c:Category {name:$cn}) "
                "MERGE (p)-[:TARGETS_CATEGORY]->(c)",
                pn=promo_name, cn=category_name,
            )

    def upsert_promo_targets_product(self, promo_name, product_id):
        with self.driver.session() as s:
            s.run(
                "MERGE (p:Promotion {name:$pn}) "
                "WITH p MATCH (t:Table) WHERE t.fqn ENDS WITH '.products' "
                "MERGE (p)-[:TARGETS_PRODUCT {product_id: $pid}]->(t)",
                pn=promo_name, pid=product_id,
            )

    # ═══ Layer 6: Supply Chain ═══

    def upsert_supplier(self, name, location, lead_time_weeks, supplies_brands=None):
        with self.driver.session() as s:
            s.run(
                "MERGE (sp:Supplier {name:$n}) "
                "SET sp.location=$l, sp.lead_time_weeks=$lt",
                n=name, l=location, lt=lead_time_weeks,
            )
            for brand in (supplies_brands or []):
                s.run(
                    "MATCH (sp:Supplier {name:$n}),(b:Brand {name:$b}) "
                    "MERGE (sp)-[:SUPPLIES]->(b)",
                    n=name, b=brand,
                )

    def upsert_supply_incident(self, supplier_name, incident_type, date, impact,
                                duration_weeks=0):
        with self.driver.session() as s:
            s.run(
                "MATCH (sp:Supplier {name:$n}) "
                "MERGE (i:SupplyIncident {supplier:$n, type:$t, date:$d}) "
                "SET i.impact=$im, i.duration_weeks=$dw "
                "MERGE (sp)-[:HAS_INCIDENT]->(i)",
                n=supplier_name, t=incident_type, d=date, im=impact, dw=duration_weeks,
            )

    def upsert_alternate_supplier(self, primary, alternate):
        with self.driver.session() as s:
            s.run(
                "MATCH (a:Supplier {name:$a}),(b:Supplier {name:$b}) "
                "MERGE (a)-[:ALTERNATE_SUPPLIER]->(b)",
                a=primary, b=alternate,
            )

    # ═══ Layer 7: Customer Relationships ═══

    def upsert_account_manager(self, name, segment, left_date=None, accounts=0):
        with self.driver.session() as s:
            set_clause = "SET am.segment=$seg, am.accounts=$acc"
            params = {"n": name, "seg": segment, "acc": accounts}
            if left_date:
                set_clause += ", am.left_date=$ld"
                params["ld"] = left_date
            s.run(f"MERGE (am:AccountManager {{name:$n}}) {set_clause}", **params)

    def upsert_contract(self, customer_segment, contract_type, tier, renewal_date):
        with self.driver.session() as s:
            s.run(
                "MERGE (c:Contract {segment:$seg, type:$t, tier:$ti}) "
                "SET c.renewal_date=$rd",
                seg=customer_segment, t=contract_type, ti=tier, rd=renewal_date,
            )

    def upsert_churn_risk(self, segment, score, reason):
        with self.driver.session() as s:
            s.run(
                "MERGE (cr:ChurnRisk {segment:$seg, reason:$r}) SET cr.score=$sc",
                seg=segment, sc=score, r=reason,
            )

    # ═══ Layer 8: Temporal Context ═══

    def upsert_competitor_action(self, competitor, action_type, date, location,
                                  impact="", region=None):
        with self.driver.session() as s:
            s.run(
                "MERGE (ca:CompetitorAction "
                "{competitor:$c, type:$t, date:$d, location:$l}) "
                "SET ca.impact=$im",
                c=competitor, t=action_type, d=date, l=location, im=impact,
            )
            if region:
                s.run(
                    "MATCH (ca:CompetitorAction "
                    "{competitor:$c, type:$t, date:$d, location:$l}),"
                    "(r:Region {name:$r}) MERGE (ca)-[:AFFECTS_REGION]->(r)",
                    c=competitor, t=action_type, d=date, l=location, r=region,
                )

    def upsert_market_condition(self, condition_type, trend, start_date,
                                 severity="moderate"):
        with self.driver.session() as s:
            s.run(
                "MERGE (mc:MarketCondition {type:$t, start_date:$sd}) "
                "SET mc.trend=$tr, mc.severity=$sv",
                t=condition_type, tr=trend, sd=start_date, sv=severity,
            )

    def upsert_policy_change(self, policy_type, description, effective_date,
                              location="", impact=""):
        with self.driver.session() as s:
            s.run(
                "MERGE (pc:PolicyChange {type:$t, effective_date:$ed}) "
                "SET pc.description=$d, pc.location=$l, pc.impact=$im",
                t=policy_type, d=description, ed=effective_date, l=location,
                im=impact,
            )

    # ═══ Layer 9: Business Rules ═══

    def upsert_discount_policy(self, category, max_pct, store_type=None,
                                approved_by=""):
        with self.driver.session() as s:
            s.run(
                "MERGE (dp:DiscountPolicy {category:$c}) "
                "SET dp.max_pct=$mp, dp.store_type=$st, dp.approved_by=$ab",
                c=category, mp=max_pct, st=store_type, ab=approved_by,
            )
            s.run(
                "MATCH (dp:DiscountPolicy {category:$c}),(cat:Category {name:$c}) "
                "MERGE (dp)-[:APPLIES_TO]->(cat)",
                c=category,
            )

    def upsert_pricing_decision(self, subcategory, action, reason, date, scope="all"):
        with self.driver.session() as s:
            s.run(
                "MERGE (pd:PricingDecision {subcategory:$sc, date:$d}) "
                "SET pd.action=$a, pd.reason=$r, pd.scope=$sp",
                sc=subcategory, a=action, r=reason, d=date, sp=scope,
            )

    def upsert_segment_rule(self, segment, field, condition, description=""):
        with self.driver.session() as s:
            s.run(
                "MERGE (sr:SegmentRule {segment:$seg, field:$f}) "
                "SET sr.condition=$c, sr.description=$d",
                seg=segment, f=field, c=condition, d=description,
            )

    # ═══ Layer 10: Loyalty ═══

    def upsert_loyalty_tier(self, name, min_spend, points_multiplier=1.0):
        with self.driver.session() as s:
            s.run(
                "MERGE (lt:LoyaltyTier {name:$n}) "
                "SET lt.min_spend=$ms, lt.points_multiplier=$pm",
                n=name, ms=min_spend, pm=points_multiplier,
            )

    def upsert_redemption_rule(self, tier, points_per_gbp, effective_date,
                                previous_ratio=None):
        with self.driver.session() as s:
            s.run(
                "MATCH (lt:LoyaltyTier {name:$t}) "
                "MERGE (rr:RedemptionRule {tier:$t, effective_date:$ed}) "
                "SET rr.points_per_gbp=$ppg, rr.previous_ratio=$pr "
                "WITH lt, rr "
                "MERGE (lt)-[:QUALIFIES_FOR]->(rr)",
                t=tier, ppg=points_per_gbp, ed=effective_date, pr=previous_ratio,
            )

    def upsert_loyalty_partner(self, partner_name, integration_date,
                                partner_type="cross_redemption"):
        with self.driver.session() as s:
            s.run(
                "MERGE (p:Partner {name:$n}) "
                "SET p.integration_date=$id, p.type=$t",
                n=partner_name, id=integration_date, t=partner_type,
            )

    def upsert_loyalty_campaign(self, name, target_tier, campaign_type, sent_date,
                                 description=""):
        with self.driver.session() as s:
            s.run(
                "MERGE (c:LoyaltyCampaign {name:$n}) "
                "SET c.type=$t, c.sent_date=$sd, c.description=$d",
                n=name, t=campaign_type, sd=sent_date, d=description,
            )
            s.run(
                "MATCH (c:LoyaltyCampaign {name:$n}),(lt:LoyaltyTier {name:$t}) "
                "MERGE (c)-[:TARGETED]->(lt)",
                n=name, t=target_tier,
            )

    # ═══ TRIGGERS edges (domain events → concepts) ═══

    def upsert_triggers(self, domain_label, domain_key, domain_value,
                        concept_name, evidence=""):
        with self.driver.session() as s:
            s.run(
                f"MATCH (d:{domain_label} {{{domain_key}:$dv}}),"
                f"(c:BusinessConcept {{name:$cn}}) "
                f"MERGE (d)-[r:TRIGGERS]->(c) SET r.evidence=$ev",
                dv=domain_value, cn=concept_name, ev=evidence,
            )

    def get_triggering_events(self, concept_name):
        events = []
        with self.driver.session() as s:
            for r in s.run(
                "MATCH (d)-[t:TRIGGERS]->(c:BusinessConcept {name:$cn}) "
                "RETURN labels(d) AS labels, properties(d) AS props, "
                "t.evidence AS evidence",
                cn=concept_name,
            ):
                events.append({
                    "node_type": r["labels"][0] if r["labels"] else "Unknown",
                    "details": dict(r["props"]),
                    "evidence": r["evidence"] or "",
                })
        return {"concept": concept_name, "triggering_events": events}

    def get_full_causal_path(self, target_concept, depth=3):
        chain = self.get_causal_chain(target_concept, depth)
        result = {"target": target_concept, "caused_by": []}
        for cause in chain.get("caused_by", []):
            cname = cause["concept"]
            triggers = self.get_triggering_events(cname)
            result["caused_by"].append({
                "concept": cname,
                "description": cause.get("description", ""),
                "triggering_events": triggers.get("triggering_events", []),
            })
        return result

    # ═══ Query Example Layer ═══

    def upsert_example(self, question, sql, tables, complexity="simple"):
        with self.driver.session() as s:
            s.run(
                "MERGE (e:QueryExample {question:$q}) "
                "SET e.sql=$s, e.tables_used=$t, e.complexity=$c",
                q=question, s=sql, t=tables, c=complexity,
            )
            for fqn in tables:
                s.run(
                    "MATCH (e:QueryExample {question:$q}),(t:Table {fqn:$f}) "
                    "MERGE (e)-[:USES_TABLE]->(t)",
                    q=question, f=fqn,
                )

    # ═══ Context Retrieval ═══

    def get_table_context(self, fqns):
        ctx = {}
        with self.driver.session() as s:
            for r in s.run(
                "UNWIND $fqns AS fqn MATCH (t:Table {fqn:fqn}) "
                "OPTIONAL MATCH (t)-[:HAS_COLUMN]->(c:Column) "
                "OPTIONAL MATCH (c)-[:FOREIGN_KEY]->(fk:Column) "
                "OPTIONAL MATCH (k:KPI)-[:COMPUTED_FROM]->(t) "
                "RETURN t.fqn AS fqn, t.name AS name, t.description AS desc, "
                "  collect(DISTINCT {name:c.name, type:c.data_type, "
                "    desc:c.description, fk_to:fk.fqn}) AS cols, "
                "  collect(DISTINCT k.name) AS kpis",
                fqns=fqns,
            ):
                ctx[r["fqn"]] = {
                    "name": r["name"],
                    "description": r["desc"],
                    "columns": [c for c in r["cols"] if c["name"]],
                    "kpis": [k for k in r["kpis"] if k],
                }
        return ctx

    def get_joins(self, fqns):
        paths = []
        with self.driver.session() as s:
            for i, t1 in enumerate(fqns):
                for t2 in fqns[i + 1:]:
                    for r in s.run(
                        "MATCH path=shortestPath("
                        "(a:Table {fqn:$t1})-[:RELATES_TO*..5]-(b:Table {fqn:$t2})) "
                        "UNWIND relationships(path) AS rel "
                        "RETURN startNode(rel).fqn AS f, endNode(rel).fqn AS t, "
                        "rel.join_condition AS jc",
                        t1=t1, t2=t2,
                    ):
                        paths.append({
                            "table1": r["f"],
                            "table2": r["t"],
                            "join_condition": r["jc"],
                        })
        return paths

    def get_domain_context_for_question(self, question):
        q_lower = question.lower()
        context = {
            "events": [], "business_rules": [], "org_context": [],
            "customer_relationships": [], "supply_chain": [], "loyalty": [],
            "pricing": [], "product_taxonomy": [], "promotion_targeting": [],
            "segment_rules": [],
        }
        with self.driver.session() as s:
            for r in s.run("MATCH (ca:CompetitorAction) RETURN ca"):
                n = r["ca"]
                context["events"].append({
                    "type": "competitor_action", "competitor": n.get("competitor", ""),
                    "action": n.get("type", ""), "date": n.get("date", ""),
                    "impact": n.get("impact", ""),
                })
            for r in s.run("MATCH (mc:MarketCondition) RETURN mc"):
                n = r["mc"]
                context["events"].append({
                    "type": "market_condition", "condition": n.get("type", ""),
                    "trend": n.get("trend", ""), "severity": n.get("severity", ""),
                })
            for r in s.run("MATCH (pc:PolicyChange) RETURN pc"):
                n = r["pc"]
                context["events"].append({
                    "type": "policy_change", "policy": n.get("type", ""),
                    "description": n.get("description", ""),
                    "effective_date": n.get("effective_date", ""),
                    "impact": n.get("impact", ""),
                })
            for r in s.run("MATCH (dp:DiscountPolicy) RETURN dp"):
                n = r["dp"]
                context["business_rules"].append({
                    "type": "discount_policy", "category": n.get("category", ""),
                    "max_pct": n.get("max_pct", 0), "store_type": n.get("store_type", ""),
                })
            for r in s.run("MATCH (pd:PricingDecision) RETURN pd"):
                n = r["pd"]
                context["pricing"].append({
                    "subcategory": n.get("subcategory", ""), "action": n.get("action", ""),
                    "reason": n.get("reason", ""), "date": n.get("date", ""),
                })
        return {k: v for k, v in context.items() if v}

    def get_full_ontology_text(self):
        ont = {"tables": {}, "kpis": [], "concepts": [], "causal_edges": []}
        with self.driver.session() as s:
            try:
                for r in s.run(
                    "MATCH (t:Table) OPTIONAL MATCH (t)-[:HAS_COLUMN]->(c:Column) "
                    "RETURN t.fqn AS fqn, t.name AS name, t.description AS desc, "
                    "collect({name:c.name, type:c.data_type, desc:c.description}) AS cols"
                ):
                    ont["tables"][r["fqn"]] = {
                        "name": r["name"], "description": r["desc"],
                        "columns": [c for c in r["cols"] if c["name"]],
                    }
            except Exception as e:
                log.warning(f"Error loading tables: {e}")
            try:
                for r in s.run(
                    "MATCH (k:KPI) RETURN k.name AS name, k.expression AS expr, k.description AS desc"
                ):
                    ont["kpis"].append({
                        "name": r["name"], "expression": r["expr"] or "",
                        "description": r["desc"] or "",
                    })
            except Exception as e:
                log.warning(f"Error loading KPIs: {e}")
            try:
                for r in s.run("MATCH (b:BusinessConcept) RETURN b"):
                    b = r["b"]
                    ont["concepts"].append({
                        "name": b.get("name", ""), "description": b.get("description", ""),
                        "synonyms": list(b.get("synonyms") or []),
                    })
            except Exception as e:
                log.warning(f"Error loading concepts: {e}")
            try:
                for r in s.run(
                    "MATCH (a:BusinessConcept)-[r:AFFECTS]->(b:BusinessConcept) "
                    "RETURN a.name AS src, b.name AS tgt, r.mechanism AS mech"
                ):
                    ont["causal_edges"].append({
                        "source": r["src"], "target": r["tgt"],
                        "mechanism": r["mech"] or "",
                    })
            except Exception as e:
                log.warning(f"Error loading causal edges: {e}")
        return json.dumps(ont, indent=2)

    def all_tables(self):
        try:
            with self.driver.session() as s:
                return [r["fqn"] for r in s.run("MATCH (t:Table) RETURN t.fqn AS fqn")]
        except Exception as e:
            log.warning(f"Error fetching all_tables: {e}")
            return []

    def get_all_kpis(self):
        with self.driver.session() as s:
            names = [r["n"] for r in s.run("MATCH (k:KPI) RETURN k.name AS n")]
        return [self.get_kpi(n) for n in names if self.get_kpi(n)]

    def get_all_concepts(self):
        with self.driver.session() as s:
            concepts = []
            for r in s.run("MATCH (b:BusinessConcept) RETURN b"):
                b = r["b"]
                concepts.append({
                    "name": b.get("name", ""), "description": b.get("description", ""),
                    "synonyms": list(b.get("synonyms") or []),
                    "calculation_hint": b.get("calculation_hint", ""),
                })
            return concepts

    def get_similar_examples(self, question: str, limit: int = 3):
        with self.driver.session() as s:
            examples = []
            keywords = question.lower().split()[:5]
            for r in s.run(
                "MATCH (e:QueryExample) "
                "WHERE ANY(word IN $keywords WHERE toLower(e.question) CONTAINS word) "
                "RETURN e.question AS question, e.sql AS sql, e.category AS category "
                "LIMIT $limit",
                keywords=keywords, limit=limit
            ):
                examples.append({
                    "question": r["question"], "sql": r["sql"], "category": r["category"],
                })
            if not examples:
                for r in s.run(
                    "MATCH (e:QueryExample) RETURN e.question AS question, e.sql AS sql, "
                    "e.category AS category LIMIT $limit",
                    limit=limit
                ):
                    examples.append({
                        "question": r["question"], "sql": r["sql"], "category": r["category"],
                    })
            return examples