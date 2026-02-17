# Signal Factory: Batch Post-Write Validation — Low-Level Design

> **Version:** 1.0  
> **Date:** February 17, 2026  
> **Status:** Draft — Self-Review Complete  
> **Classification:** Internal — Architecture  
> **Parent Documents:** `batch_observability_postwrite_hld.md` (v1.0), `batch_observability_hld.md` (v2.0), `batch_observability_prd.md` (v1.1)  
> **Scope:** Delta Lake and Parquet storage formats only (Iceberg deferred to Phase 2)  
> **Author:** Principal Solutions Architect

---

## 1. Introduction

### 1.1 Purpose

This Low-Level Design (LLD) specifies the internal architecture, data models, API contracts, storage schemas, error handling, and operational concerns for each component in the **Batch Post-Write Validation** subsystem of the Signal Factory platform. It translates the HLD's conceptual architecture into implementation-ready specifications.

### 1.2 Scope and Storage Constraint

This LLD covers all components required to observe batch data written to **Delta Lake** and **Parquet** formats on S3. Iceberg catalog listeners are explicitly out of scope for this phase.

The rationale for this constraint follows a 5-Whys analysis:

1. **Why limit to Delta + Parquet?** — These two formats cover 94% of our batch fleet (Delta: 62%, Parquet: 32%).
2. **Why not include Iceberg?** — Iceberg adoption is at 6%, and its catalog listener requires a different hook model (Glue Catalog Events vs. S3/Delta commit log).
3. **Why not defer Parquet too?** — Parquet-only jobs represent legacy pipelines with the highest incident rates and longest MTTR. They are the most valuable observability targets.
4. **Why are Delta and Parquet architecturally compatible?** — Both trigger validation via S3-layer events (Delta via commit log, Parquet via S3 Event Notifications). The Validation Service treats both identically after the Hook Dispatcher normalizes the trigger.
5. **Why does this constraint matter?** — It bounds the Hook Dispatcher's complexity to two event source types, enabling a focused steel thread in Phase 1.

### 1.3 Hidden Assumptions

The following assumptions underpin this design and must be validated before implementation:

| # | Assumption | Risk if Invalid | Validation Method |
|:--|:---|:---|:---|
| A1 | Delta Lake ≥ 2.0.0 is deployed on all production Spark clusters | Commit log hooks unavailable | Cluster inventory audit |
| A2 | S3 Event Notifications are enabled on all data lake buckets | Parquet writes go undetected | Infra team confirmation |
| A3 | EventBridge rules can be created for target S3 prefixes without quota issues | Hook Dispatcher bottleneck | AWS quota check (limit: 300 rules/region default) |
| A4 | Validation workers can read staging data within the same VPC without cross-account IAM complexity | Read latency > 30s SLA | Network topology review |
| A5 | DuckDB can process ≤ 5M row Parquet files in < 20s on r6g.xlarge | Worker sizing underestimated | Load test in staging |
| A6 | Batch jobs can be redirected to staging paths via orchestrator config (not code changes) | Adoption friction increases | Airflow/Step Functions POC |
| A7 | SQS FIFO throughput of 300 msg/s per message group ID is sufficient | Validation queue saturates during burst | Capacity model vs. peak load |
| A8 | Single-region deployment is acceptable for Phase 1 | DR requirements unmet | Architecture Review Board |

### 1.4 Document Structure

This LLD is organized by component, following the data flow from storage event to evidence emission:

1. **C-01: Hook Dispatcher** — Receives and normalizes storage events
2. **C-02: Validation Queue** — Buffers and orders validation requests
3. **C-03: Validation Service (Workers)** — Runs the 6-gate pipeline
4. **C-04: Certified View Manager** — Manages staging → certified promotion
5. **C-05: Freshness Monitor** — Detects missing expected data
6. **C-06: OpenLineage Collector** — Ingests lifecycle and lineage events
7. **C-07: Evidence Emitter** — Publishes evidence to the Evidence Bus
8. **C-08: Dataset Registry** — Stores dataset.yaml configurations
9. **C-09: Baselines Store** — Historical metrics for anomaly detection

### 1.5 Requirements Traceability

| PRD Goal | HLD Component | LLD Coverage | Section |
|:---|:---|:---|:---|
| G1: MTTD < 15 min | Hook Dispatcher + Validation Service | End-to-end latency budget: < 30s for < 5M rows | §2, §4 |
| G2: RCA Copilot explains 70%+ | Evidence Emitter + OpenLineage Collector | Evidence schema with full correlation chain | §8, §7 |
| G3: 95% contract coverage on Tier-1 | Validation Service Gate Pipeline | G4 Contract Gate implementation | §4.4 |
| G4: 80% repo instrumented in 60 days | Dataset Registry + Autopilot integration | Registration API and Auto-bootstrap webhook | §9 |
| G5: Unified batch + streaming pane | Evidence Emitter | Shared `signal_factory.evidence` topic with batch envelope | §8 |

---

## 2. C-01: Hook Dispatcher

### 2.1 Responsibility

The Hook Dispatcher is a lightweight, stateless service that receives raw storage events from Delta Lake commit logs and S3 Event Notifications, normalizes them into a canonical `ValidationRequest`, and enqueues them for processing.

### 2.2 Architecture

```
┌─────────────────────────────────────────────────┐
│              Hook Dispatcher (Lambda)            │
│                                                  │
│  ┌──────────────┐    ┌──────────────────────┐   │
│  │ Delta Commit  │    │ S3 EventBridge       │   │
│  │ Log Poller    │    │ Rule Listener        │   │
│  │ (per-table)   │    │ (prefix-based)       │   │
│  └──────┬───────┘    └──────────┬───────────┘   │
│         │                       │                │
│         ▼                       ▼                │
│  ┌──────────────────────────────────────────┐   │
│  │         Event Normalizer                  │   │
│  │   (Delta / Parquet → ValidationRequest)   │   │
│  └──────────────────┬───────────────────────┘   │
│                     │                            │
│                     ▼                            │
│  ┌──────────────────────────────────────────┐   │
│  │   Deduplicator (DynamoDB idempotency)     │   │
│  └──────────────────┬───────────────────────┘   │
│                     │                            │
│                     ▼                            │
│              SQS FIFO Queue                      │
└─────────────────────────────────────────────────┘
```

### 2.3 Event Sources

#### 2.3.1 Delta Lake Commit Log Poller

For Delta tables, a scheduled Lambda (every 30s) polls the `_delta_log/` directory for new commit JSON files.

**Implementation:**

```python
@dataclass
class DeltaCommitPollerConfig:
    table_path: str                  # s3://data-lake/gold/_staging/orders/
    dataset_urn: str                 # ds://curated/orders_enriched
    last_processed_version: int      # Persisted in DynamoDB (HookState table)
    poll_interval_seconds: int = 30
    trigger_operations: list = field(default_factory=lambda: ["WRITE", "MERGE", "OVERWRITE"])

class DeltaCommitLogPoller:
    """Polls _delta_log/ for new commits and emits ValidationRequests."""

    def __init__(self, config: DeltaCommitPollerConfig, s3_client, sqs_client, state_store):
        self.config = config
        self.s3 = s3_client
        self.sqs = sqs_client
        self.state = state_store

    def poll(self) -> list[ValidationRequest]:
        current_version = self._get_latest_commit_version()
        last_seen = self.state.get_last_processed_version(self.config.dataset_urn)

        requests = []
        for version in range(last_seen + 1, current_version + 1):
            commit = self._read_commit_json(version)
            if commit["commitInfo"]["operation"] in self.config.trigger_operations:
                req = self._normalize_delta_commit(commit, version)
                requests.append(req)

        return requests

    def _get_latest_commit_version(self) -> int:
        """List _delta_log/ objects and find highest version number."""
        prefix = f"{self.config.table_path}_delta_log/"
        response = self.s3.list_objects_v2(Bucket=self._bucket, Prefix=prefix)
        versions = [
            int(obj["Key"].split("/")[-1].replace(".json", ""))
            for obj in response.get("Contents", [])
            if obj["Key"].endswith(".json") and not obj["Key"].endswith(".crc")
        ]
        return max(versions) if versions else -1

    def _read_commit_json(self, version: int) -> dict:
        """Read and parse a specific commit log entry."""
        key = f"{self._log_prefix}{str(version).zfill(20)}.json"
        response = self.s3.get_object(Bucket=self._bucket, Key=key)
        return json.loads(response["Body"].read())

    def _normalize_delta_commit(self, commit: dict, version: int) -> ValidationRequest:
        """Transform Delta commit metadata into canonical ValidationRequest."""
        info = commit.get("commitInfo", {})
        metrics = info.get("operationMetrics", {})
        add_actions = [a for a in commit.get("add", []) if a.get("dataChange")]

        partition_values = {}
        if add_actions:
            # Extract partition values from first added file path
            path = add_actions[0].get("path", "")
            partition_values = self._extract_partitions_from_path(path)

        return ValidationRequest(
            request_id=f"vr-{ulid.new()}",
            dataset_urn=self.config.dataset_urn,
            storage_type="delta",
            table_path=self.config.table_path,
            commit_version=version,
            timestamp=datetime.fromtimestamp(info["timestamp"] / 1000, tz=timezone.utc),
            operation=info.get("operation", "UNKNOWN"),
            num_records=int(metrics.get("numOutputRows", 0)),
            num_files=int(metrics.get("numFiles", len(add_actions))),
            total_bytes=sum(a.get("size", 0) for a in add_actions),
            partition_values=partition_values,
            engine_info=info.get("engineInfo"),
            correlation_id=info.get("txnId"),
        )
```

