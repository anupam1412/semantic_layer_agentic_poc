"""
Orchestrator + Schema Agent — Assessment-First Design
=====================================================

Flow:
  1. Orchestrator receives user question
  2. Orchestrator calls SchemaAgent.assess() — a broad knowledge scan
  3. SchemaAgent searches Vertex AI (tables, KPIs, concepts, examples)
     and traverses Neo4j (joins, causal graph, KPI thresholds)
  4. SchemaAgent returns a KnowledgeReport
  5. Orchestrator evaluates the report:
     - ANSWERABLE → Phase 2: classify + decompose
     - PARTIALLY_ANSWERABLE → Phase 2 with caveats
     - NOT_ANSWERABLE → return gaps + suggestions, no SQL
  6. Phase 2: Orchestrator builds sub-questions, each pre-loaded with
     schema context from the KnowledgeReport (no redundant lookups)

Drop these classes into agentic_semantic_layer.py, replacing the existing
OrchestratorAgent and SchemaAgent classes. Also update the query() method
as shown at the bottom.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("agentic_sl")


# ─────────────────────────────────────────────
# KnowledgeReport — output of SchemaAgent.assess()
# ─────────────────────────────────────────────

@dataclass
class KnowledgeReport:
    """Everything the SchemaAgent found about the user's question."""

    # What matched
    matched_tables: list[dict] = field(default_factory=list)
    matched_kpis: list[dict] = field(default_factory=list)
    matched_concepts: list[dict] = field(default_factory=list)
    matched_examples: list[dict] = field(default_factory=list)

    # Structural context from Neo4j
    table_context: dict = field(default_factory=dict)
    joins: list[dict] = field(default_factory=list)
    causal_map: list[dict] = field(default_factory=list)
    causal_chains: dict = field(default_factory=dict)

    # KPI details from Neo4j
    kpi_details: dict = field(default_factory=dict)

    # Full ontology text for SQL generation
    ontology_text: str = ""

    # Coverage assessment
    coverage_score: float = 0.0
    gaps: list[dict] = field(default_factory=list)

    def to_summary(self) -> dict:
        return {
            "tables": len(self.matched_tables),
            "kpis": len(self.matched_kpis),
            "concepts": len(self.matched_concepts),
            "examples": len(self.matched_examples),
            "joins": len(self.joins),
            "causal_edges": len(self.causal_map),
            "coverage_score": self.coverage_score,
            "gaps": self.gaps,
        }


# ═════════════════════════════════════════════
# SCHEMA AGENT (with assess mode)
# ═════════════════════════════════════════════

