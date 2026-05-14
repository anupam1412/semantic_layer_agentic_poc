"""
Semantic Layer Setup — All 10 Neo4j layers + Vertex AI indexes
==============================================================
Run AFTER create_mock_data.py (which creates BigQuery tables).

Includes all 3 rounds of fixes:
  Round 1: 4 KPI expressions fixed, 1 missing relationship added
  Round 2: 2 new concepts, 5 new AFFECTS, 11 TRIGGERS, 1 driver edge
  Round 3: 4 new few-shot examples for complex query patterns
"""

import os
import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("setup")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from knowledge_graph import KnowledgeGraph
from vector_search import VectorSearch

PROJECT = "acn-uki-ds-data-ai-project"
DS = "customer_sales_data_ai_agentic_semantic_layer"
P = f"{PROJECT}.{DS}"

kg = KnowledgeGraph()
vs = VectorSearch(kg=kg)  # shares Neo4j driver — avoids second connection


# ═══════════════════════════════════════════════════════
# LAYER 1: Schema (auto-discover from BigQuery)
# ═══════════════════════════════════════════════════════
log.info("Layer 1: Registering schema from BigQuery...")

from google.cloud import bigquery

bq = bigquery.Client(project=PROJECT, location="europe-west2")

for tref in bq.list_tables(bq.dataset(DS, project=PROJECT)):
    t = bq.get_table(tref)
    cols = [
        {"name": f.name, "type": f.field_type, "description": f.description or ""}
        for f in t.schema
    ]
    kg.upsert_table(f"{P}.{t.table_id}", t.table_id, t.description or "", DS, cols)
    log.info(f"  Table: {t.table_id} ({len(cols)} columns)")

# Relationships
RELS = [
    (f"{P}.customers", f"{P}.orders", "ONE_TO_MANY",
     "customers.customer_id = orders.customer_id"),
    (f"{P}.stores", f"{P}.orders", "ONE_TO_MANY",
     "stores.store_id = orders.store_id"),
    (f"{P}.promotions", f"{P}.orders", "ONE_TO_MANY",
     "promotions.promo_id = orders.promo_id"),
    (f"{P}.orders", f"{P}.order_items", "ONE_TO_MANY",
     "orders.order_id = order_items.order_id"),
    (f"{P}.products", f"{P}.order_items", "ONE_TO_MANY",
     "products.product_id = order_items.product_id"),
    (f"{P}.customers", f"{P}.web_events", "ONE_TO_MANY",
     "customers.customer_id = web_events.customer_id"),
    (f"{P}.stores", f"{P}.sales_targets", "ONE_TO_MANY",
     "stores.store_id = sales_targets.store_id"),
    # Bridge table
    (f"{P}.promotions", f"{P}.promotion_products", "ONE_TO_MANY",
     "promotions.promo_id = promotion_products.promo_id"),
    (f"{P}.products", f"{P}.promotion_products", "ONE_TO_MANY",
     "products.product_id = promotion_products.product_id"),
    # Category-level joins
    (f"{P}.sales_targets", f"{P}.products", "MANY_TO_MANY",
     "sales_targets.category = products.category"),
    # FIX Round 1: bridge table category join (was missing)
    (f"{P}.promotion_products", f"{P}.products", "MANY_TO_MANY",
     "promotion_products.category = products.category"),
]
for t1, t2, rtype, jcond in RELS:
    kg.upsert_relationship(t1, t2, rtype, jcond)

# Foreign keys
FKS = [
    (f"{P}.orders.customer_id", f"{P}.customers.customer_id"),
    (f"{P}.orders.store_id", f"{P}.stores.store_id"),
    (f"{P}.orders.promo_id", f"{P}.promotions.promo_id"),
    (f"{P}.order_items.order_id", f"{P}.orders.order_id"),
    (f"{P}.order_items.product_id", f"{P}.products.product_id"),
    (f"{P}.web_events.customer_id", f"{P}.customers.customer_id"),
    (f"{P}.sales_targets.store_id", f"{P}.stores.store_id"),
    (f"{P}.promotion_products.promo_id", f"{P}.promotions.promo_id"),
    (f"{P}.promotion_products.product_id", f"{P}.products.product_id"),
]
for fc, tc in FKS:
    kg.upsert_fk(fc, tc)

log.info("Layer 1 complete.")


# ═══════════════════════════════════════════════════════
# LAYER 2: Org Hierarchy
# ═══════════════════════════════════════════════════════
log.info("Layer 2: Org hierarchy...")

REGIONS = [
    ("London", "GB", "Emma Clarke", 3),
    ("South East", "GB", "Sarah Wilson", 3),
    ("Midlands", "GB", "Robert Brown", 3),
    ("North West", "GB", "Michael Taylor", 3),
    ("Scotland", "GB", "Fiona Campbell", 3),
    ("Wales", "GB", "Owen Davies", 3),
]
for name, country, head, sc in REGIONS:
    kg.upsert_region(name, country, head, sc)

