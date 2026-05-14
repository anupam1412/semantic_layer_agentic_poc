"""
Enhanced Mock Data — BigQuery Tables with Deliberate Patterns
=============================================================
Creates 8 tables with specific data patterns supporting 7 target queries:

Q1 (Electronics stockouts):
  - Electronics order_items drop sharply after Feb 2025 (factory fire)
  - TechPro/SwiftGear brands affected, ValueLine stable
  - Cancellation rate spikes for Electronics orders

Q2 (Enterprise churn):
  - Enterprise customers: 25% churn rate (is_active=false)
  - SMB customers: 10% churn rate
  - Enterprise churn clusters after Mar 2025 (account manager departure)

Q3 (Black Friday underperformance):
  - 2024 Black Friday: strong orders with promo
  - 2025 Black Friday: weaker orders, overlapping clearance promo

Q4 (Manchester vs Birmingham):
  - STORE-010 (Manchester Flagship): orders trend UP in H2 2025
  - STORE-007 (Birmingham Standard): orders trend DOWN after Aug 2025

Q5 (Accessories decline):
  - Accessories order_items decline from Apr 2025 (product discontinuation)
  - PROD-0045 (USB-C cable): zero orders after April
  - Despite promos targeting Accessories

Q6 (Loyalty redemption spike):
  - Gold/platinum customers with promo_id spike in Q3 2025
  - Bronze/silver flat

Q7 (Software margin compression):
  - Software orders grow (volume up)
  - Analytics subcategory: unit_price drops 20% from Mar 2025
  - Cost unchanged → margin compresses
"""

import os
import random
from datetime import date, datetime, timedelta
from google.cloud import bigquery

try:
    from .dotenv_loader import load_dotenv
except ImportError:
    from dotenv_loader import load_dotenv

# Load configuration from .env if present
load_dotenv()

PROJECT = os.getenv("GCP_PROJECT", "acn-uki-ds-data-ai-project")
DATASET = os.getenv("BQ_DATASET", "customer_sales_data_ai_agentic_semantic_layer")
LOCATION = os.getenv("GCP_REGION", "europe-west2")

client = bigquery.Client(project=PROJECT, location=LOCATION)

ds = bigquery.Dataset(f"{PROJECT}.{DATASET}")
ds.location = LOCATION
client.create_dataset(ds, exists_ok=True)
print(f"Dataset '{DATASET}' ready")

random.seed(42)

# ─── Helpers ───
FIRST = ["James","Mary","Robert","Patricia","John","Jennifer","Michael","Linda","David",
         "Elizabeth","William","Barbara","Richard","Susan","Joseph","Jessica","Thomas",
         "Sarah","Charles","Karen","Daniel","Lisa","Matthew","Nancy","Anthony","Betty",
         "Mark","Margaret","Steven","Ashley","Paul","Emily","Andrew","Donna","Joshua",
         "Michelle","Kenneth","Carol","Kevin","Amanda","Brian","Dorothy","George","Melissa"]
LAST = ["Smith","Johnson","Williams","Brown","Jones","Garcia","Miller","Davis","Rodriguez",
        "Martinez","Hernandez","Lopez","Gonzalez","Wilson","Anderson","Thomas","Taylor",
        "Moore","Jackson","Martin","Lee","Perez","Thompson","White","Harris"]
COUNTRIES = ["GB","DE","FR","US","CA","AU","NL","ES","IT"]
SEGMENTS = ["enterprise","mid-market","smb"]
CHANNELS = ["organic","paid_search","paid_social","referral","email","direct"]
LOYALTY = ["bronze","silver","gold","platinum"]
DEVICE_TYPES = ["desktop","mobile","tablet"]
UTM_SOURCES = ["google","facebook","linkedin","instagram","email","direct",None]
UTM_CAMPAIGNS = ["spring_sale","summer_clearance","back_to_school","black_friday",
                 "holiday_special","new_year","brand_awareness","retargeting",None]
BRANDS = ["TechPro","ValueLine","PremiumPlus","EcoSmart","SwiftGear"]

