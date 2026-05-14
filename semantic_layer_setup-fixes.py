"""
PATCH: Apply these changes to semantic_layer_setup.py
=====================================================
ROUND 1 fixes (KPIs + relationship):
  1. stockout_rate KPI — changed to brand share drop detection
  2. target_attainment KPI — explicit orders join
  3. promo_roi KPI — alias-free expression
  4. loyalty_redemption_rate KPI — explicit join
  5. Missing RELATES_TO for promotion_products.category → products.category

ROUND 2 fixes (causal completeness + TRIGGERS):
  6. New concept: "customer relationship changes"
  7. New concept: "loyalty program changes"
  8. 5 new AFFECTS edges completing all causal paths
  9. stockout_rate added to KPI driver tree
  10. 11 TRIGGERS edges connecting domain events to concepts
"""

# ═══════════════════════════════════════════════
# ROUND 1 FIXES — KPI expressions + relationship
# ═══════════════════════════════════════════════

# Find and replace these KPI definitions in the KPIS list:

# ─── FIX 1: stockout_rate ───
STOCKOUT_RATE_FIX = {
    "name": "stockout_rate",
    "expression": (
        "SAFE_DIVIDE("
        "  COUNT(DISTINCT CASE WHEN p.category = 'Electronics' "
        "    AND p.brand IN ('TechPro','SwiftGear') THEN oi.item_id END),"
        "  COUNT(DISTINCT oi.item_id)"
        ")"
    ),
    "tables": [f"{P}.order_items", f"{P}.products"],
    "description": (
        "Share of order items from affected Electronics brands. "
        "A sharp drop indicates effective stockout. Compare current period "
        "vs prior period — a >50% drop signals supply disruption."
    ),
    "thresholds": {"green": ">= 0.10", "amber": ">= 0.05", "red": "< 0.05"},
    "dimensions": ["category", "brand", "store"],
}

# ─── FIX 2: target_attainment ───
TARGET_ATTAINMENT_FIX = {
    "name": "target_attainment",
    "expression": (
        "SAFE_DIVIDE("
        "  SUM(CASE WHEN o.status='completed' THEN o.order_total ELSE 0 END),"
        "  SUM(st.target_revenue)"
        ")"
    ),
    "tables": [f"{P}.sales_targets", f"{P}.orders", f"{P}.stores"],
    "description": (
        "Actual completed revenue vs target revenue. "
        "Join: orders o JOIN stores s ON store_id "
        "JOIN sales_targets st ON s.store_id=st.store_id "
        "AND DATE_TRUNC(o.order_date, MONTH) = st.target_month"
    ),
    "thresholds": {"green": ">= 0.90", "amber": ">= 0.75", "red": "< 0.75"},
    "dimensions": ["store", "category"],
}

# ─── FIX 3: promo_roi ───
PROMO_ROI_FIX = {
    "name": "promo_roi",
    "expression": (
        "SAFE_DIVIDE("
        "  SUM(orders.order_total) - MAX(promotions.budget_usd),"
        "  MAX(promotions.budget_usd)"
        ")"
    ),
    "tables": [f"{P}.orders", f"{P}.promotions"],
    "description": (
        "Promotion ROI. Join orders to promotions on promo_id. "
        "ROI = (total promo revenue - budget) / budget. "
        "Group by promo_id. Filter WHERE status='completed'."
    ),
    "dimensions": ["promo_type", "target_category", "target_region"],
}

# ─── FIX 4: loyalty_redemption_rate ───
LOYALTY_REDEMPTION_FIX = {
    "name": "loyalty_redemption_rate",
    "expression": (
        "SAFE_DIVIDE("
        "  COUNTIF(c.loyalty_tier IN ('gold','platinum') AND o.promo_id IS NOT NULL),"
        "  COUNT(*)"
        ")"
    ),
    "tables": [f"{P}.orders", f"{P}.customers"],
    "description": (
        "Rate of promo-linked purchases by gold/platinum loyalty members. "
        "Join: orders o JOIN customers c ON customer_id. "
        "A spike indicates loyalty program changes driving redemption."
    ),
    "dimensions": ["loyalty_tier", "store"],
}

# ─── FIX 5: Missing relationship ───
# Add this to the RELS list:
MISSING_REL = (
    f"{P}.promotion_products", f"{P}.products",
    "MANY_TO_MANY", "promotion_products.category = products.category",
)


# ═══════════════════════════════════════════════
# ROUND 2 FIXES — Causal completeness + TRIGGERS
# ═══════════════════════════════════════════════

