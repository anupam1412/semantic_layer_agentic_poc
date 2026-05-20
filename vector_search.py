"""
Vertex AI Vector Search — 4 Embedding Indexes (Fixed)
=====================================================
Fixes:
  - _fallback: inverted scoring logic corrected (more overlap = lower distance)
  - index_from_graph: handles empty ontology gracefully
  - Embeddings: fallback to zero vectors if Vertex AI unavailable
"""

import os, json, hashlib, logging
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables (same pattern as knowledge_graph.py)
env_file = Path("_env") if Path("_env").exists() else Path(".env")
if env_file.exists():
    load_dotenv(env_file)

import vertexai
from vertexai.language_models import TextEmbeddingModel, TextEmbeddingInput
from google.cloud import aiplatform

log = logging.getLogger("agentic_sl.vs")


class Embeddings:
    def __init__(self):
        try:
            vertexai.init(
                project=os.getenv("GCP_PROJECT", "acn-uki-ds-data-ai-project"),
                location=os.getenv("GCP_REGION", "europe-west2"),
            )
            self.model = TextEmbeddingModel.from_pretrained(
                os.getenv("EMBEDDING_MODEL", "text-embedding-005")
            )
        except Exception as e:
            log.warning(f"Embeddings init failed: {e}. Using zero-vector fallback.")
            self.model = None

    def embed(self, texts, task="RETRIEVAL_DOCUMENT"):
        if not self.model:
            return [[0.0] * 768 for _ in texts]
        inputs = [TextEmbeddingInput(text=t, task_type=task) for t in texts]
        out = []
        for i in range(0, len(inputs), 250):
            out.extend(
                [e.values for e in self.model.get_embeddings(inputs[i : i + 250])]
            )
        return out