CATEGORIES = {
    "Electronics": {"subs": ["Laptops","Smartphones","Tablets","Headphones","Monitors"],
                    "price_range": (100,2000), "margin_range": (0.15,0.35)},
    "Software":    {"subs": ["Productivity","Security","Design","Analytics","Cloud"],
                    "price_range": (20,500), "margin_range": (0.60,0.85)},
    "Services":    {"subs": ["Consulting","Training","Support","Implementation","Managed"],
                    "price_range": (200,5000), "margin_range": (0.40,0.65)},
    "Accessories": {"subs": ["Cases","Cables","Chargers","Stands","Adapters"],
                    "price_range": (5,100), "margin_range": (0.45,0.70)},
}

STORE_IDS = [f"STORE-{i+1:03d}" for i in range(18)] + ["STORE-ONL-LON","STORE-ONL-NAT"]
# Q4 scenario stores
MANCHESTER_FLAGSHIP = "STORE-010"
BIRMINGHAM_STANDARD = "STORE-007"

ORDER_STATUSES = ["completed"]*7 + ["pending","cancelled","refunded"]

def rand_date(start, end):
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, max(delta, 0)))

def rand_ts(d):
    return datetime(d.year, d.month, d.day, random.randint(6,23),
                    random.randint(0,59), random.randint(0,59))


