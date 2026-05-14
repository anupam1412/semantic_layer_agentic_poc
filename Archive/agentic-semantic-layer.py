"""
ADK Multi-Agent Semantic Layer
==============================
Uses Google Agent Development Kit (ADK) for agent creation and orchestration.

Architecture:
  Root Agent (OrchestratorAgent) — LlmAgent with sub_agents
    ├── SchemaAgent        — LlmAgent with Neo4j + Vertex AI tools
    ├── ExecutorAgent      — SequentialAgent (SQL gen → validate → execute)
    │   └── SQLAgent       — LlmAgent with BigQuery tools
    ├── AnalysisAgent      — LlmAgent with KPI threshold tools
    └── SynthesisAgent     — LlmAgent that produces final narrative

Three Stores:
  Neo4j    = Knowledge graph (10 domain layers, KPIs, causal reasoning)
  BigQuery = Transactional data + KPI views
  Vertex AI = Embeddings in Vector Search (4 indexes)

Supported queries:
  - Why are we seeing stockouts in Electronics this month?
  - Why is our enterprise segment churning faster than SMB?
  - Why did the Black Friday promotion underperform?
  - Why is Manchester growing while Birmingham is declining?
  - Why are Accessories sales declining despite strong promotions?
  - Why did our loyalty redemption rate spike in Q3?
  - Why is our margin declining in Software despite growing revenue?

Run with: adk web  (from parent directory)
"""

import os
import json
import re
import hashlib
import logging
from datetime import datetime
from typing import Optional

from google.adk.agents import Agent

# Local modules — use try/except for path flexibility
try:
    from .knowledge_graph import KnowledgeGraph
    from .vector_search import VectorSearch, Embeddings
    from .bq_executor import BQExecutor
except ImportError:
    from knowledge_graph import KnowledgeGraph
    from vector_search import VectorSearch, Embeddings
    from bq_executor import BQExecutor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
log = logging.getLogger("agentic_sl")

MODEL = os.getenv("GENERATIVE_MODEL", "gemini-2.5-flash")
PROJECT = os.getenv("GCP_PROJECT", "acn-uki-ds-data-ai-project")
REGION = os.getenv("GCP_REGION", "europe-west2")

# ─── Lazy-initialized store singletons ───
# Avoids crash at import time if Neo4j/Vertex AI not available
_kg: Optional[KnowledgeGraph] = None
_vs: Optional[VectorSearch] = None
_bq: Optional[BQExecutor] = None

def _get_kg():
    global _kg
    if _kg is None:
        _kg = KnowledgeGraph()
    return _kg

def _get_vs():
    global _vs
    if _vs is None:
        _vs = VectorSearch()
    return _vs

def _get_bq():
    global _bq
    if _bq is None:
        _bq = BQExecutor()
    return _bq


# ═══════════════════════════════════════════════
# TOOLS — Python functions that ADK agents can call
# ═══════════════════════════════════════════════

