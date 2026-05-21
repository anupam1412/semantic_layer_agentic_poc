"""
ADK Semantic Layer — Simplified Domain-Agnostic Architecture
=============================================================
Consolidated agent architecture with 4 agents (down from 8).
Learning agent disabled to reduce complexity.

Agent tree:
  Orchestrator (root)         — sequence 3 phases
    ├── TriageAgent           — assess knowledge, gate pipeline
    ├── PlannerAgent          — classify question, build sub-questions
    ├── InvestigatorAgent     — execute sub-questions, generate SQL, analyze
    └── SynthesisAgent        — produce final narrative

Three stores:
  Neo4j    = Knowledge graph (schema, KPIs, concepts, causal edges)
  BigQuery = Transactional data
  Local    = Sentence-Transformers embeddings (offline)

Run: adk web  (from parent directory)
"""

import os
import json
import logging
from typing import Optional

from google.adk.agents import Agent, SequentialAgent
from google.genai import types
from dotenv import load_dotenv
load_dotenv(".env")
try:
    from .knowledge_graph import KnowledgeGraph
    from .vector_search import VectorSearch
    from .bq_executor import BQExecutor
except ImportError:
    from knowledge_graph import KnowledgeGraph
    from vector_search import VectorSearch
    from bq_executor import BQExecutor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("agentic_sl")

MODEL = os.getenv("GENERATIVE_MODEL", "gemini-2.5-flash")

# ─── Generation configs for token optimization ───
# Disable thinking for simple routing/formatting agents (saves tokens, prevents stalls)
NO_THINKING = types.GenerateContentConfig(
    thinking_config=types.ThinkingConfig(thinking_budget=0),
    temperature=0.1,  # Low temp for deterministic output
)

# Enable thinking for complex reasoning (SQL generation, analysis)
WITH_THINKING = types.GenerateContentConfig(
    thinking_config=types.ThinkingConfig(thinking_budget=1024),  # Limited thinking
    temperature=0.2,
)

# ─── Lazy store singletons ───
_kg: Optional[KnowledgeGraph] = None
_vs: Optional[VectorSearch] = None
_bq: Optional[BQExecutor] = None


def _get_kg() -> KnowledgeGraph:
    global _kg
    if _kg is None:
        _kg = KnowledgeGraph()
    return _kg


def _get_vs() -> VectorSearch:
    global _vs
    if _vs is None:
        _vs = VectorSearch()
    return _vs


def _get_bq() -> BQExecutor:
    global _bq
    if _bq is None:
        _bq = BQExecutor()
    return _bq





# ═══════════════════════════════════════════════
# TOOL FUNCTIONS
# ═══════════════════════════════════════════════