class SchemaAgent:
    """
    Two modes:
      assess(question)  — broad scan for the Orchestrator's knowledge check
      resolve(sub_question, report) — focused lookup for a specific sub-question

    assess() does one comprehensive pass across all stores:
      - Vertex AI: search tables, KPIs, concepts, examples
      - Neo4j: get joins for matched tables, load causal map,
               get causal chains for matched concepts, get KPI details
      - Computes a coverage_score and identifies gaps
    """

    def assess(self, question: str, kg, vs) -> KnowledgeReport:
        """
        Broad knowledge scan. Called once per user question.
        Returns everything the Orchestrator needs for assessment + planning.
        """
        report = KnowledgeReport()

        # ── Vertex AI: semantic search across all 4 indexes ──
        report.matched_tables = vs.search_tables(question, k=8)
        report.matched_kpis = vs.search_kpis(question, k=5)
        report.matched_concepts = vs.search_concepts(question, k=5)
        report.matched_examples = vs.search_examples(question, k=5)

        # ── Neo4j: structural context for matched tables ──
        fqns = [t["fqn"] for t in report.matched_tables if t.get("fqn")]
        if fqns:
            report.table_context = kg.get_table_context(fqns)
            report.joins = kg.get_joins(fqns)

        # ── Neo4j: causal map (full) ──
        report.causal_map = kg.get_causal_map()

        # ── Neo4j: causal chains for top matched concepts ──
        for concept in report.matched_concepts[:3]:
            cname = concept.get("concept", "")
            if cname:
                try:
                    report.causal_chains[cname] = kg.get_causal_chain(cname)
                except Exception as e:
                    log.warning(f"Causal chain for '{cname}' failed: {e}")

        # ── Neo4j: KPI details for matched KPIs ──
        for kpi in report.matched_kpis:
            kname = kpi.get("kpi_name", "")
            if kname:
                try:
                    detail = kg.get_kpi(kname)
                    if detail:
                        report.kpi_details[kname] = detail
                except Exception as e:
                    log.warning(f"KPI detail for '{kname}' failed: {e}")

        # ── Full ontology text for SQL generation ──
        report.ontology_text = kg.get_full_ontology_text()

        # ── Compute coverage score and identify gaps ──
        self._compute_coverage(question, report)

        log.info(
            f"Knowledge assessment: {report.coverage_score:.0%} coverage, "
            f"{len(report.matched_tables)} tables, {len(report.matched_kpis)} KPIs, "
            f"{len(report.matched_concepts)} concepts, {len(report.gaps)} gaps"
        )
        return report

    def resolve_for_sub_question(
        self,
        sub_question: str,
        report: KnowledgeReport,
        vs,
        kg,
        target_tables: list[str] = None,
        target_kpi: str = None,
        causal_concept: str = None,
    ) -> dict:
        """
        Focused resolution for a specific sub-question.
        Reuses the KnowledgeReport where possible, does targeted lookups
        only for what's not already in the report.
        """
        # Start with tables from report, but also do a focused search
        focused_tables = vs.search_tables(sub_question, k=5)
        all_fqns = list(set(
            [t["fqn"] for t in focused_tables if t.get("fqn")]
            + (target_tables or [])
        ))

        # Get context — reuse from report if available, else query Neo4j
        context = {}
        for fqn in all_fqns:
            if fqn in report.table_context:
                context[fqn] = report.table_context[fqn]
        missing_fqns = [f for f in all_fqns if f not in context]
        if missing_fqns:
            context.update(kg.get_table_context(missing_fqns))

        # Joins — reuse from report, supplement if new tables
        joins = report.joins
        if missing_fqns:
            extra_joins = kg.get_joins(all_fqns)
            existing = {(j["table1"], j["table2"]) for j in joins}
            for j in extra_joins:
                if (j["table1"], j["table2"]) not in existing:
                    joins.append(j)

        # KPI context
        kpi_context = None
        if target_kpi:
            kpi_context = report.kpi_details.get(target_kpi)
            if not kpi_context:
                try:
                    kpi_context = kg.get_kpi(target_kpi)
                except Exception:
                    pass

        # Causal chain
        causal_chain = None
        if causal_concept:
            causal_chain = report.causal_chains.get(causal_concept)
            if not causal_chain:
                try:
                    causal_chain = kg.get_causal_chain(causal_concept)
                except Exception:
                    pass

        return {
            "fqns": all_fqns,
            "context": context,
            "joins": joins,
            "kpi_context": kpi_context,
            "causal_chain": causal_chain,
        }

    def _compute_coverage(self, question: str, report: KnowledgeReport):
        """
        Score how well the knowledge base covers this question.
        Identify specific gaps.
        """
        scores = []
        gaps = []

        # Table coverage: do we have tables that can answer this?
        table_score = min(len(report.matched_tables) / 3, 1.0)
        scores.append(table_score * 0.3)  # 30% weight
        if table_score < 0.3:
            gaps.append({
                "gap": "No relevant tables found",
                "impact": "Cannot generate SQL queries",
                "suggestion": "Register tables related to this question using register_table()",
            })

        # KPI coverage: are relevant KPIs defined?
        kpi_score = min(len(report.matched_kpis) / 2, 1.0)
        scores.append(kpi_score * 0.2)  # 20% weight
        if kpi_score < 0.3:
            gaps.append({
                "gap": "No relevant KPIs defined",
                "impact": "Cannot check thresholds or compare against targets",
                "suggestion": "Register KPIs with register_kpi() including thresholds",
            })

        # Concept coverage: does the ontology understand this domain?
        concept_score = min(len(report.matched_concepts) / 2, 1.0)
        scores.append(concept_score * 0.2)  # 20% weight
        if concept_score < 0.3:
            gaps.append({
                "gap": "No matching business concepts",
                "impact": "Cannot do causal reasoning or root-cause analysis",
                "suggestion": "Register concepts with register_concept() including synonyms",
            })

        # Causal coverage: for "why" questions, do we have AFFECTS edges?
        q_lower = question.lower()
        is_diagnostic = any(
            w in q_lower for w in ["why", "reason", "cause", "root cause", "explain", "driver"]
        )
        if is_diagnostic:
            causal_score = min(len(report.causal_map) / 5, 1.0)
            scores.append(causal_score * 0.2)  # 20% weight for diagnostic
            if causal_score < 0.3:
                gaps.append({
                    "gap": "No causal relationships (AFFECTS edges) defined",
                    "impact": "Cannot trace root causes — will investigate dimensions blindly",
                    "suggestion": "Register causal edges with register_affects(source, target, mechanism)",
                })
        else:
            scores.append(0.2)  # Full marks for non-diagnostic

        # Example coverage: do we have similar past queries?
        example_score = min(len(report.matched_examples) / 2, 1.0)
        scores.append(example_score * 0.1)  # 10% weight
        if example_score < 0.3:
            gaps.append({
                "gap": "No similar example queries found",
                "impact": "SQL generation will rely purely on LLM reasoning without few-shot guidance",
                "suggestion": "Register example queries with register_example()",
            })

        report.coverage_score = sum(scores)
        report.gaps = gaps