def assess_knowledge(question: str) -> dict:
    """Assess whether the knowledge base can answer this question.
    Searches Vertex AI for matching tables, KPIs, concepts, examples.
    Traverses Neo4j for causal edges and KPI driver trees.
    Returns a KnowledgeReport with coverage_score and gaps.
    """
    report = {}

    kg = _get_kg()
    vs = _get_vs()

    # Vertex AI semantic search across 4 indexes
    tables = vs.search_tables(question, k=8)
    kpis = vs.search_kpis(question, k=5)
    concepts = vs.search_concepts(question, k=5)
    examples = vs.search_examples(question, k=5)

    # Neo4j structural context
    fqns = [t["fqn"] for t in tables if t.get("fqn")]
    table_context = kg.get_table_context(fqns) if fqns else {}
    joins = kg.get_joins(fqns) if fqns else []
    causal_map = kg.get_causal_map()

    # Causal chains for top concepts
    causal_chains = {}
    for c in concepts[:3]:
        cname = c.get("concept", "")
        if cname:
            try:
                causal_chains[cname] = kg.get_causal_chain(cname)
            except Exception:
                pass

    # KPI details with thresholds
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

    # KPI driver tree traversal
    driver_trees = {}
    for kname in kpi_details:
        try:
            driver_trees[kname] = kg.get_kpi_driver_tree(kname)
        except Exception:
            pass

    # Domain context from Neo4j (temporal events, business rules, etc.)
    domain_context = kg.get_domain_context_for_question(question)

    # Coverage scoring
    scores = []
    gaps = []

    table_score = min(len(tables) / 3, 1.0)
    scores.append(table_score * 0.25)
    if table_score < 0.3:
        gaps.append({"gap": "No relevant tables", "suggestion": "Register tables with register_table()"})

    kpi_score = min(len(kpis) / 2, 1.0)
    scores.append(kpi_score * 0.20)
    if kpi_score < 0.3:
        gaps.append({"gap": "No relevant KPIs defined", "suggestion": "Register KPIs with register_kpi()"})

    concept_score = min(len(concepts) / 2, 1.0)
    scores.append(concept_score * 0.15)
    if concept_score < 0.3:
        gaps.append({"gap": "No matching business concepts", "suggestion": "Register concepts with register_concept()"})

    q_lower = question.lower()
    is_diagnostic = any(w in q_lower for w in ["why", "reason", "cause", "explain", "driver"])
    causal_score = min(len(causal_map) / 5, 1.0) if is_diagnostic else 1.0
    scores.append(causal_score * 0.20)
    if is_diagnostic and causal_score < 0.3:
        gaps.append({"gap": "No causal edges", "suggestion": "Register AFFECTS edges with register_affects()"})

    domain_score = min(len(domain_context.get("events", [])) / 2, 1.0) if is_diagnostic else 0.5
    scores.append(domain_score * 0.10)

    example_score = min(len(examples) / 2, 1.0)
    scores.append(example_score * 0.10)

    coverage = sum(scores)
    if coverage >= 0.6:
        status = "ANSWERABLE"
    elif coverage >= 0.3:
        status = "PARTIALLY_ANSWERABLE"
    else:
        status = "NOT_ANSWERABLE"

    report = {
        "status": status,
        "coverage_score": round(coverage, 2),
        "matched_tables": [{"fqn": t["fqn"], "name": t.get("name", "")} for t in tables],
        "matched_kpis": [{"name": k.get("kpi_name", ""), "doc": k.get("doc", "")[:100]} for k in kpis],
        "matched_concepts": [{"concept": c.get("concept", ""), "doc": c.get("doc", "")[:100]} for c in concepts],
        "matched_examples": [{"question": e.get("nl_query", "")[:80]} for e in examples],
        "causal_map_edges": len(causal_map),
        "causal_chains": {k: {"causes": len(v.get("caused_by", [])), "effects": len(v.get("affects", []))}
                          for k, v in causal_chains.items()},
        "kpi_details": {k: {"expression": v.get("expression", "")[:80],
                            "thresholds": v.get("thresholds", {}),
                            "dimensions": v.get("dimensions", [])}
                        for k, v in kpi_details.items()},
        "driver_trees": driver_trees,
        "domain_context": domain_context,
        "gaps": gaps,
        "ontology_text": kg.get_full_ontology_text(),
    }
    return report


def search_schema_for_subquestion(sub_question: str, target_tables: str = "",
                                   target_kpi: str = "", causal_concept: str = "") -> dict:
    """Focused schema resolution for a specific sub-question.
    Searches Vertex AI for tables, gets joins and causal context from Neo4j.
    Args:
        sub_question: The specific analytical question to resolve.
        target_tables: Comma-separated list of table FQNs to include.
        target_kpi: KPI name to get definition and thresholds for.
        causal_concept: Concept name to get causal chain for.
    Returns: Schema context including tables, joins, KPI details, causal chain.
    """
    kg = _get_kg()
    vs = _get_vs()

    tables = vs.search_tables(sub_question, k=5)
    fqns = list(set(
        [t["fqn"] for t in tables if t.get("fqn")]
        + [f.strip() for f in target_tables.split(",") if f.strip()]
    ))
    context = kg.get_table_context(fqns) if fqns else {}
    joins = kg.get_joins(fqns) if fqns else []

    kpi_context = None
    if target_kpi:
        kpi_context = kg.get_kpi(target_kpi)

    causal_chain = None
    if causal_concept:
        try:
            causal_chain = kg.get_causal_chain(causal_concept)
        except Exception:
            pass

    # Get domain context relevant to this sub-question
    domain = kg.get_domain_context_for_question(sub_question)

    return {
        "tables": list(context.keys()),
        "table_context": context,
        "joins": joins,
        "kpi_context": kpi_context,
        "causal_chain": causal_chain,
        "domain_context": domain,
        "ontology_text": kg.get_full_ontology_text(),
    }


