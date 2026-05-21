"""
Vector Search — Neo4j-Stored Embeddings with Local Query Embedding
==================================================================
Changes from previous version:
  - Embeddings stored in Neo4j as node properties (computed during setup)
  - Query embedding done locally with sentence-transformers (no Vertex AI runtime dependency)
  - create_indexes() method added for setup script compatibility
  - VectorSearch accepts optional neo4j_driver parameter
"""

import os, json, hashlib, logging
import numpy as np
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables (same pattern as knowledge_graph.py)
env_file = Path("_env") if Path("_env").exists() else Path(".env")
if env_file.exists():
    load_dotenv(env_file)

log = logging.getLogger("agentic_sl.vs")


# ─────────────────────────────────────────────────────────────────────────────
# Local Embeddings (sentence-transformers)
# ─────────────────────────────────────────────────────────────────────────────

class Embeddings:
    """Local sentence-transformers embeddings (replaces Vertex AI)."""
    
    def __init__(self):
        self.model = None
        self._dim = 384  # all-MiniLM-L6-v2 dimension
        try:
            from sentence_transformers import SentenceTransformer
            model_name = os.getenv("LOCAL_EMBEDDING_MODEL", "all-MiniLM-L6-v2")
            self.model = SentenceTransformer(model_name)
            log.info(f"Local embedding model loaded: {model_name}")
        except ImportError:
            log.warning("sentence-transformers not installed. Using keyword fallback.")
        except Exception as e:
            log.warning(f"Embeddings init failed: {e}. Using keyword fallback.")

    def embed(self, texts, task="RETRIEVAL_DOCUMENT"):
        """Embed texts. task param kept for API compatibility but not used."""
        if not self.model:
            return [[0.0] * self._dim for _ in texts]
        try:
            return [self.model.encode(t, convert_to_numpy=True).tolist() for t in texts]
        except Exception as e:
            log.warning(f"Embedding failed: {e}")
            return [[0.0] * self._dim for _ in texts]


# ─────────────────────────────────────────────────────────────────────────────
# Cosine Similarity
# ─────────────────────────────────────────────────────────────────────────────

def cosine_similarity(vec1, vec2):
    """Compute cosine similarity between two vectors."""
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0
    a = np.array(vec1)
    b = np.array(vec2)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


# ─────────────────────────────────────────────────────────────────────────────
# VectorSearch Class
# ─────────────────────────────────────────────────────────────────────────────