# ─── Schemas ───
SCHEMAS = {
    "stores": [
        bigquery.SchemaField("store_id","STRING",mode="REQUIRED",description="Unique store identifier"),
        bigquery.SchemaField("store_name","STRING",description="Store display name"),
        bigquery.SchemaField("region","STRING",description="Geographic region"),
        bigquery.SchemaField("city","STRING",description="City"),
        bigquery.SchemaField("store_type","STRING",description="flagship, standard, outlet, online"),
        bigquery.SchemaField("opened_date","DATE",description="When the store opened"),
        bigquery.SchemaField("capacity_sqft","INT64",description="Floor space in sqft"),
        bigquery.SchemaField("manager_name","STRING",description="Store manager"),
        bigquery.SchemaField("is_active","BOOL",description="Currently operating"),
    ],
    "customers": [
        bigquery.SchemaField("customer_id","STRING",mode="REQUIRED",description="Unique customer ID"),
        bigquery.SchemaField("name","STRING",description="Full name"),
        bigquery.SchemaField("email","STRING",description="Email"),
        bigquery.SchemaField("segment","STRING",description="enterprise, mid-market, smb"),
        bigquery.SchemaField("acquisition_channel","STRING",description="How acquired"),
        bigquery.SchemaField("loyalty_tier","STRING",description="bronze, silver, gold, platinum"),
        bigquery.SchemaField("created_at","TIMESTAMP",description="Account creation"),
        bigquery.SchemaField("country","STRING",description="ISO country code"),
        bigquery.SchemaField("preferred_store_id","STRING",description="FK to stores"),
        bigquery.SchemaField("lifetime_value","FLOAT64",description="Predicted LTV"),
        bigquery.SchemaField("is_active","BOOL",description="Active flag"),
    ],
    "products": [
        bigquery.SchemaField("product_id","STRING",mode="REQUIRED",description="Unique product ID"),
        bigquery.SchemaField("product_name","STRING",description="Display name"),
        bigquery.SchemaField("category","STRING",description="Product category"),
        bigquery.SchemaField("subcategory","STRING",description="Subcategory"),
        bigquery.SchemaField("brand","STRING",description="Brand name"),
        bigquery.SchemaField("list_price","FLOAT64",description="List price USD"),
        bigquery.SchemaField("cost","FLOAT64",description="Unit cost USD"),
        bigquery.SchemaField("launch_date","DATE",description="Product launch date"),
        bigquery.SchemaField("is_discontinued","BOOL",description="No longer sold"),
        bigquery.SchemaField("lifecycle_stage","STRING",description="new, growth, mature, decline"),
    ],
    "promotions": [
        bigquery.SchemaField("promo_id","STRING",mode="REQUIRED",description="Unique promotion ID"),
        bigquery.SchemaField("promo_name","STRING",description="Promotion name"),
        bigquery.SchemaField("promo_type","STRING",description="discount, bogo, bundle, clearance"),
        bigquery.SchemaField("discount_pct","FLOAT64",description="Discount percentage"),
        bigquery.SchemaField("start_date","DATE",description="Promotion start"),
        bigquery.SchemaField("end_date","DATE",description="Promotion end"),
        bigquery.SchemaField("target_category","STRING",description="Which category (null=all)"),
        bigquery.SchemaField("target_region","STRING",description="Which region (null=all)"),
        bigquery.SchemaField("budget_usd","FLOAT64",description="Marketing spend"),
        bigquery.SchemaField("is_active","BOOL",description="Currently running"),
    ],
    "orders": [
        bigquery.SchemaField("order_id","STRING",mode="REQUIRED",description="Unique order ID"),
        bigquery.SchemaField("customer_id","STRING",description="FK to customers"),
        bigquery.SchemaField("store_id","STRING",description="FK to stores"),
        bigquery.SchemaField("order_date","DATE",description="Date placed"),
        bigquery.SchemaField("order_total","FLOAT64",description="Total value USD"),
        bigquery.SchemaField("status","STRING",description="completed, pending, cancelled, refunded"),
        bigquery.SchemaField("promo_id","STRING",description="FK to promotions (null if none)"),
        bigquery.SchemaField("channel","STRING",description="online, in_store"),
    ],
    "order_items": [
        bigquery.SchemaField("item_id","STRING",mode="REQUIRED",description="Unique line item ID"),
        bigquery.SchemaField("order_id","STRING",description="FK to orders"),
        bigquery.SchemaField("product_id","STRING",description="FK to products"),
        bigquery.SchemaField("quantity","INT64",description="Units"),
        bigquery.SchemaField("unit_price","FLOAT64",description="Actual price charged"),
        bigquery.SchemaField("discount_amount","FLOAT64",description="Discount in USD"),
        bigquery.SchemaField("line_total","FLOAT64",description="Net line total"),
    ],
    "web_events": [
        bigquery.SchemaField("event_id","STRING",mode="REQUIRED",description="Unique event ID"),
        bigquery.SchemaField("customer_id","STRING",description="FK to customers (null=anon)"),
        bigquery.SchemaField("session_id","STRING",description="Session ID"),
        bigquery.SchemaField("event_type","STRING",description="page_view, click, add_to_cart, purchase, signup"),
        bigquery.SchemaField("page_url","STRING",description="Page URL"),
        bigquery.SchemaField("event_timestamp","TIMESTAMP",description="When"),
        bigquery.SchemaField("utm_source","STRING",description="UTM source"),
        bigquery.SchemaField("utm_campaign","STRING",description="UTM campaign"),
        bigquery.SchemaField("device_type","STRING",description="desktop, mobile, tablet"),
        bigquery.SchemaField("referrer_domain","STRING",description="Referring domain"),
    ],
    "sales_targets": [
        bigquery.SchemaField("target_id","STRING",mode="REQUIRED",description="Unique target ID"),
        bigquery.SchemaField("store_id","STRING",description="FK to stores"),
        bigquery.SchemaField("category","STRING",description="Product category"),
        bigquery.SchemaField("target_month","DATE",description="First day of target month"),
        bigquery.SchemaField("target_revenue","FLOAT64",description="Revenue target USD"),
        bigquery.SchemaField("target_units","INT64",description="Unit sales target"),
    ],
    "promotion_products": [
        bigquery.SchemaField("promo_product_id","STRING",mode="REQUIRED",description="Unique bridge row ID"),
        bigquery.SchemaField("promo_id","STRING",description="FK to promotions"),
        bigquery.SchemaField("product_id","STRING",description="FK to products (null if category-level)"),
        bigquery.SchemaField("category","STRING",description="Target category"),
        bigquery.SchemaField("subcategory","STRING",description="Target subcategory (null if category-level)"),
        bigquery.SchemaField("scope","STRING",description="category or product"),
    ],
}

DESCRIPTIONS = {
    "stores": "Physical and online store locations with regional and capacity details",
    "customers": "Customer master data with demographics, loyalty tiers, and acquisition info",
    "products": "Product catalog with categories, brands, pricing, and lifecycle stages",
    "promotions": "Marketing promotions with discount details and date ranges. Use promotion_products bridge table for proper product/category targeting joins",
    "orders": "Order headers with store, customer, and promotion references",
    "order_items": "Line-level order detail with per-item pricing and discounts",
    "web_events": "Clickstream and digital engagement events across all channels",
    "sales_targets": "Monthly revenue and unit targets by store and product category",
    "promotion_products": "Bridge table linking promotions to targeted products and categories",
}