# ═════════════════════════════════════════════
# ORCHESTRATOR AGENT (two-phase)
# ═════════════════════════════════════════════

class OrchestratorAgent:
    """
    Phase 1: Receive KnowledgeReport from SchemaAgent, decide answerability.
    Phase 2: If answerable, classify and decompose using causal map + KPIs.

    The Orchestrator never touches Vertex AI or Neo4j directly — all
    knowledge comes through the SchemaAgent's KnowledgeReport.
    """

    PLAN_SYSTEM = """You are a query planning agent for a retail analytics system.

Given a user question, a KNOWLEDGE REPORT (what the system knows), and
a CAUSAL MAP (how business concepts affect each other), classify the
question and decompose it into sub-questions.

Return JSON:
{
  "question_type": "SIMPLE" or "COMPARATIVE" or "DIAGNOSTIC",
  "sub_questions": [
    {
      "id": "sq1",
      "question": "Specific analytical question",
      "purpose": "What this reveals about the overall answer",
      "target_tables": ["table FQNs this needs"],
      "target_kpi": "KPI name or null",
      "causal_concept": "concept name or null",
      "depends_on": []
    }
  ],
  "time_context": {"current_period": "...", "comparison_period": "..."},
  "dimensions_to_analyze": ["category", "store", "region", "channel"],
  "investigation_strategy": "Brief description of the analytical approach"
}

Rules:
- SIMPLE: 1 sub-question, direct fact lookup
- COMPARATIVE: 2-3 sub-questions (current vs comparison period, delta)
- DIAGNOSTIC: 5-8 sub-questions. USE THE CAUSAL MAP — for each concept
  that CAUSES the target concept, create a sub-question investigating it.
  Always include: overall metric, then one sub-Q per causal driver.
- target_tables: use ONLY table FQNs from the knowledge report
- target_kpi: reference ONLY KPIs from the knowledge report
- causal_concept: reference ONLY concepts from the knowledge report
- Include time_context when the question involves period comparison
Return ONLY valid JSON."""

    ANSWERABILITY_THRESHOLD_FULL = 0.6
    ANSWERABILITY_THRESHOLD_PARTIAL = 0.3

    def __init__(self, cfg):
        self.gemini = GeminiClient(cfg)

    def assess_answerability(self, question: str, report: KnowledgeReport) -> dict:
        """
        Phase 1: Evaluate the KnowledgeReport to determine answerability.
        Returns a structured assessment — no LLM call needed, pure logic.
        """
        score = report.coverage_score

        if score >= self.ANSWERABILITY_THRESHOLD_FULL:
            status = "ANSWERABLE"
        elif score >= self.ANSWERABILITY_THRESHOLD_PARTIAL:
            status = "PARTIALLY_ANSWERABLE"
        else:
            status = "NOT_ANSWERABLE"

        # Build human-readable explanation
        parts = []
        if report.matched_tables:
            parts.append(
                f"Found {len(report.matched_tables)} relevant tables: "
                f"{', '.join(t.get('name','') for t in report.matched_tables[:5])}"
            )
        else:
            parts.append("No relevant tables found in the knowledge base.")

        if report.matched_kpis:
            parts.append(
                f"Found {len(report.matched_kpis)} relevant KPIs: "
                f"{', '.join(k.get('kpi_name','') for k in report.matched_kpis[:5])}"
            )
        if report.matched_concepts:
            parts.append(
                f"Found {len(report.matched_concepts)} relevant concepts: "
                f"{', '.join(c.get('concept','') for c in report.matched_concepts[:5])}"
            )
        if report.causal_map:
            parts.append(f"Causal graph has {len(report.causal_map)} edges available for root-cause analysis.")
        if report.matched_examples:
            parts.append(f"Found {len(report.matched_examples)} similar past queries for guidance.")

        assessment = {
            "status": status,
            "coverage_score": score,
            "explanation": " ".join(parts),
            "knowledge_summary": report.to_summary(),
            "gaps": report.gaps,
            "can_proceed": status in ("ANSWERABLE", "PARTIALLY_ANSWERABLE"),
            "caveats": [],
        }

        # Add caveats for partial answerability
        if status == "PARTIALLY_ANSWERABLE":
            for gap in report.gaps:
                assessment["caveats"].append(
                    f"{gap['gap']}: {gap['impact']}"
                )

        log.info(
            f"Answerability: {status} (score={score:.2f}, "
            f"gaps={len(report.gaps)})"
        )
        return assessment

    def plan(self, question: str, report: KnowledgeReport) -> dict:
        """
        Phase 2: Classify and decompose the question into sub-questions.
        Uses KnowledgeReport for all context — no direct store access.
        """
        # Build prompt context from the KnowledgeReport
        table_text = "\n".join(
            f"  - {t.get('fqn','')}: {t.get('doc','')[:120]}"
            for t in report.matched_tables[:8]
        ) or "  None found."

        kpi_text = "\n".join(
            f"  - {k.get('kpi_name','')}: {k.get('doc','')[:120]}"
            for k in report.matched_kpis[:5]
        ) or "  None found."

        concept_text = "\n".join(
            f"  - {c.get('concept','')}: {c.get('doc','')[:120]}"
            for c in report.matched_concepts[:5]
        ) or "  None found."

        causal_text = "\n".join(
            f"  {e['source']} → {e['target']} ({e.get('mechanism','')})"
            for e in report.causal_map
        ) if report.causal_map else "  No causal edges defined."

        example_text = "\n".join(
            f"  Q: {e.get('nl_query','')[:80]}\n  SQL: {e.get('sql','')[:120]}"
            for e in report.matched_examples[:3]
        ) or "  None."

        prompt = (
            f"USER QUESTION: {question}\n\n"
            f"AVAILABLE TABLES:\n{table_text}\n\n"
            f"AVAILABLE KPIs:\n{kpi_text}\n\n"
            f"AVAILABLE CONCEPTS:\n{concept_text}\n\n"
            f"CAUSAL MAP:\n{causal_text}\n\n"
            f"SIMILAR PAST QUERIES:\n{example_text}\n\n"
            f"Classify and decompose this question into sub-questions. "
            f"Use ONLY the tables, KPIs, and concepts listed above."
        )

        resp = self.gemini.generate(
            prompt, system=self.PLAN_SYSTEM,
            temperature=0, thinking_budget=0, response_json=True,
        )

        try:
            plan = json.loads(resp)
            # Validate that referenced tables/KPIs/concepts actually exist
            plan = self._validate_plan(plan, report)
            log.info(
                f"Plan: {plan.get('question_type','')} with "
                f"{len(plan.get('sub_questions',[]))} sub-questions"
            )
            return plan
        except (json.JSONDecodeError, TypeError) as e:
            log.warning(f"Failed to parse plan ({e}), falling back to SIMPLE.")
            return self._fallback_plan(question, report)

    def _validate_plan(self, plan: dict, report: KnowledgeReport) -> dict:
        """
        Ensure the plan only references tables/KPIs/concepts that actually
        exist in the KnowledgeReport. Strip invalid references.
        """
        known_fqns = {t.get("fqn","") for t in report.matched_tables}
        known_kpis = {k.get("kpi_name","") for k in report.matched_kpis}
        known_concepts = {c.get("concept","") for c in report.matched_concepts}

        for sq in plan.get("sub_questions", []):
            # Filter target_tables to only known ones
            if sq.get("target_tables"):
                sq["target_tables"] = [
                    t for t in sq["target_tables"] if t in known_fqns
                ]
            # Validate target_kpi
            if sq.get("target_kpi") and sq["target_kpi"] not in known_kpis:
                sq["target_kpi"] = None
            # Validate causal_concept
            if sq.get("causal_concept") and sq["causal_concept"] not in known_concepts:
                sq["causal_concept"] = None

        return plan

    def _fallback_plan(self, question: str, report: KnowledgeReport) -> dict:
        """Safe fallback if Gemini fails to produce a valid plan."""
        return {
            "question_type": "SIMPLE",
            "sub_questions": [{
                "id": "sq1",
                "question": question,
                "purpose": "Direct answer",
                "target_tables": [
                    t.get("fqn","") for t in report.matched_tables[:5]
                ],
                "target_kpi": (
                    report.matched_kpis[0].get("kpi_name")
                    if report.matched_kpis else None
                ),
                "causal_concept": None,
                "depends_on": [],
            }],
            "time_context": {},
            "dimensions_to_analyze": [],
            "investigation_strategy": "Direct query — fallback mode",
        }