class VectorSearch:
    """
    Vector search using:
    - Pre-computed embeddings stored in Neo4j (as node properties)
    - Local sentence-transformers for query embedding
    - In-memory cosine similarity search
    """
    
    def __init__(self, neo4j_driver=None):
        """
        Initialize VectorSearch.
        
        Args:
            neo4j_driver: Optional Neo4j driver (used by setup script)
        """
        self._neo4j_driver = neo4j_driver
        self.emb = Embeddings()
        self._meta: dict[str, dict] = {}
        self._embeddings: dict[str, list] = {}  # id -> embedding vector
        self._kg = None
        self._meta_loaded = False

    def _get_driver(self):
        """Get Neo4j driver from passed reference or from KnowledgeGraph."""
        if self._neo4j_driver:
            return self._neo4j_driver
        if self._kg is None:
            try:
                from .knowledge_graph import KnowledgeGraph
                self._kg = KnowledgeGraph()
            except ImportError:
                try:
                    from knowledge_graph import KnowledgeGraph
                    self._kg = KnowledgeGraph()
                except Exception as e:
                    log.warning(f"Could not load KnowledgeGraph: {e}")
                    return None
            except Exception as e:
                log.warning(f"Could not load KnowledgeGraph: {e}")
                return None
        return self._kg.driver if self._kg else None

    def _run_query(self, query, params=None):
        """Run a Cypher query and return results."""
        driver = self._get_driver()
        if not driver:
            return []
        with driver.session() as s:
            result = s.run(query, **(params or {}))
            return [dict(r) for r in result]

    def _ensure_meta_loaded(self):
        """Load metadata and embeddings from Neo4j into memory cache."""
        if self._meta_loaded:
            return
        
        if not self._get_driver():
            log.warning("No Neo4j driver available, cannot load cache")
            return
        
        log.info("Auto-populating VectorSearch cache from Neo4j...")
        
        try:
            # Load tables with embeddings
            results = self._run_query("""
                MATCH (t:Table)
                OPTIONAL MATCH (t)-[:HAS_COLUMN]->(c:Column)
                WITH t, collect(DISTINCT c.name)[0..10] AS cols
                RETURN t.fqn AS fqn, t.name AS name, t.description AS description,
                       t.embedding AS embedding, cols
            """)
            for r in results:
                if not r.get("fqn"):
                    continue
                cols_str = ", ".join(r.get("cols", []) or [])
                doc = f"Table: {r.get('name', '')} ({r['fqn']})\nDesc: {r.get('description', '')}\nCols: {cols_str}"
                item_id = self._id(r["fqn"])
                self._meta[item_id] = {
                    "fqn": r["fqn"],
                    "name": r.get("name", ""),
                    "doc": doc,
                    "_type": "table",
                }
                if r.get("embedding"):
                    self._embeddings[item_id] = r["embedding"]
            log.info(f"  Loaded {len([m for m in self._meta.values() if m.get('_type') == 'table'])} tables")
            
            # Load KPIs with embeddings
            results = self._run_query("""
                MATCH (k:KPI)
                RETURN k.name AS name, k.description AS description,
                       k.expression AS expression, k.embedding AS embedding
            """)
            for r in results:
                if not r.get("name"):
                    continue
                doc = f"KPI: {r['name']}\nDescription: {r.get('description', '')}\nExpression: {r.get('expression', '')}"
                item_id = self._id(r["name"])
                self._meta[item_id] = {
                    "kpi_name": r["name"],
                    "doc": doc,
                    "_type": "kpi",
                }
                if r.get("embedding"):
                    self._embeddings[item_id] = r["embedding"]
            log.info(f"  Loaded {len([m for m in self._meta.values() if m.get('_type') == 'kpi'])} KPIs")
            
            # Load concepts with embeddings
            results = self._run_query("""
                MATCH (b:BusinessConcept)
                RETURN b.name AS name, b.description AS description,
                       b.synonyms AS synonyms, b.embedding AS embedding
            """)
            for r in results:
                if not r.get("name"):
                    continue
                synonyms = r.get("synonyms") or []
                if isinstance(synonyms, str):
                    synonyms = [synonyms]
                doc = f"Concept: {r['name']}\nDescription: {r.get('description', '')}\nSynonyms: {', '.join(synonyms[:5])}"
                item_id = self._id(r["name"])
                self._meta[item_id] = {
                    "concept": r["name"],
                    "doc": doc,
                    "_type": "concept",
                }
                if r.get("embedding"):
                    self._embeddings[item_id] = r["embedding"]
            log.info(f"  Loaded {len([m for m in self._meta.values() if m.get('_type') == 'concept'])} concepts")
            
            # Load examples with embeddings
            results = self._run_query("""
                MATCH (e:QueryExample)
                RETURN e.question AS question, e.sql AS sql, e.cypher AS cypher,
                       e.complexity AS complexity, e.type AS type, e.embedding AS embedding
            """)
            for r in results:
                if not r.get("question"):
                    continue
                ex_type = r.get("type", "sql")
                if ex_type == "cypher":
                    doc = f"Q: {r['question']}\nCypher: {r.get('cypher', '')}"
                else:
                    doc = f"Q: {r['question']}\nSQL: {r.get('sql', '')}"
                item_id = self._id(r["question"])
                self._meta[item_id] = {
                    "nl_query": r["question"],
                    "sql": r.get("sql", ""),
                    "cypher": r.get("cypher", ""),
                    "doc": doc,
                    "complexity": r.get("complexity", "simple"),
                    "type": ex_type,
                    "_type": "example",
                }
                if r.get("embedding"):
                    self._embeddings[item_id] = r["embedding"]
            log.info(f"  Loaded {len([m for m in self._meta.values() if m.get('_type') == 'example'])} examples")
            
            self._meta_loaded = True
            log.info(f"VectorSearch cache populated: {len(self._meta)} items, {len(self._embeddings)} with embeddings")
            
        except Exception as e:
            log.error(f"Error populating VectorSearch cache: {e}")

    @staticmethod
    def _id(t):
        return hashlib.md5(t.encode()).hexdigest()

    def _search(self, item_type, query, k):
        """Search items of a specific type using vector similarity or keyword fallback."""
        self._ensure_meta_loaded()
        
        # Filter to items of the requested type
        type_items = {id: meta for id, meta in self._meta.items() 
                      if meta.get("_type") == item_type}
        
        if not type_items:
            return []
        
        # Try vector search if we have embeddings
        query_emb = self.emb.embed([query])[0]
        has_vectors = query_emb and any(query_emb) and self._embeddings
        
        if has_vectors:
            scored = []
            for item_id, meta in type_items.items():
                item_emb = self._embeddings.get(item_id, [])
                if item_emb and len(item_emb) == len(query_emb):
                    sim = cosine_similarity(query_emb, item_emb)
                    distance = 1.0 - sim  # Lower = better
                else:
                    distance = 1.0  # No embedding, worst score
                scored.append((distance, meta))
            
            scored.sort(key=lambda x: x[0])
            return [{"distance": s[0], **{k: v for k, v in s[1].items() if k != "_type"}} 
                    for s in scored[:k]]
        else:
            # Keyword fallback
            return self._fallback(query, k, type_items)

    def _fallback(self, q, k, items=None):
        """Keyword-overlap fallback when embeddings unavailable."""
        if items is None:
            items = self._meta
        
        qw = set(q.lower().split())
        if not qw:
            return [{"distance": 1.0, **{k: v for k, v in meta.items() if k != "_type"}} 
                    for meta in list(items.values())[:k]]

        scored = []
        for meta in items.values():
            doc_text = " ".join(str(v) for v in meta.values() if not isinstance(v, list)).lower()
            doc_words = set(doc_text.split())
            overlap = len(qw & doc_words)
            distance = 1.0 - (overlap / max(len(qw), 1))
            scored.append((distance, meta))

        scored.sort(key=lambda x: x[0])
        return [{"distance": s[0], **{k: v for k, v in s[1].items() if k != "_type"}} 
                for s in scored[:k]]

    # ─────────────────────────────────────────────────────────────────────────
    # Setup Methods
    # ─────────────────────────────────────────────────────────────────────────

    def create_indexes(self):
        """
        Compute and store embeddings in Neo4j.
        Called by setup script after graph is populated.
        """
        log.info("Computing and storing embeddings in Neo4j...")
        
        if not self._get_driver():
            log.error("No Neo4j driver available")
            return
        
        if not self.emb.model:
            log.error("No embedding model available. Install sentence-transformers.")
            return
        
        def embed(text):
            return self.emb.embed([text])[0]
        
        # Embed tables
        tables = self._run_query("""
            MATCH (t:Table)
            OPTIONAL MATCH (t)-[:HAS_COLUMN]->(c:Column)
            WITH t, collect(DISTINCT c.name)[0..10] AS cols
            RETURN t.fqn AS fqn, t.name AS name, t.description AS description, cols
        """)
        for t in tables:
            if not t.get("fqn"):
                continue
            cols_str = ", ".join(t.get("cols", []) or [])
            doc = f"Table: {t.get('name', '')} ({t['fqn']})\nDesc: {t.get('description', '')}\nCols: {cols_str}"
            emb = embed(doc)
            self._run_query(
                "MATCH (t:Table {fqn: $fqn}) SET t.embedding = $embedding",
                {"fqn": t["fqn"], "embedding": emb}
            )
        log.info(f"  Embedded {len(tables)} tables")
        
        # Embed KPIs
        kpis = self._run_query("""
            MATCH (k:KPI)
            RETURN k.name AS name, k.description AS description, k.expression AS expression
        """)
        for k in kpis:
            if not k.get("name"):
                continue
            doc = f"KPI: {k['name']}\nDescription: {k.get('description', '')}\nExpression: {k.get('expression', '')}"
            emb = embed(doc)
            self._run_query(
                "MATCH (k:KPI {name: $name}) SET k.embedding = $embedding",
                {"name": k["name"], "embedding": emb}
            )
        log.info(f"  Embedded {len(kpis)} KPIs")
        
        # Embed concepts
        concepts = self._run_query("""
            MATCH (b:BusinessConcept)
            RETURN b.name AS name, b.description AS description, b.synonyms AS synonyms
        """)
        for c in concepts:
            if not c.get("name"):
                continue
            synonyms = c.get("synonyms") or []
            if isinstance(synonyms, str):
                synonyms = [synonyms]
            doc = f"Concept: {c['name']}\nDescription: {c.get('description', '')}\nSynonyms: {', '.join(synonyms[:5])}"
            emb = embed(doc)
            self._run_query(
                "MATCH (b:BusinessConcept {name: $name}) SET b.embedding = $embedding",
                {"name": c["name"], "embedding": emb}
            )
        log.info(f"  Embedded {len(concepts)} concepts")
        
        # Embed examples
        examples = self._run_query("""
            MATCH (e:QueryExample)
            RETURN e.question AS question, e.sql AS sql, e.cypher AS cypher, e.type AS type
        """)
        for e in examples:
            if not e.get("question"):
                continue
            ex_type = e.get("type", "sql")
            if ex_type == "cypher":
                doc = f"Q: {e['question']}\nCypher: {e.get('cypher', '')}"
            else:
                doc = f"Q: {e['question']}\nSQL: {e.get('sql', '')}"
            emb = embed(doc)
            self._run_query(
                "MATCH (e:QueryExample {question: $question}) SET e.embedding = $embedding",
                {"question": e["question"], "embedding": emb}
            )
        log.info(f"  Embedded {len(examples)} examples")
        
        log.info("Embeddings stored in Neo4j successfully.")

    def index_from_graph(self, kg=None):
        """Alias for create_indexes() for backward compatibility."""
        self.create_indexes()

    def index_example(self, q, sql, tables):
        """Add a new example with embedding."""
        if not self.emb.model:
            log.warning("No embedding model, cannot index example")
            return
        doc = f"Q: {q}\nSQL: {sql}"
        emb = self.emb.embed([doc])[0]
        self._run_query(
            """
            MERGE (e:QueryExample {question: $question})
            SET e.sql = $sql, e.embedding = $embedding, e.type = 'sql'
            """,
            {"question": q, "sql": sql, "embedding": emb}
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Public Search Methods (same interface as before)
    # ─────────────────────────────────────────────────────────────────────────

    def search_tables(self, q, k=5):
        return [
            {
                "fqn": r.get("fqn", ""),
                "name": r.get("name", ""),
                "doc": r.get("doc", ""),
                "score": r.get("distance", 1),
            }
            for r in self._search("table", q, k)
        ]

    def search_kpis(self, q, k=5):
        return [
            {"kpi_name": r.get("kpi_name", ""), "doc": r.get("doc", "")}
            for r in self._search("kpi", q, k)
        ]

    def search_concepts(self, q, k=5):
        return [
            {"concept": r.get("concept", ""), "doc": r.get("doc", "")}
            for r in self._search("concept", q, k)
        ]

    def search_examples(self, q, k=5):
        return [
            {
                "nl_query": r.get("nl_query", ""),
                "sql": r.get("sql", ""),
                "doc": r.get("doc", ""),
                "complexity": r.get("complexity", "simple"),
            }
            for r in self._search("example", q, k)
        ]