# ─── Create Tables ───
for name, schema in SCHEMAS.items():
    ref = bigquery.Table(f"{PROJECT}.{DATASET}.{name}", schema=schema)
    ref.description = DESCRIPTIONS[name]
    client.delete_table(ref, not_found_ok=True)
    client.create_table(ref)
    print(f"  Created {name}")


# ═══════════════════════════════════════════════════════
# GENERATE DATA WITH SCENARIO PATTERNS
# ═══════════════════════════════════════════════════════

# ─── Stores (20) ───
CITIES = {"London":"London","South East":"Brighton","Midlands":"Birmingham",
          "North West":"Manchester","Scotland":"Edinburgh","Wales":"Cardiff"}
stores = []
store_meta = [
    ("STORE-001","London Flagship","London","London","flagship",15000),
    ("STORE-002","London Standard","London","London","standard",8000),
    ("STORE-003","London Outlet","London","London","outlet",5000),
    ("STORE-004","Brighton Outlet","South East","Brighton","outlet",5000),
    ("STORE-005","Brighton Standard","South East","Brighton","standard",8000),
    ("STORE-006","Guildford Standard","South East","Guildford","standard",6000),
    ("STORE-007","Birmingham Standard","Midlands","Birmingham","standard",8000),
    ("STORE-008","Birmingham Flagship","Midlands","Birmingham","flagship",12000),
    ("STORE-009","Coventry Outlet","Midlands","Coventry","outlet",4000),
    ("STORE-010","Manchester Flagship","North West","Manchester","flagship",14000),
    ("STORE-011","Manchester Standard","North West","Manchester","standard",7000),
    ("STORE-012","Liverpool Outlet","North West","Liverpool","outlet",5000),
    ("STORE-013","Edinburgh Flagship","Scotland","Edinburgh","flagship",10000),
    ("STORE-014","Edinburgh Standard","Scotland","Edinburgh","standard",6000),
    ("STORE-015","Glasgow Outlet","Scotland","Glasgow","outlet",4500),
    ("STORE-016","Cardiff Flagship","Wales","Cardiff","flagship",9000),
    ("STORE-017","Cardiff Standard","Wales","Cardiff","standard",5500),
    ("STORE-018","Swansea Outlet","Wales","Swansea","outlet",3500),
    ("STORE-ONL-LON","Online London","London","Online","online",0),
    ("STORE-ONL-NAT","Online National","London","Online","online",0),
]
for sid, name, region, city, stype, cap in store_meta:
    stores.append({"store_id":sid,"store_name":name,"region":region,"city":city,
                   "store_type":stype,"opened_date":"2019-01-01",
                   "capacity_sqft":cap,"manager_name":f"Manager {sid}","is_active":True})
print(f"  {len(stores)} stores")


# ─── Products (100) with specific scenario products ───
products = []
pid = 1
for cat, info in CATEGORIES.items():
    for sub in info["subs"]:
        for brand in random.sample(BRANDS, min(3, len(BRANDS))):
            cost = round(random.uniform(*info["price_range"]) * 0.4, 2)
            price = round(cost / (1 - random.uniform(*info["margin_range"])), 2)
            launch = rand_date(date(2021,1,1), date(2025,6,1))
            is_disc = False
            stage = "mature"

            # Q5: specific discontinued product
            if cat == "Accessories" and sub == "Cables" and brand == "SwiftGear":
                products.append({
                    "product_id": "PROD-0045", "product_name": "SwiftGear USB-C Cable Pro",
                    "category": "Accessories", "subcategory": "Cables", "brand": "SwiftGear",
                    "list_price": 24.99, "cost": 8.50,
                    "launch_date": "2022-01-15", "is_discontinued": True,
                    "lifecycle_stage": "decline"})
                products.append({
                    "product_id": "PROD-0089", "product_name": "SwiftGear USB-C Cable V2",
                    "category": "Accessories", "subcategory": "Cables", "brand": "SwiftGear",
                    "list_price": 29.99, "cost": 12.00,
                    "launch_date": "2025-04-15", "is_discontinued": False,
                    "lifecycle_stage": "new"})
                pid += 2
                continue

            products.append({
                "product_id": f"PROD-{pid:04d}",
                "product_name": f"{brand} {sub} {cat[0]}{pid}",
                "category": cat, "subcategory": sub, "brand": brand,
                "list_price": price, "cost": cost,
                "launch_date": launch.isoformat(),
                "is_discontinued": is_disc, "lifecycle_stage": stage})
            pid += 1
            if len(products) >= 100: break
        if len(products) >= 100: break
    if len(products) >= 100: break