def execute_bigquery_sql(sql: str) -> dict:
    """Validate and execute a BigQuery SQL query.
    First does a dry-run validation, then executes if valid.
    Returns: status, rows, total_rows, schema, or error message.
    """
    bq = _get_bq()
    ok, err = bq.validate(sql)
    if not ok:
        return {"status": "validation_error", "error": err, "sql": sql}
    result = bq.execute(sql)
    return result


def check_kpi_thresholds(kpi_name: str, actual_value: float) -> dict:
    """Check a KPI value against its defined thresholds in Neo4j.
    Returns: kpi_status (green/amber/red), threshold details, breach description.
    """
    kg = _get_kg()
    kpi = kg.get_kpi(kpi_name)
    if not kpi:
        return {"kpi_status": "unknown", "error": f"KPI '{kpi_name}' not found"}

    thresholds = kpi.get("thresholds", {})
    status = "unknown"
    breach = None

    # Evaluate thresholds (simple numeric comparison)
    for level in ["green", "amber", "red"]:
        cond = thresholds.get(level, "")
        if not cond:
            continue
        try:
            # Parse condition like ">= 500000" or "< 0.05"
            parts = cond.strip().split()
            if len(parts) == 2:
                op, val = parts[0], float(parts[1])
                met = False
                if op == ">=":
                    met = actual_value >= val
                elif op == ">":
                    met = actual_value > val
                elif op == "<=":
                    met = actual_value <= val
                elif op == "<":
                    met = actual_value < val
                elif op == "=":
                    met = actual_value == val
                if met:
                    status = level
                    break
        except (ValueError, IndexError):
            continue

    if status == "red":
        breach = f"KPI '{kpi_name}' value {actual_value} is in RED zone ({thresholds.get('red', '')})"
    elif status == "amber":
        breach = f"KPI '{kpi_name}' value {actual_value} is in AMBER zone ({thresholds.get('amber', '')})"

    return {
        "kpi_name": kpi_name,
        "actual_value": actual_value,
        "kpi_status": status,
        "thresholds": thresholds,
        "breach": breach,
        "dimensions": kpi.get("dimensions", []),
    }


def get_domain_context(question: str) -> dict:
    """Retrieve domain-specific context from Neo4j knowledge graph.
    Includes: temporal events (competitor actions, market conditions),
    business rules, org hierarchy, supply chain incidents, product taxonomy,
    loyalty program changes, pricing decisions.
    """
    return _get_kg().get_domain_context_for_question(question)


def get_kpi_driver_tree(kpi_name: str) -> dict:
    """Traverse the KPI driver tree in Neo4j.
    Returns the hierarchical decomposition of a KPI into its component drivers.
    Example: Revenue -> DRIVEN_BY -> [Order Count, AOV] -> DRIVEN_BY -> [Traffic, Conversion, ...]
    """
    return _get_kg().get_kpi_driver_tree(kpi_name)


def cache_successful_query(question: str, sql: str, tables_used: str) -> dict:
    """Cache a successful query for future few-shot learning.
    Stores in both Neo4j (as QueryExample node) and Vertex AI (as embedding).
    Args:
        question: The natural language question.
        sql: The SQL query that successfully answered it.
        tables_used: Comma-separated list of table FQNs used.
    """
    kg = _get_kg()
    vs = _get_vs()
    table_list = [t.strip() for t in tables_used.split(",") if t.strip()]
    kg.upsert_example(question, sql, table_list, "diagnostic")
    vs.index_example(question, sql, table_list)
    return {"cached": True, "question": question[:80]}


# ═══════════════════════════════════════════════
# ADK AGENT DEFINITIONS
# ═══════════════════════════════════════════════

# Agent 2: Schema Agent — searches and resolves knowledge
schema_agent = Agent(
    name="SchemaAgent",
    model=MODEL,
    description=(
        "Searches the knowledge base (Vertex AI Vector Search + Neo4j graph) "
        "to find relevant tables, KPIs, concepts, causal relationships, and "
        "domain context for a given question. Use this agent to assess whether "
        "the system can answer a question and to get schema context for SQL generation."
    ),
    instruction=(
        "You are a schema resolution agent. When asked to assess a question, "
        "use the assess_knowledge tool to scan all knowledge stores. "
        "When asked to resolve a sub-question, use search_schema_for_subquestion "
        "with specific target_tables, target_kpi, and causal_concept from the plan. "
        "Also use get_domain_context to find temporal events, business rules, "
        "and competitive intelligence relevant to the question. "
        "Use get_kpi_driver_tree to decompose KPIs into their component drivers. "
        "Always report what you found and what gaps exist."
    ),
    tools=[assess_knowledge, search_schema_for_subquestion,
           get_domain_context, get_kpi_driver_tree],
)

