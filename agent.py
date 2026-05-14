"""
ADK Multi-Agent Semantic Layer — 8-Agent Architecture
=====================================================
Each agent has ONE reasoning job. The root Orchestrator is a thin
sequencer that delegates to specialist sub-agents.

Agent tree:
  Orchestrator (root)         — sequence 4 phases
    ├── TriageAgent           — assess knowledge, gate pipeline
    ├── PlannerAgent          — classify question, build sub-questions
    ├── InvestigatorAgent     — execute sub-questions (has 3 sub-agents)
    │   ├── SchemaAgent       — resolve tables, joins, context
    │   ├── ExecutorAgent     — generate SQL, validate, retry, execute
    │   └── AnalysisAgent     — score findings, check KPI thresholds
    ├── SynthesisAgent        — produce final narrative
    └── LearningAgent         — cache queries, flag ontology gaps

Three stores:
  Neo4j    = Knowledge graph (10 domain layers)
  BigQuery = Transactional data (9 tables)
  Vertex AI = Embeddings (4 Vector Search indexes)

Run: adk web  (from parent directory)
"""

import os
import json
import logging
from typing import Optional
from dotenv import load_dotenv

# Try both _env and .env for compatibility
if os.path.exists("_env"):
    load_dotenv("_env")
else:
    load_dotenv(".env")

from google.adk.agents import Agent

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