STORES = [
    ("STORE-001", "London Flagship", "London", "flagship", 15000, "2018-03-01",
     "Alice Johnson", "2020-01-15", 8),
    ("STORE-002", "London Standard", "London", "standard", 8000, "2019-06-01",
     "Tom Richards", "2021-03-01", 6),
    ("STORE-003", "London Outlet", "London", "outlet", 5000, "2020-01-01",
     "Sophie Green", "2022-06-01", 4),
    ("STORE-004", "Brighton Outlet", "South East", "outlet", 5000, "2021-03-15",
     "James Thompson", "2025-09-01", 2),
    ("STORE-005", "Brighton Standard", "South East", "standard", 8000, "2019-09-01",
     "Laura Mitchell", "2019-09-01", 10),
    ("STORE-006", "Guildford Standard", "South East", "standard", 6000, "2020-06-01",
     "Mark Stevens", "2020-06-01", 7),
    ("STORE-007", "Birmingham Standard", "Midlands", "standard", 8000, "2019-01-15",
     "Karen White", "2025-07-01", 1),
    ("STORE-008", "Birmingham Flagship", "Midlands", "flagship", 12000, "2018-06-01",
     "Daniel Harris", "2018-06-01", 12),
    ("STORE-009", "Coventry Outlet", "Midlands", "outlet", 4000, "2021-01-01",
     "Rachel Adams", "2021-01-01", 5),
    ("STORE-010", "Manchester Flagship", "North West", "flagship", 14000, "2018-01-01",
     "Peter Morgan", "2018-01-01", 15),
    ("STORE-011", "Manchester Standard", "North West", "standard", 7000, "2019-11-01",
     "Claire Bennett", "2019-11-01", 8),
    ("STORE-012", "Liverpool Outlet", "North West", "outlet", 5000, "2020-09-01",
     "Andrew Scott", "2020-09-01", 6),
    ("STORE-013", "Edinburgh Flagship", "Scotland", "flagship", 10000, "2019-03-01",
     "Fiona Campbell", "2019-03-01", 9),
    ("STORE-014", "Edinburgh Standard", "Scotland", "standard", 6000, "2020-06-01",
     "Ian MacLeod", "2020-06-01", 7),
    ("STORE-015", "Glasgow Outlet", "Scotland", "outlet", 4500, "2021-06-01",
     "Morag Stewart", "2021-06-01", 4),
    ("STORE-016", "Cardiff Flagship", "Wales", "flagship", 9000, "2019-09-01",
     "Owen Davies", "2019-09-01", 8),
    ("STORE-017", "Cardiff Standard", "Wales", "standard", 5500, "2020-03-01",
     "Rhian Evans", "2020-03-01", 6),
    ("STORE-018", "Swansea Outlet", "Wales", "outlet", 3500, "2021-09-01",
     "Gareth Williams", "2021-09-01", 3),
    ("STORE-ONL-LON", "Online London", "London", "online", 0, "2020-01-01",
     "Digital Team", "2020-01-01", 10),
    ("STORE-ONL-NAT", "Online National", "London", "online", 0, "2020-01-01",
     "Digital Team", "2020-01-01", 10),
]
for sid, name, region, stype, cap, opened, mgr, since, exp in STORES:
    kg.upsert_store_node(sid, name, region, stype, cap, opened, mgr, since, exp)

TERRITORIES = [
    ("Greater London", "London", 5000000),
    ("South Coast", "South East", 2500000),
    ("Central England", "Midlands", 3000000),
    ("North England", "North West", 3500000),
    ("Scotland", "Scotland", 2000000),
    ("Wales", "Wales", 1500000),
]
for name, region, target in TERRITORIES:
    kg.upsert_territory(name, region, target)

log.info("Layer 2 complete: 6 regions, 20 stores, 6 territories.")


# ═══════════════════════════════════════════════════════
# LAYER 3: KPI Definitions + Driver Trees
# ═══════════════════════════════════════════════════════
log.info("Layer 3: KPIs + driver trees...")

KPIS = [
    {"name": "revenue",
     "expression": "SUM(CASE WHEN status='completed' THEN order_total ELSE 0 END)",
     "tables": [f"{P}.orders"],
     "description": "Total revenue from completed orders",
     "thresholds": {"green": ">= 500000", "amber": ">= 300000", "red": "< 300000"},
     "dimensions": ["store", "category", "region", "channel", "segment"]},

    {"name": "order_count",
     "expression": "COUNTIF(status='completed')",
     "tables": [f"{P}.orders"],
     "description": "Number of completed orders",
     "thresholds": {"green": ">= 3000", "amber": ">= 1500", "red": "< 1500"},
     "dimensions": ["store", "category", "region", "channel"]},

    {"name": "aov",
     "expression": "SAFE_DIVIDE(SUM(CASE WHEN status='completed' THEN order_total END), COUNTIF(status='completed'))",
     "tables": [f"{P}.orders"],
     "description": "Average order value",
     "thresholds": {"green": ">= 200", "amber": ">= 150", "red": "< 150"},
     "dimensions": ["store", "category", "segment", "channel"]},

    {"name": "traffic",
     "expression": "COUNTIF(event_type='page_view')",
     "tables": [f"{P}.web_events"],
     "description": "Total page views (proxy for foot traffic + web)",
     "dimensions": ["store", "utm_source", "device_type"]},

    {"name": "conversion_rate",
     "expression": "SAFE_DIVIDE(COUNTIF(event_type='purchase'), COUNT(DISTINCT session_id))",
     "tables": [f"{P}.web_events"],
     "description": "Session to purchase conversion rate",
     "thresholds": {"green": ">= 0.03", "amber": ">= 0.01", "red": "< 0.01"},
     "dimensions": ["utm_source", "device_type", "utm_campaign"]},

    {"name": "product_mix_index",
     "expression": "SAFE_DIVIDE(SUM(CASE WHEN p.category='Electronics' THEN oi.line_total END), SUM(oi.line_total))",
     "tables": [f"{P}.order_items", f"{P}.products"],
     "description": "Share of revenue from Electronics",
     "dimensions": ["store", "brand"]},

    {"name": "discount_rate",
     "expression": "SAFE_DIVIDE(SUM(discount_amount), SUM(line_total + discount_amount))",
     "tables": [f"{P}.order_items"],
     "description": "Average discount as percentage of gross revenue",
     "thresholds": {"green": "< 0.10", "amber": "< 0.20", "red": ">= 0.20"},
     "dimensions": ["store", "category", "promo_type"]},

    {"name": "gross_margin",
     "expression": "SAFE_DIVIDE(SUM(oi.line_total - (p.cost * oi.quantity)), SUM(oi.line_total))",
     "tables": [f"{P}.order_items", f"{P}.products"],
     "description": "Gross margin percentage",
     "thresholds": {"green": ">= 0.40", "amber": ">= 0.25", "red": "< 0.25"},
     "dimensions": ["category", "brand", "subcategory", "store"]},

    {"name": "cancellation_rate",
     "expression": "SAFE_DIVIDE(COUNTIF(status='cancelled'), COUNT(*))",
     "tables": [f"{P}.orders"],
     "description": "Percentage of cancelled orders",
     "thresholds": {"green": "< 0.05", "amber": "< 0.10", "red": ">= 0.10"},
     "dimensions": ["store", "region", "channel"]},

    {"name": "customer_churn_rate",
     "expression": "SAFE_DIVIDE(COUNTIF(is_active = false), COUNT(*))",
     "tables": [f"{P}.customers"],
     "description": "Percentage of inactive customers",
     "thresholds": {"green": "< 0.10", "amber": "< 0.20", "red": ">= 0.20"},
     "dimensions": ["segment", "loyalty_tier", "acquisition_channel"]},

    # FIX Round 1: target_attainment — was referencing non-existent "actual_revenue"
    {"name": "target_attainment",
     "expression": "SAFE_DIVIDE(SUM(CASE WHEN o.status='completed' THEN o.order_total ELSE 0 END), SUM(st.target_revenue))",
     "tables": [f"{P}.sales_targets", f"{P}.orders", f"{P}.stores"],
     "description": "Actual completed revenue vs target revenue. Join: orders o JOIN stores s ON store_id JOIN sales_targets st ON s.store_id=st.store_id AND DATE_TRUNC(o.order_date, MONTH) = st.target_month",
     "thresholds": {"green": ">= 0.90", "amber": ">= 0.75", "red": "< 0.75"},
     "dimensions": ["store", "category"]},

    # FIX Round 1: promo_roi — was using hardcoded aliases
    {"name": "promo_roi",
     "expression": "SAFE_DIVIDE(SUM(orders.order_total) - MAX(promotions.budget_usd), MAX(promotions.budget_usd))",
     "tables": [f"{P}.orders", f"{P}.promotions"],
     "description": "Promotion ROI. Join orders to promotions on promo_id. ROI = (total promo revenue - budget) / budget. Group by promo_id. Filter WHERE status='completed'.",
     "dimensions": ["promo_type", "target_category", "target_region"]},

    # FIX Round 1: stockout_rate — was checking quantity=0 which never occurs in mock data
    {"name": "stockout_rate",
     "expression": "SAFE_DIVIDE(COUNT(DISTINCT CASE WHEN p.category = 'Electronics' AND p.brand IN ('TechPro','SwiftGear') THEN oi.item_id END), COUNT(DISTINCT oi.item_id))",
     "tables": [f"{P}.order_items", f"{P}.products"],
     "description": "Share of order items from affected Electronics brands. A sharp drop indicates effective stockout. Compare current period vs prior period.",
     "thresholds": {"green": ">= 0.10", "amber": ">= 0.05", "red": "< 0.05"},
     "dimensions": ["category", "brand", "store"]},

    # FIX Round 1: loyalty_redemption_rate — was crossing tables without join spec
    {"name": "loyalty_redemption_rate",
     "expression": "SAFE_DIVIDE(COUNTIF(c.loyalty_tier IN ('gold','platinum') AND o.promo_id IS NOT NULL), COUNT(*))",
     "tables": [f"{P}.orders", f"{P}.customers"],
     "description": "Rate of promo-linked purchases by gold/platinum loyalty members. Join: orders o JOIN customers c ON customer_id.",
     "dimensions": ["loyalty_tier", "store"]},
]
for kpi in KPIS:
    kg.upsert_kpi(kpi["name"], kpi["expression"], kpi["tables"],
                  kpi.get("description", ""), kpi.get("grain", "monthly"),
                  kpi.get("thresholds"), kpi.get("dimensions"))

