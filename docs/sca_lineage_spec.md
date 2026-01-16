# SCA Element-Level Lineage Integration Specification

**Version:** 1.0  
**Date:** January 16, 2026  
**Status:** Draft for SCA Team Review  
**Owner:** Signal Factory Platform Team

---

## Executive Summary

This specification defines the interface contract between the **SCA (Static Code Analysis)** team and the **Signal Factory Knowledge Plane** for integrating element-level (column-level) lineage into the Data Observability Platform. The integration enables RCA Copilot to answer critical questions during incidents: "Who writes this column?", "Who reads this column?", and "What is the blast radius of this schema change?"

### Design Stance

| System | Responsibility |
|--------|----------------|
| **Signal Factory** | Runtime truth: what happened, when, impact, first-bad/last-good |
| **SCA Lineage** | Design-time intent: what code *should* read/write at column granularity |

**Critical Boundary:** Lineage is **RCA enrichment**, not a gate. Lineage never blocks ingestion or alerting.

---

## 1. Architecture Overview

### 1.1 Three Truth Sources

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        DATA OBSERVABILITY PLATFORM                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐          │
│   │  RUNTIME TRUTH  │   │ KNOWLEDGE TRUTH │   │ DESIGN-TIME     │          │
│   │                 │   │                 │   │ INTENT (NEW)    │          │
│   │ • Enforcer      │   │ • Dataset/Svc   │   │                 │          │
│   │   Evidence      │   │   Topology      │   │ • SCA LineageSpec│         │
│   │ • Signal        │   │ • Ownership     │   │ • Column-level  │          │
│   │   Engines       │   │ • Causal edges  │   │   dependencies  │          │
│   │ • Incidents     │   │                 │   │ • Transform     │          │
│   │                 │   │                 │   │   mappings      │          │
│   └────────┬────────┘   └────────┬────────┘   └────────┬────────┘          │
│            │                     │                     │                    │
│            └─────────────────────┼─────────────────────┘                    │
│                                  ▼                                          │
│                    ┌─────────────────────────┐                              │
│                    │     KNOWLEDGE PLANE     │                              │
│                    │  Neptune (Graph) +      │                              │
│                    │  DynamoDB (Indexes)     │                              │
│                    └─────────────────────────┘                              │
│                                  │                                          │
│                                  ▼                                          │
│                    ┌─────────────────────────┐                              │
│                    │      RCA COPILOT        │                              │
│                    │  "Who is impacted by    │                              │
│                    │   this schema change?"  │                              │
│                    └─────────────────────────┘                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 Integration Pattern

**Asynchronous LineageSpec event stream → Lineage Ingestor → Neptune topology edges + DynamoDB lookup indexes**

This pattern is:
- Decoupled from runtime processing
- Scalable (bounded cardinality)
- Non-blocking (never affects producer/runtime paths)
- Immediately improves RCA and blast radius analysis

---

## 2. Process Flow

### 2.1 End-to-End Flow: Deployment → Runtime → RCA