# Agent 4: SQL Agent — generates and executes BigQuery SQL
sql_agent = Agent(
    name="SQLAgent",
    model=MODEL,
    description=(
        "Generates BigQuery SQL queries from schema context and executes them. "
        "Handles validation, execution, and retry on failure."
    ),
    instruction=(
        "You are a BigQuery SQL expert. Given a sub-question and schema context, "
        "generate ONE SQL query using only the tables and columns provided. "
        "Rules: fully qualified table names with backticks, SAFE_DIVIDE for division, "
        "COUNTIF for conditional counts, DATE_SUB for YoY comparisons. "
        "After generating SQL, use execute_bigquery_sql to run it. "
        "If execution fails, analyze the error and generate corrected SQL. "
        "Retry up to 2 times. When a KPI definition is provided, use its exact expression. "
        "Include domain context (events, business rules) as comments in the SQL for traceability."
    ),
    tools=[execute_bigquery_sql],
)

# Agent 5: Analysis Agent — scores findings and checks thresholds
analysis_agent = Agent(
    name="AnalysisAgent",
    model=MODEL,
    description=(
        "Analyzes query results, scores findings by impact, checks KPI thresholds, "
        "and flags anomalies using domain context from the knowledge graph."
    ),
    instruction=(
        "You are a data analyst. Given query results for a sub-question: "
        "1. Summarize the finding in one sentence with specific numbers. "
        "2. Score the impact (0.0-1.0) and direction (positive/negative/neutral). "
        "3. If a target KPI is specified, use check_kpi_thresholds to evaluate it. "
        "4. Use domain context to explain anomalies — check for competitor actions, "
        "   supply incidents, policy changes, manager transitions, pricing decisions. "
        "5. Flag any business rule violations (e.g., discount exceeding policy max). "
        "Report your analysis as structured JSON with: finding, metric_value, "
        "impact_score, direction, kpi_status, threshold_breach, domain_factors, details."
    ),
    tools=[check_kpi_thresholds, get_domain_context],
)

# Agent 6: Synthesis Agent — produces final narrative
synthesis_agent = Agent(
    name="SynthesisAgent",
    model=MODEL,
    description=(
        "Synthesizes all findings into a structured root-cause narrative "
        "with KPI health assessment, ranked causes, and recommendations."
    ),
    instruction=(
        "You are a senior business analyst. Synthesize all findings into:\n\n"
        "## Executive Summary\n"
        "2-3 sentences with specific numbers.\n\n"
        "## KPI Health\n"
        "For each KPI checked, show: current value, threshold status (green/amber/red), "
        "driver tree decomposition showing which drivers are underperforming.\n\n"
        "## Root Causes (ranked by impact)\n"
        "For each cause, include:\n"
        "- What happened (with numbers)\n"
        "- Domain context (competitor actions, supply issues, policy changes, etc.)\n"
        "- Evidence from the data\n\n"
        "## Key Findings\n"
        "Notable patterns.\n\n"
        "## Recommendations\n"
        "Actionable next steps.\n\n"
        "## Data Quality Notes\n"
        "Any caveats.\n\n"
        "Use specific numbers. Reference domain events by name and date. "
        "If the answer is partial due to knowledge gaps, state what's missing."
    ),
    tools=[],
)


# ═══════════════════════════════════════════════
# ROOT AGENT — Orchestrator with assessment-first flow
# ═══════════════════════════════════════════════