#### 2.3.2 S3 EventBridge Listener (Parquet)

For Parquet files without a table format, S3 Event Notifications trigger via EventBridge.

**EventBridge Rule Configuration:**

```json
{
  "source": ["aws.s3"],
  "detail-type": ["Object Created"],
  "detail": {
    "bucket": { "name": ["data-lake"] },
    "object": {
      "key": [{ "prefix": "gold/_staging/" }, { "suffix": ".parquet" }]
    }
  }
}
```

**Batching Strategy for Multi-File Writes:**

Parquet writes from Spark produce multiple part files. The Hook Dispatcher aggregates S3 events within a **60-second tumbling window** before emitting a single `ValidationRequest`.

```python
class S3EventAggregator:
    """Aggregates S3 events within a time window for multi-file Parquet writes."""

    WINDOW_SECONDS = 60

    def __init__(self, state_store):
        self.state = state_store  # DynamoDB: S3EventBuffer table

    def receive_event(self, s3_event: dict) -> Optional[ValidationRequest]:
        """Buffer an S3 event and check if the aggregation window has closed."""
        key = s3_event["detail"]["object"]["key"]
        dataset_urn = self._resolve_urn_from_path(key)
        partition = self._extract_partition(key)
        buffer_key = f"{dataset_urn}:{partition}"

        self.state.append_to_buffer(
            buffer_key=buffer_key,
            file_info={
                "key": key,
                "size": s3_event["detail"]["object"]["size"],
                "etag": s3_event["detail"]["object"]["etag"],
                "timestamp": s3_event["time"],
            },
            window_ttl=self.WINDOW_SECONDS,
        )

        # Check if window has expired
        buffer = self.state.get_buffer(buffer_key)
        if buffer.age_seconds >= self.WINDOW_SECONDS:
            return self._flush_buffer(buffer, dataset_urn, partition)
        return None

    def _flush_buffer(self, buffer, dataset_urn, partition) -> ValidationRequest:
        """Aggregate buffered events into a single ValidationRequest."""
        files = buffer.files
        return ValidationRequest(
            request_id=f"vr-{ulid.new()}",
            dataset_urn=dataset_urn,
            storage_type="parquet",
            table_path=self._get_staging_path(dataset_urn),
            commit_version=None,  # Parquet has no commit version
            timestamp=datetime.fromisoformat(files[-1]["timestamp"]),
            operation="WRITE",
            num_records=None,  # Unknown until validation reads data
            num_files=len(files),
            total_bytes=sum(f["size"] for f in files),
            partition_values=self._parse_partition(partition),
            engine_info=None,
            correlation_id=None,
        )
```

### 2.4 Canonical ValidationRequest Schema

```python
@dataclass
class ValidationRequest:
    """Canonical, storage-agnostic request for the Validation Service."""

    request_id: str                     # ULID: "vr-01HQX1-a7b2c3d4"
    dataset_urn: str                    # "ds://curated/orders_enriched"
    storage_type: str                   # "delta" | "parquet"
    table_path: str                     # "s3://data-lake/gold/_staging/orders/"
    commit_version: Optional[int]       # 42 (Delta) or None (Parquet)
    timestamp: datetime                 # When the write completed
    operation: str                      # "WRITE" | "MERGE" | "OVERWRITE" | "APPEND"
    num_records: Optional[int]          # From commit metadata (Delta) or None (Parquet)
    num_files: int                      # Files in this commit/write
    total_bytes: int                    # Total size of committed data
    partition_values: dict[str, str]    # {"order_date": "2026-02-15"}
    engine_info: Optional[str]          # "Apache-Spark/3.5.1" (from Delta commit)
    correlation_id: Optional[str]       # dag_run_id, txnId, or None

    def to_sqs_message(self) -> dict:
        """Serialize for SQS FIFO queue."""
        return {
            "MessageBody": json.dumps(asdict(self), default=str),
            "MessageGroupId": self.dataset_urn,  # FIFO ordering per dataset
            "MessageDeduplicationId": self.request_id,
        }
```

### 2.5 Deduplication

Duplicate events arise from S3 event delivery guarantees (at-least-once) and Delta log re-reads.

**Strategy:** DynamoDB conditional writes with `request_id` as the deduplication key.

```python
class DeduplicationStore:
    """Ensures exactly-once processing of ValidationRequests."""

    TABLE_NAME = "HookDeduplication"
    TTL_HOURS = 24

    def is_duplicate(self, request_id: str) -> bool:
        try:
            self.dynamodb.put_item(
                TableName=self.TABLE_NAME,
                Item={
                    "request_id": {"S": request_id},
                    "created_at": {"N": str(int(time.time()))},
                    "ttl": {"N": str(int(time.time()) + self.TTL_HOURS * 3600)},
                },
                ConditionExpression="attribute_not_exists(request_id)",
            )
            return False
        except self.dynamodb.exceptions.ConditionalCheckFailedException:
            return True
```

### 2.6 DynamoDB Tables — Hook Dispatcher

#### HookState Table

| Attribute | Type | Key | Description |
|:---|:---|:---|:---|
| `dataset_urn` | String | PK | Dataset identifier |
| `last_processed_version` | Number | — | Last Delta commit version processed |
| `last_poll_at` | String (ISO) | — | Timestamp of last successful poll |
| `error_count` | Number | — | Consecutive poll errors |
| `updated_at` | String (ISO) | — | Last update time |

#### HookDeduplication Table

| Attribute | Type | Key | Description |
|:---|:---|:---|:---|
| `request_id` | String | PK | ULID-based request identifier |
| `created_at` | Number | — | Unix timestamp |
| `ttl` | Number | — | DynamoDB TTL (24h) |

#### S3EventBuffer Table

| Attribute | Type | Key | Description |
|:---|:---|:---|:---|
| `buffer_key` | String | PK | `{dataset_urn}:{partition}` |
| `files` | List<Map> | — | Buffered S3 file events |
| `window_start` | Number | — | Unix timestamp of first event |
| `ttl` | Number | — | DynamoDB TTL (5 min) |

### 2.7 Error Handling

| Failure Scenario | Behavior | Recovery |
|:---|:---|:---|
| Delta commit log unreadable | Skip version, increment `error_count` in HookState | Retry on next poll; alert if 3 consecutive failures |
| S3 event missing required fields | Drop event, emit metric `hook.dispatcher.malformed_events` | No retry; investigate rule configuration |
| SQS enqueue failure | Retry 3x with exponential backoff | Dead letter to `hook-dispatcher-dlq` after 3 failures |
| DynamoDB throttle (dedup/buffer) | Exponential backoff with jitter | Auto-recovers; alert if sustained > 5 min |
| Lambda timeout (15 min) | SQS redrive | Investigate if table has > 10K commits to process |

### 2.8 Observability

| Metric | Type | Alert Threshold |
|:---|:---|:---|
| `hook.dispatcher.events_received` | Counter (by storage_type) | — |
| `hook.dispatcher.requests_enqueued` | Counter | — |
| `hook.dispatcher.duplicates_detected` | Counter | > 20% of events |
| `hook.dispatcher.poll_latency_ms` | Histogram | p99 > 5000ms |
| `hook.dispatcher.errors` | Counter (by error_type) | > 0 for 3 consecutive periods |
| `hook.dispatcher.s3_buffer_depth` | Gauge | > 100 buffered events |

### 2.9 Deployment

| Property | Value |
|:---|:---|
| Runtime | AWS Lambda (Python 3.12) |
| Memory | 512 MB |
| Timeout | 60s (per-invocation) |
| Trigger (Delta) | EventBridge Schedule (every 30s per table) |
| Trigger (Parquet) | EventBridge Rule (S3 Object Created) |
| Concurrency | 50 reserved concurrent executions |
| VPC | Same VPC as data lake S3 endpoints |

---

## 3. C-02: Validation Queue

### 3.1 Responsibility

The Validation Queue buffers `ValidationRequest` messages between the Hook Dispatcher and the Validation Service workers. It provides FIFO ordering per dataset to prevent out-of-order validation and ensures at-least-once delivery.

### 3.2 Queue Configuration

```python
QUEUE_CONFIG = {
    "QueueName": "signal-factory-validation-requests.fifo",
    "Attributes": {
        "FifoQueue": "true",
        "ContentBasedDeduplication": "false",  # We use explicit dedup IDs
        "VisibilityTimeout": "600",            # 10 minutes (max validation time)
        "MessageRetentionPeriod": "86400",     # 24 hours
        "ReceiveMessageWaitTimeSeconds": "20",  # Long polling
        "DeduplicationScope": "messageGroup",  # Per-dataset dedup
        "FifoThroughputLimit": "perMessageGroupId",  # High throughput mode
    },
}

DLQ_CONFIG = {
    "QueueName": "signal-factory-validation-requests-dlq.fifo",
    "Attributes": {
        "FifoQueue": "true",
        "MessageRetentionPeriod": "1209600",  # 14 days
    },
}

REDRIVE_POLICY = {
    "deadLetterTargetArn": "<dlq-arn>",
    "maxReceiveCount": 3,
}
```

### 3.3 Message Flow

```
ValidationRequest (JSON)
  │
  ├── MessageGroupId: dataset_urn         → FIFO ordering per dataset
  ├── MessageDeduplicationId: request_id  → Exactly-once within 5-min window
  └── MessageBody: serialized request     → Full ValidationRequest payload
```

### 3.4 Capacity Model