```
┌───────────────────────────────────────────────────────────────────────────┐
│  PHASE 1: BUILD TIME (SCA Runs)                                           │
├───────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│   [PR Merged] → [Build Started] → [SCA Analysis] → [LineageSpec Emitted]  │
│                                                                           │
│   SCA extracts:                                                           │
│   • Input datasets + columns                                              │
│   • Output datasets + columns                                             │
│   • Transform mappings (input→output column relationships)                │
│   • Confidence scoring                                                    │
│                                                                           │
└───────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  PHASE 2: DEPLOYMENT (LineageSpec Published)                              │
├───────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│   CI/CD publishes TWO artifacts:                                          │
│                                                                           │
│   1. DeploymentEvent                2. LineageSpec                        │
│      ├─ job: orders-delta-landing      ├─ lineage_spec_id: lspec:...     │
│      ├─ version: 2026.01.16.1          ├─ commit: 9f31c2d                │
│      ├─ commit: 9f31c2d                ├─ inputs: [datasets + columns]   │
│      └─ timestamp: ...                 └─ outputs: [datasets + columns]  │
│                                                                           │
│   CRITICAL JOIN: deployment ↔ lineage_spec via commit SHA                 │
│                                                                           │
└───────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  PHASE 3: LINEAGE INGESTION (Asynchronous)                                │
├───────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│   Lineage Ingestor (Signal Factory service):                              │
│   1. Consumes LineageSpec from Kafka/S3                                   │
│   2. Validates schema + URN formats                                       │
│   3. Writes bounded topology edges to Neptune                             │
│   4. Updates fast lookup indexes in DynamoDB                              │
│                                                                           │
│   NO per-run edges. NO evidence events. Only topology.                    │
│                                                                           │
└───────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  PHASE 4: RUNTIME (Out-of-Band Enforcement)                               │
├───────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│   Incident occurs:                                                        │
│   • Producer deploys, removes `payment_method` from events                │
│   • Schema fingerprint changes: A1B2 → C9D8                               │
│   • Enforcer emits Evidence FAIL with reason_code: FIELD_REMOVED          │
│   • Signal Engine creates SCHEMA_DRIFT incident                           │
│                                                                           │
│   IMPORTANT: Lineage is NOT consulted during gate evaluation              │
│                                                                           │
└───────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  PHASE 5: RCA TRAVERSAL (Lineage Used Here)                               │
├───────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│   RCA Copilot queries:                                                    │
│                                                                           │
│   1. Start from incident → identify implicated column (payment_method)    │
│   2. Query Neptune: "Which jobs READ_COL payment_method?"                 │
│   3. For each job, find deployed version at incident time                 │
│   4. Rank impacted consumers by confidence                                │
│                                                                           │
│   Result:                                                                 │
│   • orders-delta-landing@2026.01.16.1 reads payment_method (HIGH conf)    │
│   • revenue-kpi-dashboard depends on payment_method_norm                  │
│                                                                           │
└───────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Responsibility Split (Critical)

| Question | Answered By | Uses Lineage? |
|----------|-------------|---------------|
| Did the schema change? | Enforcer | ❌ No |
| Which field changed? | Contract-lite gate | ❌ No |
| Is the change compatible? | Contract-lite gate | ❌ No |
| Should we emit FAIL evidence? | Enforcer | ❌ No |
| **Who is impacted downstream?** | **RCA Copilot** | **✅ Yes** |
| **Which jobs read that column?** | **Lineage graph** | **✅ Yes** |
| **Blast radius ranking** | **Lineage + confidence** | **✅ Yes** |

**One-sentence rule:**
> Contract-lite gates answer "Is this data valid?"  
> Lineage answers "Who cares if it isn't?"

---

## 3. Canonical Identifiers

### 3.1 Dataset URN (Required)

Must match Signal Factory dataset identity:

```
urn:dp:<domain>:<dataset>:v<major>
```

**Examples:**
- `urn:dp:orders:order_created:v1`
- `urn:dp:billing:invoice_line:v2`
- `urn:dp:inventory:stock_level:v1`

### 3.2 Column URN (Required for Element-Level Lineage)

Stable column identity within a dataset:

```
urn:col:<dataset_urn>:<column_name>
```

**Examples:**
- `urn:col:urn:dp:orders:order_created:v1:payment_method`
- `urn:col:urn:dp:orders:order_created:v1:customer_id`
- `urn:col:urn:dp:orders:order_created:v1:order_id`

### 3.3 Producer Identity

```
<producer_type>:<producer_name>
```

**Types:** `job:` (batch), `svc:` (service), `pipeline:` (orchestration)

**Examples:**
- `job:orders-delta-landing`
- `svc:order-service`
- `pipeline:orders_daily_agg`

### 3.4 Rename Support (Recommended)

If your organization supports column renames, include:
- `column_id`: Stable UUID that survives renames
- `aliases[]`: Previous names for the column

---

## 4. LineageSpec Schema (v1)

### 4.1 Transport Options

**Option A: Kafka (Recommended)**
```
Topic: signal_factory.lineage_specs
Key: lineage_spec_id
Value: LineageSpec JSON
```

**Option B: S3 + Manifest**
```
S3 prefix: s3://<bucket>/lineage/specs/<org>/<repo>/<commit_sha>/lineage_spec.json
Manifest events: signal_factory.lineage_spec_manifests (Kafka)
```

### 4.2 Delivery Guarantees

- At-least-once delivery (Signal Factory dedupes by `lineage_spec_id`)
- Specs are **immutable** (no updates; new spec = new version)

### 4.3 Required Fields (MUST)

```json
{
  "spec_version": "1.0",
  
  "lineage_spec_id": "lspec:orders-delta-landing:git:9f31c2d",
  
  "emitted_at": "2026-01-16T12:30:00Z",
  
  "producer": {
    "type": "JOB",
    "name": "orders-delta-landing",
    "platform": "SPARK",
    "runtime": "EMR",
    "owner_team": "checkout-platform",
    "repo": "github:org/orders-analytics",
    "ref": {
      "ref_type": "GIT_SHA",
      "ref_value": "9f31c2d"
    }
  },
  
  "lineage": {
    "inputs": [
      {
        "dataset_urn": "urn:dp:orders:order_created:v1",
        "columns": ["customer_id", "order_id", "payment_method"],
        "column_urns": [
          "urn:col:urn:dp:orders:order_created:v1:customer_id",
          "urn:col:urn:dp:orders:order_created:v1:order_id",
          "urn:col:urn:dp:orders:order_created:v1:payment_method"
        ]
      }
    ],
    "outputs": [
      {
        "dataset_urn": "urn:dp:orders:order_created_curated:v1",
        "columns": ["customer_id", "order_id", "payment_method_norm"],
        "column_urns": [
          "urn:col:urn:dp:orders:order_created_curated:v1:customer_id",
          "urn:col:urn:dp:orders:order_created_curated:v1:order_id",
          "urn:col:urn:dp:orders:order_created_curated:v1:payment_method_norm"
        ]
      }
    ]
  },
  
  "confidence": {
    "overall": "HIGH",
    "reasons": ["STATIC_SQL", "SPARK_DF_ANALYSIS"],
    "coverage": {
      "input_columns_pct": 0.92,
      "output_columns_pct": 0.88
    }
  }
}
```

### 4.4 Field Specifications

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `spec_version` | string | ✅ | Schema version (currently "1.0") |
| `lineage_spec_id` | string | ✅ | Globally unique identifier for deduplication |
| `emitted_at` | ISO8601 | ✅ | Timestamp when spec was generated |
| `producer.type` | enum | ✅ | JOB, SERVICE, PIPELINE |
| `producer.name` | string | ✅ | Unique name within type |
| `producer.platform` | enum | ✅ | SPARK, AIRFLOW, DBT, FLINK, CUSTOM |
| `producer.runtime` | enum | ✅ | EMR, EKS, GLUE, DATABRICKS, SNOWFLAKE, OTHER |
| `producer.owner_team` | string | ✅ | Team responsible for this producer |
| `producer.repo` | string | ✅ | Source repository reference |
| `producer.ref` | object | ✅ | Code reference (GIT_SHA, TAG, BRANCH) |
| `lineage.inputs[]` | array | ✅ | Input datasets and columns |
| `lineage.outputs[]` | array | ✅ | Output datasets and columns |
| `confidence.overall` | enum | ✅ | HIGH, MEDIUM, LOW |
| `confidence.reasons[]` | array | ✅ | Why this confidence level |
| `confidence.coverage` | object | ✅ | Column coverage percentages |

### 4.5 Optional Fields (SHOULD)

```json
{
  "transforms": [
    {
      "output_column": "payment_method_norm",
      "input_columns": ["payment_method"],
      "operation": "CASE_NORMALIZE",
      "details_ref": "s3://bucket/transform_details.json"
    }
  ],
  
  "data_access": {
    "queries": ["SELECT customer_id, order_id, UPPER(payment_method) ..."],
    "tables": ["orders_db.raw.orders"]
  },
  
  "tags": ["PII_TOUCHING", "TIER1", "REVENUE_CRITICAL"],
  
  "deployment_linkage": {
    "job_version": "2026.01.16.1",
    "deployed_at": "2026-01-16T10:00:00Z"
  }
}
```

### 4.6 Raw Reference Fallback

If SCA cannot resolve URNs directly, emit raw refs with mapping hints:

```json
{
  "raw_refs": {
    "inputs": [
      {"type": "KAFKA_TOPIC", "value": "orders.created"}
    ],
    "outputs": [
      {"type": "DELTA_TABLE", "value": "s3://bucket/orders_created_curated"}
    ]
  }
}
```

Signal Factory will map raw refs to URNs using its resolution service.

---

## 5. Confidence Model

### 5.1 Confidence Levels

| Level | Criteria | RCA Treatment |
|-------|----------|---------------|
| **HIGH** | Static SQL, resolvable DataFrame plan, strongly inferred | Primary ranking factor |
| **MEDIUM** | Partial resolution, some dynamic behavior, star-expansion resolved | Secondary consideration |
| **LOW** | Heavy dynamic SQL, reflection, runtime-constructed columns | Shown with warning |

### 5.2 Confidence Reasons (Non-Exhaustive)

```
STATIC_SQL              - Pure SQL with explicit column references
SPARK_DF_ANALYSIS       - Spark DataFrame plan fully resolved
DBT_MANIFEST            - dbt manifest provides complete lineage
DYNAMIC_SQL_DETECTED    - Contains string interpolation or dynamic table names
STAR_EXPANSION          - SELECT * resolved at analysis time
REFLECTION_DETECTED     - Uses reflection/metaprogramming
UDF_OPAQUE              - UDFs without documented lineage
CONFIG_DRIVEN           - Table names from config files
```

### 5.3 Coverage Metrics

```json
"coverage": {
  "input_columns_pct": 0.92,   // 92% of input columns resolved
  "output_columns_pct": 0.88   // 88% of output columns resolved
}
```

**Important:** If SCA cannot enumerate columns (e.g., `SELECT *`), emit dataset-level edges and set confidence to LOW.

---

## 6. Neptune Graph Model

### 6.1 Node Types

| Node Type | Label | Properties | Description |
|-----------|-------|------------|-------------|
| **Job** | `Job` | `id`, `name`, `platform`, `runtime`, `owner_team` | Batch processing job |
| **Service** | `Service` | `id`, `name`, `owner_team` | Real-time service |
| **Dataset** | `Dataset` | `urn`, `domain`, `tier` | Data product |
| **Column** | `Column` | `urn`, `name`, `dataset_urn` | Column within dataset |
| **LineageSpec** | `LineageSpec` | `id`, `commit`, `emitted_at`, `confidence` | Lineage artifact |
| **Deployment** | `Deployment` | `id`, `version`, `deployed_at`, `commit` | Specific deployment |

### 6.2 Edge Types

| Edge | From → To | Properties | Meaning |
|------|-----------|------------|---------|
| `READS` | Job/Service → Dataset | `confidence`, `spec_id` | Producer reads this dataset |
| `WRITES` | Job/Service → Dataset | `confidence`, `spec_id` | Producer writes this dataset |
| `READS_COL` | Job/Service → Column | `confidence`, `spec_id` | Producer reads this column |
| `WRITES_COL` | Job/Service → Column | `confidence`, `spec_id` | Producer writes this column |
| `DESCRIBES` | LineageSpec → Job/Service | | Spec describes this producer |
| `AT_COMMIT` | LineageSpec → Commit | | Spec generated at this commit |
| `DEPLOYS` | Deployment → Job/Service | `version` | Deployment of producer |
| `HAS_COLUMN` | Dataset → Column | | Dataset contains column |

### 6.3 Graph Example

```
                    ┌──────────────────────────┐
                    │ Deployment               │
                    │ orders-delta-landing     │
                    │ @2026.01.16.1            │
                    └───────────┬──────────────┘
                                │ [DEPLOYS]
                                ▼
                    ┌──────────────────────────┐
                    │ Job                      │
                    │ orders-delta-landing     │
                    └───────────┬──────────────┘
                                │
         ┌──────────────────────┼──────────────────────┐
         │ [READS]              │ [WRITES]             │
         ▼                      │                      ▼