class VectorSearch:
    def __init__(self):
        aiplatform.init(
            project=os.getenv("GCP_PROJECT", "acn-uki-ds-data-ai-project"),
            location=os.getenv("GCP_REGION", "europe-west2"),
        )
        self.emb = Embeddings()
        self.endpoint = None
        ep_id = os.getenv("VS_INDEX_ENDPOINT_ID", "")
        if ep_id:
            try:
                self.endpoint = aiplatform.MatchingEngineIndexEndpoint(ep_id)
            except Exception as e:
                log.warning(f"VS endpoint init failed: {e}")
        self._idx = {
            "tables": os.getenv("VS_TABLES_INDEX_ID", ""),
            "kpis": os.getenv("VS_KPIS_INDEX_ID", ""),
            "concepts": os.getenv("VS_CONCEPTS_INDEX_ID", ""),
            "examples": os.getenv("VS_EXAMPLES_INDEX_ID", ""),
        }
        self._dep = {
            "tables": "tables_deployed",
            "kpis": "kpis_deployed",
            "concepts": "concepts_deployed",
            "examples": "examples_deployed",
        }
        self._meta: dict[str, dict] = {}
        self._kg = None  # Lazy reference to KnowledgeGraph
        self._meta_loaded = False

    def _ensure_meta_loaded(self):
        """Auto-populate _meta cache from Neo4j if empty."""
        if self._meta_loaded:
            return
        
        if self._kg is None:
            try:
                # Try package import first (when running via ADK from parent dir)
                from .knowledge_graph import KnowledgeGraph
                self._kg = KnowledgeGraph()
            except ImportError:
                try:
                    # Fallback to direct import (when running standalone)
                    from knowledge_graph import KnowledgeGraph
                    self._kg = KnowledgeGraph()
                except Exception as e:
                    log.warning(f"Could not load KnowledgeGraph: {e}")
                    return
            except Exception as e:
                log.warning(f"Could not load KnowledgeGraph: {e}")
                return
        
        log.info("Auto-populating VectorSearch cache from Neo4j...")
        
        try:
            # Load tables
            tables = self._kg.all_tables()
            for fqn in tables:
                ctx = self._kg.get_table_context([fqn])
                if fqn in ctx:
                    info = ctx[fqn]
                    cols = ", ".join([c["name"] for c in info.get("columns", [])[:10]])
                    doc = f"Table: {info.get('name', '')} ({fqn})\nDesc: {info.get('description', '')}\nCols: {cols}"
                    self._meta[self._id(fqn)] = {
                        "fqn": fqn,
                        "name": info.get("name", ""),
                        "doc": doc,
                    }
            log.info(f"  Loaded {len(tables)} tables")
            
            # Load KPIs
            kpis = self._kg.get_all_kpis()
            for k in kpis:
                name = k.get("name", "")
                doc = f"KPI: {name}\nDescription: {k.get('description', '')}\nExpression: {k.get('expression', '')}"
                self._meta[self._id(name)] = {
                    "kpi_name": name,
                    "doc": doc,
                }
            log.info(f"  Loaded {len(kpis)} KPIs")
            
            # Load concepts (both BusinessConcept and OntConcept)
            concepts = self._kg.get_all_concepts()
            for c in concepts:
                name = c.get("name", "")
                synonyms = ", ".join(c.get("synonyms", [])[:5])
                doc = f"Concept: {name}\nDescription: {c.get('description', '')}\nSynonyms: {synonyms}"
                self._meta[self._id(name)] = {
                    "concept": name,
                    "doc": doc,
                }
            log.info(f"  Loaded {len(concepts)} concepts")
            
            # Load examples (both SQL and Cypher)
            examples = self._kg.get_similar_examples("", limit=100)
            for ex in examples:
                q = ex.get("question", "")
                if not q:
                    continue
                ex_type = ex.get("type", "sql")
                if ex_type == "cypher":
                    doc = f"Q: {q}\nCypher: {ex.get('cypher', '')}"
                    self._meta[self._id(q)] = {
                        "nl_query": q,
                        "cypher": ex.get("cypher", ""),
                        "doc": doc,
                        "complexity": "complex",
                        "type": "cypher",
                    }
                else:
                    doc = f"Q: {q}\nSQL: {ex.get('sql', '')}"
                    self._meta[self._id(q)] = {
                        "nl_query": q,
                        "sql": ex.get("sql", ""),
                        "doc": doc,
                        "complexity": ex.get("complexity", "simple"),
                        "type": "sql",
                    }
            log.info(f"  Loaded {len(examples)} examples")
            
            self._meta_loaded = True
            log.info(f"VectorSearch cache populated: {len(self._meta)} items total")
            
        except Exception as e:
            log.error(f"Error populating VectorSearch cache: {e}")

    @staticmethod
    def _id(t):
        return hashlib.md5(t.encode()).hexdigest()

    def _upsert(self, coll, dps):
        idx = self._idx.get(coll)
        if idx:
            try:
                aiplatform.MatchingEngineIndex(idx).upsert_datapoints(
                    datapoints=[
                        aiplatform.compat.types.matching_engine_index.IndexDatapoint(
                            datapoint_id=d["id"], feature_vector=d["embedding"]
                        )
                        for d in dps
                    ]
                )
            except Exception as e:
                log.warning(f"Upsert {coll}: {e}")
        for d in dps:
            self._meta[d["id"]] = d["meta"]

    def _search(self, dep_id, query, k):
        # Ensure cache is loaded before searching
        self._ensure_meta_loaded()
        
        if self.endpoint:
            try:
                emb = self.emb.embed([query], task="RETRIEVAL_QUERY")[0]
                resp = self.endpoint.find_neighbors(
                    deployed_index_id=dep_id, queries=[emb], num_neighbors=k
                )
                return [
                    {"distance": n.distance, **self._meta.get(n.id, {})}
                    for n in (resp[0] if resp and resp[0] else [])
                ]
            except Exception as e:
                log.warning(f"VS gRPC failed ({e}), using keyword fallback")
        return self._fallback(query, k)

    def _fallback(self, q, k):
        """Keyword-overlap fallback when Vector Search is unreachable.

        FIX: More keyword overlap now gives LOWER distance (better match).
        Previous version had this inverted.
        """
        qw = set(q.lower().split())
        if not qw:
            return list(self._meta.values())[:k]

        scored = []
        for meta in self._meta.values():
            doc_text = " ".join(str(v) for v in meta.values()).lower()
            doc_words = set(doc_text.split())
            overlap = len(qw & doc_words)
            # Higher overlap → lower distance (better match)
            distance = 1.0 - (overlap / max(len(qw), 1))
            scored.append((distance, meta))

        scored.sort(key=lambda x: x[0])
        return [{"distance": s[0], **s[1]} for s in scored[:k]]

    def index_from_graph(self, kg):
        """Pull all data from Neo4j and index into Vertex AI."""
        raw = kg.get_full_ontology_text()
        if not raw:
            log.warning("Empty ontology, nothing to index.")
            return

        ont = json.loads(raw)

        # Tables
        for fqn, info in ont.get("tables", {}).items():
            cols = ", ".join(c["name"] for c in info.get("columns", []))
            metrics = ""
            # Find KPIs computed from this table
            for kpi in ont.get("kpis", []):
                if fqn in kpi.get("tables", []):
                    metrics += f", {kpi['name']}"
            doc = (
                f"Table: {info.get('name', '')} ({fqn})\n"
                f"Desc: {info.get('description', '')}\n"
                f"Cols: {cols}"
            )
            if metrics:
                doc += f"\nMetrics: {metrics.lstrip(', ')}"
            emb = self.emb.embed([doc])[0]
            self._upsert(
                "tables",
                [{"id": self._id(fqn), "embedding": emb,
                  "meta": {"fqn": fqn, "name": info.get("name", ""), "doc": doc}}],
            )

        # KPIs
        for kpi in ont.get("kpis", []):
            doc = (
                f"KPI: {kpi['name']}\n"
                f"Expression: {kpi.get('expression', '')}\n"
                f"Description: {kpi.get('description', '')}\n"
                f"Tables: {', '.join(kpi.get('tables', []))}"
            )
            emb = self.emb.embed([doc])[0]
            self._upsert(
                "kpis",
                [{"id": self._id(kpi["name"]), "embedding": emb,
                  "meta": {"kpi_name": kpi["name"], "doc": doc}}],
            )

        # Concepts (with causal edges embedded in the doc)
        cm = ont.get("causal_map", [])
        for c in ont.get("business_concepts", []):
            cname = c["concept"]
            causes = [e["source"] for e in cm if e["target"] == cname]
            effects = [e["target"] for e in cm if e["source"] == cname]
            causal = ""
            if causes:
                causal += f"\nCaused by: {', '.join(causes)}"
            if effects:
                causal += f"\nAffects: {', '.join(effects)}"
            doc = (
                f"Concept: {cname}\n"
                f"Description: {c.get('description', '')}\n"
                f"Synonyms: {', '.join(c.get('synonyms', []))}\n"
                f"Calculation: {c.get('calculation_hint', '')}"
                f"{causal}"
            )
            emb = self.emb.embed([doc])[0]
            self._upsert(
                "concepts",
                [{"id": self._id(cname), "embedding": emb,
                  "meta": {"concept": cname, "doc": doc}}],
            )

        # Examples
        for ex in ont.get("example_queries", []):
            doc = (
                f"Q: {ex['question']}\n"
                f"SQL: {ex['sql']}\n"
                f"Complexity: {ex.get('complexity', 'simple')}"
            )
            emb = self.emb.embed([doc])[0]
            self._upsert(
                "examples",
                [{"id": self._id(ex["question"]), "embedding": emb,
                  "meta": {
                      "nl_query": ex["question"],
                      "sql": ex["sql"],
                      "doc": doc,
                      "complexity": ex.get("complexity", "simple"),
                  }}],
            )

        log.info(
            f"Indexed: {len(ont.get('tables', {}))} tables, "
            f"{len(ont.get('kpis', []))} KPIs, "
            f"{len(ont.get('business_concepts', []))} concepts, "
            f"{len(ont.get('example_queries', []))} examples"
        )

    def index_example(self, q, sql, tables):
        doc = f"Q: {q}\nSQL: {sql}"
        emb = self.emb.embed([doc])[0]
        self._upsert(
            "examples",
            [{"id": self._id(q), "embedding": emb,
              "meta": {"nl_query": q, "sql": sql, "doc": doc}}],
        )

    # ── Search methods ──

    def search_tables(self, q, k=5):
        return [
            {
                "fqn": r.get("fqn", ""),
                "name": r.get("name", ""),
                "doc": r.get("doc", ""),
                "score": r.get("distance", 1),
            }
            for r in self._search(self._dep["tables"], q, k)
        ]

    def search_kpis(self, q, k=5):
        return [
            {"kpi_name": r.get("kpi_name", ""), "doc": r.get("doc", "")}
            for r in self._search(self._dep["kpis"], q, k)
        ]

    def search_concepts(self, q, k=5):
        return [
            {"concept": r.get("concept", ""), "doc": r.get("doc", "")}
            for r in self._search(self._dep["concepts"], q, k)
        ]

    def search_examples(self, q, k=5):
        return [
            {
                "nl_query": r.get("nl_query", ""),
                "sql": r.get("sql", ""),
                "doc": r.get("doc", ""),
                "complexity": r.get("complexity", "simple"),
            }
            for r in self._search(self._dep["examples"], q, k)
        ]