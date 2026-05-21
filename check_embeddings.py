"""
check_embeddings.py — Embedding & Vector Index Verification
============================================================
Run from inside the project folder:

    python check_embeddings.py

Checks (in order):
  1. Neo4j connection
  2. sentence-transformers model loads correctly
  3. Node embedding coverage (all 4 node types)
  4. Zero-vector detection (flags silent setup failures)
  5. Vector index existence and state (ONLINE / POPULATING)
  6. Live end-to-end similarity search on all 4 indexes
  7. Keyword fallback smoke test
"""

import os
import sys

# ─── Load _env without requiring python-dotenv ────────────────────────────────
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
else:
    print(f"  WARNING: _env not found at {env_path} — using existing env vars")

# ─── Config from env ──────────────────────────────────────────────────────────
NEO4J_URI      = os.getenv("NEO4J_URI",      "bolt://localhost:7687")
NEO4J_USER     = os.getenv("NEO4J_USER",     "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-mpnet-base-v2")

PASS = "  ✓"
FAIL = "  ✗"
WARN = "  !"

# ─── 1. Neo4j connection ──────────────────────────────────────────────────────
print("\n=== 1. Neo4j connection ===")
try:
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session() as s:
        s.run("RETURN 1").single()
    print(f"{PASS} Connected to {NEO4J_URI}")
except Exception as e:
    print(f"{FAIL} Cannot connect to Neo4j: {e}")
    print("      Check NEO4J_URI in _env and that Neo4j is running (sudo systemctl start neo4j in WSL)")
    sys.exit(1)

# ─── 2. Embedding model ───────────────────────────────────────────────────────
print(f"\n=== 2. Embedding model ({EMBEDDING_MODEL}) ===")
try:
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(EMBEDDING_MODEL)
    test_vec = model.encode(["test sentence"], convert_to_numpy=True, show_progress_bar=False)[0]
    print(f"{PASS} Model loaded — produces {len(test_vec)}-dim vectors")
    if len(test_vec) != 768:
        print(f"{WARN} Expected 768 dimensions, got {len(test_vec)}.")
        print("      Neo4j vector indexes were created for 768-dim. You will need to")
        print("      drop and recreate them if the dimension changed.")
except ImportError:
    print(f"{FAIL} sentence-transformers not installed.")
    print("      Run: pip install sentence-transformers")
    sys.exit(1)
except Exception as e:
    print(f"{FAIL} Model failed to load: {e}")
    print(f"      Check EMBEDDING_MODEL in _env. Current value: '{EMBEDDING_MODEL}'")
    sys.exit(1)

# ─── 3. Node embedding coverage ───────────────────────────────────────────────
print("\n=== 3. Node embedding coverage ===")
EXPECTED = {
    "Table":           9,
    "KPI":            14,
    "BusinessConcept": 13,
    "QueryExample":   11,
}
coverage_ok = True
with driver.session() as s:
    for label, expected_count in EXPECTED.items():
        total    = s.run(f"MATCH (n:{label}) RETURN count(n) AS c").single()["c"]
        embedded = s.run(
            f"MATCH (n:{label}) WHERE n.embedding IS NOT NULL RETURN count(n) AS c"
        ).single()["c"]
        missing  = total - embedded
        icon = PASS if embedded == total else FAIL
        if embedded != total:
            coverage_ok = False
        hint = f" ← {missing} missing — re-run semantic_layer_setup.py" if missing else ""
        print(f"{icon} {label}: {embedded}/{total} nodes have embeddings{hint}")

if not coverage_ok:
    print(f"\n{WARN} Some nodes are missing embeddings.")
    print("      Re-run: python semantic_layer_setup.py")

# ─── 4. Zero-vector detection ─────────────────────────────────────────────────
print("\n=== 4. Zero-vector check ===")
zero_found = False
with driver.session() as s:
    for label in EXPECTED:
        zero_count = s.run(
            f"MATCH (n:{label}) "
            f"WHERE n.embedding IS NOT NULL AND n.embedding[0] = 0.0 "
            f"RETURN count(n) AS c"
        ).single()["c"]
        if zero_count > 0:
            zero_found = True
            print(f"{FAIL} {label}: {zero_count} nodes have zero-vectors (embedding model failed silently during setup)")
        else:
            print(f"{PASS} {label}: no zero-vectors")

if zero_found:
    print(f"\n{WARN} Zero-vectors mean setup ran but the embedding model wasn't working.")
    print("      Fix EMBEDDING_MODEL in _env, then re-run: python semantic_layer_setup.py")