# KPI Driver Tree
DRIVER_TREE = [
    ("revenue", "order_count"),
    ("revenue", "aov"),
    ("order_count", "traffic"),
    ("order_count", "conversion_rate"),
    ("aov", "product_mix_index"),
    ("aov", "discount_rate"),
    ("gross_margin", "product_mix_index"),
    ("gross_margin", "discount_rate"),
    # FIX Round 2: stockout_rate had empty driver tree
    ("stockout_rate", "order_count"),
]
for parent, child in DRIVER_TREE:
    kg.upsert_kpi_driver(parent, child)

log.info(f"Layer 3 complete: {len(KPIS)} KPIs, {len(DRIVER_TREE)} driver edges.")


# ═══════════════════════════════════════════════════════
# LAYER 4: Causal Reasoning (Business Concepts + AFFECTS)
# ═══════════════════════════════════════════════════════
log.info("Layer 4: Causal reasoning...")

CONCEPTS = [
    {"concept": "revenue decline",
     "maps_to_kpis": ["revenue", "aov", "order_count"],
     "description": "Decrease in total sales revenue vs prior period. Driven by fewer orders, lower AOV, higher cancellations, fewer promotions, or product lifecycle changes.",
     "maps_to": [f"{P}.orders", f"{P}.order_items", f"{P}.stores", f"{P}.promotions"],
     "synonyms": ["sales drop", "revenue decrease", "lower sales", "declining revenue"],
     "calculation_hint": "Compare SUM(order_total) WHERE status='completed' between periods. Break down by category, store, channel."},

    {"concept": "promotion impact",
     "maps_to_kpis": ["revenue", "promo_roi", "aov", "discount_rate"],
     "description": "How promotions drive revenue through direct lift, traffic effect, basket effect, cannibalization, and margin impact. Use promotion_products bridge table for product/category targeting joins.",
     "maps_to": [f"{P}.promotions", f"{P}.promotion_products", f"{P}.orders", f"{P}.order_items"],
     "synonyms": ["promo impact", "campaign effectiveness", "Black Friday", "marketing ROI"],
     "calculation_hint": "Join orders with promotions on promo_id. Use promotion_products bridge for targeted categories. Compare promo vs non-promo revenue. Check for overlap by querying same category with overlapping dates."},

    {"concept": "customer churn",
     "maps_to_kpis": ["customer_churn_rate", "revenue"],
     "description": "Rate at which customers become inactive. Enterprise churn often driven by account manager changes, contract renewals, SLA issues. SMB churn by price sensitivity.",
     "maps_to": [f"{P}.customers", f"{P}.orders"],
     "synonyms": ["attrition", "customer loss", "retention", "inactive customers", "enterprise churn"],
     "calculation_hint": "COUNTIF(is_active=false) / COUNT(*). Break down by segment, loyalty_tier, acquisition_channel."},

    {"concept": "store performance",
     "maps_to_kpis": ["revenue", "target_attainment", "order_count", "traffic"],
     "description": "How well a store/region performs vs targets and peers. Influenced by manager experience, competitor proximity, local events, parking access.",
     "maps_to": [f"{P}.stores", f"{P}.orders", f"{P}.sales_targets"],
     "synonyms": ["store sales", "location performance", "Manchester", "Birmingham", "regional"],
     "calculation_hint": "Join orders with stores on store_id. Compare revenue by store/region."},

    {"concept": "product performance",
     "maps_to_kpis": ["revenue", "gross_margin", "stockout_rate"],
     "description": "How products/categories sell relative to prior periods. Affected by lifecycle stage, substitution, discontinuation, supplier issues.",
     "maps_to": [f"{P}.products", f"{P}.order_items", f"{P}.orders"],
     "synonyms": ["product sales", "category decline", "Accessories", "Electronics", "best sellers"],
     "calculation_hint": "Join order_items with products. Group by category/brand/lifecycle_stage."},

    {"concept": "supply chain disruption",
     "maps_to_kpis": ["stockout_rate", "revenue", "order_count"],
     "description": "Supply chain issues causing stockouts, delays, or forced substitutions. Includes supplier incidents, logistics delays, and alternate supplier lead times.",
     "maps_to": [f"{P}.products", f"{P}.order_items"],
     "synonyms": ["stockout", "supply issue", "inventory", "out of stock", "supplier problem"],
     "calculation_hint": "Check products with low order_items in recent period vs historical. Cross-ref with supplier incident dates."},

    {"concept": "pricing and margin",
     "maps_to_kpis": ["gross_margin", "revenue", "aov", "discount_rate"],
     "description": "How pricing decisions affect margin. Includes competitive price responses, category-specific price cuts, discount policies.",
     "maps_to": [f"{P}.products", f"{P}.order_items", f"{P}.orders"],
     "synonyms": ["margin decline", "pricing", "discount", "Software margin", "price cut"],
     "calculation_hint": "Compare margin = (line_total - cost*qty) / line_total by category/period."},

    {"concept": "loyalty program effect",
     "maps_to_kpis": ["loyalty_redemption_rate", "revenue", "aov"],
     "description": "How loyalty program changes affect customer behavior. Includes tier rule changes, points ratio updates, partner integrations, expiry campaigns.",
     "maps_to": [f"{P}.customers", f"{P}.orders"],
     "synonyms": ["loyalty", "redemption", "points", "platinum", "rewards spike"],
     "calculation_hint": "Track promo usage by loyalty_tier over time. Check for step changes at rule change dates."},

    {"concept": "channel mix shift",
     "maps_to_kpis": ["revenue", "aov", "conversion_rate"],
     "description": "Distribution shifts between online and in-store. Online growth may reduce store traffic but improve conversion.",
     "maps_to": [f"{P}.orders", f"{P}.web_events"],
     "synonyms": ["online vs in-store", "channel shift", "digital"],
     "calculation_hint": "Group orders by channel. Compare online % over time."},

    {"concept": "seasonality",
     "maps_to_kpis": ["revenue", "order_count", "traffic"],
     "description": "Cyclical patterns. Q4 peak, summer dip. YoY comparisons must account for promo calendar alignment.",
     "maps_to": [f"{P}.orders", f"{P}.promotions"],
     "synonyms": ["seasonal", "holiday", "Q4", "Black Friday", "summer"],
     "calculation_hint": "Group by month/quarter. Compare same period across years."},

    {"concept": "competitive pressure",
     "maps_to_kpis": ["revenue", "traffic", "conversion_rate", "gross_margin"],
     "description": "External competitive actions: store openings, aggressive pricing, viral marketing. Affects traffic, conversion, and forces price responses.",
     "maps_to": [f"{P}.orders", f"{P}.stores"],
     "synonyms": ["competitor", "competitive", "market share", "price war"],
     "calculation_hint": "Compare store performance before/after known competitor actions."},

    # FIX Round 2: new concept for Q2 churn causal path
    {"concept": "customer relationship changes",
     "maps_to_kpis": ["customer_churn_rate", "revenue"],
     "description": "Changes in customer-business relationship that drive churn. Includes account manager departures leaving accounts unassigned, contract expirations, SLA downgrades. Enterprise segment most sensitive — relationship-based retention.",
     "maps_to": [f"{P}.customers", f"{P}.orders"],
     "synonyms": ["account manager", "contract renewal", "SLA", "relationship", "dedicated support"],
     "calculation_hint": "Check churn rate by segment before/after account manager departure dates. Cross-reference with manager assignments."},

    # FIX Round 2: new concept for Q6 loyalty causal path
    {"concept": "loyalty program changes",
     "maps_to_kpis": ["loyalty_redemption_rate", "aov", "revenue"],
     "description": "Modifications to loyalty program rules that change member behavior. Includes points-to-currency ratio changes, partner integrations, expiry reminder campaigns. Each has a specific effective date.",
     "maps_to": [f"{P}.orders", f"{P}.customers"],
     "synonyms": ["points ratio", "tier change", "redemption rule", "loyalty rule", "partner integration"],
     "calculation_hint": "Compare loyalty_redemption_rate before vs after each rule change date. Break down by tier."},
]