# ─── JSON Serialization Helper ───
def _json_safe(obj):
    """Recursively convert Neo4j types to JSON-serializable Python types."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_json_safe(v) for v in obj)
    # Handle Neo4j Date/DateTime/Time types
    if hasattr(obj, 'isoformat'):
        return obj.isoformat()
    # Handle Neo4j Duration
    if hasattr(obj, 'iso_format'):
        return obj.iso_format()
    # Handle other Neo4j types that have a string representation
    if type(obj).__module__.startswith('neo4j'):
        return str(obj)
    return obj


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
# Grouped by which agent uses them.


# ── Triage tools ──

def assess_knowledge(question: str) -> dict:
    """Comprehensive knowledge scan across all three stores.

    Searches Vertex AI (4 indexes) and traverses Neo4j (causal map,
    KPI details, domain context). Returns coverage_score, status
    (ANSWERABLE/PARTIALLY_ANSWERABLE/NOT_ANSWERABLE), matched items,
    and actionable gaps.
    """
    kg = _get_kg()
    vs = _get_vs()

    tables = vs.search_tables(question, k=8)
    kpis = vs.search_kpis(question, k=5)
    concepts = vs.search_concepts(question, k=5)
    examples = vs.search_examples(question, k=5)

    fqns = [t["fqn"] for t in tables if t.get("fqn")]
    table_context = kg.get_table_context(fqns) if fqns else {}
    joins = kg.get_joins(fqns) if fqns else []
    causal_map = kg.get_causal_map()

    causal_chains = {}
    for c in concepts[:3]:
        cname = c.get("concept", "")
        if cname:
            try:
                causal_chains[cname] = kg.get_causal_chain(cname)
            except Exception:
                pass

    kpi_details = {}
    driver_trees = {}
    for k in kpis:
        kname = k.get("kpi_name", "")
        if kname:
            try:
                detail = kg.get_kpi(kname)
                if detail:
                    kpi_details[kname] = detail
                    driver_trees[kname] = kg.get_kpi_driver_tree(kname)
            except Exception:
                pass

    domain_context = kg.get_domain_context_for_question(question)
    ontology_text = kg.get_full_ontology_text()

    q_lower = question.lower()
    is_diagnostic = any(
        w in q_lower for w in ["why", "reason", "cause", "explain", "driver"]
    )

    scores, gaps = [], []

    ts = min(len(tables) / 3, 1.0)
    scores.append(ts * 0.25)
    if ts < 0.3:
        gaps.append({"gap": "No relevant tables", "suggestion": "Register tables"})

    ks = min(len(kpis) / 2, 1.0)
    scores.append(ks * 0.20)
    if ks < 0.3:
        gaps.append({"gap": "No relevant KPIs", "suggestion": "Register KPIs with thresholds"})

    cs = min(len(concepts) / 2, 1.0)
    scores.append(cs * 0.15)
    if cs < 0.3:
        gaps.append({"gap": "No matching concepts", "suggestion": "Register concepts with AFFECTS edges"})

    cas = min(len(causal_map) / 5, 1.0) if is_diagnostic else 1.0
    scores.append(cas * 0.20)
    if is_diagnostic and cas < 0.3:
        gaps.append({"gap": "No causal edges", "suggestion": "Register AFFECTS relationships"})

    di = sum(len(v) for v in domain_context.values() if isinstance(v, list))
    scores.append((min(di / 3, 1.0) if is_diagnostic else 0.5) * 0.10)
    scores.append(min(len(examples) / 2, 1.0) * 0.10)

    coverage = round(sum(scores), 2)
    status = (
        "ANSWERABLE" if coverage >= 0.6
        else "PARTIALLY_ANSWERABLE" if coverage >= 0.3
        else "NOT_ANSWERABLE"
    )

    log.info(f"Triage: {status} ({coverage:.0%}), {len(tables)} tables, {len(gaps)} gaps")

    return _json_safe({
        "status": status,
        "coverage_score": coverage,
        "is_diagnostic": is_diagnostic,
        "matched_tables": [
            {"fqn": t["fqn"], "name": t.get("name", ""), "doc": t.get("doc", "")[:150]}
            for t in tables
        ],
        "matched_kpis": [
            {"name": k.get("kpi_name", ""), "doc": k.get("doc", "")[:120]}
            for k in kpis
        ],
        "matched_concepts": [
            {"concept": c.get("concept", ""), "doc": c.get("doc", "")[:120]}
            for c in concepts
        ],
        "matched_examples": [
            {"question": e.get("nl_query", "")[:80], "sql": e.get("sql", "")[:120]}
            for e in examples
        ],
        "table_context": table_context,
        "joins": joins,
        "causal_map": causal_map,
        "causal_chains": {
            k: {"caused_by": len(v.get("caused_by", [])), "affects": len(v.get("affects", []))}
            for k, v in causal_chains.items()
        },
        "kpi_details": kpi_details,
        "driver_trees": driver_trees,
        "domain_context": domain_context,
        "gaps": gaps,
        "ontology_text": ontology_text,
    })


# ── Planner tools ──

def get_kpi_driver_tree(kpi_name: str) -> dict:
    """Traverse DRIVEN_BY edges in Neo4j to decompose a KPI into drivers.
    Returns hierarchical tree: Revenue -> [Order Count, AOV] -> [Traffic, ...]
    """
    return _json_safe(_get_kg().get_kpi_driver_tree(kpi_name))


def get_causal_chain(concept_name: str) -> dict:
    """Get what causes and what is affected by a business concept.
    Traverses AFFECTS edges in Neo4j up to 3 hops.
    """
    return _json_safe(_get_kg().get_causal_chain(concept_name))


def get_triggering_events(concept_name: str) -> dict:
    """Find domain events that TRIGGER a business concept.

    Traverses TRIGGERS edges from domain nodes (SupplyIncident,
    CompetitorAction, AccountManager, PricingDecision, RedemptionRule,
    PolicyChange, LoyaltyCampaign) into the named concept.

    Example: get_triggering_events("supply chain disruption")
    → [{"node_type": "SupplyIncident", "details": {"type": "factory_fire",
        "date": "2025-02-10", "supplier": "Shenzhen Tech Co"}, "evidence": "..."}]

    Use this to create SPECIFIC sub-questions about actual events rather
    than generic investigation of a concept.
    """
    return _json_safe(_get_kg().get_triggering_events(concept_name))


def get_full_causal_path(target_concept: str) -> dict:
    """Trace full path: domain events → TRIGGERS → concepts → AFFECTS → target.

    For each concept that causes the target, also returns the specific
    domain events that triggered it. This gives the Planner concrete
    events to investigate rather than abstract concepts.

    Example: get_full_causal_path("revenue decline")
    → caused_by: [
        {concept: "supply chain disruption",
         triggering_events: [{type: "SupplyIncident", details: {factory_fire...}}]},
        {concept: "competitive pressure",
         triggering_events: [{type: "CompetitorAction", details: {store_opening...}}]},
        ...
      ]
    """
    return _json_safe(_get_kg().get_full_causal_path(target_concept))


# ── Schema tools (Investigator > Schema) ──

def search_schema_for_subquestion(
    sub_question: str,
    target_tables: str = "",
    target_kpi: str = "",
    causal_concept: str = "",
) -> dict:
    """Focused schema resolution for a sub-question.
    Searches Vertex AI for tables, gets joins + domain context from Neo4j.
    Args:
        sub_question: The analytical question.
        target_tables: Comma-separated FQNs or list of FQNs to include.
        target_kpi: KPI name for thresholds.
        causal_concept: Concept name for causal chain.
    """
    kg = _get_kg()
    vs = _get_vs()

    # Normalize target_tables to list (handle both string and list inputs)
    if isinstance(target_tables, list):
        table_list = [t.strip() for t in target_tables if t and str(t).strip()]
    elif isinstance(target_tables, str) and target_tables.strip():
        table_list = [f.strip() for f in target_tables.split(",") if f.strip()]
    else:
        table_list = []

    focused = vs.search_tables(sub_question, k=5)
    fqns = list(set(
        [t["fqn"] for t in focused if t.get("fqn")]
        + table_list
    ))
    context = kg.get_table_context(fqns) if fqns else {}
    joins = kg.get_joins(fqns) if fqns else []

    kpi_ctx = None
    if target_kpi:
        try:
            kpi_ctx = kg.get_kpi(target_kpi)
        except Exception:
            pass

    causal = None
    if causal_concept:
        try:
            causal = kg.get_causal_chain(causal_concept)
        except Exception:
            pass

    domain = kg.get_domain_context_for_question(sub_question)

    return _json_safe({
        "tables": list(context.keys()),
        "table_context": context,
        "joins": joins,
        "kpi_context": kpi_ctx,
        "causal_chain": causal,
        "domain_context": domain,
        "ontology_text": kg.get_full_ontology_text(),
    })


# ── Executor tools (Investigator > Executor) ──

def execute_bigquery_sql(sql: str) -> dict:
    """Validate and execute BigQuery SQL.
    Dry-run first (checks keywords, estimates bytes), then executes.
    Returns up to 500 rows.
    """
    bq = _get_bq()
    ok, msg = bq.validate(sql)
    if not ok:
        return {"status": "validation_error", "error": msg, "sql": sql}
    return _json_safe(bq.execute(sql))


# ── Analysis tools (Investigator > Analysis) ──

def check_kpi_thresholds(kpi_name: str, actual_value: float) -> dict:
    """Check KPI value against green/amber/red thresholds in Neo4j.
    Returns status, breach description, and sliceable dimensions.
    """
    kg = _get_kg()
    kpi = kg.get_kpi(kpi_name)
    if not kpi:
        return {"kpi_status": "unknown", "error": f"KPI '{kpi_name}' not found"}

    thresholds = kpi.get("thresholds", {})
    status = "unknown"
    breach = None

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
                    (op == "<" and actual_value < val) or
                    (op == "=" and abs(actual_value - val) < 0.001)
                )
                if met:
                    status = level
                    break
        except (ValueError, IndexError):
            continue

    if status in ("red", "amber"):
        breach = f"KPI '{kpi_name}' = {actual_value} is {status.upper()} ({thresholds.get(status, '')})"

    return _json_safe({
        "kpi_name": kpi_name,
        "actual_value": actual_value,
        "kpi_status": status,
        "thresholds": thresholds,
        "breach": breach,
        "dimensions": kpi.get("dimensions", []),
    })


def get_domain_context(question: str) -> dict:
    """Pull domain context from all 10 Neo4j layers.
    Returns: events, supply_chain, org_context, customer_relationships,
    loyalty, pricing, business_rules, product_taxonomy, promotion_targeting,
    segment_rules. Sections are keyword-gated — customer_relationships
    activates on churn/enterprise/segment, loyalty on redemption/points/tier.
    """
    return _json_safe(_get_kg().get_domain_context_for_question(question))


# ── Learning tools ──

def cache_successful_query(question: str, sql: str, tables_used: str) -> dict:
    """Cache query for few-shot learning (Neo4j + Vertex AI).
    Args: tables_used = comma-separated FQNs.
    """
    kg = _get_kg()
    vs = _get_vs()
    tlist = [t.strip() for t in tables_used.split(",") if t.strip()]
    try:
        kg.upsert_example(question, sql, tlist, "learned")
        vs.index_example(question, sql, tlist)
        return {"cached": True, "question": question[:80]}
    except Exception as e:
        return {"cached": False, "error": str(e)[:200]}


def suggest_ontology_improvements(
    question: str, gaps: str, coverage_score: float
) -> dict:
    """Log ontology improvement suggestions based on query gaps.
    Called by LearningAgent when coverage was partial or concepts were missing.
    Args:
        question: The original user question.
        gaps: Comma-separated list of gap descriptions.
        coverage_score: The triage coverage score.
    """
    suggestions = []
    gap_list = [g.strip() for g in gaps.split(",") if g.strip()]
    for g in gap_list:
        if "table" in g.lower():
            suggestions.append({"type": "register_table", "reason": g})
        elif "kpi" in g.lower():
            suggestions.append({"type": "register_kpi", "reason": g})
        elif "concept" in g.lower() or "causal" in g.lower():
            suggestions.append({"type": "register_concept_or_affects", "reason": g})
        else:
            suggestions.append({"type": "general", "reason": g})
    log.info(f"Ontology suggestions for '{question[:50]}': {len(suggestions)} items")
    return {
        "question": question[:80],
        "coverage_score": coverage_score,
        "suggestions": suggestions,
    }


# ═══════════════════════════════════════════════
# AGENT DEFINITIONS — 8 agents, each with 1 job
# ═══════════════════════════════════════════════


# ── Agent 2: Triage ──
triage_agent = Agent(
    name="TriageAgent",
    model=MODEL,
    description="Assesses whether the knowledge base can answer a question.",
    instruction=(
        "You are the triage agent. Your ONE job: determine if the system can "
        "answer the user's question.\n\n"
        "1. Call assess_knowledge with the user's question.\n"
        "2. Read the coverage_score and status.\n"
        "3. Report clearly:\n"
        "   - ANSWERABLE (>= 0.6): list what was found, proceed.\n"
        "   - PARTIALLY_ANSWERABLE (0.3-0.6): list what was found AND "
        "     what's missing. Note caveats but proceed.\n"
        "   - NOT_ANSWERABLE (< 0.3): list specific gaps and suggestions. "
        "     Tell the user exactly what to register.\n\n"
        "Include the full KnowledgeReport in your response — the Planner "
        "agent needs the matched tables, KPIs, concepts, causal map, "
        "driver trees, and domain context."
    ),
    tools=[assess_knowledge],
)


# ── Agent 3: Planner ──
planner_agent = Agent(
    name="PlannerAgent",
    model=MODEL,
    description="Classifies question type and decomposes into sub-questions.",
    instruction=(
        "You are the planner agent. Your ONE job: classify the question and "
        "create a structured plan of sub-questions.\n\n"

        "═══ STEP 1: CLASSIFY ═══\n"
        "Determine which of 7 types this question is.\n\n"

        "═══ STEP 2: BUILD SUB-QUESTIONS ═══\n"
        "Follow the category-specific strategy below AND use the 3 sources.\n\n"

        "LOOKUP (1 sub-Q):\n"
        "  Single fact retrieval. One SQL query, one table scan.\n\n"

        "TREND (1-2 sub-Qs):\n"
        "  Time series. GROUP BY time period. Check KPI threshold on latest.\n\n"

        "PERIOD_COMPARE (2-3 sub-Qs):\n"
        "  SQ1: Metrics for period A (e.g. Black Friday 2024)\n"
        "  SQ2: Same metrics for period B (e.g. Black Friday 2025)\n"
        "  SQ3: Delta analysis — what changed between the periods\n"
        "  MUST: Call get_triggering_events to find what happened BETWEEN\n"
        "  the two periods (competitor actions, promotions, policy changes).\n"
        "  MUST: If promo-related, check for promotion overlap via bridge table.\n\n"

        "ENTITY_COMPARE (3-5 sub-Qs):\n"
        "  SQ1: Metrics for entity A (e.g. Manchester Flagship revenue trend)\n"
        "  SQ2: Same metrics for entity B (e.g. Birmingham Standard)\n"
        "  SQ3+: Contextual differentiators — one sub-Q per differentiator\n"
        "  MUST: Call get_triggering_events for 'store performance' and\n"
        "  'competitive pressure' to find competitor openings, policy changes,\n"
        "  traffic source changes near each entity.\n"
        "  MUST: Check org hierarchy — manager experience and tenure differ.\n\n"

        "SEGMENT_COMPARE (3-5 sub-Qs):\n"
        "  SQ1: Metric for segment A (e.g. enterprise churn rate)\n"
        "  SQ2: Same metric for segment B (e.g. SMB churn rate)\n"
        "  SQ3: Timeline — when did the gap open? Before/after a key date.\n"
        "  SQ4+: Relationship factors — account manager changes, contracts\n"
        "  MUST: Call get_triggering_events for 'customer relationship changes'\n"
        "  to find account manager departures, contract expirations.\n"
        "  MUST: Reference specific dates from events in sub-questions.\n\n"

        "ROOT_CAUSE (5-8 sub-Qs from 3 sources):\n"
        "  Source 1: KPI DRIVER TREE — call get_kpi_driver_tree. Create one\n"
        "  sub-Q per leaf driver (e.g. traffic, conversion, product mix).\n"
        "  Source 2: CAUSAL AFFECTS — call get_causal_chain for the target\n"
        "  concept. One sub-Q per cause concept.\n"
        "  Source 3: TRIGGERING EVENTS — for each causal concept, call\n"
        "  get_triggering_events. Make sub-Qs SPECIFIC: include event type,\n"
        "  entity name, and date. 'Check TechPro volume after factory fire\n"
        "  on Feb 10 2025' NOT 'investigate supply chain disruption'.\n"
        "  Or call get_full_causal_path to get Sources 2+3 in one call.\n"
        "  MUST: Check ALL domain layers — supply chain, product lifecycle,\n"
        "  competitor products, pricing decisions, business rule violations.\n\n"

        "ANOMALY (3-6 sub-Qs):\n"
        "  SQ1 MUST BE A TREND QUERY: detect exactly when the spike/drop\n"
        "  happened. 'Monthly loyalty_redemption_rate by tier for 12 months'\n"
        "  This PINPOINTS the anomaly window (which month, which tier).\n"
        "  SQ2+: Investigate what changed IN that specific time window.\n"
        "  Call get_triggering_events to find rule changes, campaigns,\n"
        "  partner integrations that took effect during the anomaly period.\n"
        "  Create one sub-Q per triggering event found.\n"
        "  MUST: Focus on the SPECIFIC TIME WINDOW, not general trends.\n\n"

        "═══ STEP 3: OUTPUT FORMAT ═══\n"
        "For each sub-question specify:\n"
        "  - question: the specific analytical question\n"
        "  - purpose: what this reveals about the overall answer\n"
        "  - target_tables: FQNs from the triage report\n"
        "  - target_kpi: KPI name (if checking thresholds)\n"
        "  - causal_concept: concept name (if investigating a cause)\n\n"
        "Output the plan as structured JSON. Use ONLY tables, KPIs, and "
        "concepts that appeared in the triage report."
    ),
    tools=[get_kpi_driver_tree, get_causal_chain, get_triggering_events,
           get_full_causal_path],
)


# ── Agent 5: Schema (sub-agent of Investigator) ──
schema_agent = Agent(
    name="SchemaAgent",
    model=MODEL,
    description="Resolves schema context for a sub-question.",
    instruction=(
        "You are the schema agent. Your ONE job: find the right tables, "
        "joins, KPI definitions, and domain context for a sub-question.\n\n"
        "Call search_schema_for_subquestion with the sub-question text, "
        "target_tables, target_kpi, and causal_concept from the plan.\n"
        "Also call get_domain_context to find relevant temporal events, "
        "business rules, and competitive intelligence.\n\n"
        "Return the full schema context to the Executor."
    ),
    tools=[search_schema_for_subquestion, get_domain_context],
)


# ── Agent 6: Executor (sub-agent of Investigator) ──
executor_agent = Agent(
    name="ExecutorAgent",
    model=MODEL,
    description="Generates BigQuery SQL and executes it with retry.",
    instruction=(
        "You are the SQL executor. Your ONE job: generate valid BigQuery SQL "
        "from schema context and execute it.\n\n"
        "RULES:\n"
        "- Fully qualified table names with backticks\n"
        "- SAFE_DIVIDE for all division\n"
        "- COUNTIF for conditional counts\n"
        "- WHERE status='completed' for revenue calculations\n"
        "- Use promotion_products bridge table for promo-product joins\n"
        "- When a KPI expression is provided, use it exactly\n\n"
        "PROCESS:\n"
        "1. Generate ONE SQL query from the schema context\n"
        "2. Call execute_bigquery_sql\n"
        "3. If it fails, read the error message carefully\n"
        "4. Fix the SQL (wrong column name? missing join? syntax error?)\n"
        "5. Retry (max 2 retries, 3 total attempts)\n\n"
        "Return the final SQL and query results."
    ),
    tools=[execute_bigquery_sql],
)


# ── Agent 7: Analysis (sub-agent of Investigator) ──
analysis_agent = Agent(
    name="AnalysisAgent",
    model=MODEL,
    description="Scores findings and checks KPI thresholds.",
    instruction=(
        "You are the analysis agent. Your ONE job: interpret query results "
        "and score their significance.\n\n"
        "For each finding:\n"
        "1. Summarize in one sentence with specific numbers\n"
        "2. Score impact (0.0-1.0) and direction (positive/negative/neutral)\n"
        "3. If a KPI is involved, call check_kpi_thresholds\n"
        "4. Call get_domain_context to find explanatory factors:\n"
        "   - competitor actions, supply incidents, policy changes\n"
        "   - customer_relationships: account manager departures, contracts,\n"
        "     churn risk scores (crucial for segment churn questions)\n"
        "   - segment_rules: how segments are defined (spend thresholds)\n"
        "   - loyalty: rule changes, campaigns, partner integrations\n"
        "   - pricing decisions, discount policies\n"
        "5. Flag any business rule violations\n\n"
        "Report: finding summary, metric_value, impact_score, direction, "
        "kpi_status, domain_factors."
    ),
    tools=[check_kpi_thresholds, get_domain_context],
)


# ── Agent 4: Investigator (coordinates Schema → Executor → Analysis) ──
investigator_agent = Agent(
    name="InvestigatorAgent",
    model=MODEL,
    description="Executes each sub-question through Schema, Executor, and Analysis.",
    instruction=(
        "You are the investigator. Your ONE job: execute each sub-question "
        "from the plan by coordinating three specialist agents.\n\n"
        "For EACH sub-question in the plan:\n"
        "1. Delegate to SchemaAgent — pass the sub-question, target_tables, "
        "   target_kpi, and causal_concept\n"
        "2. Delegate to ExecutorAgent — pass the schema context + sub-question. "
        "   The Executor generates SQL, validates, retries, and executes.\n"
        "3. Delegate to AnalysisAgent — pass the query results + domain context. "
        "   The Analysis agent scores the finding.\n\n"
        "Collect all findings into a list. Include both successful and failed "
        "sub-questions (with error details for failures).\n\n"
        "Return the complete findings list to the Orchestrator."
    ),
    tools=[],
    sub_agents=[schema_agent, executor_agent, analysis_agent],
)


# ── Agent 8: Synthesis ──
synthesis_agent = Agent(
    name="SynthesisAgent",
    model=MODEL,
    description="Produces the final narrative from all findings.",
    instruction=(
        "You are the synthesis agent. Your ONE job: write a structured "
        "executive report from all findings.\n\n"
        "Structure:\n"
        "## Executive Summary\n"
        "2-3 sentences with specific numbers.\n\n"
        "## KPI Health\n"
        "For each KPI: value, threshold status, driver decomposition.\n\n"
        "## Root Causes (ranked by impact score)\n"
        "For each: what happened (numbers), domain context (event name + date), "
        "supporting evidence.\n\n"
        "## Recommendations\n"
        "Actionable next steps tied to causes.\n\n"
        "## Data Quality Notes\n"
        "Caveats, partial coverage, missing data.\n\n"
        "Use specific numbers. Reference events by name and date."
    ),
    tools=[],
)


# ── Agent 9: Learning ──
learning_agent = Agent(
    name="LearningAgent",
    model=MODEL,
    description="Caches successful queries and flags ontology improvements.",
    instruction=(
        "You are the learning agent. TWO jobs after each query:\n\n"
        "1. CACHE: For each successful SQL query in the findings, call "
        "   cache_successful_query with the question, SQL, and tables used "
        "   (comma-separated FQNs).\n\n"
        "2. IMPROVE: If the triage reported gaps or coverage was below 0.8, "
        "   call suggest_ontology_improvements with the question, gap "
        "   descriptions, and coverage score. This logs what should be added "
        "   to the knowledge graph to improve future answers."
    ),
    tools=[cache_successful_query, suggest_ontology_improvements],
)


# ═══════════════════════════════════════════════
# ROOT AGENT — thin sequencer
# ═══════════════════════════════════════════════

root_agent = Agent(
    name="OrchestratorAgent",
    model=MODEL,
    description=(
        "Root orchestrator for the retail analytics semantic layer. "
        "Sequences four phases: triage, plan, investigate, synthesize."
    ),
    instruction=(
        "You are the orchestrator. Your job is to SEQUENCE four agents — "
        "you do NOT do analysis yourself.\n\n"
        "STEP 1: Delegate to TriageAgent with the user's question.\n"
        "  - If NOT_ANSWERABLE: return the triage response directly to the user.\n"
        "  - If ANSWERABLE or PARTIALLY_ANSWERABLE: continue.\n\n"
        "STEP 2: Delegate to PlannerAgent. Pass the triage report so it knows "
        "what tables, KPIs, and concepts are available.\n\n"
        "STEP 3: Delegate to InvestigatorAgent. Pass the plan. It will "
        "coordinate Schema → Executor → Analysis for each sub-question.\n\n"
        "STEP 4: Delegate to SynthesisAgent. Pass all findings. If the triage "
        "was PARTIALLY_ANSWERABLE, tell Synthesis to note the caveats.\n\n"
        "STEP 5: Delegate to LearningAgent. Pass the findings and triage gaps.\n\n"
        "Return the Synthesis agent's output as your final answer.\n\n"
        "IMPORTANT: You are a coordinator. Never generate SQL, never analyze "
        "data, never write the final narrative. Delegate everything."
    ),
    tools=[],
    sub_agents=[
        triage_agent,
        planner_agent,
        investigator_agent,
        synthesis_agent,
        learning_agent,
    ],
)