┌─────────────────┐             │         ┌─────────────────────────┐
│ Dataset         │             │         │ Dataset                 │
│ order_created   │             │         │ order_created_curated   │
│ v1              │             │         │ v1                      │
└────────┬────────┘             │         └────────────┬────────────┘
         │                      │                      │
         │ [HAS_COLUMN]         │         [HAS_COLUMN] │
         ▼                      │                      ▼
┌─────────────────┐             │         ┌─────────────────────────┐
│ Column          │             │         │ Column                  │
│ payment_method  │◄────────────┘         │ payment_method_norm     │
└─────────────────┘  [READS_COL]          └─────────────────────────┘
                                                       ▲
                                                       │ [WRITES_COL]
                                          Job ─────────┘
```

### 6.4 Gremlin Query Patterns

**Find all consumers of a dataset:**
```groovy
g.V().has('Dataset', 'urn', 'urn:dp:orders:order_created:v1')
  .in('READS')
  .project('producer', 'confidence')
    .by('name')
    .by(inE('READS').values('confidence'))
```

**Find all consumers of a specific column:**
```groovy
g.V().has('Column', 'urn', 'urn:col:urn:dp:orders:order_created:v1:payment_method')
  .in('READS_COL')
  .project('producer', 'type', 'confidence')
    .by('name')
    .by('type')
    .by(inE('READS_COL').values('confidence'))