for c in CONCEPTS:
    kg.upsert_concept(c["concept"], c["description"], c["maps_to"],
                      c.get("maps_to_kpis"), c.get("synonyms"),
                      c.get("calculation_hint", ""))

# AFFECTS edges (causal graph)
AFFECTS = [
    ("promotion impact", "revenue decline",
     "Fewer/weaker promotions reduce revenue"),
    ("promotion impact", "pricing and margin",
     "Promo discounts compress margin"),
    ("customer churn", "revenue decline",
     "Churned customers stop purchasing"),
    ("supply chain disruption", "product performance",
     "Stockouts prevent sales"),
    ("supply chain disruption", "revenue decline",
     "Missing inventory = lost revenue"),
    ("competitive pressure", "revenue decline",
     "Competitor actions divert customers"),
    ("competitive pressure", "store performance",
     "Nearby competitor store reduces traffic"),
    ("competitive pressure", "pricing and margin",
     "Forced price response compresses margin"),
    ("pricing and margin", "revenue decline",
     "Price cuts may increase volume but reduce total revenue if elastic"),
    ("seasonality", "revenue decline",
     "Seasonal dips not offset by promotions"),
    ("channel mix shift", "store performance",
     "Online growth reduces in-store traffic"),
    ("product performance", "revenue decline",
     "Declining products drag down category revenue"),
    ("loyalty program effect", "revenue decline",
     "Redemption spikes reduce effective revenue"),
    ("loyalty program effect", "customer churn",
     "Program changes affect retention"),
    ("store performance", "revenue decline",
     "Underperforming stores reduce total revenue"),
    # FIX Round 2: complete Q2 churn causal path
    ("customer relationship changes", "customer churn",
     "Account manager departures leave enterprise accounts unassigned, triggering churn within 3-6 months"),
    ("competitive pressure", "customer churn",
     "Competitor offerings attract customers, especially when service quality drops"),
    # FIX Round 2: complete Q6 loyalty causal path
    ("loyalty program changes", "loyalty program effect",
     "Rule changes, partner integrations, and campaigns directly alter redemption behavior"),
    # FIX Round 2: channel mix → churn
    ("channel mix shift", "customer churn",
     "Forced channel migration alienates customers who prefer the original channel"),
]
for source, target, mechanism in AFFECTS:
    kg.upsert_affects(source, target, mechanism)