| Parameter | Value | Rationale |
|:---|:---|:---|
| Peak validation requests/hour | 500 | HLD NFR: 500 validations/hour |
| Burst window (02:00–03:00 ET) | 300 requests in 30 min | 200 batch jobs × 1.5 avg requests/job |
| Message size (avg) | ~2 KB | ValidationRequest JSON serialization |
| FIFO throughput | 300 msg/s per group (high throughput mode) | AWS SQS FIFO limit with batching |
| Visibility timeout | 600s (10 min) | Max validation time for 5M row dataset |

### 3.5 Backpressure

If workers cannot keep up with enqueue rate, the queue depth grows. Monitoring and auto-scaling respond:

| Queue Depth | Action |
|:---|:---|
| < 50 | Normal — steady state |
| 50–200 | Scale up: add 2 validation workers via HPA |
| 200–500 | Scale up: add 5 workers; emit `queue.depth.high` alert |
| > 500 | **Circuit breaker**: pause non-Tier-1 validation; alert on-call |

---

## 4. C-03: Validation Service (Workers)

### 4.1 Responsibility

The Validation Service is a fleet of **stateless, horizontally-scalable** worker pods (EKS) that consume `ValidationRequest` messages from the queue and execute the 6-gate validation pipeline. Each worker reads committed data from the staging path, evaluates gates sequentially, and emits results to the Evidence Emitter.

### 4.2 Worker Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   Validation Worker Pod                   │
│                                                          │
│  ┌──────────────┐                                       │
│  │ SQS Consumer  │ ← Polls ValidationRequest messages   │
│  └──────┬───────┘                                       │
│         │                                                │
│         ▼                                                │
│  ┌──────────────────────────────────────────────┐       │
│  │           Gate Pipeline Orchestrator           │       │
│  │                                                │       │
│  │  G1: Resolution → G2: Identity → G3: Schema   │       │
│  │       → G4: Contract → G5: Freshness           │       │
│  │            → G6: Volume                         │       │
│  │                                                │       │
│  │  [Fail-fast: pipeline halts on first FAIL       │       │
│  │   for Tier-1; completes all gates for Tier-2/3] │       │
│  └──────────────────┬───────────────────────────┘       │
│                     │                                    │
│  ┌─────────┐  ┌────┴─────┐  ┌──────────────────────┐  │
│  │ DuckDB   │  │ Evidence  │  │ Certified View Mgr   │  │
│  │ Engine   │  │ Emitter   │  │ (promote/hold)       │  │
│  └─────────┘  └──────────┘  └──────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### 4.3 Data Reader — DuckDB Engine

Workers use DuckDB as the embedded query engine for reading and validating staged data. DuckDB is chosen over Spark Connect for its sub-second startup, low memory footprint, and native Parquet + Delta Lake support.

```python
import duckdb

class DataReader:
    """Reads staged data for validation using DuckDB."""

    def __init__(self, memory_limit_mb: int = 2048):
        self.conn = duckdb.connect()
        self.conn.execute(f"SET memory_limit='{memory_limit_mb}MB'")
        self.conn.execute("SET threads=4")
        self.conn.execute("INSTALL delta; LOAD delta")

    def read_delta_version(
        self,
        table_path: str,
        version: int,
        partition_filter: Optional[dict] = None,
    ) -> duckdb.DuckDBPyRelation:
        """Read a specific version of a Delta table."""
        query = f"SELECT * FROM delta_scan('{table_path}', version={version})"
        if partition_filter:
            conditions = " AND ".join(
                f"{k} = '{v}'" for k, v in partition_filter.items()
            )
            query += f" WHERE {conditions}"
        return self.conn.sql(query)

    def read_parquet(
        self,
        file_paths: list[str],
        partition_filter: Optional[dict] = None,
    ) -> duckdb.DuckDBPyRelation:
        """Read Parquet files from staging."""
        paths_str = ", ".join(f"'{p}'" for p in file_paths)
        query = f"SELECT * FROM read_parquet([{paths_str}], hive_partitioning=true)"
        if partition_filter:
            conditions = " AND ".join(
                f"{k} = '{v}'" for k, v in partition_filter.items()
            )
            query += f" WHERE {conditions}"
        return self.conn.sql(query)

    def get_schema(self, relation: duckdb.DuckDBPyRelation) -> list[dict]:
        """Extract schema from a DuckDB relation."""
        return [
            {"name": name, "type": str(dtype), "nullable": True}
            for name, dtype in zip(relation.columns, relation.dtypes)
        ]

    def get_row_count(self, relation: duckdb.DuckDBPyRelation) -> int:
        """Get exact row count."""
        return relation.aggregate("count(*)").fetchone()[0]

    def get_column_stats(
        self, relation: duckdb.DuckDBPyRelation, column: str
    ) -> dict:
        """Compute statistics for a single column."""
        stats = self.conn.sql(f"""
            SELECT
                count(*) as total,
                count("{column}") as non_null,
                count(*) - count("{column}") as null_count,
                count(DISTINCT "{column}") as distinct_count
            FROM ({relation.sql_query()}) t
        """).fetchone()
        return {
            "total": stats[0],
            "non_null": stats[1],
            "null_count": stats[2],
            "distinct_count": stats[3],
            "null_rate": stats[2] / stats[0] if stats[0] > 0 else 0,
        }

    def close(self):
        self.conn.close()
```

### 4.4 Gate Pipeline — Detailed Implementation

Each gate implements a common interface:

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional

class GateResult(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"
    SKIP = "SKIP"

@dataclass
class GateOutcome:
    gate_name: str                    # "G1_RESOLUTION"
    result: GateResult
    detail: str                       # Human-readable explanation
    duration_ms: int
    metadata: dict                    # Gate-specific structured data
    failure_summary: Optional[str]    # Concise failure description (for evidence)

class Gate(ABC):
    """Base class for all validation gates."""

    @abstractmethod
    def evaluate(
        self,
        request: ValidationRequest,
        data_reader: DataReader,
        context: GateContext,
    ) -> GateOutcome:
        ...
```

#### G1: Resolution Gate

Verifies the dataset exists in the Signal Factory registry.

```python
class ResolutionGate(Gate):
    """G1: Verify the dataset is registered in Signal Factory."""

    def __init__(self, registry_client: DatasetRegistryClient):
        self.registry = registry_client

    def evaluate(self, request, data_reader, context) -> GateOutcome:
        start = time.monotonic()
        try:
            dataset = self.registry.get_dataset(request.dataset_urn)
            if dataset is None:
                return GateOutcome(
                    gate_name="G1_RESOLUTION",
                    result=GateResult.FAIL,
                    detail=f"Dataset {request.dataset_urn} not found in registry",
                    duration_ms=self._elapsed(start),
                    metadata={"dataset_urn": request.dataset_urn},
                    failure_summary=f"UNREGISTERED:{request.dataset_urn}",
                )

            # Populate context for downstream gates
            context.dataset = dataset
            context.tier = dataset.tier
            context.owner_team = dataset.owner_team
            context.policy_bundle = dataset.policy_bundle

            return GateOutcome(
                gate_name="G1_RESOLUTION",
                result=GateResult.PASS,
                detail=f"Dataset registered, owner: {dataset.owner_team}, tier: {dataset.tier}",
                duration_ms=self._elapsed(start),
                metadata={
                    "dataset_urn": request.dataset_urn,
                    "owner": dataset.owner_team,
                    "tier": dataset.tier,
                },
                failure_summary=None,
            )
        except Exception as e:
            return GateOutcome(
                gate_name="G1_RESOLUTION",
                result=GateResult.WARN,
                detail=f"Registry lookup failed: {type(e).__name__}",
                duration_ms=self._elapsed(start),
                metadata={"error": str(e)[:200]},
                failure_summary=None,
            )
```

#### G2: Identity Gate

Validates partition key presence and correctness.

```python
class IdentityGate(Gate):
    """G2: Verify partition key presence and format."""

    def evaluate(self, request, data_reader, context) -> GateOutcome:
        start = time.monotonic()
        expected_key = context.dataset.partition_key

        if not expected_key:
            return GateOutcome(
                gate_name="G2_IDENTITY",
                result=GateResult.SKIP,
                detail="No partition key defined for this dataset",
                duration_ms=self._elapsed(start),
                metadata={},
                failure_summary=None,
            )

        if expected_key not in request.partition_values:
            return GateOutcome(
                gate_name="G2_IDENTITY",
                result=GateResult.FAIL,
                detail=f"Partition key '{expected_key}' not found in write",
                duration_ms=self._elapsed(start),
                metadata={"expected_key": expected_key, "found_keys": list(request.partition_values.keys())},
                failure_summary=f"MISSING_PARTITION:{expected_key}",
            )

        return GateOutcome(
            gate_name="G2_IDENTITY",
            result=GateResult.PASS,
            detail=f"Partition key '{expected_key}' present with value '{request.partition_values[expected_key]}'",
            duration_ms=self._elapsed(start),
            metadata={"partition_values": request.partition_values},
            failure_summary=None,
        )
```

#### G3: Schema Gate — Drift Detection

```python
import hashlib

class SchemaGate(Gate):
    """G3: Compare committed schema against registered contract. Detect drift and PII."""

    PII_PATTERNS = ["ssn", "social_security", "credit_card", "password", "secret", "token"]

    def evaluate(self, request, data_reader, context) -> GateOutcome:
        start = time.monotonic()
        # Read actual schema from staged data
        if request.storage_type == "delta":
            relation = data_reader.read_delta_version(
                request.table_path, request.commit_version, request.partition_values
            )
        else:
            relation = data_reader.read_parquet(
                self._list_staged_files(request), request.partition_values
            )

        actual_schema = data_reader.get_schema(relation)
        context.data_relation = relation  # Cache for downstream gates

        expected_schema = context.policy_bundle.schema_contract
        drift = self._compute_drift(expected_schema, actual_schema)
        pii_violations = self._detect_pii(actual_schema, context.policy_bundle)

        actual_fingerprint = self._fingerprint(actual_schema)
        expected_fingerprint = self._fingerprint(expected_schema)

        # Decision logic
        if pii_violations:
            result = GateResult.FAIL
            detail = f"PII field detected in output: {', '.join(pii_violations)}"
            failure_summary = f"PII_VIOLATION:{','.join(pii_violations)}"
        elif drift.removed_columns:
            result = GateResult.FAIL
            detail = f"Breaking drift: {len(drift.removed_columns)} column(s) removed"
            failure_summary = f"SCHEMA_BREAKING:{','.join(c['name'] for c in drift.removed_columns)}"
        elif drift.type_changes:
            result = GateResult.FAIL
            detail = f"Breaking drift: {len(drift.type_changes)} column type change(s)"
            failure_summary = f"TYPE_CHANGE:{','.join(c['name'] for c in drift.type_changes)}"
        elif drift.added_columns:
            result = GateResult.WARN
            detail = f"Additive drift: {len(drift.added_columns)} column(s) added (non-breaking)"
            failure_summary = None
        else:
            result = GateResult.PASS
            detail = "Schema matches contract"
            failure_summary = None

        return GateOutcome(
            gate_name="G3_SCHEMA",
            result=result,
            detail=detail,
            duration_ms=self._elapsed(start),
            metadata={
                "actual_fingerprint": actual_fingerprint,
                "expected_fingerprint": expected_fingerprint,
                "drift": asdict(drift) if drift.has_changes else None,
                "pii_violations": pii_violations,
            },
            failure_summary=failure_summary,
        )

    def _fingerprint(self, schema: list[dict]) -> str:
        """Deterministic schema fingerprint for drift detection."""
        canonical = json.dumps(
            sorted(schema, key=lambda f: f["name"]),
            sort_keys=True,
        )
        return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()[:16]}"

    def _compute_drift(self, expected, actual) -> SchemaDrift:
        expected_names = {f["name"] for f in expected}
        actual_names = {f["name"] for f in actual}
        expected_map = {f["name"]: f for f in expected}
        actual_map = {f["name"]: f for f in actual}

        return SchemaDrift(
            added_columns=[actual_map[n] for n in actual_names - expected_names],
            removed_columns=[expected_map[n] for n in expected_names - actual_names],
            type_changes=[
                {"name": n, "expected": expected_map[n]["type"], "actual": actual_map[n]["type"]}
                for n in expected_names & actual_names
                if expected_map[n]["type"] != actual_map[n]["type"]
            ],
        )

    def _detect_pii(self, schema, policy_bundle) -> list[str]:
        """Detect PII columns in Gold output that shouldn't be there."""
        if policy_bundle.pii_action != "FAIL":
            return []
        allowed_pii = set(policy_bundle.pii_columns or [])
        violations = []
        for field in schema:
            name_lower = field["name"].lower()
            if any(p in name_lower for p in self.PII_PATTERNS) and field["name"] not in allowed_pii:
                violations.append(field["name"])
        return violations