```

**RCA: Blast radius for schema change:**
```groovy
// Starting from incident with implicated column
g.V().has('Column', 'urn', $column_urn)
  .in('READS_COL').as('consumer')
  .out('DEPLOYS').has('deployed_at', lt($incident_time)).as('deployment')
  .select('consumer', 'deployment')
    .by(project('name', 'type'))
    .by('version')
  .order().by(select('consumer').values('confidence'), desc)
```

### 6.5 Cardinality Rules (Critical)

| What to Write | What NOT to Write |
|---------------|-------------------|
| ✅ Dataset-level READS/WRITES | ❌ Per-run execution edges |
| ✅ Column-level READS_COL/WRITES_COL | ❌ Per-record lineage |
| ✅ Deployment nodes (bounded TTL) | ❌ Every schema version as nodes |
| ✅ LineageSpec references | ❌ Full transform AST in graph |

**TTL Policy:**
- Deployment nodes: 30-90 days
- LineageSpec nodes: Keep indefinitely (useful for history)
- Column nodes: Permanent (low cardinality)

---

## 7. DynamoDB Data Model

### 7.1 Lookup Index Tables

These indexes provide fast O(1) lookups for common RCA queries, avoiding expensive Neptune traversals.

**Table: DatasetToWritersIndex**

| PK | SK | Attributes |
|----|----|-----------| 
| `dataset_urn` | `producer#<producer_id>` | `producer_name`, `producer_type`, `confidence`, `spec_id`, `commit`, `updated_at` |