def assess_knowledge(question: str) -> dict:
    """Scan knowledge graph to determine if question is answerable.
    
    Returns: status, coverage, matched tables/KPIs/concepts, causal chains.
    
    Calls:
      - VectorSearch.search_tables(q, k) -> list of {fqn, name, doc, score}
      - VectorSearch.search_kpis(q, k) -> list of {kpi_name, doc}
      - VectorSearch.search_concepts(q, k) -> list of {concept, doc}
      - VectorSearch.search_examples(q, k) -> list of {nl_query, sql, doc}
      - KnowledgeGraph.get_table_context(fqns) -> dict {fqn: {name, desc, columns, kpis}}
      - KnowledgeGraph.get_joins(fqns) -> list of {table1, table2, join_condition}
      - KnowledgeGraph.get_causal_map() -> list of {source, target, mechanism}
      - KnowledgeGraph.get_causal_chain(concept_name) -> {concept, caused_by, affects}
      - KnowledgeGraph.get_kpi(name) -> {name, expression, description, thresholds, dimensions}
      - KnowledgeGraph.get_domain_context_for_question(q) -> dict of domain context
    """
    print(f"\n[TRIAGE] ════════════════════════════════════════════════════════")
    print(f"[TRIAGE] Question: {question}")
    print(f"[TRIAGE] ════════════════════════════════════════════════════════")
    
    kg = _get_kg()
    vs = _get_vs()

    # Search across all indexes
    tables = vs.search_tables(question, k=8)
    kpis = vs.search_kpis(question, k=5)
    concepts = vs.search_concepts(question, k=5)
    examples = vs.search_examples(question, k=5)
    
    print(f"[TRIAGE] Vector search results:")
    print(f"[TRIAGE]   Tables: {[t.get('name', '') for t in tables]}")
    print(f"[TRIAGE]   KPIs: {[k.get('kpi_name', '') for k in kpis]}")
    print(f"[TRIAGE]   Concepts: {[c.get('concept', '') for c in concepts]}")

    # Get schema context from Neo4j
    fqns = [t["fqn"] for t in tables if t.get("fqn")]
    table_context = kg.get_table_context(fqns) if fqns else {}
    joins = kg.get_joins(fqns) if fqns else []
    causal_map = kg.get_causal_map()
    
    print(f"[TRIAGE]   Causal edges: {len(causal_map)}")

    # Get causal chains for top concepts
    causal_chains = {}
    for c in concepts[:3]:
        cname = c.get("concept", "")
        if cname:
            try:
                causal_chains[cname] = kg.get_causal_chain(cname)
            except Exception:
                pass

    # Get KPI details
    kpi_details = {}
    for k in kpis:
        kname = k.get("kpi_name", "")
        if kname:
            try:
                detail = kg.get_kpi(kname)
                if detail:
                    kpi_details[kname] = detail
            except Exception:
                pass

    # Determine if diagnostic query
    q_lower = question.lower()
    is_diagnostic = any(
        w in q_lower for w in [
            "why", "reason", "cause", "explain", "driver", "root cause",
            "spike", "drop", "increase", "decrease", "decline", "degraded"
        ]
    )

    # Calculate coverage score
    scores = []
    scores.append(min(len(tables) / 3, 1.0) * 0.30)
    scores.append(min(len(kpis) / 2, 1.0) * 0.25)
    scores.append(min(len(concepts) / 2, 1.0) * 0.20)
    scores.append((min(len(causal_map) / 5, 1.0) if is_diagnostic else 1.0) * 0.15)
    scores.append(min(len(examples) / 2, 1.0) * 0.10)

    coverage = round(sum(scores), 2)
    status = (
        "ANSWERABLE" if coverage >= 0.6
        else "PARTIALLY_ANSWERABLE" if coverage >= 0.3
        else "NOT_ANSWERABLE"
    )

    print(f"[TRIAGE] → Status: {status} (coverage: {coverage:.0%}), diagnostic: {is_diagnostic}")

    # Return compact triage (saves ~2000 tokens vs full details)
    # Convert date objects to strings for JSON serialization
    return _json_safe({
        "status": status,
        "coverage": coverage,
        "is_diagnostic": is_diagnostic,
        "tables": [t.get("name", "") for t in tables[:6]],  # Just names, top 6
        "table_fqns": [t.get("fqn", "") for t in tables[:6]],
        "kpis": [k.get("kpi_name", "") for k in kpis],
        "concepts": [c.get("concept", "") for c in concepts],
        "causal_concepts": list(causal_chains.keys()),  # Just concept names
        "joins": len(joins),  # Just count
    })


def get_kpi_driver_tree(kpi_name: str) -> dict:
    """Get KPI driver hierarchy from Neo4j.
    
    Calls: KnowledgeGraph.get_kpi_driver_tree(kpi_name, depth=3)
    Returns: {kpi, drivers: [{name, description, depth}, ...]}
    """
    print(f"\n[CYPHER] get_kpi_driver_tree('{kpi_name}')")
    result = _get_kg().get_kpi_driver_tree(kpi_name)
    print(f"[CYPHER] → {len(result.get('drivers', []))} drivers found")
    return _json_safe(result)


def get_causal_chain(concept_name: str) -> dict:
    """Get causes and effects of a concept via AFFECTS edges.
    
    Calls: KnowledgeGraph.get_causal_chain(concept_name, depth=3)
    Returns: {concept, caused_by: [{concept, description}, ...], affects: [...]}
    """
    print(f"\n[CYPHER] get_causal_chain('{concept_name}')")
    result = _get_kg().get_causal_chain(concept_name)
    causes = len(result.get('caused_by', []))
    effects = len(result.get('affects', []))
    print(f"[CYPHER] → {causes} causes, {effects} effects")
    return _json_safe(result)


def get_full_causal_path(target_concept: str) -> dict:
    """Trace full path: events → concepts → AFFECTS → target.
    
    Calls: KnowledgeGraph.get_full_causal_path(target_concept, depth=3)
    Returns: {target, caused_by: [{concept, description, triggering_events}, ...]}
    """
    print(f"\n[CYPHER] get_full_causal_path('{target_concept}')")
    result = _get_kg().get_full_causal_path(target_concept)
    causes = len(result.get('caused_by', []))
    print(f"[CYPHER] → {causes} causal paths found")
    return _json_safe(result)