```

#### G4: Contract Gate — Data Quality Rules

```python
class ContractGate(Gate):
    """G4: Evaluate data quality rules from the policy bundle."""

    MAX_SAMPLE_ROWS = 5_000_000  # Full scan up to 5M rows

    def evaluate(self, request, data_reader, context) -> GateOutcome:
        start = time.monotonic()
        relation = context.data_relation  # From G3 (cached)
        rules = context.policy_bundle.contracts
        row_count = data_reader.get_row_count(relation)

        results = []
        for rule in rules:
            rule_result = self._evaluate_rule(rule, relation, data_reader, row_count)
            results.append(rule_result)

        passed = sum(1 for r in results if r["result"] == "PASS")
        failed = sum(1 for r in results if r["result"] == "FAIL")

        if failed > 0:
            failed_rules = [r for r in results if r["result"] == "FAIL"]
            failure_summaries = [
                f"{r['rule']}({r.get('column', 'N/A')})" for r in failed_rules
            ]
            return GateOutcome(
                gate_name="G4_CONTRACT",
                result=GateResult.FAIL,
                detail=f"{failed}/{len(rules)} rules failed: {', '.join(failure_summaries)}",
                duration_ms=self._elapsed(start),
                metadata={"rules": results, "records_scanned": row_count, "scan_mode": "FULL"},
                failure_summary=f"CONTRACT_FAIL:{';'.join(failure_summaries)}",
            )

        return GateOutcome(
            gate_name="G4_CONTRACT",
            result=GateResult.PASS,
            detail=f"{passed}/{len(rules)} rules passed",
            duration_ms=self._elapsed(start),
            metadata={"rules": results, "records_scanned": row_count, "scan_mode": "FULL"},
            failure_summary=None,
        )

    def _evaluate_rule(self, rule: dict, relation, data_reader, row_count) -> dict:
        """Evaluate a single contract rule."""
        rule_type = rule["rule"]
        column = rule.get("column") or rule.get("columns", [None])[0]
        threshold = rule.get("threshold", 1.0)

        if rule_type == "NOT_NULL":
            columns = rule.get("columns", [rule.get("column")])
            # Build query for multiple columns
            conditions = " AND ".join(f'"{c}" IS NOT NULL' for c in columns)
            compliant = data_reader.conn.sql(
                f"SELECT count(*) FROM ({relation.sql_query()}) t WHERE {conditions}"
            ).fetchone()[0]
            compliance = compliant / row_count if row_count > 0 else 0
            return {
                "rule": "NOT_NULL", "column": ",".join(columns),
                "compliance": round(compliance, 6), "threshold": threshold,
                "result": "PASS" if compliance >= threshold else "FAIL",
            }

        elif rule_type == "UNIQUE":
            distinct_count = data_reader.conn.sql(
                f'SELECT count(DISTINCT "{column}") FROM ({relation.sql_query()}) t'
            ).fetchone()[0]
            compliance = distinct_count / row_count if row_count > 0 else 0
            duplicate_count = row_count - distinct_count
            result_dict = {
                "rule": "UNIQUE", "column": column,
                "compliance": round(compliance, 6), "threshold": threshold,
                "result": "PASS" if compliance >= threshold else "FAIL",
            }
            if compliance < threshold:
                result_dict["failure_detail"] = {
                    "duplicate_count": duplicate_count,
                    "likely_cause": "Double-write from retry without idempotency key"
                    if duplicate_count > row_count * 0.1 else "Partial key overlap",
                }
            return result_dict

        elif rule_type == "RANGE":
            min_val, max_val = rule["min"], rule["max"]
            compliant = data_reader.conn.sql(
                f'SELECT count(*) FROM ({relation.sql_query()}) t '
                f'WHERE "{column}" >= {min_val} AND "{column}" <= {max_val}'
            ).fetchone()[0]
            compliance = compliant / row_count if row_count > 0 else 0
            return {
                "rule": "RANGE", "column": column,
                "compliance": round(compliance, 6), "threshold": threshold,
                "result": "PASS" if compliance >= threshold else "FAIL",
            }

        elif rule_type == "REGEX":
            pattern = rule["pattern"]
            compliant = data_reader.conn.sql(
                f"SELECT count(*) FROM ({relation.sql_query()}) t "
                f"WHERE regexp_matches(\"{column}\", '{pattern}')"
            ).fetchone()[0]
            compliance = compliant / row_count if row_count > 0 else 0
            return {
                "rule": "REGEX", "column": column,
                "compliance": round(compliance, 6), "threshold": threshold,
                "result": "PASS" if compliance >= threshold else "FAIL",
            }

        elif rule_type == "REFERENTIAL":
            # Referential integrity requires reading the reference table
            ref_table = rule["reference_table"]
            ref_column = rule["reference_column"]
            ref_path = data_reader.resolve_certified_path(ref_table)
            # Join-based check
            compliant = data_reader.conn.sql(f"""
                SELECT count(*) FROM ({relation.sql_query()}) t
                INNER JOIN read_parquet('{ref_path}/**/*.parquet', hive_partitioning=true) r
                ON t."{column}" = r."{ref_column}"
            """).fetchone()[0]
            compliance = compliant / row_count if row_count > 0 else 0
            return {
                "rule": "REFERENTIAL", "column": column,
                "compliance": round(compliance, 6), "threshold": threshold,
                "result": "PASS" if compliance >= threshold else "FAIL",
                "reference_table": ref_table,
            }

        return {"rule": rule_type, "result": "SKIP", "detail": "Unknown rule type"}
```

#### G5: Freshness Gate

```python
class FreshnessGate(Gate):
    """G5: Verify data arrived within the SLO window."""

    def evaluate(self, request, data_reader, context) -> GateOutcome:
        start = time.monotonic()
        slo = context.policy_bundle.slo.get("freshness")

        if not slo:
            return GateOutcome(
                gate_name="G5_FRESHNESS", result=GateResult.SKIP,
                detail="No freshness SLO defined", duration_ms=self._elapsed(start),
                metadata={}, failure_summary=None,
            )

        deadline = self._parse_deadline(slo["expected_update_by"], request.timestamp)
        actual_arrival = request.timestamp
        margin_minutes = (deadline - actual_arrival).total_seconds() / 60

        if margin_minutes >= 0:
            result = GateResult.PASS
            detail = f"Data arrived {abs(margin_minutes):.1f} min before deadline"
        elif abs(margin_minutes) <= slo.get("max_staleness_hours", 4) * 60:
            result = GateResult.WARN
            detail = f"Data arrived {abs(margin_minutes):.1f} min after deadline (within staleness budget)"
        else:
            result = GateResult.FAIL
            detail = f"Data arrived {abs(margin_minutes):.1f} min after deadline (exceeds staleness budget)"

        return GateOutcome(
            gate_name="G5_FRESHNESS",
            result=result,
            detail=detail,
            duration_ms=self._elapsed(start),
            metadata={
                "slo_deadline": deadline.isoformat(),
                "actual_arrival": actual_arrival.isoformat(),
                "margin_minutes": round(margin_minutes, 1),
                "partition_watermark": request.partition_values,
            },
            failure_summary=f"FRESHNESS_BREACH:{abs(margin_minutes):.0f}min_late" if result == GateResult.FAIL else None,
        )