```json
{
  "PK": "urn:dp:orders:order_created:v1",
  "SK": "producer#job:orders-delta-landing",
  "producer_name": "orders-delta-landing",
  "producer_type": "JOB",
  "confidence": "HIGH",
  "spec_id": "lspec:orders-delta-landing:git:9f31c2d",
  "commit": "9f31c2d",
  "updated_at": "2026-01-16T12:30:00Z"
}
```

**Table: DatasetToReadersIndex**

| PK | SK | Attributes |
|----|----|-----------| 
| `dataset_urn` | `consumer#<consumer_id>` | `consumer_name`, `consumer_type`, `confidence`, `spec_id`, `commit`, `updated_at` |

**Table: ColumnToWritersIndex**

| PK | SK | Attributes |
|----|----|-----------| 
| `column_urn` | `producer#<producer_id>` | `producer_name`, `producer_type`, `confidence`, `spec_id`, `updated_at` |

**Table: ColumnToReadersIndex**

| PK | SK | Attributes |
|----|----|-----------| 
| `column_urn` | `consumer#<consumer_id>` | `consumer_name`, `consumer_type`, `confidence`, `spec_id`, `updated_at` |

### 7.2 Access Patterns

| Query | Table | Key Condition |
|-------|-------|---------------|
| Who writes dataset X? | DatasetToWritersIndex | PK = `dataset_urn` |
| Who reads dataset X? | DatasetToReadersIndex | PK = `dataset_urn` |
| Who writes column Y? | ColumnToWritersIndex | PK = `column_urn` |
| Who reads column Y? | ColumnToReadersIndex | PK = `column_urn` |