# ─── 5. Vector index state ────────────────────────────────────────────────────
print("\n=== 5. Vector index state ===")
EXPECTED_INDEXES = {
    "table_embeddings",
    "kpi_embeddings",
    "concept_embeddings",
    "example_embeddings",
}
found_indexes = {}
with driver.session() as s:
    try:
        rows = s.run("SHOW VECTOR INDEXES")
        for r in rows:
            name = r["name"]
            if name in EXPECTED_INDEXES:
                found_indexes[name] = {
                    "state": r["state"],
                    "pct":   r.get("populationPercent") or 0.0,
                }
    except Exception as e:
        print(f"{FAIL} Could not query vector indexes: {e}")
        print("      Neo4j 5.11+ required for native vector indexes")

for idx in sorted(EXPECTED_INDEXES):
    if idx in found_indexes:
        info  = found_indexes[idx]
        state = info["state"]
        pct   = info["pct"]
        icon  = PASS if state == "ONLINE" and pct >= 99.0 else WARN
        print(f"{icon} {idx}: {state} ({pct:.0f}% populated)")
        if state == "POPULATING":
            print(f"       ↳ Still building — wait 15 seconds and re-run this script")
        elif state != "ONLINE":
            print(f"       ↳ Unexpected state '{state}' — check Neo4j logs")
    else:
        print(f"{FAIL} {idx}: NOT FOUND")
        print(f"       ↳ Re-run semantic_layer_setup.py to create it")

# ─── 6. Live end-to-end similarity search ────────────────────────────────────
print("\n=== 6. Live similarity search ===")

# Import VectorSearch from the project
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from knowledge_graph import KnowledgeGraph
    from vector_search import VectorSearch
    kg = KnowledgeGraph()
    vs = VectorSearch(kg=kg)
except Exception as e:
    print(f"{FAIL} Could not import project modules: {e}")
    driver.close()
    sys.exit(1)

SEARCH_TESTS = [
    (
        "tables",
        vs.search_tables,
        "revenue by store last month",
        "fqn",
        ["orders", "stores"],          # expected FQN substrings in top results
    ),
    (
        "kpis",
        vs.search_kpis,
        "gross margin percentage",
        "kpi_name",
        ["gross_margin", "revenue"],
    ),
    (
        "concepts",
        vs.search_concepts,
        "why are sales declining",
        "concept",
        ["revenue decline", "promotion impact"],
    ),
    (
        "examples",
        vs.search_examples,
        "compare store performance year over year",
        "nl_query",
        ["store", "revenue"],
    ),
]

search_ok = True
for index_name, search_fn, query, key, expected_keywords in SEARCH_TESTS:
    print(f"\n  [{index_name}] query: \"{query}\"")
    try:
        results = search_fn(query, k=3)
        if not results:
            print(f"  {FAIL} No results returned — index may be empty")
            search_ok = False
            continue
        for i, r in enumerate(results):
            val   = r.get(key, "") or ""
            score = r.get("score", 0.0)
            icon  = PASS if score > 0.3 else WARN
            print(f"  {icon} #{i+1} {val[:65]:<65}  score: {score:.4f}")
        # Check top result contains at least one expected keyword
        top_val = (results[0].get(key) or "").lower()
        if not any(kw.lower() in top_val for kw in expected_keywords):
            print(f"  {WARN} Top result doesn't match expected keywords {expected_keywords}")
            print(f"       ↳ This may indicate keyword fallback is running instead of vector search")
    except Exception as e:
        print(f"  {FAIL} Search failed: {e}")
        search_ok = False

# ─── 7. Keyword fallback smoke test ───────────────────────────────────────────
print("\n=== 7. Keyword fallback smoke test ===")
print("  (Checks the fallback works correctly if vector search ever fails)")
try:
    results = vs._keyword_fallback("table_embeddings", "orders revenue", k=3)
    if results:
        top = results[0].get("name") or results[0].get("fqn") or "unknown"
        print(f"{PASS} Fallback returned {len(results)} results — top: {top}")
    else:
        print(f"{WARN} Fallback returned no results — emb_doc may not be set on nodes")
except Exception as e:
    print(f"{FAIL} Fallback error: {e}")

# ─── Summary ──────────────────────────────────────────────────────────────────
print("\n=== Summary ===")
all_indexes_online = all(
    found_indexes.get(idx, {}).get("state") == "ONLINE"
    for idx in EXPECTED_INDEXES
)
if coverage_ok and not zero_found and all_indexes_online and search_ok:
    print(f"{PASS} All checks passed — embeddings are working correctly.")
    print("      You can now run: cd .. && adk web --port 8001")
else:
    print(f"{WARN} Some checks failed — review the output above before running adk web.")

kg.close()
driver.close()