# Pad to 100
while len(products) < 100:
    cat = random.choice(list(CATEGORIES.keys()))
    info = CATEGORIES[cat]
    sub = random.choice(info["subs"])
    cost = round(random.uniform(*info["price_range"]) * 0.4, 2)
    price = round(cost / (1 - random.uniform(*info["margin_range"])), 2)
    products.append({
        "product_id": f"PROD-{len(products)+1:04d}",
        "product_name": f"{random.choice(BRANDS)} {sub} X{len(products)}",
        "category": cat, "subcategory": sub, "brand": random.choice(BRANDS),
        "list_price": price, "cost": cost,
        "launch_date": rand_date(date(2022,1,1),date(2025,1,1)).isoformat(),
        "is_discontinued": False, "lifecycle_stage": "mature"})

product_map = {p["product_id"]: p for p in products}
product_ids = [p["product_id"] for p in products]
electronics_prods = [p["product_id"] for p in products if p["category"]=="Electronics"]
software_analytics_prods = [p["product_id"] for p in products if p["category"]=="Software" and p["subcategory"]=="Analytics"]
accessories_prods = [p["product_id"] for p in products if p["category"]=="Accessories"]
print(f"  {len(products)} products")


# ─── Customers (1000) with Q2 churn pattern ───
customers = []
for i in range(1000):
    seg = random.choices(SEGMENTS, weights=[15, 30, 55])[0]  # More SMB
    ltv_ranges = {"enterprise":(5000,80000),"mid-market":(1000,20000),"smb":(100,5000)}
    tier = random.choices(LOYALTY, weights=[40,30,20,10])[0]

    # Q2 pattern: enterprise customers churn more
    if seg == "enterprise":
        is_active = random.random() > 0.25  # 25% churn rate
    elif seg == "mid-market":
        is_active = random.random() > 0.15  # 15% churn rate
    else:
        is_active = random.random() > 0.10  # 10% churn rate

    customers.append({
        "customer_id": f"CUST-{i+1:05d}",
        "name": f"{random.choice(FIRST)} {random.choice(LAST)}",
        "email": f"user{i}@example.com", "segment": seg,
        "acquisition_channel": random.choice(CHANNELS),
        "loyalty_tier": tier,
        "created_at": rand_ts(rand_date(date(2021,1,1),date(2025,12,1))).isoformat(),
        "country": random.choice(COUNTRIES),
        "preferred_store_id": random.choice(STORE_IDS),
        "lifetime_value": round(random.uniform(*ltv_ranges[seg]), 2),
        "is_active": is_active})
cust_ids = [c["customer_id"] for c in customers]
enterprise_custs = [c["customer_id"] for c in customers if c["segment"]=="enterprise"]
gold_plat_custs = [c["customer_id"] for c in customers if c["loyalty_tier"] in ("gold","platinum")]
print(f"  {len(customers)} customers ({sum(1 for c in customers if not c['is_active'])} inactive)")


# ─── Promotions (50+) with Q3 Black Friday scenario ───
promos = []
promo_types = ["discount","bogo","bundle","clearance"]
for i in range(45):
    start = rand_date(date(2024,1,1), date(2026,2,1))
    duration = random.choice([7,14,21,30])
    promos.append({
        "promo_id": f"PROMO-{i+1:03d}",
        "promo_name": f"{random.choice(['Flash','Super','Mega','Spring','Summer'])} {random.choice(['Sale','Deal','Offer'])} {i+1}",
        "promo_type": random.choice(promo_types),
        "discount_pct": random.choice([5,10,15,20,25,30]),
        "start_date": start.isoformat(),
        "end_date": (start + timedelta(days=duration)).isoformat(),
        "target_category": random.choice(list(CATEGORIES.keys()) + [None]*3),
        "target_region": random.choice(["London","Midlands","North West",None,None]),
        "budget_usd": round(random.uniform(1000, 50000), 2),
        "is_active": False})