### 7.3 Index Update Strategy

On LineageSpec ingestion:
1. Parse `lineage.inputs[]` → update DatasetToReadersIndex + ColumnToReadersIndex
2. Parse `lineage.outputs[]` → update DatasetToWritersIndex + ColumnToWritersIndex
3. Set TTL based on `emitted_at` + retention policy (default: 90 days)

---

## 8. Step-by-Step Example: Schema Drift Incident

### Scenario
A producer (`order-service`) deploys and removes `payment_method` from `orders.created` events. RCA Copilot needs to identify impacted downstream consumers.

### Step 1: Build Phase (SCA Runs)

```bash
# Trigger: PR merged for orders-delta-landing Spark job
# SCA analyzes the code and extracts lineage
```

**SCA Output:**
```json
{
  "lineage_spec_id": "lspec:orders-delta-landing:git:9f31c2d",
  "producer": {
    "type": "JOB",
    "name": "orders-delta-landing",
    "platform": "SPARK"
  },
  "lineage": {
    "inputs": [{
      "dataset_urn": "urn:dp:orders:order_created:v1",
      "column_urns": [
        "urn:col:urn:dp:orders:order_created:v1:order_id",
        "urn:col:urn:dp:orders:order_created:v1:customer_id",
        "urn:col:urn:dp:orders:order_created:v1:payment_method"
      ]
    }],
    "outputs": [{
      "dataset_urn": "urn:dp:orders:order_created_curated:v1",
      "column_urns": [
        "urn:col:urn:dp:orders:order_created_curated:v1:payment_method_norm"
      ]
    }]
  },
  "confidence": {"overall": "HIGH"}
}
```

### Step 2: Deployment Phase

CI/CD publishes:
```json
// DeploymentEvent
{
  "job": "orders-delta-landing",
  "version": "2026.01.16.1",
  "commit": "9f31c2d",
  "timestamp": "2026-01-16T10:00:00Z"
}

// LineageSpec (same commit)
{
  "lineage_spec_id": "lspec:orders-delta-landing:git:9f31c2d",
  "commit": "9f31c2d"
}
```

### Step 3: Neptune Graph Updated

**Nodes Created/Updated:**
- `Job:orders-delta-landing`
- `Dataset:urn:dp:orders:order_created:v1`
- `Dataset:urn:dp:orders:order_created_curated:v1`
- `Column:urn:col:urn:dp:orders:order_created:v1:payment_method`
- `Column:urn:col:urn:dp:orders:order_created_curated:v1:payment_method_norm`
- `Deployment:orders-delta-landing@2026.01.16.1`
- `LineageSpec:lspec:orders-delta-landing:git:9f31c2d`

**Edges Created:**
```cypher
(Deployment)-[:DEPLOYS]->(Job)
(LineageSpec)-[:DESCRIBES]->(Job)
(Job)-[:READS]->(Dataset:order_created)
(Job)-[:WRITES]->(Dataset:order_created_curated)
(Job)-[:READS_COL]->(Column:payment_method)
(Job)-[:WRITES_COL]->(Column:payment_method_norm)
```

### Step 4: Runtime Incident

Producer `order-service` deploys and removes `payment_method`:
- Schema fingerprint changes: `A1B2 → C9D8`
- Enforcer emits Evidence FAIL: `FIELD_REMOVED:payment_method`
- Signal Engine creates incident: `INC-2026-01-16-001`

### Step 5: RCA Copilot Traversal

**Query 1: Find consumers of the removed column**
```groovy
g.V().has('Column', 'urn', 'urn:col:urn:dp:orders:order_created:v1:payment_method')
  .in('READS_COL')
  .project('consumer', 'confidence')
```

**Result:**
```json
[
  {"consumer": "orders-delta-landing", "confidence": "HIGH"}
]
```

**Query 2: Get deployment version at incident time**
```groovy
g.V().has('Job', 'name', 'orders-delta-landing')
  .in('DEPLOYS')
  .has('deployed_at', lt('2026-01-16T12:00:00Z'))
  .order().by('deployed_at', desc)
  .limit(1)
```