# ═════════════════════════════════════════════
# UPDATED query() METHOD
# ═════════════════════════════════════════════
# Replace the query() method in AgenticSemanticLayer with this:

def query_method(self, question: str, max_rows: int = 500):
    """
    Main query flow with assessment-first design.

    1. SchemaAgent.assess() → KnowledgeReport
    2. Orchestrator.assess_answerability() → ANSWERABLE / PARTIAL / NOT
    3. If answerable: Orchestrator.plan() → sub-questions
    4. Per sub-question: SchemaAgent.resolve() → Executor → Analysis
    5. Synthesis → final answer
    """
    log.info(f"Query: {question}")
    trace = AgentTrace()

    # ── Phase 1: Schema Agent assesses knowledge ──
    with trace.step("SchemaAgent", "assess_knowledge") as ts:
        ts.set_input({"question": question})
        report = self.schema_agent.assess(question, self.kg, self.vs)
        ts.set_output(report.to_summary())
        ts.set_details({
            "coverage_score": report.coverage_score,
            "tables_found": [t.get("name","") for t in report.matched_tables],
            "kpis_found": [k.get("kpi_name","") for k in report.matched_kpis],
            "concepts_found": [c.get("concept","") for c in report.matched_concepts],
            "causal_edges": len(report.causal_map),
            "gaps": len(report.gaps),
        })

    # ── Phase 1b: Orchestrator evaluates answerability ──
    with trace.step("OrchestratorAgent", "assess_answerability") as ts:
        ts.set_input({"coverage_score": report.coverage_score, "gaps": report.gaps})
        assessment = self.orchestrator.assess_answerability(question, report)
        ts.set_output(assessment)
        ts.set_details({
            "status": assessment["status"],
            "can_proceed": assessment["can_proceed"],
        })

    # ── If not answerable, return early with gaps ──
    if not assessment["can_proceed"]:
        log.info(f"NOT_ANSWERABLE: {assessment['explanation']}")
        return AgenticResult(
            question=question,
            question_type="NOT_ANSWERABLE",
            plan={"assessment": assessment},
            findings=[],
            synthesis=(
                f"I don't have enough knowledge to answer this question.\n\n"
                f"**Assessment:** {assessment['explanation']}\n\n"
                f"**Knowledge gaps:**\n"
                + "\n".join(
                    f"- {g['gap']}: {g['suggestion']}"
                    for g in assessment["gaps"]
                )
            ),
            sql_queries=[],
            confidence=0.0,
            trace=trace.to_dict(),
            metadata={
                "status": "NOT_ANSWERABLE",
                "coverage_score": report.coverage_score,
                "gaps": assessment["gaps"],
                "trace_id": trace.trace_id,
            },
        )

    # ── Phase 2: Orchestrator plans sub-questions ──
    with trace.step("OrchestratorAgent", "plan") as ts:
        ts.set_input({
            "question": question,
            "coverage_score": report.coverage_score,
            "causal_edges": len(report.causal_map),
        })
        plan = self.orchestrator.plan(question, report)
        q_type = plan.get("question_type", "SIMPLE")
        sub_qs = plan.get("sub_questions", [])
        ts.set_output({
            "question_type": q_type,
            "sub_questions": len(sub_qs),
            "strategy": plan.get("investigation_strategy", ""),
        })

    log.info(f"Plan: {q_type}, {len(sub_qs)} sub-questions")

    # ── Phase 3: Execute each sub-question ──
    findings = []
    all_sqls = []

    for idx, sq in enumerate(sub_qs):
        sq_text = sq.get("question", question)
        sq_purpose = sq.get("purpose", "")
        sq_tables = sq.get("target_tables", [])
        sq_kpi = sq.get("target_kpi")
        sq_causal = sq.get("causal_concept")
        sq_id = sq.get("id", f"sq{idx+1}")
        log.info(f"  Sub-Q [{sq_id}]: {sq_text[:80]}")

        # Schema agent: focused resolution (reuses KnowledgeReport)
        with trace.step("SchemaAgent", f"resolve_{sq_id}") as ts:
            ts.set_input({
                "sub_question": sq_text,
                "target_tables": sq_tables,
                "target_kpi": sq_kpi,
                "causal_concept": sq_causal,
            })
            schema = self.schema_agent.resolve_for_sub_question(
                sq_text, report, self.vs, self.kg,
                target_tables=sq_tables,
                target_kpi=sq_kpi,
                causal_concept=sq_causal,
            )
            ts.set_output({
                "tables": schema["fqns"],
                "has_kpi": schema["kpi_context"] is not None,
                "has_causal": schema["causal_chain"] is not None,
            })

        # Executor: SQL lifecycle against BigQuery
        with trace.step("ExecutorAgent", f"execute_{sq_id}") as ts:
            finding = self.executor.execute_sub_question(
                sq_text, sq_purpose, schema["context"], schema["joins"],
                report.matched_concepts, report.matched_examples,
                report.ontology_text,
                kpi_context=schema["kpi_context"],
                causal_chain=schema["causal_chain"],
            )
            ts.set_output({
                "status": finding["status"],
                "rows": finding.get("total_rows", 0),
                "attempts": finding.get("attempts", 1),
            })
            if finding["status"] == "failed":
                ts.set_error(finding.get("error", ""))

        if finding["sql"]:
            all_sqls.append(finding["sql"])

        # Analysis: score + KPI threshold check
        with trace.step("AnalysisAgent", f"analyze_{sq_id}") as ts:
            finding = self.analysis.analyze(finding, kpi_context=schema["kpi_context"])
            a = finding.get("analysis") or {}
            ts.set_output({
                "impact": a.get("impact_score", 0),
                "kpi_status": a.get("kpi_status", "unknown"),
                "direction": a.get("direction", "neutral"),
            })

        findings.append(finding)

    # ── Phase 4: Synthesis ──
    with trace.step("SynthesisAgent", "synthesize") as ts:
        synth = self.synthesis.synthesize(question, q_type, findings)
        # Prepend caveats if partially answerable
        if assessment["status"] == "PARTIALLY_ANSWERABLE" and assessment["caveats"]:
            caveat_text = (
                "**Note:** This answer may be incomplete due to knowledge gaps:\n"
                + "\n".join(f"- {c}" for c in assessment["caveats"])
                + "\n\n"
            )
            synth = caveat_text + synth
        ts.set_output({"length": len(synth)})

    # ── Phase 5: Cache ──
    successful = [f for f in findings if f.get("status") == "success"]
    confidence = len(successful) / max(len(findings), 1)

    if successful and all_sqls:
        with trace.step("Cache", "store") as ts:
            try:
                import re
                fqns = set()
                known = self.kg.all_tables()
                for f in findings:
                    if f.get("sql"):
                        for ref in re.findall(r'`([^`]+\.[^`]+\.[^`]+)`', f["sql"]):
                            if ref in known:
                                fqns.add(ref)
                self.kg.upsert_example(question, all_sqls[0], list(fqns), q_type.lower())
                self.vs.index_example(question, all_sqls[0], list(fqns))
                ts.set_output({"cached": True, "tables": list(fqns)})
            except Exception as e:
                ts.set_error(str(e))

    return AgenticResult(
        question=question,
        question_type=q_type,
        plan=plan,
        findings=findings,
        synthesis=synth,
        sql_queries=all_sqls,
        confidence=confidence,
        trace=trace.to_dict(),
        metadata={
            "agent_count": 6,
            "status": assessment["status"],
            "coverage_score": report.coverage_score,
            "sub_questions": len(sub_qs),
            "successful_findings": len(successful),
            "total_sql_attempts": sum(f.get("attempts", 1) for f in findings),
            "causal_edges": len(report.causal_map),
            "gaps": assessment["gaps"],
            "caveats": assessment.get("caveats", []),
            "trace_id": trace.trace_id,
        },
    )