# Q3: 2024 Black Friday (strong)
promos.append({
    "promo_id": "PROMO-BF2024", "promo_name": "Black Friday 2024 Mega Sale",
    "promo_type": "discount", "discount_pct": 30,
    "start_date": "2024-11-29", "end_date": "2024-12-02",
    "target_category": None, "target_region": None,
    "budget_usd": 100000, "is_active": False})

# Q3: 2025 Black Friday (underperforming)
promos.append({
    "promo_id": "PROMO-BF2025", "promo_name": "Black Friday 2025 Sale",
    "promo_type": "discount", "discount_pct": 30,
    "start_date": "2025-11-28", "end_date": "2025-12-01",
    "target_category": None, "target_region": None,
    "budget_usd": 100000, "is_active": False})

# Q3: Overlapping clearance (problem)
promos.append({
    "promo_id": "PROMO-CLR2025", "promo_name": "Electronics Clearance Nov 2025",
    "promo_type": "clearance", "discount_pct": 20,
    "start_date": "2025-11-20", "end_date": "2025-12-05",
    "target_category": "Electronics", "target_region": None,
    "budget_usd": 15000, "is_active": False})

# Q5: Accessories promo (strong promo despite decline)
promos.append({
    "promo_id": "PROMO-ACC01", "promo_name": "Accessories Spring Special",
    "promo_type": "discount", "discount_pct": 25,
    "start_date": "2025-04-01", "end_date": "2025-04-30",
    "target_category": "Accessories", "target_region": None,
    "budget_usd": 20000, "is_active": False})
promos.append({
    "promo_id": "PROMO-ACC02", "promo_name": "Accessories Summer Blowout",
    "promo_type": "discount", "discount_pct": 30,
    "start_date": "2025-06-01", "end_date": "2025-06-30",
    "target_category": "Accessories", "target_region": None,
    "budget_usd": 25000, "is_active": False})

promo_ids = [p["promo_id"] for p in promos]
promo_map = {p["promo_id"]: p for p in promos}
print(f"  {len(promos)} promotions")


# ─── Promotion Products bridge table ───
print("Generating promotion_products bridge table...")
promo_products = []
pp_id = 1
all_cats = list(CATEGORIES.keys())

for p in promos:
    pid = p["promo_id"]
    tgt_cat = p.get("target_category")

    if tgt_cat:
        # Category-level targeting: one row per targeted category
        promo_products.append({
            "promo_product_id": f"PP-{pp_id:05d}",
            "promo_id": pid,
            "product_id": None,
            "category": tgt_cat,
            "subcategory": None,
            "scope": "category"})
        pp_id += 1

        # Also link to specific products in that category for product-level promos
        if p["promo_type"] == "clearance":
            # Clearance promos target specific products (mature/decline lifecycle)
            for prod in products:
                if prod["category"] == tgt_cat and prod["lifecycle_stage"] in ("mature", "decline"):
                    promo_products.append({
                        "promo_product_id": f"PP-{pp_id:05d}",
                        "promo_id": pid,
                        "product_id": prod["product_id"],
                        "category": tgt_cat,
                        "subcategory": prod["subcategory"],
                        "scope": "product"})
                    pp_id += 1
    else:
        # All-category promos: one row per category
        for cat in all_cats:
            promo_products.append({
                "promo_product_id": f"PP-{pp_id:05d}",
                "promo_id": pid,
                "product_id": None,
                "category": cat,
                "subcategory": None,
                "scope": "category"})
            pp_id += 1

print(f"  {len(promo_products)} promotion_product bridge rows")


# ─── Orders + Order Items (25000 orders) with ALL scenario patterns ───
print("Generating orders + items with scenario patterns...")
orders = []
order_items = []
item_counter = 1

start_d = date(2024, 1, 1)
end_d = date(2026, 3, 15)