**Result:**
```json
{"version": "2026.01.16.1", "deployed_at": "2026-01-16T10:00:00Z"}
```

### Step 6: RCA Output

```
INCIDENT: INC-2026-01-16-001
FAILURE SIGNATURE: FIELD_REMOVED:payment_method
DATASET: urn:dp:orders:order_created:v1

ROOT CAUSE:
- Producer: order-service deployed schema change removing payment_method
- First bad: 2026-01-16T11:58:02Z
- Last good: 2026-01-16T11:57:59Z

BLAST RADIUS:
1. orders-delta-landing@2026.01.16.1 (HIGH confidence)
   - Reads payment_method column
   - Likely failing/parsing nulls
   
2. revenue-kpi-dashboard (MEDIUM confidence)
   - Depends on payment_method_norm from curated dataset
   - Downstream KPI degradation likely

SUGGESTED MITIGATIONS:
- Rollback order-service deployment
- OR hotfix orders-delta-landing to handle missing field
- OR quarantine route for affected dataset
```

---

## 9. Operational Requirements

### 9.1 Freshness SLOs

| Tier | Spec Emission | Ingestion Latency |
|------|---------------|-------------------|
| Tier-1 producers | Every merge to main | < 1 hour |
| Tier-2 producers | Every merge to main | < 4 hours |
| Non-Tier producers | Daily at minimum | < 24 hours |

### 9.2 Backfill Support

SCA team must support backfill by:
- Repository + commit range
- Date range
- Producer name filter

### 9.3 Validation Rules (Signal Factory Enforces)

LineageSpec will be **rejected** (dead-lettered) if:
- Missing `lineage_spec_id`, `producer`, or `lineage.inputs/outputs`
- Invalid URN formats
- Dataset URNs unknown AND no `raw_refs` mapping hints provided
- `confidence.overall` missing

### 9.4 Graceful Degradation

Copilot behavior when lineage is unavailable:
```json
{
  "blast_radius": "UNKNOWN",
  "reason": "Lineage unavailable for this producer",
  "suggestion": "Contact checkout-platform team for lineage onboarding"
}
```

---

## 10. Definition of Done (Acceptance Checklist)

SCA is "interface-complete" when:

| # | Requirement | Status |
|---|-------------|--------|
| 1 | Emits LineageSpec v1 to agreed transport (Kafka or S3) | ☐ |
| 2 | At least dataset-level inputs/outputs for 90% of Tier-1 producers | ☐ |
| 3 | Column-level lineage for ≥70% of Tier-1 producers (with confidence+coverage) | ☐ |
| 4 | Dynamic/unknown cases correctly marked LOW confidence (not omitted silently) | ☐ |
| 5 | Backfill supported for onboarding existing producers | ☐ |
| 6 | Spec IDs are immutable and dedupable | ☐ |
| 7 | Commit SHA linkage enables deployment ↔ lineage join | ☐ |
| 8 | Transform hints provided for common patterns (SHOULD) | ☐ |

### Steel Thread Validation

The minimum viable integration is proven when:
1. One Spark job with SCA lineage per deploy
2. One schema drift incident on upstream dataset
3. RCA output shows:
   - Implicated column
   - Top 3 impacted consumers reading that column
   - Deployed version of each consumer at incident time

---

## 11. Anti-Patterns to Avoid

| Anti-Pattern | Why It's Bad | What to Do Instead |
|--------------|--------------|-------------------|
| Push lineage into Enforcer gates | Too heavy, too brittle, creates false negatives | Keep lineage at RCA layer only |
| Write per-run lineage to Neptune | Cardinality explosion | Write only topology edges |
| Require SCA lineage for dataset identity | Creates circular dependency | Signal Factory owns URN mapping |
| Treat LOW confidence as truth | Misleads RCA | Always show confidence in output |
| Overwrite LineageSpec in place | Loses history | Append-only, version by commit |

---

## 12. Governance & Ownership

### Team Responsibilities