# ─── FIX 6+7: Add these to the CONCEPTS list ───

NEW_CONCEPTS = [
    {
        "concept": "customer relationship changes",
        "maps_to_kpis": ["customer_churn_rate", "revenue"],
        "description": (
            "Changes in the customer-business relationship that drive churn. "
            "Includes: account manager departures (leaving accounts unassigned), "
            "contract expirations without renewal, SLA downgrades, "
            "loss of dedicated support. Enterprise segment is most sensitive — "
            "enterprise customers have relationship-based retention while SMB "
            "is price-based. A key account manager departure can trigger "
            "cascading churn across their managed accounts within 3-6 months."
        ),
        "maps_to": [f"{P}.customers", f"{P}.orders"],
        "synonyms": [
            "account manager", "contract renewal", "SLA", "relationship",
            "dedicated support", "account management", "customer service",
        ],
        "calculation_hint": (
            "Check churn rate by segment before/after account manager departure dates. "
            "Cross-reference customer.preferred_store_id with manager assignments. "
            "Look for clustering of is_active=false within 3-6 months of departure."
        ),
    },
    {
        "concept": "loyalty program changes",
        "maps_to_kpis": ["loyalty_redemption_rate", "aov", "revenue"],
        "description": (
            "Modifications to loyalty program rules that change member behavior. "
            "Includes: points-to-currency ratio changes, tier threshold adjustments, "
            "new partner integrations enabling cross-redemption, "
            "expiry reminder campaigns driving redemption urgency, "
            "new tier benefits. Each change has a specific effective date — "
            "look for step-changes in redemption behavior at those dates."
        ),
        "maps_to": [f"{P}.orders", f"{P}.customers"],
        "synonyms": [
            "points ratio", "tier change", "redemption rule", "loyalty rule",
            "partner integration", "points expiry", "program change",
        ],
        "calculation_hint": (
            "Compare loyalty_redemption_rate in the month before vs after each rule change date. "
            "Break down by tier to see which tiers were affected. "
            "Check if partner integration date correlates with cross-channel redemption spike."
        ),
    },
]

# ─── FIX 8: Add these to the AFFECTS list ───

NEW_AFFECTS = [
    # Complete the churn causal path
    ("customer relationship changes", "customer churn",
     "Account manager departures leave enterprise accounts unassigned, "
     "triggering relationship-based churn within 3-6 months"),
    ("competitive pressure", "customer churn",
     "Competitor offerings attract customers, especially when service quality drops"),
    # Complete the loyalty causal path (what CAUSES loyalty program effect)
    ("loyalty program changes", "loyalty program effect",
     "Rule changes, partner integrations, and campaigns directly alter "
     "redemption behavior and purchase patterns"),
    # Supply chain → stockout (more direct path)
    ("supply chain disruption", "revenue decline",
     "Already exists — keeping for completeness"),
    # Channel mix affects customer behavior
    ("channel mix shift", "customer churn",
     "Forced channel migration (store closures, online-only) alienates "
     "customers who prefer the original channel"),
]
# Note: filter out the duplicate "supply chain disruption" → "revenue decline"
# which already exists. Only register edges that are new.

# ─── FIX 9: Add to DRIVER_TREE list ───
# stockout_rate decomposes into order_count (proxy)
NEW_DRIVER_EDGES = [
    ("stockout_rate", "order_count"),
]

# ─── FIX 10: TRIGGERS edges (domain events → concepts) ───
# Add this AFTER all Layer 6-10 data is registered.