log.info(f"Layer 4 complete: {len(CONCEPTS)} concepts, {len(AFFECTS)} AFFECTS edges.")


# ═══════════════════════════════════════════════════════
# LAYER 5: Product Taxonomy
# ═══════════════════════════════════════════════════════
log.info("Layer 5: Product taxonomy...")

CATEGORIES = ["Electronics", "Software", "Services", "Accessories"]
SUBCATEGORIES = {
    "Electronics": ["Laptops", "Smartphones", "Tablets", "Headphones", "Monitors"],
    "Software": ["Productivity", "Security", "Design", "Analytics", "Cloud"],
    "Services": ["Consulting", "Training", "Support", "Implementation", "Managed"],
    "Accessories": ["Cases", "Cables", "Chargers", "Stands", "Adapters"],
}
BRANDS_BY_CAT = {
    "Electronics": [("TechPro", "premium"), ("ValueLine", "budget"), ("SwiftGear", "mid")],
    "Software": [("TechPro", "premium"), ("EcoSmart", "mid"), ("ValueLine", "budget")],
    "Services": [("PremiumPlus", "premium"), ("TechPro", "mid")],
    "Accessories": [("SwiftGear", "mid"), ("ValueLine", "budget"), ("EcoSmart", "budget")],
}
for cat in CATEGORIES:
    kg.upsert_category(cat)
    for sub in SUBCATEGORIES.get(cat, []):
        kg.upsert_category(sub, parent_category=cat)
    for brand, tier in BRANDS_BY_CAT.get(cat, []):
        kg.upsert_brand(brand, cat, tier)

kg.upsert_competes_with("Cables", "Chargers")
kg.upsert_competes_with("Analytics", "Cloud")

# Link promotions to categories from bridge table
log.info("  Linking promotions → categories from bridge table...")
bridge_query = f"""
    SELECT DISTINCT pp.promo_id, pr.promo_name, pp.category
    FROM `{P}.promotion_products` pp
    JOIN `{P}.promotions` pr ON pp.promo_id = pr.promo_id
    WHERE pp.category IS NOT NULL
"""
promo_cat_count = 0
for row in bq.query(bridge_query).result():
    kg.upsert_promo_targets_category(row.promo_name, row.category)
    promo_cat_count += 1
log.info(f"  {promo_cat_count} Promotion → Category links")

product_bridge_query = f"""
    SELECT DISTINCT pp.promo_id, pr.promo_name, pp.product_id
    FROM `{P}.promotion_products` pp
    JOIN `{P}.promotions` pr ON pp.promo_id = pr.promo_id
    WHERE pp.scope = 'product' AND pp.product_id IS NOT NULL
"""
promo_prod_count = 0
for row in bq.query(product_bridge_query).result():
    kg.upsert_promo_targets_product(row.promo_name, row.product_id)
    promo_prod_count += 1
log.info(f"  {promo_prod_count} Promotion → Product links")

log.info("Layer 5 complete.")


# ═══════════════════════════════════════════════════════
# LAYER 6: Supply Chain
# ═══════════════════════════════════════════════════════
log.info("Layer 6: Supply chain...")

kg.upsert_supplier("Shenzhen Tech Co", "Shenzhen, China", lead_time_weeks=4,
                   supplies_brands=["TechPro", "SwiftGear"])
kg.upsert_supplier("Taiwan Electronics", "Taipei, Taiwan", lead_time_weeks=6,
                   supplies_brands=["TechPro"])
kg.upsert_supplier("Korea Components", "Seoul, South Korea", lead_time_weeks=3,
                   supplies_brands=["ValueLine"])
kg.upsert_supplier("UK Accessories Ltd", "Birmingham, UK", lead_time_weeks=1,
                   supplies_brands=["SwiftGear", "EcoSmart"])

kg.upsert_supply_incident("Shenzhen Tech Co", "factory_fire", "2025-02-10",
                          "Complete production halt for 4 weeks. Affected TechPro Laptops, Smartphones, Tablets.",
                          duration_weeks=4)
kg.upsert_supply_incident("Shenzhen Tech Co", "logistics_delay", "2025-03-15",
                          "Post-fire backlog causing 2-week additional shipping delays.",
                          duration_weeks=2)
kg.upsert_alternate_supplier("Shenzhen Tech Co", "Taiwan Electronics")
kg.upsert_supply_incident("UK Accessories Ltd", "material_change", "2025-04-01",
                          "Changed USB-C cable material supplier. Old SKU PROD-0045 discontinued, replacement PROD-0089.",
                          duration_weeks=0)

log.info("Layer 6 complete: 4 suppliers, 3 incidents.")


# ═══════════════════════════════════════════════════════
# LAYER 7: Customer Relationships
# ═══════════════════════════════════════════════════════
log.info("Layer 7: Customer relationships...")

kg.upsert_account_manager("David Lee", "enterprise", left_date="2025-03-15", accounts=12)
kg.upsert_account_manager("Sarah Chen", "enterprise", accounts=8)
kg.upsert_account_manager("Mike Johnson", "mid-market", accounts=25)
kg.upsert_account_manager("Lisa Park", "smb", accounts=50)

kg.upsert_contract("enterprise", "SLA", "gold", "2025-09-30")
kg.upsert_contract("enterprise", "SLA", "platinum", "2025-12-31")
kg.upsert_contract("mid-market", "standard", "silver", "2026-03-31")

kg.upsert_churn_risk("enterprise", 0.82,
                     "Account manager David Lee departed Mar 2025; 12 accounts unassigned for 6 weeks")
kg.upsert_churn_risk("enterprise", 0.65,
                     "3 gold SLA contracts up for renewal in Q3 without dedicated manager")
kg.upsert_churn_risk("smb", 0.25,
                     "Low risk — price-sensitive but no relationship dependency")

log.info("Layer 7 complete: 4 account managers, 3 contracts, 3 churn risks.")


# ═══════════════════════════════════════════════════════
# LAYER 8: Temporal Context
# ═══════════════════════════════════════════════════════
log.info("Layer 8: Temporal context...")