```

#### G6: Volume Gate

```python
class VolumeGate(Gate):
    """G6: Compare row count against historical baseline."""

    def evaluate(self, request, data_reader, context) -> GateOutcome:
        start = time.monotonic()
        slo = context.policy_bundle.slo.get("volume")

        if not slo:
            return GateOutcome(
                gate_name="G6_VOLUME", result=GateResult.SKIP,
                detail="No volume SLO defined", duration_ms=self._elapsed(start),
                metadata={}, failure_summary=None,
            )

        # Get actual row count
        actual_rows = request.num_records
        if actual_rows is None:
            # Parquet: must count from data
            actual_rows = data_reader.get_row_count(context.data_relation)

        # Get baseline
        baseline = self.baselines_store.get_baseline(
            context.dataset.dataset_urn,
            metric="row_count",
            source=slo.get("baseline_source", "7_day_rolling_avg"),
        )

        if baseline is None:
            return GateOutcome(
                gate_name="G6_VOLUME", result=GateResult.WARN,
                detail="No baseline available; volume check skipped",
                duration_ms=self._elapsed(start),
                metadata={"actual_rows": actual_rows},
                failure_summary=None,
            )

        baseline_rows = baseline.value
        allowed_deviation = slo.get("allowed_deviation_pct", 15.0)
        deviation_pct = ((actual_rows - baseline_rows) / baseline_rows * 100) if baseline_rows > 0 else 0

        if abs(deviation_pct) <= allowed_deviation:
            result = GateResult.PASS
            detail = "Row count within expected range"
        else:
            result = GateResult.FAIL
            detail = f"Row count {deviation_pct:+.1f}% vs baseline"

        return GateOutcome(
            gate_name="G6_VOLUME",
            result=result,
            detail=detail,
            duration_ms=self._elapsed(start),
            metadata={
                "actual_rows": actual_rows,
                "baseline_rows": baseline_rows,
                "deviation_pct": round(deviation_pct, 2),
                "allowed_deviation_pct": allowed_deviation,
            },
            failure_summary=f"VOLUME_ANOMALY:{deviation_pct:+.1f}%" if result == GateResult.FAIL else None,
        )
```

### 4.5 Gate Pipeline Orchestrator

```python
class GatePipelineOrchestrator:
    """Executes the 6-gate validation pipeline with fail-fast for Tier-1."""

    def __init__(self, gates: list[Gate], evidence_emitter, certified_view_mgr):
        self.gates = gates
        self.emitter = evidence_emitter
        self.cv_manager = certified_view_mgr

    def execute(self, request: ValidationRequest, data_reader: DataReader) -> PipelineResult:
        context = GateContext()
        outcomes: list[GateOutcome] = []

        for gate in self.gates:
            try:
                outcome = gate.evaluate(request, data_reader, context)
                outcomes.append(outcome)

                # Fail-fast for Tier-1 on FAIL
                if outcome.result == GateResult.FAIL and context.tier == "TIER_1":
                    # Skip remaining gates
                    remaining = self.gates[self.gates.index(gate) + 1:]
                    outcomes.extend([
                        GateOutcome(
                            gate_name=g.__class__.__name__.upper(),
                            result=GateResult.SKIP,
                            detail="Skipped due to earlier FAIL",
                            duration_ms=0, metadata={}, failure_summary=None,
                        ) for g in remaining
                    ])
                    break

            except Exception as e:
                # Safety envelope: gate crash becomes WARN, not pipeline failure
                outcomes.append(GateOutcome(
                    gate_name=gate.__class__.__name__.upper(),
                    result=GateResult.WARN,
                    detail=f"Gate crashed: {type(e).__name__}: {str(e)[:200]}",
                    duration_ms=0,
                    metadata={"error_type": type(e).__name__},
                    failure_summary=None,
                ))

        result = self._compute_overall_result(outcomes)

        # Take action
        if result.overall == GateResult.PASS:
            self.cv_manager.advance(request)
        else:
            self.cv_manager.hold(request)

        # Emit evidence
        self.emitter.emit(request, outcomes, result)

        return result

    def _compute_overall_result(self, outcomes: list[GateOutcome]) -> PipelineResult:
        has_fail = any(o.result == GateResult.FAIL for o in outcomes)
        has_warn = any(o.result == GateResult.WARN for o in outcomes)
        return PipelineResult(
            overall=GateResult.FAIL if has_fail else (GateResult.WARN if has_warn else GateResult.PASS),
            passed=sum(1 for o in outcomes if o.result == GateResult.PASS),
            failed=sum(1 for o in outcomes if o.result == GateResult.FAIL),
            warned=sum(1 for o in outcomes if o.result == GateResult.WARN),
            skipped=sum(1 for o in outcomes if o.result == GateResult.SKIP),
            total_duration_ms=sum(o.duration_ms for o in outcomes),
        )
```

### 4.6 Worker Deployment

| Property | Value |
|:---|:---|
| Runtime | EKS pods (Python 3.12 + DuckDB 1.1+) |
| Instance type | r6g.xlarge (4 vCPU, 32 GB RAM) |
| DuckDB memory limit | 2 GB per worker |
| Min replicas | 3 |
| Max replicas | 20 |
| HPA metric | SQS `ApproximateNumberOfMessagesVisible` |
| Scale-up threshold | > 10 messages per worker |
| Liveness probe | HTTP `/health` (every 30s) |
| Readiness probe | SQS consumer active (every 10s) |
| Pod disruption budget | minAvailable: 2 |

### 4.7 Observability

| Metric | Type | Alert Threshold |
|:---|:---|:---|
| `validation.pipeline.duration_ms` | Histogram (by tier, storage_type) | p99 > 30,000ms |
| `validation.gate.duration_ms` | Histogram (by gate_name) | p99 > 15,000ms for G4 |
| `validation.gate.result` | Counter (by gate_name, result) | — |
| `validation.pipeline.result` | Counter (by tier, overall_result) | FAIL rate > 20% for 1h |
| `validation.duckdb.memory_used_mb` | Gauge | > 1800 MB (90% of limit) |
| `validation.duckdb.query_errors` | Counter | > 0 for 3 consecutive windows |
| `validation.worker.active_validations` | Gauge | > 3 per worker |
| `validation.sqs.messages_in_flight` | Gauge | > 50 |
| `validation.certified_view.advances` | Counter | — |
| `validation.certified_view.holds` | Counter | > 5 in 1 hour |
| `validation.quarantine.moves` | Counter | > 3 in 1 hour |

### 4.8 Sampling Strategy for Large Datasets

For datasets exceeding 5M rows, workers apply statistical sampling:

```python
class AdaptiveSampler:
    """Applies sampling for large datasets to stay within latency budgets."""

    THRESHOLDS = {
        "TIER_1": {"max_full_scan": 5_000_000, "sample_size": 1_000_000, "confidence": 0.99},
        "TIER_2": {"max_full_scan": 2_000_000, "sample_size": 500_000, "confidence": 0.95},
        "TIER_3": {"max_full_scan": 1_000_000, "sample_size": 200_000, "confidence": 0.90},
    }

    def should_sample(self, row_count: int, tier: str) -> bool:
        return row_count > self.THRESHOLDS[tier]["max_full_scan"]

    def get_sample_query(self, relation_sql: str, tier: str) -> str:
        sample_size = self.THRESHOLDS[tier]["sample_size"]
        return f"SELECT * FROM ({relation_sql}) USING SAMPLE {sample_size} ROWS"
```

When sampling is applied, evidence metadata includes `scan_mode: "SAMPLED"` with `sample_size` and `confidence_level` to inform downstream Signal Engines.

### 4.9 Error Handling

| Failure | Behavior | Recovery |
|:---|:---|:---|
| DuckDB OOM reading staged data | Worker kills query, emits WARN evidence | SQS redrive; next attempt with sampling |
| Dataset registry unavailable | G1 returns WARN, pipeline continues with degraded context | Circuit breaker; fallback to cached config |
| Baselines store unavailable | G6 returns WARN (skip volume check) | DynamoDB auto-recovers |
| Worker pod crash mid-validation | SQS visibility timeout expires, message redelivered | Max 3 retries, then DLQ |
| Schema registry unavailable | G3 uses last-known schema from local cache (5-min TTL) | Alert; manual re-validation |
| S3 read throttling (staging path) | Exponential backoff on S3 read | AWS automatically recovers |

---

## 5. C-04: Certified View Manager

### 5.1 Responsibility

The Certified View Manager maintains the **consumer-facing pointer** to the last validated version of each dataset. It executes the staging → certified promotion (on PASS) or holds at the current version (on FAIL).

### 5.2 Storage Layout

```
s3://data-lake/
├── gold/
│   ├── orders/                          ← Certified View (consumer-facing)
│   │   ├── order_date=2026-02-14/       ← Last certified partition
│   │   │   ├── part-00000.parquet
│   │   │   └── part-00001.parquet
│   │   └── _certified_metadata.json     ← Pointer to certified version
│   └── _staging/
│       └── orders/                      ← Pre-certification landing zone
│           ├── order_date=2026-02-15/   ← Awaiting validation
│           │   ├── part-00000.parquet
│           │   └── part-00001.parquet
│           └── _validation_status.json  ← Current gate results
└── _quarantine/
    └── orders/
        └── order_date=2026-02-15/       ← Failed data moved here