def get_schema_context(
    question: str,
    target_tables: str = "",
    target_kpi: str = "",
    causal_concept: str = "",
) -> dict:
    """Get schema context for SQL generation.
    
    Calls:
      - VectorSearch.search_tables(question, k=5)
      - KnowledgeGraph.get_table_context(fqns)
      - KnowledgeGraph.get_joins(fqns)
      - KnowledgeGraph.get_kpi(target_kpi)
      - KnowledgeGraph.get_causal_chain(causal_concept)
      - KnowledgeGraph.get_full_ontology_text()
    """
    print(f"\n[SCHEMA] get_schema_context()")
    print(f"[SCHEMA]   question: {question[:80]}...")
    print(f"[SCHEMA]   target_tables: {target_tables}")
    print(f"[SCHEMA]   target_kpi: {target_kpi}")
    print(f"[SCHEMA]   causal_concept: {causal_concept}")
    
    kg = _get_kg()
    vs = _get_vs()
    # Resolve location entities from Neo4j
    location_hints = kg.get_location_hints(question)
    if location_hints:
        print(f"[SCHEMA]   → Location hints: {location_hints}")
        
    # Search for relevant tables
    focused = vs.search_tables(question, k=5)
# Handle target_tables as either list or comma-separated string
    if isinstance(target_tables, list):
        extra_tables = [t.strip() for t in target_tables if t and isinstance(t, str)]
    else:
        extra_tables = [f.strip() for f in (target_tables or "").split(",") if f.strip()]

    fqns = list(set(
        [t["fqn"] for t in focused if t.get("fqn")]
        + extra_tables
    ))
    
    print(f"[SCHEMA]   → Found tables: {fqns}")
    
    # Get table context and joins
    context = kg.get_table_context(fqns) if fqns else {}
    joins = kg.get_joins(fqns) if fqns else []

    # Get KPI context if specified
    kpi_ctx = None
    if target_kpi:
        try:
            kpi_ctx = kg.get_kpi(target_kpi)
            print(f"[SCHEMA]   → KPI '{target_kpi}': {kpi_ctx.get('expression', 'N/A')[:60]}")
        except Exception:
            pass

    # Get causal context if specified
    causal = None
    if causal_concept:
        try:
            causal = kg.get_causal_chain(causal_concept)
        except Exception:
            pass

    # Return focused context only (no full ontology - saves ~5000 tokens)
    # Convert date objects to strings for JSON serialization
    return _json_safe({
        "tables": context,
        "joins": joins,
        "kpi": kpi_ctx,
        "causal": causal,
        "location_hints":location_hints,
    })


def _json_safe(obj):
    """Convert non-JSON-serializable objects to strings."""
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    elif hasattr(obj, 'isoformat'):  # date, datetime, time
        return obj.isoformat()
    elif isinstance(obj, (int, float, str, bool, type(None))):
        return obj
    else:
        return str(obj)


def execute_sql(sql: str) -> dict:
    """Validate and execute BigQuery SQL.
    
    Calls:
      - BQExecutor.validate(sql) -> (bool, str)
      - BQExecutor.execute(sql) -> {status, sql, schema, rows, total_rows, bytes_processed}
    """
    print(f"\n[SQL] ════════════════════════════════════════════════════════")
    print(f"[SQL] {sql}")
    print(f"[SQL] ════════════════════════════════════════════════════════\n")
    
    bq = _get_bq()
    ok, msg = bq.validate(sql)
    if not ok:
        print(f"[SQL] ❌ Validation failed: {msg}")
        return {"status": "error", "error": msg, "sql": sql}
    
    result = bq.execute(sql)
    row_count = len(result.get("rows", []))
    print(f"[SQL] ✅ Returned {row_count} rows")
    
    # Convert date objects to strings for JSON serialization
    return _json_safe(result)


def check_kpi_threshold(kpi_name: str, actual_value: float) -> dict:
    """Check KPI value against thresholds.
    
    Calls: KnowledgeGraph.get_kpi(kpi_name)
    Returns: {kpi, value, status (green/amber/red), thresholds}
    """
    print(f"\n[KPI] check_kpi_threshold('{kpi_name}', {actual_value})")
    
    kg = _get_kg()
    kpi = kg.get_kpi(kpi_name)
    if not kpi:
        print(f"[KPI] ❌ KPI '{kpi_name}' not found")
        return {"status": "unknown", "error": f"KPI '{kpi_name}' not found"}

    thresholds = kpi.get("thresholds", {})
    status = "unknown"

    for level in ["green", "amber", "red"]:
        cond = thresholds.get(level, "")
        if not cond:
            continue
        try:
            parts = cond.strip().split()
            if len(parts) == 2:
                op, val = parts[0], float(parts[1])
                met = (
                    (op == ">=" and actual_value >= val) or
                    (op == ">" and actual_value > val) or
                    (op == "<=" and actual_value <= val) or
                    (op == "<" and actual_value < val)
                )
                if met:
                    status = level
                    break
        except (ValueError, IndexError):
            continue

    print(f"[KPI] → Status: {status.upper()} (thresholds: {thresholds})")
    
    return _json_safe({
        "kpi": kpi_name,
        "value": actual_value,
        "status": status,
        "thresholds": thresholds,
    })