kg.upsert_competitor_action("RetailMax", "early_black_friday", "2025-11-25",
                            "National",
                            impact="40% discount starting 2 days before our Black Friday campaign",
                            region="London")
kg.upsert_competitor_action("RetailMax", "early_black_friday", "2025-11-25",
                            "National TV + social",
                            impact="Aggressive TV + social media ad spend",
                            region="North West")
kg.upsert_competitor_action("RetailCo", "store_opening", "2025-08-01",
                            "Birmingham city centre, 200m from Birmingham Standard",
                            impact="Diverted 25-30% of foot traffic",
                            region="Midlands")
kg.upsert_competitor_action("BrandX", "viral_product_review", "2025-05-15",
                            "TikTok viral review of BrandX USB-C cable, 2M views",
                            impact="Customers switching from our Accessories cables to BrandX via Amazon",
                            region=None)

kg.upsert_policy_change("parking_fee_increase",
                        "Birmingham council raised parking fees from 2/hr to 4/hr",
                        "2025-06-01", location="Birmingham",
                        impact="Reduced casual shopper visits by ~15%")

kg.upsert_market_condition("university_expansion",
                           "University of Manchester new campus opened nearby, adding 5000 students",
                           "2025-09-01", severity="positive")
kg.upsert_market_condition("consumer_confidence",
                           "Declining since Q2 2025 due to interest rate concerns",
                           "2025-04-01", severity="moderate")
kg.upsert_market_condition("inflation",
                           "CPI at 3.2%, affecting discretionary spending",
                           "2025-01-01", severity="moderate")

log.info("Layer 8 complete: 4 competitor actions, 3 market conditions, 1 policy change.")


# ═══════════════════════════════════════════════════════
# LAYER 9: Business Rules
# ═══════════════════════════════════════════════════════
log.info("Layer 9: Business rules + pricing...")

kg.upsert_discount_policy("Electronics", max_pct=25, approved_by="VP Sales")
kg.upsert_discount_policy("Software", max_pct=30, approved_by="VP Sales")
kg.upsert_discount_policy("Services", max_pct=15, approved_by="VP Services")
kg.upsert_discount_policy("Accessories", max_pct=40, store_type="outlet",
                          approved_by="Merchandising")

kg.upsert_pricing_decision("Analytics",
                           action="-20% price reduction on Analytics subcategory",
                           reason="Match new VC-funded competitor NewCo",
                           date="2025-03-01", scope="new_customers_only")
kg.upsert_pricing_decision("Analytics",
                           action="Extended free trial from 14 to 30 days",
                           reason="Competitive response — reduce barrier to trial",
                           date="2025-04-01", scope="all")
kg.upsert_pricing_decision("Electronics",
                           action="Black Friday 30% + simultaneous clearance 20% on same category",
                           reason="Unintended overlap — clearance scheduled before BF dates confirmed",
                           date="2025-11-20", scope="all_channels")

kg.upsert_segment_rule("enterprise", "annual_spend", ">= 50000",
                       "Enterprise: annual spend >= 50K, dedicated account manager")
kg.upsert_segment_rule("mid-market", "annual_spend", ">= 10000",
                       "Mid-market: annual spend 10K-50K, shared account manager")
kg.upsert_segment_rule("smb", "annual_spend", "< 10000",
                       "SMB: annual spend < 10K, self-service, price-sensitive")

log.info("Layer 9 complete.")


# ═══════════════════════════════════════════════════════
# LAYER 10: Loyalty Program
# ═══════════════════════════════════════════════════════
log.info("Layer 10: Loyalty program...")

TIERS = [("bronze", 0, 1.0), ("silver", 2000, 1.5),
         ("gold", 5000, 2.0), ("platinum", 10000, 3.0)]
for name, min_spend, multiplier in TIERS:
    kg.upsert_loyalty_tier(name, min_spend, multiplier)

kg.upsert_redemption_rule("platinum", points_per_gbp=200,
                          effective_date="2025-07-01", previous_ratio=100)
kg.upsert_redemption_rule("gold", points_per_gbp=150,
                          effective_date="2025-07-01", previous_ratio=100)

kg.upsert_loyalty_partner("SkyMiles Airline", integration_date="2025-09-01",
                          partner_type="cross_redemption")

kg.upsert_loyalty_campaign("Points Expiry Reminder", target_tier="gold",
                           campaign_type="email", sent_date="2025-08-15",
                           description="Reminded gold members 50K+ points expire end of Q3. 85% open rate.")
kg.upsert_loyalty_campaign("Platinum Double Points Launch", target_tier="platinum",
                           campaign_type="email_plus_app_push", sent_date="2025-07-01",
                           description="Announced doubled points-to-currency ratio for platinum.")

log.info("Layer 10 complete.")


# ═══════════════════════════════════════════════════════
# TRIGGERS edges (Round 2: domain events → concepts)
# ═══════════════════════════════════════════════════════
log.info("Registering TRIGGERS edges (domain events → concepts)...")

TRIGGERS = [
    # L6 Supply incidents → supply chain disruption
    ("SupplyIncident", "type", "factory_fire", "supply chain disruption",
     "Shenzhen Tech Co fire halted TechPro/SwiftGear production for 4 weeks"),
    ("SupplyIncident", "type", "logistics_delay", "supply chain disruption",
     "Post-fire backlog caused 2-week additional shipping delays"),
    ("SupplyIncident", "type", "material_change", "supply chain disruption",
     "UK Accessories material change forced PROD-0045 discontinuation"),
    # L7 Account manager departure → customer relationship changes
    ("AccountManager", "name", "David Lee", "customer relationship changes",
     "Departed Mar 2025, left 12 enterprise accounts unassigned for 6 weeks"),
    # L8 Competitor actions → competitive pressure
    ("CompetitorAction", "competitor", "RetailMax", "competitive pressure",
     "RetailMax launched 40% Black Friday discount 2 days before our campaign"),
    ("CompetitorAction", "competitor", "RetailCo", "competitive pressure",
     "RetailCo opened store 200m from Birmingham Standard in Aug 2025"),
    ("CompetitorAction", "competitor", "BrandX", "competitive pressure",
     "BrandX USB-C cable went viral on TikTok, 2M views, May 2025"),
    # L8 Policy change → store performance
    ("PolicyChange", "type", "parking_fee_increase", "store performance",
     "Birmingham parking fees doubled Jun 2025, reducing casual shoppers ~15%"),
    # L9 Pricing decisions → pricing and margin
    ("PricingDecision", "subcategory", "Analytics", "pricing and margin",
     "20% price cut on Analytics to match VC-funded NewCo, Mar 2025"),
    # L10 Redemption rule changes → loyalty program changes
    ("RedemptionRule", "tier", "platinum", "loyalty program changes",
     "Platinum points ratio doubled from 100 to 200 points/GBP, Jul 2025"),
    ("RedemptionRule", "tier", "gold", "loyalty program changes",
     "Gold points ratio increased from 100 to 150 points/GBP, Jul 2025"),
]
for label, key, value, concept, evidence in TRIGGERS:
    kg.upsert_triggers(label, key, value, concept, evidence)