TRIGGERS_EDGES = [
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

# ─── HOW TO APPLY ───
# Add to the bottom of semantic_layer_setup.py, before the VERIFICATION section:
#
# log.info("Round 2 fixes: new concepts + AFFECTS + TRIGGERS...")
#
# for c in NEW_CONCEPTS:
#     kg.upsert_concept(c["concept"], c["description"], c["maps_to"],
#                       c.get("maps_to_kpis"), c.get("synonyms"), c.get("calculation_hint",""))
#
# for source, target, mechanism in NEW_AFFECTS:
#     if source != target:  # skip self-edges
#         kg.upsert_affects(source, target, mechanism)
#
# for parent, child in NEW_DRIVER_EDGES:
#     kg.upsert_kpi_driver(parent, child)
#
# for label, key, value, concept, evidence in TRIGGERS_EDGES:
#     kg.upsert_triggers(label, key, value, concept, evidence)
#
# for q, sql, tables, complexity in NEW_EXAMPLES:
#     kg.upsert_example(q, sql, tables, complexity)
#     vs.index_example(q, sql, tables)
#
# log.info(f"  {len(NEW_CONCEPTS)} concepts, {len(NEW_AFFECTS)} AFFECTS, "
#          f"{len(TRIGGERS_EDGES)} TRIGGERS, {len(NEW_EXAMPLES)} examples")


# ═══════════════════════════════════════════════
# ROUND 3 FIXES — Missing few-shot examples
# ═══════════════════════════════════════════════

NEW_EXAMPLES = [
    # Before/after date comparison (SEGMENT_COMPARE, ENTITY_COMPARE)
    (
        "Compare enterprise churn rate before vs after March 2025",
        (
            f"SELECT "
            f"  CASE WHEN created_at < '2025-03-15' THEN 'before_mar2025' "
            f"       ELSE 'after_mar2025' END AS period, "
            f"  segment, "
            f"  COUNT(*) AS total, "
            f"  COUNTIF(is_active = false) AS churned, "
            f"  ROUND(SAFE_DIVIDE(COUNTIF(is_active = false), COUNT(*)) * 100, 1) AS churn_pct "
            f"FROM `{P}.customers` "
            f"WHERE segment IN ('enterprise', 'smb') "
            f"GROUP BY 1, 2 ORDER BY segment, period"
        ),
        [f"{P}.customers"],
        "segment_compare",
    ),

    # Monthly metric trend by dimension (ANOMALY detection)
    (
        "Show monthly loyalty redemption rate by tier for 12 months",
        (
            f"SELECT "
            f"  DATE_TRUNC(o.order_date, MONTH) AS month, "
            f"  c.loyalty_tier, "
            f"  COUNT(*) AS total_orders, "
            f"  COUNTIF(o.promo_id IS NOT NULL) AS promo_orders, "
            f"  ROUND(SAFE_DIVIDE(COUNTIF(o.promo_id IS NOT NULL), COUNT(*)) * 100, 1) AS redemption_pct "
            f"FROM `{P}.orders` o "
            f"JOIN `{P}.customers` c ON o.customer_id = c.customer_id "
            f"WHERE c.loyalty_tier IN ('gold', 'platinum') "
            f"  AND o.order_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 12 MONTH) "
            f"GROUP BY 1, 2 ORDER BY 1, 2"
        ),
        [f"{P}.orders", f"{P}.customers"],
        "anomaly",
    ),

    # Brand-specific volume comparison across periods (ROOT_CAUSE stockout)
    (
        "Compare Electronics order volume by brand before vs after February 2025",
        (
            f"SELECT "
            f"  CASE WHEN o.order_date < '2025-02-15' THEN 'before_fire' "
            f"       ELSE 'after_fire' END AS period, "
            f"  p.brand, "
            f"  COUNT(DISTINCT oi.item_id) AS items, "
            f"  SUM(oi.line_total) AS revenue "
            f"FROM `{P}.orders` o "
            f"JOIN `{P}.order_items` oi ON o.order_id = oi.order_id "
            f"JOIN `{P}.products` p ON oi.product_id = p.product_id "
            f"WHERE p.category = 'Electronics' "
            f"  AND o.order_date BETWEEN '2024-11-01' AND '2025-06-01' "
            f"  AND o.status = 'completed' "
            f"GROUP BY 1, 2 ORDER BY 2, 1"
        ),
        [f"{P}.orders", f"{P}.order_items", f"{P}.products"],
        "root_cause",
    ),

    # Entity-pair comparison (ENTITY_COMPARE two stores)
    (
        "Compare Manchester Flagship vs Birmingham Standard monthly revenue",
        (
            f"SELECT "
            f"  DATE_TRUNC(o.order_date, MONTH) AS month, "
            f"  s.store_name, "
            f"  COUNT(DISTINCT o.order_id) AS orders, "
            f"  ROUND(SUM(o.order_total), 2) AS revenue, "
            f"  ROUND(SAFE_DIVIDE(SUM(o.order_total), COUNT(DISTINCT o.order_id)), 2) AS aov "
            f"FROM `{P}.orders` o "
            f"JOIN `{P}.stores` s ON o.store_id = s.store_id "
            f"WHERE s.store_id IN ('STORE-010', 'STORE-007') "
            f"  AND o.status = 'completed' "
            f"  AND o.order_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 12 MONTH) "
            f"GROUP BY 1, 2 ORDER BY 1, 2"
        ),
        [f"{P}.orders", f"{P}.stores"],
        "entity_compare",
    ),
]