| Responsibility | Owner |
|----------------|-------|
| Generating LineageSpec | SCA Team |
| Confidence scoring algorithms | SCA Team |
| Repo/CI integration | SCA Team |
| Ingestion contract & validation | Signal Factory |
| URN normalization & resolution | Signal Factory |
| Neptune/DynamoDB storage model | Signal Factory |
| RCA Copilot usage | Signal Factory |

### SLAs

Lineage is **best-effort** for RCA enrichment:
- Stale lineage should never block alerting or incident creation
- Copilot degrades gracefully showing "lineage unavailable / low confidence"
- No hard dependency from runtime enforcement to lineage availability

---

## Appendix A: Platform-Specific Extraction Guidance

### Spark (SQL + DataFrame)

```
HIGH confidence when:
- SQL strings with explicit column references
- DataFrame operations with resolved column names
- Catalyst plan analysis succeeds

MEDIUM confidence when:
- SELECT * resolved at analysis time
- Config-driven table names

LOW confidence when:
- Dynamic SQL via string interpolation
- Reflection-based schema discovery
```

### dbt

```
HIGH confidence when:
- manifest.json provides complete model lineage
- ref() and source() macros fully resolved

MEDIUM confidence when:
- Jinja templating with static values

LOW confidence when:
- Dynamic model names
- External macro dependencies
```

### Airflow/Orchestration

```
Focus on:
- Operator-level lineage (which task writes which table)
- XCom for inter-task data passing
- Sensor dependencies

Note: Airflow itself doesn't transform data, so lineage is typically
at dataset granularity, not column granularity.
```

---

## Appendix B: JSON Schema (Formal)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "LineageSpec",
  "type": "object",
  "required": ["spec_version", "lineage_spec_id", "emitted_at", "producer", "lineage", "confidence"],
  "properties": {
    "spec_version": {"type": "string", "const": "1.0"},
    "lineage_spec_id": {"type": "string", "pattern": "^lspec:.*$"},
    "emitted_at": {"type": "string", "format": "date-time"},
    "producer": {
      "type": "object",
      "required": ["type", "name", "platform", "runtime", "owner_team", "repo", "ref"],
      "properties": {
        "type": {"enum": ["JOB", "SERVICE", "PIPELINE"]},
        "name": {"type": "string"},
        "platform": {"enum": ["SPARK", "AIRFLOW", "DBT", "FLINK", "CUSTOM"]},
        "runtime": {"enum": ["EMR", "EKS", "GLUE", "DATABRICKS", "SNOWFLAKE", "OTHER"]},
        "owner_team": {"type": "string"},
        "repo": {"type": "string"},
        "ref": {
          "type": "object",
          "required": ["ref_type", "ref_value"],
          "properties": {
            "ref_type": {"enum": ["GIT_SHA", "TAG", "BRANCH"]},
            "ref_value": {"type": "string"}
          }
        }
      }
    },
    "lineage": {
      "type": "object",
      "required": ["inputs", "outputs"],
      "properties": {
        "inputs": {
          "type": "array",
          "items": {"$ref": "#/definitions/DatasetLineage"}
        },
        "outputs": {
          "type": "array",
          "items": {"$ref": "#/definitions/DatasetLineage"}
        }
      }
    },
    "confidence": {
      "type": "object",
      "required": ["overall", "reasons", "coverage"],
      "properties": {
        "overall": {"enum": ["HIGH", "MEDIUM", "LOW"]},
        "reasons": {"type": "array", "items": {"type": "string"}},
        "coverage": {
          "type": "object",
          "properties": {
            "input_columns_pct": {"type": "number", "minimum": 0, "maximum": 1},
            "output_columns_pct": {"type": "number", "minimum": 0, "maximum": 1}
          }
        }
      }
    }
  },
  "definitions": {
    "DatasetLineage": {
      "type": "object",
      "required": ["dataset_urn"],
      "properties": {
        "dataset_urn": {"type": "string", "pattern": "^urn:dp:.*$"},
        "columns": {"type": "array", "items": {"type": "string"}},
        "column_urns": {"type": "array", "items": {"type": "string", "pattern": "^urn:col:.*$"}}
      }
    }
  }
}
```

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-01-16 | Signal Factory Team | Initial specification |

---

*This specification is the authoritative interface contract between SCA and Signal Factory teams. Changes require review from both teams.*
