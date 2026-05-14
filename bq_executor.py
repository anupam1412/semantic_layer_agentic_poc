"""BigQuery SQL Validator + Executor."""

import os
import logging
from dotenv import load_dotenv

# Try both _env and .env for compatibility
if os.path.exists("_env"):
    load_dotenv("_env")
else:
    load_dotenv(".env")

from google.cloud import bigquery

log = logging.getLogger("agentic_sl.bq")


class BQExecutor:
    def __init__(self):
        self.client = bigquery.Client(
            project=os.getenv("GCP_PROJECT", os.getenv("BQ_PROJECT", "acn-uki-ds-data-ai-project")),
            location=os.getenv("GCP_REGION", "europe-west2"),
        )
        self.dataset = os.getenv("BQ_DATASET", "telecom_network_analytics")
        self.max_bytes = 10 * 1024**3  # 10 GB scan limit

    def validate(self, sql: str) -> tuple[bool, str]:
        """Dry-run validation: forbidden keywords, SELECT/WITH start, byte estimate."""
        forbidden = {
            "DELETE", "DROP", "TRUNCATE", "ALTER", "CREATE",
            "INSERT", "UPDATE", "MERGE",
        }
        tokens = sql.upper().split()
        for kw in forbidden:
            if kw in tokens:
                return False, f"Forbidden keyword: {kw}"
        if not tokens or tokens[0] not in ("SELECT", "WITH"):
            return False, "Query must start with SELECT or WITH"
        try:
            job = self.client.query(
                sql,
                job_config=bigquery.QueryJobConfig(
                    dry_run=True, use_query_cache=False
                ),
            )
            if (job.total_bytes_processed or 0) > self.max_bytes:
                return False, f"Scan too large: {job.total_bytes_processed} bytes"
        except Exception as e:
            return False, str(e)[:500]
        return True, "OK"

    def execute(self, sql: str, max_rows: int = 500) -> dict:
        """Execute validated SQL and return up to max_rows."""
        try:
            job = self.client.query(sql)
            result = job.result()
            rows = [dict(r.items()) for i, r in enumerate(result) if i < max_rows]
            return {
                "status": "success",
                "sql": sql,
                "schema": [
                    {"name": f.name, "type": f.field_type} for f in result.schema
                ],
                "rows": rows,
                "total_rows": result.total_rows,
                "bytes_processed": job.total_bytes_processed,
            }
        except Exception as e:
            return {"status": "error", "sql": sql, "error": str(e)[:500]}