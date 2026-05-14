"""
FastAPI wrapper for the Multi-Agent Semantic Layer.
===================================================
TWO deployment modes:
  1. ADK mode:  `adk web` serves the conversational agent UI at :8000
                This API runs alongside on :8080 for admin + programmatic access
  2. Standalone: `uvicorn api:app --port 8080` for REST-only access

The /query endpoint uses the same tool functions as the ADK agents,
giving identical results whether called via REST or through ADK chat.
"""

import os
import sys
import json
import logging
from datetime import datetime

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Ensure local imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from knowledge_graph import KnowledgeGraph
from vector_search import VectorSearch
from bq_executor import BQExecutor

# Import the tool functions (same ones ADK agents use)
from agent import (
    assess_knowledge,
    search_schema_for_subquestion,
    execute_bigquery_sql,
    check_kpi_thresholds,
    get_domain_context,
    get_kpi_driver_tree,
    get_causal_chain,
    get_triggering_events,
    get_full_causal_path,
    cache_successful_query,
    suggest_ontology_improvements,
    _get_kg,
    _get_vs,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("api")

app = FastAPI(
    title="Multi-Agent Semantic Layer API",
    description=(
        "REST interface for the retail analytics semantic layer. "
        "Uses the same tool functions as the ADK agents."
    ),
    version="3.0",
)

# In-memory trace history
_traces: list[dict] = []
_MAX_TRACES = 50


# ─── Request/Response Models ───


class QueryReq(BaseModel):
    question: str


class AssessReq(BaseModel):
    question: str


class SchemaReq(BaseModel):
    sub_question: str
    target_tables: str = ""
    target_kpi: str = ""
    causal_concept: str = ""


class SqlReq(BaseModel):
    sql: str


class KpiCheckReq(BaseModel):
    kpi_name: str
    actual_value: float


class TableReg(BaseModel):
    project: str
    dataset: str
    table: str
    columns: list[dict]
    description: str = ""


class ConceptReg(BaseModel):
    concept: str
    description: str
    maps_to: list[str]
    maps_to_kpis: list[str] = []
    synonyms: list[str] = []
    calculation_hint: str = ""


class AffectsReg(BaseModel):
    source: str
    target: str
    mechanism: str = ""


class ExampleReg(BaseModel):
    question: str
    sql: str
    tables_used: list[str]
    complexity: str = "simple"


# ─── Core Endpoints (mirror the ADK tool functions) ───


@app.post("/assess")
async def assess(req: AssessReq):
    """Run knowledge assessment (same as SchemaAgent's assess_knowledge tool)."""
    try:
        report = assess_knowledge(req.question)
        _traces.append({
            "type": "assess",
            "question": req.question,
            "status": report.get("status"),
            "coverage": report.get("coverage_score"),
            "timestamp": datetime.utcnow().isoformat(),
        })
        if len(_traces) > _MAX_TRACES:
            _traces.pop(0)
        return report
    except Exception as e:
        raise HTTPException(500, str(e)[:500])


@app.post("/resolve")
async def resolve(req: SchemaReq):
    """Resolve schema for a sub-question (same as search_schema_for_subquestion)."""
    try:
        return search_schema_for_subquestion(
            req.sub_question, req.target_tables, req.target_kpi, req.causal_concept
        )
    except Exception as e:
        raise HTTPException(500, str(e)[:500])


@app.post("/execute")
async def execute(req: SqlReq):
    """Validate and execute BigQuery SQL (same as execute_bigquery_sql)."""
    try:
        return execute_bigquery_sql(req.sql)
    except Exception as e:
        raise HTTPException(500, str(e)[:500])


@app.post("/check-kpi")
async def check_kpi(req: KpiCheckReq):
    """Check KPI against thresholds (same as check_kpi_thresholds)."""
    try:
        return check_kpi_thresholds(req.kpi_name, req.actual_value)
    except Exception as e:
        raise HTTPException(500, str(e)[:500])


@app.post("/domain-context")
async def domain_ctx(req: AssessReq):
    """Get domain context from Neo4j (same as get_domain_context)."""
    try:
        return get_domain_context(req.question)
    except Exception as e:
        raise HTTPException(500, str(e)[:500])


@app.post("/kpi-drivers/{kpi_name}")
async def kpi_drivers(kpi_name: str):
    """Get KPI driver tree from Neo4j."""
    try:
        return get_kpi_driver_tree(kpi_name)
    except Exception as e:
        raise HTTPException(500, str(e)[:500])


# ─── Admin Endpoints ───


@app.post("/admin/register-table")
async def register_table(req: TableReg):
    """Register a table in Neo4j and update its embedding on the node."""
    kg = _get_kg()
    vs = _get_vs()
    fqn = f"{req.project}.{req.dataset}.{req.table}"
    kg.upsert_table(fqn, req.table, req.description, req.dataset, req.columns)
    vs.create_indexes(kg)
    return {"status": "registered", "fqn": fqn}


@app.post("/admin/register-concept")
async def register_concept(req: ConceptReg):
    """Register a business concept with MAPS_TO and MEASURES edges."""
    kg = _get_kg()
    vs = _get_vs()
    kg.upsert_concept(
        req.concept, req.description, req.maps_to,
        req.maps_to_kpis, req.synonyms, req.calculation_hint,
    )
    vs.create_indexes(kg)
    return {"status": "registered", "concept": req.concept}


@app.post("/admin/register-affects")
async def register_affects(req: AffectsReg):
    """Register a causal AFFECTS edge between two concepts."""
    kg = _get_kg()
    kg.upsert_affects(req.source, req.target, req.mechanism)
    return {"status": "registered", "edge": f"{req.source} → {req.target}"}


@app.post("/admin/register-example")
async def register_example(req: ExampleReg):
    """Register a few-shot SQL example."""
    kg = _get_kg()
    vs = _get_vs()
    kg.upsert_example(req.question, req.sql, req.tables_used, req.complexity)
    vs.index_example(req.question, req.sql, req.tables_used)
    return {"status": "registered", "question": req.question[:80]}


@app.post("/admin/reload")
async def reload():
    """Re-embed all Neo4j nodes and refresh vector indexes.

    Embeddings live on Neo4j nodes (not Vertex AI Matching Engine).
    No longer required after every restart — embeddings persist on nodes.
    Only needed if ontology data changes after initial setup.
    """
    kg = _get_kg()
    vs = _get_vs()
    vs.create_indexes(kg)
    return {"status": "reloaded", "backend": "neo4j_native_vector"}


@app.get("/admin/ontology")
async def ontology():
    """Return full ontology as JSON (serialized from Neo4j)."""
    kg = _get_kg()
    return json.loads(kg.get_full_ontology_text())


@app.get("/admin/catalog")
async def catalog():
    """List registered tables, concepts, KPIs, and examples."""
    kg = _get_kg()
    with kg.driver.session() as s:
        examples = [
            r["e"]["question"]
            for r in s.run("MATCH (e:QueryExample) RETURN e LIMIT 50")
        ]
    return {
        "tables": kg.all_tables(),
        "concepts": kg.all_concepts(),
        "kpis": [k["name"] for k in (kg.get_all_kpis() or []) if k],
        "examples": examples,
    }


@app.get("/admin/causal-chain/{concept}")
async def causal_chain_ep(concept: str):
    """Trace causes and effects for a concept (same as get_causal_chain)."""
    try:
        return get_causal_chain(concept)
    except Exception as e:
        raise HTTPException(500, str(e)[:500])


@app.get("/admin/triggering-events/{concept}")
async def triggering_events_ep(concept: str):
    """Find domain events that TRIGGER a concept (TRIGGERS edges)."""
    try:
        return get_triggering_events(concept)
    except Exception as e:
        raise HTTPException(500, str(e)[:500])


@app.get("/admin/full-causal-path/{concept}")
async def full_causal_path_ep(concept: str):
    """Full trace: domain events → TRIGGERS → concepts → AFFECTS → target."""
    try:
        return get_full_causal_path(concept)
    except Exception as e:
        raise HTTPException(500, str(e)[:500])


@app.post("/admin/suggest-improvements")
async def suggest_improvements(req: AssessReq):
    """Run triage and return ontology improvement suggestions."""
    try:
        report = assess_knowledge(req.question)
        gap_str = ", ".join(g.get("gap", "") for g in report.get("gaps", []))
        return suggest_ontology_improvements(
            req.question, gap_str, report.get("coverage_score", 0)
        )
    except Exception as e:
        raise HTTPException(500, str(e)[:500])


@app.get("/admin/causal-map")
async def causal_map():
    """Return the full causal map (AFFECTS edges)."""
    kg = _get_kg()
    edges = kg.get_causal_map()
    return {"total_edges": len(edges), "causal_map": edges}


@app.get("/admin/traces")
async def list_traces():
    """List recent API calls."""
    return {"total": len(_traces), "traces": list(reversed(_traces))}


# ─── Health ───


@app.get("/health")
async def health():
    kg = _get_kg()
    tables = kg.all_tables()
    concepts = kg.all_concepts()
    return {
        "status": "ok",
        "stores": {
            "neo4j": "connected",
            "bigquery": "configured",
            "embedding_model": "all-mpnet-base-v2 (local, offline)",
        },
        "agents": 7,  # 8 defined, LearningAgent disabled
        "tables": len(tables),
        "concepts": len(concepts),
    }