def get_domain_context(question: str) -> dict:
    """Get domain events and context from Neo4j.
    
    Calls: KnowledgeGraph.get_domain_context_for_question(question)
    Returns dict with: events, business_rules, org_context, customer_relationships,
                       supply_chain, loyalty, pricing, product_taxonomy, 
                       promotion_targeting, segment_rules
    """
    print(f"\n[DOMAIN] get_domain_context('{question[:60]}...')")
    result = _get_kg().get_domain_context_for_question(question)
    
    # Count non-empty sections
    non_empty = {k: len(v) for k, v in result.items() if v}
    print(f"[DOMAIN] → Found: {non_empty}")
    
    # Convert date objects to strings for JSON serialization
    return _json_safe(result)


# ═══════════════════════════════════════════════
# AGENTS — Optimized for Token Efficiency
# ═══════════════════════════════════════════════


# ── Agent 1: Triage (NO THINKING - simple tool call) ──
triage_agent = Agent(
    name="TriageAgent",
    model=MODEL,
    description="Assesses if the knowledge base can answer the question.",
    instruction=(
        "Call assess_knowledge(question). Return the result.\n"
        "If NOT_ANSWERABLE, explain what's missing."
    ),
    tools=[assess_knowledge],
    generate_content_config=NO_THINKING,
)


# ── Agent 2: Planner (WITH THINKING - needs reasoning for sub-questions) ──
planner_agent = Agent(
    name="PlannerAgent",
    model=MODEL,
    description="Creates sub-questions for investigation.",
    instruction=(
        "Create 2-5 sub-questions based on triage.\n\n"
        "For diagnostic questions about KPI degradation:\n"
        "  1. FIRST create a TREND sub-question with daily granularity\n"
        "  2. This pinpoints WHEN the issue occurred\n"
        "  3. THEN investigate causes for that specific window\n"
        "═══ WHEN TO USE CAUSAL TOOLS ═══\n"
        "If triage shows diagnostic=True OR question contains 'why', 'cause', 'reason', "
        "'spike', 'drop', 'decline', 'increase':\n"
        "  1. FIRST call get_causal_chain(concept_name) for the target KPI/concept\n"
        "  2. Create sub-questions for each cause in the chain\n"
        "  3. Or call get_full_causal_path for causes + triggering events together\n\n"
        "═══ OUTPUT FORMAT ═══\n"
        "JSON array: [{question, target_tables, target_kpi, causal_concept}, ...]\n"
        "Use ONLY names from triage report. Be concise."
    ),
    tools=[get_kpi_driver_tree, get_causal_chain, get_full_causal_path],
    generate_content_config=WITH_THINKING,
)


# ── Agent 3: Investigator (WITH THINKING - needs reasoning for SQL) ──
investigator_agent = Agent(
    name="InvestigatorAgent",
    model=MODEL,
    description="Executes sub-questions with SQL.",
    instruction=(
        "For each sub-question:\n"
        "1. get_schema_context → get tables/joins/KPI expression\n"
        "2. Write BigQuery SQL (use backticks, SAFE_DIVIDE)\n"
        "3. execute_sql → get data\n"
        "4. check_kpi_threshold if needed\n"
        "5. get_domain_context for events\n\n"
        "If SQL fails, fix and retry once. Return findings with numbers."
    ),
    tools=[get_schema_context, execute_sql, check_kpi_threshold, 
           get_domain_context, get_causal_chain, get_full_causal_path],
    generate_content_config=WITH_THINKING,
)


# ── Agent 4: Synthesis (NO THINKING - formatting only) ──
synthesis_agent = Agent(
    name="SynthesisAgent",
    model=MODEL,
    description="Produces final report.",
    instruction=(
        "Write concise report:\n"
        "## Summary (2 sentences with key numbers)\n"
        "## Findings (metric, status, trend)\n"
        "## Root Causes (ranked by impact)\n"
        "## Recommendations (actionable)\n\n"
        "Use specific numbers. No fluff."
    ),
    tools=[],
    generate_content_config=NO_THINKING,
)


# ═══════════════════════════════════════════════
# ROOT AGENT — SequentialAgent for reliable flow
# ═══════════════════════════════════════════════

root_agent = SequentialAgent(
    name="OrchestratorAgent",
    description="Executes: Triage → Plan → Investigate → Synthesize",
    sub_agents=[
        triage_agent,
        planner_agent,
        investigator_agent,
        synthesis_agent,
    ],
)