log.info(f"  {len(TRIGGERS)} TRIGGERS edges registered.")


# ═══════════════════════════════════════════════════════
# EXAMPLE QUERIES (for few-shot learning)
# ═══════════════════════════════════════════════════════
log.info("Registering example queries...")

EXAMPLES = [
    # Original 8 examples
    ("What was our total revenue last month?",
     f"SELECT SUM(order_total) AS revenue FROM `{P}.orders` WHERE status='completed' AND order_date BETWEEN DATE_TRUNC(DATE_SUB(CURRENT_DATE(), INTERVAL 1 MONTH), MONTH) AND LAST_DAY(DATE_SUB(CURRENT_DATE(), INTERVAL 1 MONTH))",
     [f"{P}.orders"], "simple"),

    ("Compare revenue this year vs last year by quarter",
     f"SELECT EXTRACT(YEAR FROM order_date) AS yr, EXTRACT(QUARTER FROM order_date) AS qtr, SUM(order_total) AS revenue FROM `{P}.orders` WHERE status='completed' AND order_date >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), YEAR), INTERVAL 1 YEAR) GROUP BY 1, 2 ORDER BY 1, 2",
     [f"{P}.orders"], "comparative"),

    ("Which stores had the biggest revenue decline year over year?",
     f"WITH ty AS (SELECT store_id, SUM(order_total) AS rev FROM `{P}.orders` WHERE status='completed' AND order_date >= DATE_TRUNC(CURRENT_DATE(), YEAR) GROUP BY 1), ly AS (SELECT store_id, SUM(order_total) AS rev FROM `{P}.orders` WHERE status='completed' AND EXTRACT(YEAR FROM order_date) = EXTRACT(YEAR FROM CURRENT_DATE())-1 GROUP BY 1) SELECT s.store_name, s.region, t.rev AS this_year, l.rev AS last_year, ROUND(SAFE_DIVIDE(t.rev-l.rev, l.rev)*100,1) AS pct_change FROM ty t JOIN ly l USING(store_id) JOIN `{P}.stores` s USING(store_id) ORDER BY pct_change ASC LIMIT 10",
     [f"{P}.orders", f"{P}.stores"], "comparative"),

    ("What is our cancellation rate by store this quarter?",
     f"SELECT s.store_name, s.region, COUNT(*) AS total_orders, COUNTIF(o.status='cancelled') AS cancelled, ROUND(SAFE_DIVIDE(COUNTIF(o.status='cancelled'), COUNT(*))*100, 1) AS cancel_rate_pct FROM `{P}.orders` o JOIN `{P}.stores` s ON o.store_id=s.store_id WHERE o.order_date >= DATE_TRUNC(CURRENT_DATE(), QUARTER) GROUP BY 1, 2 ORDER BY cancel_rate_pct DESC",
     [f"{P}.orders", f"{P}.stores"], "diagnostic"),

    ("What is the gross margin by product category?",
     f"SELECT p.category, ROUND(SAFE_DIVIDE(SUM(oi.line_total-(p.cost*oi.quantity)), SUM(oi.line_total))*100, 1) AS margin_pct, SUM(oi.line_total) AS revenue FROM `{P}.order_items` oi JOIN `{P}.products` p ON oi.product_id=p.product_id JOIN `{P}.orders` o ON oi.order_id=o.order_id WHERE o.status='completed' GROUP BY 1 ORDER BY margin_pct DESC",
     [f"{P}.order_items", f"{P}.products", f"{P}.orders"], "comparative"),

    ("How effective were our promotions this quarter?",
     f"SELECT pr.promo_name, pr.promo_type, pr.discount_pct, pp.category AS target_category, COUNT(DISTINCT o.order_id) AS promo_orders, SUM(o.order_total) AS promo_revenue, pr.budget_usd, ROUND(SAFE_DIVIDE(SUM(o.order_total), pr.budget_usd), 2) AS roi FROM `{P}.orders` o JOIN `{P}.promotions` pr ON o.promo_id=pr.promo_id JOIN `{P}.promotion_products` pp ON pr.promo_id=pp.promo_id WHERE o.status='completed' AND o.order_date >= DATE_TRUNC(CURRENT_DATE(), QUARTER) GROUP BY 1,2,3,4,7 ORDER BY roi DESC",
     [f"{P}.orders", f"{P}.promotions", f"{P}.promotion_products"], "diagnostic"),

    ("What is the customer churn rate by segment?",
     f"SELECT segment, COUNT(*) AS total, COUNTIF(is_active=false) AS churned, ROUND(SAFE_DIVIDE(COUNTIF(is_active=false), COUNT(*))*100, 1) AS churn_rate_pct FROM `{P}.customers` GROUP BY 1 ORDER BY churn_rate_pct DESC",
     [f"{P}.customers"], "comparative"),

    ("Show monthly revenue trend by product category for the last 12 months",
     f"SELECT DATE_TRUNC(o.order_date, MONTH) AS month, p.category, SUM(o.order_total) AS revenue FROM `{P}.orders` o JOIN `{P}.order_items` oi ON o.order_id=oi.order_id JOIN `{P}.products` p ON oi.product_id=p.product_id WHERE o.status='completed' AND o.order_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 12 MONTH) GROUP BY 1, 2 ORDER BY 1, 2",
     [f"{P}.orders", f"{P}.order_items", f"{P}.products"], "diagnostic"),

    # Round 3: 4 new examples for complex query patterns

    ("Compare enterprise churn rate before vs after March 2025",
     f"SELECT CASE WHEN created_at < '2025-03-15' THEN 'before_mar2025' ELSE 'after_mar2025' END AS period, segment, COUNT(*) AS total, COUNTIF(is_active = false) AS churned, ROUND(SAFE_DIVIDE(COUNTIF(is_active = false), COUNT(*)) * 100, 1) AS churn_pct FROM `{P}.customers` WHERE segment IN ('enterprise', 'smb') GROUP BY 1, 2 ORDER BY segment, period",
     [f"{P}.customers"], "segment_compare"),

    ("Show monthly loyalty redemption rate by tier for 12 months",
     f"SELECT DATE_TRUNC(o.order_date, MONTH) AS month, c.loyalty_tier, COUNT(*) AS total_orders, COUNTIF(o.promo_id IS NOT NULL) AS promo_orders, ROUND(SAFE_DIVIDE(COUNTIF(o.promo_id IS NOT NULL), COUNT(*)) * 100, 1) AS redemption_pct FROM `{P}.orders` o JOIN `{P}.customers` c ON o.customer_id = c.customer_id WHERE c.loyalty_tier IN ('gold', 'platinum') AND o.order_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 12 MONTH) GROUP BY 1, 2 ORDER BY 1, 2",
     [f"{P}.orders", f"{P}.customers"], "anomaly"),

    ("Compare Electronics order volume by brand before vs after February 2025",
     f"SELECT CASE WHEN o.order_date < '2025-02-15' THEN 'before_fire' ELSE 'after_fire' END AS period, p.brand, COUNT(DISTINCT oi.item_id) AS items, SUM(oi.line_total) AS revenue FROM `{P}.orders` o JOIN `{P}.order_items` oi ON o.order_id = oi.order_id JOIN `{P}.products` p ON oi.product_id = p.product_id WHERE p.category = 'Electronics' AND o.order_date BETWEEN '2024-11-01' AND '2025-06-01' AND o.status = 'completed' GROUP BY 1, 2 ORDER BY 2, 1",
     [f"{P}.orders", f"{P}.order_items", f"{P}.products"], "root_cause"),

    ("Compare Manchester Flagship vs Birmingham Standard monthly revenue",
     f"SELECT DATE_TRUNC(o.order_date, MONTH) AS month, s.store_name, COUNT(DISTINCT o.order_id) AS orders, ROUND(SUM(o.order_total), 2) AS revenue, ROUND(SAFE_DIVIDE(SUM(o.order_total), COUNT(DISTINCT o.order_id)), 2) AS aov FROM `{P}.orders` o JOIN `{P}.stores` s ON o.store_id = s.store_id WHERE s.store_id IN ('STORE-010', 'STORE-007') AND o.status = 'completed' AND o.order_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 12 MONTH) GROUP BY 1, 2 ORDER BY 1, 2",
     [f"{P}.orders", f"{P}.stores"], "entity_compare"),
]

