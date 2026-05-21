# Use-Case Agnostic Semantic Layer

This architecture separates the **core engine** (agents, tools, stores) from **configuration** (tables, KPIs, concepts, domain events), making it easy to deploy the same semantic layer for different domains.

## Quick Start

```bash
# Load retail configuration
python config_loader.py --config-dir configs/retail
ONTOLOGY_CONFIG=configs/retail/ontology.yaml adk web .

# Load healthcare configuration  
python config_loader.py --config-dir configs/healthcare
ONTOLOGY_CONFIG=configs/healthcare/ontology.yaml adk web .
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Core Engine (use-case agnostic)                            │
│  agent.py, backend_factory.py, knowledge_graph.py,         │
│  vector_search.py, bq_executor.py, config_loader.py        │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  Configuration (domain-specific)                            │
│  ontology.yaml, domain_layers.yaml, domain_data.json       │
└─────────────────────────────────────────────────────────────┘
                            │
            ┌───────────────┼───────────────┐
            ▼               ▼               ▼
      configs/retail  configs/healthcare  configs/finance
```

## Directory Structure

```
semantic_layer_agentic_poc/
├── agent.py                    # ADK agents (use-case agnostic)
├── backend_factory.py          # Backend factory pattern
├── knowledge_graph.py          # Neo4j interface
├── vector_search.py            # Vector search interface
├── bq_executor.py              # BigQuery executor
├── config_loader.py            # Configuration loader
├── scenario_config.py          # Scenario switching
│
├── configs/
│   ├── retail/                 # Retail domain
│   │   ├── ontology.yaml       # Tables, KPIs, concepts
│   │   ├── domain_layers.yaml  # Event type schemas
│   │   └── domain_data.json    # Actual domain events
│   │
│   ├── healthcare/             # Healthcare domain
│   │   ├── ontology.yaml
│   │   ├── domain_layers.yaml
│   │   └── domain_data.json
│   │
│   └── [your-domain]/          # Add your own
│       ├── ontology.yaml
│       ├── domain_layers.yaml
│       └── domain_data.json
```

## Configuration Files

### 1. ontology.yaml

Defines the semantic layer schema for your domain:

| Section | Purpose |
|---------|---------|
| `meta` | Project name, BigQuery project/dataset |
| `tables` | BigQuery table definitions with columns |
| `joins` | Relationships between tables |
| `kpis` | Metrics with formulas, thresholds, drivers |
| `concepts` | Business concepts for causal reasoning |
| `affects_edges` | Causal relationships (what affects what) |
| `examples` | Few-shot SQL examples by query category |

### 2. domain_layers.yaml

Defines event types that explain metric movements:

| Section | Purpose |
|---------|---------|
| `layers` | Event categories (e.g., supply_incidents, staffing_events) |
| `properties` | Schema for each event type |
| `triggers_concepts` | Which concepts each layer can trigger |
| `trigger_rules` | Conditions for creating TRIGGERS edges |

### 3. domain_data.json

Actual domain events (populated separately):

```json
{
  "supply_incidents": [
    {
      "id": "SI-001",
      "product_id": "SKU-1234",
      "incident_type": "stockout",
      "start_date": "2024-01-15",
      "revenue_impact": 50000
    }
  ],
  "competitor_actions": [...]
}
```

## Adding a New Domain

1. Create a new directory: `configs/your-domain/`

2. Copy and modify the template:
   ```bash
   cp -r configs/retail configs/your-domain
   ```

3. Edit `ontology.yaml`:
   - Update `meta` with your BigQuery project/dataset
   - Define your tables and columns
   - Define your KPIs with appropriate thresholds
   - Define business concepts relevant to your domain
   - Add causal edges (what affects what)
   - Add few-shot SQL examples

4. Edit `domain_layers.yaml`:
   - Define event types for your domain
   - Map events to concepts they trigger

5. Create `domain_data.json` with actual events

6. Load the configuration:
   ```bash
   python config_loader.py --config-dir configs/your-domain
   ```

7. Run ADK:
   ```bash
   ONTOLOGY_CONFIG=configs/your-domain/ontology.yaml adk web .
   ```

## Variable Substitution

Use `${variable}` syntax in ontology.yaml for reusable values:

```yaml
meta:
  bigquery_project: "my-project"
  bigquery_dataset: "my_dataset"

tables:
  - name: orders
    fqn: "${bigquery_project}.${bigquery_dataset}.orders"  # Resolves automatically
```

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `ONTOLOGY_CONFIG` | Path to ontology.yaml | `configs/retail/ontology.yaml` |
| `DOMAIN_LAYERS_CONFIG` | Path to domain_layers.yaml | Same dir as ontology |
| `DOMAIN_DATA` | Path to domain_data.json | Same dir as ontology |
| `SCENARIO` | Backend scenario (1, 2, or 3) | `1` |
| `NEO4J_URI` | Neo4j connection URI | `bolt://localhost:7687` |
| `GEMINI_MODEL` | Gemini model name | `gemini-2.5-flash` |

## Example Domains

### Retail (included)
- **Tables**: orders, products, customers, stores, promotions
- **KPIs**: Revenue, OrderCount, AOV, GrossMargin, CustomerRetention
- **Concepts**: revenue_decline, margin_erosion, customer_churn, supply_disruption
- **Domain layers**: supply_incidents, competitor_actions, pricing_decisions, etc.

### Healthcare (included)
- **Tables**: patients, encounters, procedures, departments, physicians
- **KPIs**: ReadmissionRate, AverageLoS, BedOccupancy, CostPerEncounter
- **Concepts**: readmission_spike, staffing_shortage, bed_shortage, complication_increase
- **Domain layers**: staffing_events, infection_events, capacity_events, etc.

### Finance (template)
- **Tables**: transactions, accounts, customers, products, branches
- **KPIs**: NIM, NPL_Ratio, CAR, ROE, CustomerChurnRate
- **Concepts**: credit_risk_increase, liquidity_pressure, compliance_breach
- **Domain layers**: market_events, regulatory_changes, customer_complaints, etc.

## Validation

```bash
# Dry run (parse only, don't write to stores)
python config_loader.py --config-dir configs/retail --dry-run

# Load ontology only (no domain events)
python config_loader.py --config-dir configs/retail --ontology-only

# Load domain events only
python config_loader.py --config-dir configs/retail --domain-only
```

## Core Engine Components

The core engine is **completely domain-agnostic**:

| Component | What it does |
|-----------|--------------|
| `agent.py` | ADK agent definitions with tools |
| `backend_factory.py` | Returns correct backend based on scenario |
| `knowledge_graph.py` | Generic Neo4j operations (upsert, query) |
| `vector_search.py` | Generic embedding operations |
| `bq_executor.py` | Generic SQL execution |
| `config_loader.py` | Loads YAML configs into stores |

The agents don't know about "retail" or "healthcare" — they work with generic concepts like "tables", "KPIs", "concepts", and "domain events". The domain knowledge comes entirely from configuration.