root_agent = Agent(
    name="OrchestratorAgent",
    model=MODEL,
    description=(
        "Root orchestrator for the retail analytics semantic layer. "
        "Receives natural language questions, assesses knowledge coverage, "
        "classifies question type, decomposes into sub-questions using "
        "the causal graph, and coordinates specialist agents."
    ),
    instruction=(
        "You are the orchestrator for a retail analytics system backed by "
        "BigQuery (transactional data), Neo4j (knowledge graph with 10 domain layers), "
        "and Vertex AI (semantic search).\n\n"

        "PHASE 1 — KNOWLEDGE ASSESSMENT:\n"
        "First, delegate to SchemaAgent to assess whether you can answer the question. "
        "Use the assess_knowledge tool. Check the coverage_score:\n"
        "- >= 0.6: ANSWERABLE — proceed to Phase 2\n"
        "- 0.3-0.6: PARTIALLY_ANSWERABLE — proceed with caveats\n"
        "- < 0.3: NOT_ANSWERABLE — tell the user what's missing and how to fix it\n\n"

        "PHASE 2 — CLASSIFY THE QUESTION:\n"
        "Use these 7 categories based on the REASONING TYPE required:\n\n"

        "LOOKUP — Single fact retrieval. 'What was revenue last month?'\n"
        "  → 1 sub-question. Schema agent for tables, SQL agent for one query.\n\n"

        "TREND — Time series analysis. 'Show monthly revenue trend for 12 months'\n"
        "  → 1-2 sub-questions. Include GROUP BY time period. Check KPI threshold on latest value.\n\n"

        "PERIOD_COMPARE — Compare same metric across two time periods.\n"
        "  'Why did Black Friday underperform vs last year?'\n"
        "  → 2-3 sub-questions: period A metrics, period B metrics, delta analysis.\n"
        "  MUST check temporal events (competitor actions, market conditions) between the periods.\n"
        "  MUST check promotion overlap via bridge table if promo-related.\n\n"

        "ENTITY_COMPARE — Compare two specific entities (stores, products, brands).\n"
        "  'Why is Manchester growing while Birmingham is declining?'\n"
        "  → 3-5 sub-questions: metrics per entity, then contextual factors.\n"
        "  MUST check org hierarchy (manager experience), competitor actions per region,\n"
        "  local policy changes, store capacity differences.\n\n"

        "SEGMENT_COMPARE — Compare customer segments or cohorts.\n"
        "  'Why is enterprise churning faster than SMB?'\n"
        "  → 3-5 sub-questions: metric per segment, then relationship factors.\n"
        "  MUST check customer relationships (account manager changes, contract renewals),\n"
        "  loyalty tier rules, segment definitions.\n\n"

        "ROOT_CAUSE — Trace WHY a metric changed. The deepest analysis.\n"
        "  'Why are Accessories declining despite strong promotions?'\n"
        "  → 5-8 sub-questions built from TWO sources:\n"
        "    1. KPI DRIVER TREE: decompose the metric (revenue → order_count × AOV → ...)\n"
        "       Create one sub-question per driver at each level.\n"
        "    2. CAUSAL MAP: for each concept that AFFECTS the target, create a sub-question.\n"
        "  MUST check: supply chain incidents, product discontinuations, competitor products,\n"
        "  pricing decisions, business rule violations. Use ALL domain layers.\n\n"

        "ANOMALY — Explain an unexpected spike or drop.\n"
        "  'Why did loyalty redemption rate spike in Q3?'\n"
        "  → 3-6 sub-questions: detect the anomaly period via trend query,\n"
        "    then search for what changed in that period.\n"
        "  MUST check: rule changes, campaign sends, partner integrations, policy changes.\n"
        "  Focus on the SPECIFIC TIME WINDOW of the anomaly.\n\n"

        "PHASE 3 — DECOMPOSE INTO SUB-QUESTIONS:\n"
        "For each sub-question, specify:\n"
        "- target_tables: FQNs from the KnowledgeReport\n"
        "- target_kpi: KPI name if checking thresholds\n"
        "- causal_concept: concept name if investigating a causal factor\n"
        "- domain_layers_to_check: which Neo4j layers are relevant\n\n"

        "PHASE 4 — EXECUTE:\n"
        "For each sub-question:\n"
        "1. Delegate to SchemaAgent to resolve schema context\n"
        "2. Delegate to SQLAgent to generate and execute BigQuery SQL\n"
        "3. Delegate to AnalysisAgent to score the finding and check thresholds\n\n"

        "PHASE 5 — SYNTHESIZE:\n"
        "Delegate to SynthesisAgent to produce the final narrative.\n"
        "The synthesis structure varies by category:\n"
        "- LOOKUP/TREND: direct answer with numbers\n"
        "- PERIOD_COMPARE: side-by-side comparison + temporal context\n"
        "- ENTITY_COMPARE: per-entity breakdown + differentiating factors\n"
        "- SEGMENT_COMPARE: per-segment breakdown + relationship factors\n"
        "- ROOT_CAUSE: KPI driver tree decomposition + ranked causal factors\n"
        "- ANOMALY: timeline of changes that explain the anomaly\n\n"

        "Always use cache_successful_query at the end.\n"
        "IMPORTANT: Only reference tables, KPIs, and concepts from the KnowledgeReport."
    ),
    tools=[assess_knowledge, cache_successful_query],
    sub_agents=[schema_agent, sql_agent, analysis_agent, synthesis_agent],
)