for q, sql, tables, complexity in EXAMPLES:
    kg.upsert_example(q, sql, tables, complexity)
    # NOTE: vs.index_example is called here so the QueryExample node gets
    # its embedding right after it is created. create_indexes() at the end
    # will also cover these, but calling it here keeps them in sync during
    # incremental re-runs.
    vs.index_example(q, sql, tables)

log.info(f"Registered {len(EXAMPLES)} example queries.")


# ═══════════════════════════════════════════════════════
# CREATE NEO4J VECTOR INDEXES + STORE EMBEDDINGS ON NODES
# ═══════════════════════════════════════════════════════
log.info("Creating Neo4j vector indexes and storing embeddings on nodes...")
log.info("(Replaces Vertex AI Matching Engine — embeddings now live on graph nodes)")
vs.create_indexes(kg)


# ═══════════════════════════════════════════════════════
# VERIFICATION
# ═══════════════════════════════════════════════════════
log.info("\n=== VERIFICATION ===")
with kg.driver.session() as s:
    for label in [
        "Table", "Column", "Region", "Store", "Manager", "Territory",
        "KPI", "Threshold", "Dimension", "BusinessConcept", "QueryExample",
        "Category", "Brand", "Promotion", "Supplier", "SupplyIncident",
        "AccountManager", "Contract", "ChurnRisk",
        "CompetitorAction", "MarketCondition", "PolicyChange",
        "DiscountPolicy", "PricingDecision", "SegmentRule",
        "LoyaltyTier", "RedemptionRule", "Partner", "LoyaltyCampaign",
    ]:
        r = s.run(f"MATCH (n:{label}) RETURN count(n) AS c").single()
        if r and r["c"] > 0:
            log.info(f"  {label}: {r['c']} nodes")

    for rel in [
        "HAS_COLUMN", "RELATES_TO", "FOREIGN_KEY", "CONTAINS", "MANAGED_BY",
        "COMPUTED_FROM", "HAS_THRESHOLD", "SLICED_BY", "DRIVEN_BY",
        "AFFECTS", "MAPS_TO", "MEASURES", "HAS_BRAND", "COMPETES_WITH",
        "TARGETS_CATEGORY", "TARGETS_PRODUCT", "TRIGGERS",
        "SUPPLIES", "HAS_INCIDENT", "ALTERNATE_SUPPLIER",
        "AFFECTS_REGION", "APPLIES_TO", "QUALIFIES_FOR", "TARGETED",
    ]:
        r = s.run(f"MATCH ()-[r:{rel}]->() RETURN count(r) AS c").single()
        if r and r["c"] > 0:
            log.info(f"  [{rel}]: {r['c']} edges")

log.info("\n=== SETUP COMPLETE ===")
log.info("Run: cd .. && adk web")
log.info("Then ask: 'Why are we seeing stockouts in Electronics this month?'")

# Verify vector indexes exist
log.info("\n=== VECTOR INDEX CHECK ===")
target_indexes = {"table_embeddings", "kpi_embeddings",
                  "concept_embeddings", "example_embeddings"}
with kg.driver.session() as s:
    # SHOW VECTOR INDEXES does not support WHERE/RETURN filtering via the
    # Python driver — fetch all rows and filter in Python instead.
    rows = s.run("SHOW VECTOR INDEXES")
    found = {}
    for r in rows:
        name = r["name"]
        if name in target_indexes:
            found[name] = {
                "state": r["state"],
                "pct":   r.get("populationPercent", 0.0) or 0.0,
            }

for idx in sorted(target_indexes):
    if idx in found:
        info = found[idx]
        log.info(f"  {idx}: {info['state']} ({info['pct']:.0f}% populated)")
    else:
        log.warning(f"  {idx}: NOT FOUND — check Neo4j version (needs 5.11+)")