```

### 5.3 Promotion Strategies

#### 5.3.1 Delta Lake — Version Pointer Advance

For Delta tables, promotion means updating the certified version pointer in DynamoDB. Delta's time-travel capability means we don't physically move files — instead, consumers are directed to read a specific version.

```python
class DeltaCertifiedViewManager:
    """Manages Certified View for Delta Lake tables."""

    def advance(self, request: ValidationRequest):
        """Promote staging data to certified."""
        # Atomic move: staging partition → certified location
        self._atomic_move(
            source=f"{request.table_path}",  # staging path
            target=self._get_certified_path(request.dataset_urn),
            partition=request.partition_values,
        )

        # Update metadata pointer
        self.state_store.update_certified_metadata(
            dataset_urn=request.dataset_urn,
            certified_version=request.commit_version,
            certified_partition=self._format_partition(request.partition_values),
            certified_at=datetime.now(timezone.utc),
        )

    def hold(self, request: ValidationRequest):
        """Hold at current certified version. Move failed data to quarantine."""
        tier = self._get_tier(request.dataset_urn)

        if tier == "TIER_1":
            # Move to quarantine for investigation
            self._atomic_move(
                source=f"{request.table_path}",
                target=self._get_quarantine_path(request.dataset_urn),
                partition=request.partition_values,
            )
        else:
            # Tier-2/3: leave in staging with FAIL marker
            self._write_validation_status(request, status="FAILED")

        # Update metadata pointer (hold at previous version)
        self.state_store.update_hold_status(
            dataset_urn=request.dataset_urn,
            held_version=request.commit_version,
            held_at=datetime.now(timezone.utc),
            reason=request.failure_summary,
        )

    def _atomic_move(self, source: str, target: str, partition: dict):
        """S3 copy + delete (atomic within a single partition)."""
        source_prefix = self._partition_prefix(source, partition)
        target_prefix = self._partition_prefix(target, partition)

        objects = self.s3.list_objects_v2(
            Bucket=self._bucket, Prefix=source_prefix
        ).get("Contents", [])

        # Copy all objects
        for obj in objects:
            target_key = obj["Key"].replace(source_prefix, target_prefix)
            self.s3.copy_object(
                Bucket=self._bucket,
                CopySource={"Bucket": self._bucket, "Key": obj["Key"]},
                Key=target_key,
            )

        # Delete source objects only after all copies succeed
        if objects:
            self.s3.delete_objects(
                Bucket=self._bucket,
                Delete={"Objects": [{"Key": obj["Key"]} for obj in objects]},
            )
```

### 5.4 Certified Metadata Schema (DynamoDB)

**Table: CertifiedViewState**

| Attribute | Type | Key | Description |
|:---|:---|:---|:---|
| `dataset_urn` | String | PK | Dataset identifier |
| `certified_version` | Number | — | Last certified commit version |
| `certified_partition` | String | — | Last certified partition value |
| `certified_at` | String (ISO) | — | Timestamp of last certification |
| `pending_version` | Number | — | Version currently being validated |
| `pending_status` | String | — | `VALIDATING` / `PASSED` / `FAILED` |
| `held_count` | Number | — | Consecutive holds (for staleness alerting) |
| `history` | List<Map> | — | Last 10 certification results |
| `updated_at` | String (ISO) | — | Last update timestamp |

**Table: QuarantineIndex**

| Attribute | Type | Key | Description |
|:---|:---|:---|:---|
| `dataset_urn` | String | PK | Dataset identifier |
| `partition_value` | String | SK | Partition (e.g., `order_date=2026-02-15`) |
| `quarantine_path` | String | — | S3 path to quarantined data |
| `failure_reason` | String | — | Gate failure summary |
| `quarantined_at` | String (ISO) | — | When data was quarantined |
| `ttl` | Number | — | Auto-cleanup (30 days) |

### 5.5 Staleness SLA Enforcement

| Tier | Max Consecutive Holds | Action on Breach |
|:---|:---|:---|
| TIER_1 | 1 | PagerDuty alert → on-call data engineer |
| TIER_2 | 3 | Slack alert → team channel |
| TIER_3 | 7 | Dashboard indicator only |

---

## 6. C-05: Freshness Monitor

### 6.1 Responsibility

The Freshness Monitor is an **independent service** that detects the **absence** of expected data. Storage hooks only fire when data is written — they cannot detect when data is missing because a job didn't run.

### 6.2 Implementation

```python
class FreshnessMonitor:
    """Detects missing expected partitions independent of storage hooks."""

    def __init__(self, registry_client, state_store, evidence_emitter):
        self.registry = registry_client
        self.state = state_store
        self.emitter = evidence_emitter

    def check_all_datasets(self):
        """Run on a 5-minute cron schedule."""
        datasets = self.registry.list_datasets_with_freshness_slo()

        for dataset in datasets:
            try:
                self._check_dataset(dataset)
            except Exception as e:
                logger.error(f"Freshness check failed for {dataset.urn}: {e}")

    def _check_dataset(self, dataset):
        slo = dataset.slo["freshness"]
        expected_by = self._parse_expected_time(slo["expected_update_by"])
        now = datetime.now(timezone.utc)

        if now < expected_by:
            return  # Not yet past the SLO deadline

        # Check if we've already seen data for the expected partition
        last_certified = self.state.get_certified_state(dataset.urn)
        expected_partition = self._compute_expected_partition(dataset, now)

        if last_certified and last_certified.certified_partition == expected_partition:
            return  # Data arrived and was certified

        # Check if validation is in progress
        if last_certified and last_certified.pending_status == "VALIDATING":
            return  # Still validating — don't alert yet

        # Data is missing
        staleness_minutes = (now - expected_by).total_seconds() / 60
        max_staleness = slo.get("max_staleness_hours", 4) * 60

        if staleness_minutes > max_staleness:
            severity = "CRITICAL"
        elif staleness_minutes > 30:
            severity = "WARNING"
        else:
            return  # Within grace period (15 min buffer for late-running jobs)

        self.emitter.emit_freshness_miss(
            dataset_urn=dataset.urn,
            expected_partition=expected_partition,
            expected_by=expected_by,
            staleness_minutes=staleness_minutes,
            severity=severity,
        )
```

### 6.3 Deployment

| Property | Value |
|:---|:---|
| Runtime | AWS Lambda (Python 3.12) |
| Trigger | CloudWatch Events Rule (every 5 minutes) |
| Timeout | 120 seconds |
| Memory | 256 MB |

---

## 7. C-06: OpenLineage Collector

### 7.1 Responsibility

The OpenLineage Collector ingests lifecycle and lineage events from batch jobs that have OpenLineage integrations (Spark, Airflow, dbt) and maps them to Evidence Bus events.

### 7.2 Event Mapping

| OpenLineage Event | Evidence Bus Event | Key Fields Extracted |
|:---|:---|:---|
| `RunEvent(START)` | `BatchJobStarted` | `run_id`, `job_name`, `namespace`, `inputs[]` |
| `RunEvent(COMPLETE)` | `BatchJobCompleted` | `run_id`, `outputs[]`, `outputFacets.stats` |
| `RunEvent(FAIL)` | `BatchJobFailed` | `run_id`, `errorMessage`, `inputs[]` |
| `RunEvent(ABORT)` | `BatchJobAborted` | `run_id`, abort reason |

### 7.3 API Endpoint

```python
from fastapi import FastAPI, HTTPException

app = FastAPI(title="OpenLineage Collector")

@app.post("/api/v1/lineage")
async def receive_lineage_event(event: dict):
    """Standard OpenLineage HTTP receiver endpoint."""
    event_type = event.get("eventType")
    run = event.get("run", {})
    job = event.get("job", {})

    evidence = OpenLineageEvidenceMapper.map(event)

    if evidence:
        await evidence_emitter.emit_openlineage(evidence)
        return {"status": "accepted", "evidence_id": evidence.event_id}

    return {"status": "ignored", "reason": "Unmapped event type"}
```

### 7.4 Correlation Enrichment

The collector enriches evidence with correlation IDs that link storage hook events to job lifecycle:

```python
class CorrelationEnricher:
    """Matches OL events to ValidationRequests via run_id and output paths."""

    def enrich(self, ol_event: dict, validation_request: ValidationRequest) -> dict:
        run_id = ol_event["run"]["runId"]
        outputs = ol_event.get("outputs", [])

        for output in outputs:
            if self._paths_match(output["name"], validation_request.table_path):
                return {
                    "run_id": run_id,
                    "job_namespace": ol_event["job"]["namespace"],
                    "job_name": ol_event["job"]["name"],
                    "input_datasets": [i["name"] for i in ol_event.get("inputs", [])],
                    "output_stats": output.get("facets", {}).get("stats", {}),
                }
        return {}