for i in range(25000):
    d = rand_date(start_d, end_d)
    store = random.choice(STORE_IDS)

    # Q4: Manchester grows, Birmingham declines after Aug 2025
    if d >= date(2025, 8, 1):
        if random.random() < 0.08:
            store = MANCHESTER_FLAGSHIP  # Boost Manchester
        if store == BIRMINGHAM_STANDARD and random.random() < 0.35:
            store = random.choice([s for s in STORE_IDS if s != BIRMINGHAM_STANDARD])

    # Find active promos
    active_promos = [p for p in promos if p["start_date"] <= d.isoformat() <= p["end_date"]]
    promo = random.choice(active_promos) if active_promos and random.random() > 0.6 else None

    # Q6: boost promo usage for gold/platinum in Q3 2025
    cust = random.choice(cust_ids)
    if date(2025,7,1) <= d <= date(2025,9,30) and cust in gold_plat_custs and active_promos:
        promo = random.choice(active_promos)  # Always use promo for loyalty members in Q3

    num_items = random.choices([1,2,3,4,5], weights=[40,30,15,10,5])[0]
    order_total = 0
    oid = f"ORD-{i+1:06d}"
    status = random.choice(ORDER_STATUSES)

    for _ in range(num_items):
        prod_id = random.choice(product_ids)
        prod = product_map[prod_id]

        # Q1: After Feb 2025, reduce Electronics orders for TechPro/SwiftGear
        if d >= date(2025, 2, 15) and d <= date(2025, 5, 1):
            if prod["category"] == "Electronics" and prod["brand"] in ("TechPro", "SwiftGear"):
                if random.random() < 0.7:  # 70% chance to skip this product
                    prod_id = random.choice([p for p in product_ids if product_map[p]["category"] != "Electronics"])
                    prod = product_map[prod_id]
                else:
                    status = random.choice(["cancelled","cancelled","completed"])  # Higher cancel rate

        # Q5: After Apr 2025, PROD-0045 (discontinued cable) gets zero orders
        if d >= date(2025, 4, 15) and prod_id == "PROD-0045":
            prod_id = "PROD-0089"  # Replacement product
            prod = product_map.get(prod_id, prod)

        # Q5: Reduce Accessories volume despite promos after Apr 2025
        if d >= date(2025, 4, 1) and prod["category"] == "Accessories":
            if random.random() < 0.4:  # 40% chance to switch away
                prod_id = random.choice([p for p in product_ids if product_map[p]["category"] != "Accessories"])
                prod = product_map[prod_id]

        qty = random.randint(1, 5)
        base_price = prod["list_price"]

        # Q7: Software Analytics price cut from Mar 2025 for new orders
        if d >= date(2025, 3, 1) and prod["subcategory"] == "Analytics":
            base_price = base_price * 0.80  # 20% price reduction

        discount = 0
        if promo:
            disc_pct = promo["discount_pct"]
            if promo.get("target_category") is None or promo["target_category"] == prod["category"]:
                discount = round(base_price * qty * disc_pct / 100, 2)

        line = round(base_price * qty - discount, 2)
        order_total += line

        order_items.append({
            "item_id": f"ITEM-{item_counter:07d}",
            "order_id": oid, "product_id": prod_id,
            "quantity": qty, "unit_price": round(base_price, 2),
            "discount_amount": discount, "line_total": max(line, 0)})
        item_counter += 1

    orders.append({
        "order_id": oid, "customer_id": cust,
        "store_id": store, "order_date": d.isoformat(),
        "order_total": round(order_total, 2), "status": status,
        "promo_id": promo["promo_id"] if promo else None,
        "channel": "online" if "ONL" in store else random.choice(["in_store","online"])})

print(f"  {len(orders)} orders, {len(order_items)} items")


# ─── Web Events (50000) ───
print("Generating web events...")
events = []
evt_types = ["page_view","click","add_to_cart","purchase","signup"]
for i in range(50000):
    d = rand_date(start_d, end_d)
    cid = random.choice(cust_ids) if random.random() > 0.3 else None
    events.append({
        "event_id": f"EVT-{i+1:06d}",
        "customer_id": cid,
        "session_id": f"SES-{random.randint(1,15000):06d}",
        "event_type": random.choices(evt_types, weights=[45,25,15,10,5])[0],
        "page_url": f"https://shop.example.com/{random.choice(['','products/','cart/','checkout/','account/'])}",
        "event_timestamp": rand_ts(d).isoformat(),
        "utm_source": random.choice(UTM_SOURCES),
        "utm_campaign": random.choice(UTM_CAMPAIGNS),
        "device_type": random.choice(DEVICE_TYPES),
        "referrer_domain": random.choice(["google.com","facebook.com","linkedin.com","direct",None])})
