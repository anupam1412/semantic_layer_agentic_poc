"""
Test script to debug VectorSearch cache population.
Run from the semantic_layer_agentic_poc directory.
"""

import os
import sys

# Ensure we're in the right directory
print(f"Working directory: {os.getcwd()}")
print(f"Python path: {sys.path[:3]}")
print()

# Test 1: Can we import KnowledgeGraph?
print("=" * 60)
print("TEST 1: Import KnowledgeGraph")
print("=" * 60)
try:
    from knowledge_graph import KnowledgeGraph
    kg = KnowledgeGraph()
    print("✅ KnowledgeGraph imported and initialized")
except Exception as e:
    print(f"❌ Failed: {e}")
    sys.exit(1)

# Test 2: Check Neo4j connection
print()
print("=" * 60)
print("TEST 2: Neo4j Connection")
print("=" * 60)
try:
    tables = kg.all_tables()
    print(f"✅ all_tables(): {len(tables)} tables")
    for t in tables[:3]:
        print(f"   - {t}")
except Exception as e:
    print(f"❌ all_tables() failed: {e}")

try:
    kpis = kg.get_all_kpis()
    print(f"✅ get_all_kpis(): {len(kpis)} KPIs")
    for k in kpis[:3]:
        print(f"   - {k.get('name', 'unnamed')}")
except Exception as e:
    print(f"❌ get_all_kpis() failed: {e}")

try:
    concepts = kg.get_all_concepts()
    print(f"✅ get_all_concepts(): {len(concepts)} concepts")
    for c in concepts[:3]:
        print(f"   - {c.get('name', 'unnamed')}")
except Exception as e:
    print(f"❌ get_all_concepts() failed: {e}")

try:
    examples = kg.get_similar_examples([""], limit=10)
    print(f"✅ get_similar_examples(): {len(examples)} examples")
    for ex in examples[:2]:
        print(f"   - {ex.get('question', 'no question')[:50]}...")
except Exception as e:
    print(f"❌ get_similar_examples() failed: {e}")

# Test 3: VectorSearch cache population
print()
print("=" * 60)
print("TEST 3: VectorSearch Cache Population")
print("=" * 60)
try:
    from vector_search import VectorSearch
    vs = VectorSearch()
    print(f"✅ VectorSearch created, _meta has {len(vs._meta)} items")
    
    # Force cache population
    print("Calling _ensure_meta_loaded()...")
    vs._ensure_meta_loaded()
    print(f"✅ After _ensure_meta_loaded(), _meta has {len(vs._meta)} items")
    
except Exception as e:
    import traceback
    print(f"❌ VectorSearch failed: {e}")
    traceback.print_exc()

# Test 4: Search functionality
print()
print("=" * 60)
print("TEST 4: Search Functionality")
print("=" * 60)
try:
    from vector_search import VectorSearch
    vs = VectorSearch()
    
    print("Searching for 'call drop rate'...")
    tables = vs.search_tables("call drop rate", k=3)
    print(f"  Tables found: {len(tables)}")
    for t in tables:
        print(f"    - {t.get('name', t.get('fqn', 'unknown'))}")
    
    kpis = vs.search_kpis("call drop rate", k=3)
    print(f"  KPIs found: {len(kpis)}")
    for k in kpis:
        print(f"    - {k.get('kpi_name', 'unknown')}")
    
    concepts = vs.search_concepts("call drop interference", k=3)
    print(f"  Concepts found: {len(concepts)}")
    for c in concepts:
        print(f"    - {c.get('concept', 'unknown')}")
        
except Exception as e:
    import traceback
    print(f"❌ Search failed: {e}")
    traceback.print_exc()

print()
print("=" * 60)
print("DONE")
print("=" * 60)