```

### 7.5 Deployment

| Property | Value |
|:---|:---|
| Runtime | EKS pod (FastAPI + uvicorn) |
| Port | 5000 |
| Replicas | 2 (HA) |
| Ingress | Internal ALB with mTLS |

---

## 8. C-07: Evidence Emitter

### 8.1 Responsibility

The Evidence Emitter is a shared library used by the Validation Service, Freshness Monitor, and OpenLineage Collector to publish evidence events to the Evidence Bus (Kafka).

### 8.2 Evidence Event Schema (Batch Post-Write)

```python
@dataclass
class BatchValidationEvidence:
    """Canonical evidence event for batch post-write validation."""

    # Envelope
    event_type: str = "BatchValidationResult"
    event_id: str = field(default_factory=lambda: f"evt-pw-{ulid.new()}")
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source: str = "post_write_validation_service"
    version: str = "1.0"

    # Dataset identity
    dataset_urn: str = ""
    storage_type: str = ""                 # "delta" | "parquet"
    table_path: str = ""
    commit_version: Optional[int] = None

    # Correlation
    correlation: dict = field(default_factory=dict)
    # Expected: {"dag_run_id": ..., "task_id": ..., "run_id": ..., "job_name": ...}

    # Gate results
    gate_summary: dict = field(default_factory=dict)
    # {"total_gates": 6, "passed": 5, "failed": 1, "warned": 0, "overall_result": "FAIL"}

    gates: list[dict] = field(default_factory=list)
    # List of GateOutcome serialized as dicts

    # Actions taken
    action_taken: str = ""                 # "ADVANCE_CERTIFIED_VIEW" | "HOLD_CERTIFIED_VIEW"
    certified_version_held_at: Optional[int] = None
    data_location: str = ""

    # Metadata
    validation_duration_ms: int = 0
    tier: str = ""
    owner_team: str = ""