print(f"  {len(events)} web events")


# ─── Sales Targets ───
print("Generating sales targets...")
targets = []
tid = 1
top_stores = [s["store_id"] for s in stores[:10]]
for yr in [2024, 2025, 2026]:
    months = range(1,13) if yr < 2026 else range(1,4)
    for month in months:
        for store_id in top_stores:
            for cat in CATEGORIES:
                base = random.uniform(10000, 50000)
                targets.append({
                    "target_id": f"TGT-{tid:05d}",
                    "store_id": store_id, "category": cat,
                    "target_month": date(yr, month, 1).isoformat(),
                    "target_revenue": round(base, 2),
                    "target_units": random.randint(50, 500)})
                tid += 1
print(f"  {len(targets)} targets")


# ─── Load into BigQuery ───
def load_rows(table, rows, batch_size=1000):
    ref = f"{PROJECT}.{DATASET}.{table}"
    for i in range(0, len(rows), batch_size):
        errs = client.insert_rows_json(ref, rows[i:i+batch_size])
        if errs:
            print(f"  ERR {table} batch {i}: {errs[:2]}")
    print(f"  Loaded {len(rows)} → {table}")

print("\nLoading data...")
load_rows("stores", stores)
load_rows("products", products)
load_rows("customers", customers)
load_rows("promotions", promos)
load_rows("promotion_products", promo_products)
load_rows("orders", orders)
load_rows("order_items", order_items)
load_rows("web_events", events)
load_rows("sales_targets", targets)


# ─── Verify ───
print("\n=== Verification ===")
for t in SCHEMAS:
    r = list(client.query(f"SELECT COUNT(*) c FROM `{PROJECT}.{DATASET}.{t}`").result())
    print(f"  {t}: {r[0].c} rows")

# Verify scenario patterns
print("\n=== Scenario Pattern Checks ===")

# Q1: Electronics orders should drop after Feb 2025
for row in client.query(f"""
    SELECT IF(o.order_date < '2025-02-15', 'before_fire', 'after_fire') AS period,
           COUNT(DISTINCT oi.item_id) AS items
    FROM `{PROJECT}.{DATASET}.orders` o
    JOIN `{PROJECT}.{DATASET}.order_items` oi ON o.order_id=oi.order_id
    JOIN `{PROJECT}.{DATASET}.products` p ON oi.product_id=p.product_id
    WHERE p.category='Electronics' AND p.brand IN ('TechPro','SwiftGear')
      AND o.order_date BETWEEN '2024-11-01' AND '2025-05-01'
    GROUP BY 1
""").result():
    print(f"  Q1 Electronics ({row.period}): {row.items} items")

# Q2: Enterprise churn rate should be higher
for row in client.query(f"""
    SELECT segment, COUNT(*) AS total, COUNTIF(is_active=false) AS churned,
           ROUND(SAFE_DIVIDE(COUNTIF(is_active=false), COUNT(*))*100, 1) AS churn_pct
    FROM `{PROJECT}.{DATASET}.customers` GROUP BY 1 ORDER BY churn_pct DESC
""").result():
    print(f"  Q2 Churn: {row.segment} = {row.churn_pct}%")

# Q4: Manchester vs Birmingham after Aug 2025
for row in client.query(f"""
    SELECT store_id, COUNT(*) AS orders, ROUND(SUM(order_total),0) AS revenue
    FROM `{PROJECT}.{DATASET}.orders`
    WHERE store_id IN ('STORE-010','STORE-007') AND order_date >= '2025-08-01'
    GROUP BY 1
""").result():
    print(f"  Q4 Store {row.store_id}: {row.orders} orders, ${row.revenue}")

print("\n=== Done! Run semantic_layer_setup.py next ===")