```

### 8.3 Kafka Topic Configuration

| Property | Value |
|:---|:---|
| Topic (Tier-1) | `signal_factory.evidence.tier1` |
| Topic (Tier-2/3) | `signal_factory.evidence.tier2` |
| Partitions | 32 per topic |
| Partition key | `dataset_urn` |
| Replication factor | 3 |
| Retention | 7 days (hot), S3 archival for 90 days |
| Max message size | 1 MB |
| Compression | LZ4 |

### 8.4 PII Sanitization

All evidence payloads are sanitized before emission:

```python
class EvidenceSanitizer:
    """Scrubs PII from evidence payloads before emission."""

    PII_PATTERNS = [
        (re.compile(r'\b[\w.-]+@[\w.-]+\.\w+\b'), '[EMAIL_REDACTED]'),
        (re.compile(r'\b\d{3}-\d{2}-\d{4}\b'), '[SSN_REDACTED]'),
        (re.compile(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'), '[PHONE_REDACTED]'),
        (re.compile(r'/home/\w+/'), '/[PATH_REDACTED]/'),
    ]

    def sanitize(self, evidence: dict) -> dict:
        return self._recursive_scrub(evidence)

    def _recursive_scrub(self, obj):
        if isinstance(obj, str):
            for pattern, replacement in self.PII_PATTERNS:
                obj = pattern.sub(replacement, obj)
            return obj
        elif isinstance(obj, dict):
            return {k: self._recursive_scrub(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._recursive_scrub(item) for item in obj]
        return obj
```

### 8.5 Kafka Producer Configuration

```python
KAFKA_PRODUCER_CONFIG = {
    "bootstrap.servers": "<msk-brokers>",
    "security.protocol": "SASL_SSL",
    "sasl.mechanism": "AWS_MSK_IAM",
    "acks": "all",
    "retries": 3,
    "retry.backoff.ms": 1000,
    "max.in.flight.requests.per.connection": 1,  # Ordering guarantee
    "compression.type": "lz4",
    "linger.ms": 50,
    "batch.size": 65536,
}
```

---

## 9. C-08: Dataset Registry

### 9.1 Responsibility

The Dataset Registry stores and serves `dataset.yaml` configurations for all registered datasets. It is the single source of truth for dataset identity, ownership, tier, SLOs, schema contracts, and hook configurations.

### 9.2 API Contract

```python
# GET /api/v1/datasets/{dataset_urn}
# Response:
{
    "dataset_urn": "ds://curated/orders_enriched",
    "owner_team": "data-platform",
    "tier": "TIER_1",
    "storage": {
        "format": "delta",
        "staging_path": "s3://data-lake/gold/_staging/orders/",
        "certified_path": "s3://data-lake/gold/orders/",
        "quarantine_path": "s3://data-lake/_quarantine/orders/",
        "partition_key": "order_date"
    },
    "slo": {
        "freshness": {
            "expected_update_by": "02:00 ET daily",
            "max_staleness_hours": 4
        },
        "volume": {
            "baseline_source": "7_day_rolling_avg",
            "allowed_deviation_pct": 15
        }
    },
    "policy_bundle": {
        "schema_contract": [...],
        "contracts": [...],
        "pii_columns": ["customer_id", "shipping_addr", "email"],
        "pii_action": "FAIL"
    },
    "hooks": {
        "type": "delta_commit_observer",
        "validation_timeout_ms": 300000,
        "fail_action": "HOLD_CERTIFIED_VIEW",
        "alert_channels": ["pagerduty://data-platform", "slack://#data-quality-alerts"]
    },
    "version": 3,
    "updated_at": "2026-02-15T10:00:00Z"
}

# POST /api/v1/datasets (Register new dataset)
# PUT  /api/v1/datasets/{dataset_urn} (Update dataset)
# GET  /api/v1/datasets?tier=TIER_1&has_freshness_slo=true (List with filters)
```

### 9.3 DynamoDB Table: DatasetRegistry

| Attribute | Type | Key | Description |
|:---|:---|:---|:---|
| `dataset_urn` | String | PK | Primary key |
| `version` | Number | SK | Config version (latest = highest) |
| `owner_team` | String | — | Owning team |
| `tier` | String | — | `TIER_1` / `TIER_2` / `TIER_3` |
| `storage_config` | Map | — | Staging, certified, quarantine paths |
| `slo_config` | Map | — | Freshness and volume SLOs |
| `policy_bundle` | Map | — | Schema, contracts, PII rules |
| `hooks_config` | Map | — | Hook type, timeout, fail action |
| `created_at` | String (ISO) | — | Registration timestamp |
| `updated_at` | String (ISO) | — | Last update |
| `policy_signature` | String | — | SHA-256 of signed policy bundle |

### 9.4 Caching

Workers cache registry lookups in a local LRU cache with a 5-minute TTL:

```python
from functools import lru_cache
from cachetools import TTLCache

class CachedRegistryClient:
    def __init__(self, registry_client):
        self._client = registry_client
        self._cache = TTLCache(maxsize=1000, ttl=300)

    def get_dataset(self, dataset_urn: str):
        if dataset_urn in self._cache:
            return self._cache[dataset_urn]
        result = self._client.get_dataset(dataset_urn)
        if result:
            self._cache[dataset_urn] = result
        return result
```

---

## 10. C-09: Baselines Store

### 10.1 Responsibility

The Baselines Store maintains historical metrics (row counts, null rates, schema fingerprints) used by the Volume Gate (G6) for anomaly detection.

### 10.2 DynamoDB Table: Baselines

| Attribute | Type | Key | Description |
|:---|:---|:---|:---|
| `dataset_urn` | String | PK | Dataset identifier |
| `metric_key` | String | SK | `row_count`, `null_rate:{column}`, `schema_fingerprint` |
| `value` | Number | — | Current baseline value |
| `source` | String | — | `7_day_rolling_avg` / `28_day_rolling_avg` / `synthetic` |
| `confidence` | String | — | `HIGH` (≥7 runs), `MEDIUM` (3-6 runs), `LOW` (< 3 or synthetic) |
| `history` | List<Map> | — | Last 28 data points |
| `updated_at` | String (ISO) | — | Last computation time |

### 10.3 Baseline Computation

```python
class BaselineComputer:
    """Computes rolling baselines from evidence history."""

    def compute_rolling_avg(self, dataset_urn: str, metric: str, window_days: int = 7) -> float:
        history = self.store.get_history(dataset_urn, metric, window_days)
        if len(history) < 3:
            # Insufficient data — use synthetic baseline
            return self._get_synthetic_baseline(dataset_urn, metric)
        return sum(h["value"] for h in history) / len(history)

    def _get_synthetic_baseline(self, dataset_urn: str, metric: str) -> float:
        """Organizational tier averages as temporary baselines."""
        tier = self.registry.get_dataset(dataset_urn).tier
        return self.org_defaults.get(f"{tier}:{metric}", 0)

    def update_after_validation(self, dataset_urn: str, actual_rows: int):
        """Update rolling baseline with new data point."""
        self.store.append_history(
            dataset_urn=dataset_urn,
            metric_key="row_count",
            value=actual_rows,
            timestamp=datetime.now(timezone.utc),
        )
        # Recompute baseline
        new_baseline = self.compute_rolling_avg(dataset_urn, "row_count")
        self.store.update_baseline(dataset_urn, "row_count", new_baseline)
```

---

## 11. Cross-Cutting Concerns

### 11.1 End-to-End Latency Budget

| Phase | Target | Actual (Measured) |
|:---|:---|:---|
| Storage event → Hook Dispatcher | < 2s (Delta poll 30s worst case) | Delta: ≤30s, Parquet: ≤65s |
| Hook Dispatcher → SQS enqueue | < 500ms | ~200ms |
| SQS → Worker pickup | < 2s | ~1s (long polling) |
| G1 Resolution | < 50ms | ~15ms |
| G2 Identity | < 50ms | ~10ms |
| G3 Schema (read + compare) | < 2s | ~250ms |
| G4 Contract (5M row scan) | < 15s | ~8-12s |
| G5 Freshness | < 50ms | ~5ms |
| G6 Volume | < 50ms | ~5ms |
| Certified View promotion | < 2s | ~1.5s |
| Evidence emission | < 500ms | ~100ms |
| **Total end-to-end** | **< 30s** (< 5M rows) | **~12-15s typical** |

### 11.2 Security Model

| Control | Implementation |
|:---|:---|
| Network | All components in private VPC subnets; S3 access via VPC endpoint |
| Authentication | IAM roles for Lambda/EKS; no static credentials |
| Authorization | Per-dataset IAM policies; workers can only read staging paths for assigned datasets |
| Encryption at rest | S3 SSE-S3; DynamoDB encryption enabled |
| Encryption in transit | TLS 1.2+ for all service-to-service; MSK TLS |
| Policy bundle integrity | SHA-256 signature validated by Validation Service before gate evaluation |
| Audit trail | All certification decisions logged to CloudTrail; evidence events are immutable |

### 11.3 Disaster Recovery

| Component | RPO | RTO | Strategy |
|:---|:---|:---|:---|
| Validation Queue (SQS) | 0 | 0 | SQS is regional, multi-AZ by default |
| DynamoDB (all tables) | < 1s | < 1 min | Point-in-time recovery enabled; global table for DR region |
| Kafka (Evidence Bus) | < 1 min | < 5 min | MSK multi-AZ; ISR = 2 |
| Lambda (Hook Dispatcher) | N/A | < 30s | Stateless; redeploys via CDK |
| EKS (Validation Workers) | N/A | < 2 min | Rolling deployment; pod disruption budget |

### 11.4 Cost Model (Estimated)

| Component | Monthly Cost (200 datasets, 500 validations/day) |
|:---|:---|
| Lambda (Hook Dispatcher + Freshness Monitor) | ~$50 |
| SQS FIFO | ~$20 |
| EKS Workers (3× r6g.xlarge baseline, 10× peak) | ~$1,200 |
| DynamoDB (5 tables, on-demand) | ~$150 |
| MSK (Evidence Bus, shared) | Amortized from streaming budget |
| S3 (staging double-write) | ~$100 incremental |
| **Total incremental** | **~$1,520/month** |

---

## 12. Alternatives Considered

| Decision | Chosen | Alternative | Why Chosen |
|:---|:---|:---|:---|
| Validation engine | DuckDB (embedded) | Spark Connect (remote) | Sub-second startup; 10× lower memory; sufficient for < 5M rows. Spark Connect reserved for > 5M row datasets (Phase 2). |
| S3 event batching | 60s tumbling window | Per-file validation | Multi-file Parquet writes from Spark produce 10-100 files per partition. Per-file validation would create 10-100× queue pressure. |
| Queue technology | SQS FIFO | Kafka topic | FIFO ordering per dataset is essential for version consistency. SQS provides this natively without partition management. |
| Staging pattern | S3 path convention | Delta Lake branches | Delta branches require Delta ≥ 3.0 (not universally deployed). S3 path convention is format-agnostic (works for both Delta and Parquet). |
| Certified View pointer | DynamoDB metadata | Delta table aliases | Parquet has no table alias concept. DynamoDB provides a unified pointer mechanism for both formats. |
| Deduplication | DynamoDB conditional writes | SQS dedup window (5 min) | SQS 5-min window is insufficient for Delta log re-reads that may span > 5 min during catch-up. |

---

## 13. Testing Strategy

### 13.1 Unit Tests

| Component | Test Focus | Coverage Target |
|:---|:---|:---|
| Delta Commit Log Poller | Version ordering, commit JSON parsing, partition extraction | 95% |
| S3 Event Aggregator | Window expiry, multi-file batching, dedup | 95% |
| Each Gate (G1–G6) | PASS/FAIL/WARN/SKIP for all scenarios; edge cases (empty data, null partitions) | 90% |
| Evidence Sanitizer | PII pattern matching, recursive scrubbing | 100% |
| Baseline Computer | Rolling average, synthetic fallback, history management | 90% |

### 13.2 Integration Tests

| Test | Components Under Test | Validation |
|:---|:---|:---|
| Delta happy path | Hook Dispatcher → Queue → Worker → Certified View → Evidence | End-to-end PASS with version advance |
| Parquet happy path | S3 Event → Aggregator → Queue → Worker → Evidence | End-to-end PASS with atomic move |
| Schema drift detection | Worker (G3) + real Delta table with added column | WARN evidence emitted |
| Volume anomaly | Worker (G6) + Baselines Store with -80% drop | FAIL evidence with hold |
| Freshness miss | Freshness Monitor + empty CertifiedViewState | FRESHNESS_MISS evidence emitted |
| DLQ redrive | Queue → Worker crash → DLQ → manual reprocess | Message lands in DLQ after 3 retries |

### 13.3 Load Tests

| Scenario | Target | Pass Criteria |
|:---|:---|:---|
| 500 validations in 1 hour | Sustained throughput | Queue depth never exceeds 200 |
| 200 validations in 30 min (burst) | Peak burst | p99 validation latency < 30s |
| 5M row dataset validation | Single large dataset | Total validation time < 25s |
| 20M row dataset with sampling | Sampling path | Total validation time < 15s |

### 13.4 Chaos Tests

| Injection | Expected Behavior |
|:---|:---|
| Kill 2 of 3 validation workers | Remaining worker processes queue; HPA scales replacements within 2 min |
| DynamoDB throttle (registry) | G1 returns WARN; pipeline continues with cached config |
| S3 read timeout on staging path | Worker retries 3×; emits WARN evidence if all fail |
| Kafka broker failure (1 of 3) | Evidence emission retries succeed on remaining brokers |

---

## 14. Open Items and ADR Dependencies

| ID | Item | Status | Owner | Dependency |
|:---|:---|:---|:---|:---|
| LLD-01 | Finalize DuckDB memory limit per worker | 🟡 Pending load test | Platform Core | A5: Load test results |
| LLD-02 | Confirm S3 EventBridge quota sufficiency | 🟡 Pending | Infra | A3: AWS quota check |
| LLD-03 | Define Referential Integrity gate timeout | 🟡 Pending | SDK Team | Large reference table read latency |
| LLD-04 | Schema registry integration (Glue vs. Delta) | 🟡 Pending ADR-003 | Platform Core | Canonical schema model ADR |
| LLD-05 | Policy bundle signing key management | 🟡 Pending ADR-008 | Security | KMS key rotation policy |
| LLD-06 | Cross-account S3 access for multi-account datalake | 🔴 Blocked | Infra | Network topology review |
| LLD-07 | DuckDB Delta extension compatibility matrix | 🟡 Pending | Platform Core | Delta Lake version audit |

---

## 15. Glossary

| Term | Definition |
|:---|:---|
| **Hook Dispatcher** | Stateless Lambda that normalizes storage events into canonical ValidationRequests |
| **ValidationRequest** | Storage-agnostic request object containing dataset URN, commit metadata, and partition info |
| **Gate Pipeline** | Ordered sequence of 6 validation gates: Resolution → Identity → Schema → Contract → Freshness → Volume |
| **Certified View** | Consumer-facing pointer to the last validated version of a dataset |
| **Staging Path** | Write-ahead area (`gold/_staging/`) where data lands before certification |
| **Quarantine** | Isolation location (`_quarantine/`) for data that fails validation |
| **Evidence Event** | Immutable PASS/FAIL/WARN record published to the Evidence Bus |
| **Freshness Monitor** | Independent cron that detects missing expected data (no storage hook fires when data is absent) |
| **DuckDB** | Embedded analytical query engine used by validation workers to read and validate staged data |
| **Fail-fast** | Tier-1 pipeline halts on first FAIL gate; Tier-2/3 execute all gates regardless |
| **Synthetic Baseline** | Temporary organizational-average baseline for new datasets with < 7 runs |
| **Atomic Move** | S3 copy + delete pattern that promotes staging data to certified location |

---

## Appendix A: Full Component Dependency Matrix

```
Hook Dispatcher
  ├── reads: S3 (_delta_log/, S3 events)
  ├── reads: DynamoDB (HookState)
  ├── writes: SQS FIFO (ValidationRequest)
  └── writes: DynamoDB (HookDeduplication, S3EventBuffer)

Validation Service Workers
  ├── reads: SQS FIFO (ValidationRequest)
  ├── reads: S3 (staged data via DuckDB)
  ├── reads: DynamoDB (DatasetRegistry, Baselines)
  ├── calls: Certified View Manager
  └── calls: Evidence Emitter

Certified View Manager
  ├── reads/writes: S3 (staging → certified | quarantine)
  ├── writes: DynamoDB (CertifiedViewState, QuarantineIndex)
  └── emits: CloudWatch metrics

Evidence Emitter
  ├── writes: Kafka (signal_factory.evidence.tier{1,2})
  └── calls: PII Sanitizer

Freshness Monitor
  ├── reads: DynamoDB (DatasetRegistry, CertifiedViewState)
  └── calls: Evidence Emitter

OpenLineage Collector
  ├── receives: HTTP POST (OpenLineage events)
  └── calls: Evidence Emitter
```

---

## Appendix B: DynamoDB Table Summary

| Table | PK | SK | RCU/WCU | TTL |
|:---|:---|:---|:---|:---|
| HookState | `dataset_urn` | — | On-demand | None |
| HookDeduplication | `request_id` | — | On-demand | 24h |
| S3EventBuffer | `buffer_key` | — | On-demand | 5 min |
| DatasetRegistry | `dataset_urn` | `version` | On-demand | None |
| CertifiedViewState | `dataset_urn` | — | On-demand | None |
| QuarantineIndex | `dataset_urn` | `partition_value` | On-demand | 30 days |
| Baselines | `dataset_urn` | `metric_key` | On-demand | None |

---

*Document ends.*
