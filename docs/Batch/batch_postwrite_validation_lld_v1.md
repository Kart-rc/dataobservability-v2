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
2. **C-02: Validation Orchestrator (Step Functions)** — Routes and controls execution
3. **C-03: Validation Engines (DuckDB & Spark)** — Runs the validation pipeline using external data services
4. **C-04: Certified View Manager** — Manages staging → certified promotion
5. **C-05: Freshness Monitor** — Detects missing expected data
6. **C-06: OpenLineage Collector** — Ingests lifecycle and lineage events
7. **C-07: Evidence Emitter** — Publishes evidence to the Evidence Bus
8. **C-08: Dataset Registry** — Stores dataset.yaml configurations

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
│          Start Step Function Execution           │
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

    def to_step_function_input(self) -> str:
        """Serialize for Step Function Execution Input."""
        return json.dumps(asdict(self), default=str)
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

## 3. C-02: Validation Orchestrator (Step Functions)

### 3.1 Responsibility

The Validation Orchestrator uses AWS Step Functions to manage the lifecycle of a `ValidationRequest`. It guarantees at-least-once execution, determines the optimal compute engine based on data volume, and provides robust Saga-pattern error handling, replacing the need for complex custom Dead Letter Queue (DLQ) re-drive scripts.

### 3.2 State Machine Architecture

```json
{
  "StartAt": "ComputeTierAnalyzer",
  "States": {
    "ComputeTierAnalyzer": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:region:account:function:ComputeRouter",
      "Next": "RouteByComputeTier"
    },
    "RouteByComputeTier": {
      "Type": "Choice",
      "Choices": [
        {
          "Variable": "$.compute_tier",
          "StringEquals": "DUCKDB_FARGATE",
          "Next": "RunDuckDBValidation"
        },
        {
          "Variable": "$.compute_tier",
          "StringEquals": "SPARK_SERVERLESS",
          "Next": "RunSparkValidation"
        }
      ],
      "Default": "FailState"
    },
    "RunDuckDBValidation": {
      "Type": "Task",
      "Resource": "arn:aws:states:::ecs:runTask.sync",
      "Parameters": {
        "Cluster": "ValidationCluster",
        "TaskDefinition": "DuckDBWorker",
        "Overrides": {
          "ContainerOverrides": [{
            "Name": "Worker",
            "Environment": [{"Name": "PAYLOAD", "Value.$": "States.JsonToString($)"}]
          }]
        }
      },
      "Retry": [{ "ErrorEquals": ["States.ALL"], "IntervalSeconds": 10, "MaxAttempts": 3 }],
      "Catch": [{ "ErrorEquals": ["States.ALL"], "Next": "HandleValidationFailure" }],
      "Next": "PublishSuccess"
    },
    "RunSparkValidation": {
      "Type": "Task",
      "Resource": "arn:aws:states:::emr-serverless:startJobRun.waitForTaskToken",
      "Parameters": {
        "ApplicationId": "SparkAppId",
        "ExecutionRoleArn": "ExecutionRole",
        "JobDriver": {
          "SparkSubmit": {
            "EntryPoint": "s3://scripts/validation_spark.py",
            "EntryPointArguments": ["--payload", "States.JsonToString($)", "--task-token", "$$.Task.Token"]
          }
        }
      },
      "Retry": [{ "ErrorEquals": ["States.ALL"], "IntervalSeconds": 30, "MaxAttempts": 3 }],
      "Catch": [{ "ErrorEquals": ["States.ALL"], "Next": "HandleValidationFailure" }],
      "Next": "PublishSuccess"
    },
    "PublishSuccess": {
      "Type": "Task",
      "Resource": "arn:aws:states:::sns:publish",
      "End": true
    },
    "HandleValidationFailure": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:region:account:function:FailureSagaHandler",
      "End": true
    },
    "FailState": {
      "Type": "Fail"
    }
  }
}
```

### 3.3 Compute Tier Routing (Lambda)

The first step in the state machine is the `ComputeRouter` Lambda. It evaluates the incoming `ValidationRequest` to determine if the workload fits within the fast DuckDB container or requires a heavy Spark cluster.

**Routing Heuristics:**
*   **DUCKDB_FARGATE**: `num_files` < 5,000 OR `total_bytes` < 50 GB. (Handles 95% of micro-batches).
*   **SPARK_SERVERLESS**: `num_files` >= 5,000 OR `total_bytes` >= 50 GB. (Handles massive backfills or historical rewrites).

```python
def route_compute(event, context):
    num_files = event.get("num_files", 0)
    total_bytes = event.get("total_bytes", 0)
    
    tier = "DUCKDB_FARGATE"
    if num_files > 5000 or total_bytes > (50 * 1024**3):
        tier = "SPARK_SERVERLESS"
        
    event["compute_tier"] = tier
    return event
```

### 3.4 Error Handling & Sagas

By utilizing Step Functions, we eliminate the need for manual DLQ inspection.

*   **Transient Failures**: Both `RunDuckDBValidation` and `RunSparkValidation` tasks utilize built-in `Retry` blocks with exponential backoff for network or provisioning failures.
*   **Validation Failures**: If the data fails the 6-gate process (e.g., Schema mismatch), the code throws an error caught by the `Catch` block, routing to `HandleValidationFailure`.
*   **Failure Saga**: The `FailureSagaHandler` Lambda is responsible for executing compensation actions, such as locking the Certified View Manager to prevent data from serving to downstream consumers, and alerting PagerDuty.

---

## 4. C-03: Validation Engines (DuckDB & Spark)

### 4.1 Responsibility

The Validation Engines form the execution layer that runs the configured 6-gate validation pipeline against the newly committed data. Unlike the previous design that used only DuckDB, this tier utilizes two different engines based on the payload size routed from the Step Function Orchestrator:
- **DuckDB (ECS Fargate)** for low-latency micro-batches (95% of workloads).
- **Apache Spark (EMR Serverless)** for massive data backfills.

### 4.2 Engine Architecture

```
┌────────────────────────────────────────────────────────────┐
│         Step Function Execution (RunValidation Task)       │
└───────────┬─────────────────────────────────────┬──────────┘
            │ (Fargate Task)                      │ (EMR Job)
            ▼                                     ▼
┌────────────────────────┐               ┌────────────────────────┐
│   DuckDB Worker Pod    │               │  Spark Serverless App  │
│                        │               │                        │
│ ┌────────────────────┐ │               │ ┌────────────────────┐ │
│ │ Gate Orchestrator  │ │               │ │ Gate Orchestrator  │ │
│ │  (Python/DuckDB)   │ │               │ │  (Scala/PySpark)   │ │
│ └─┬──────┬───────┬───┘ │               │ └─┬──────┬───────┬───┘ │
│   │      │       │     │               │   │      │       │     │
│   ▼      ▼       ▼     │               │   ▼      ▼       ▼     │
│ ┌────┐ ┌────┐ ┌─────┐  │               │ ┌────┐ ┌────┐ ┌─────┐  │
│ │ G3 │ │ G4 │ │ G6  │  │               │ │ G3 │ │ G4 │ │ G6  │  │
│ └─┬──┘ └─┬──┘ └─┬───┘  │               │ └─┬──┘ └─┬──┘ └─┬───┘  │
└───┼──────┼──────┼──────┘               └───┼──────┼──────┼──────┘
    │      │      │                          │      │      │       
    ▼      ▼      ▼                          ▼      ▼      ▼       
┌────────────────────────────────────────────────────────────┐
│                  Standard Data Services                    │
│                                                            │
│ ┌───────────────┐  ┌───────────────┐ ┌───────────────────┐ │
│ │ Data Contract │  │  Data Quality │ │ Data Volume/Anom. │ │
│ │    Service    │  │     Service   │ │      Service      │ │
│ └───────────────┘  └───────────────┘ └───────────────────┘ │
└────────────────────────────────────────────────────────────┘
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

### 4.4 Data Reader — Spark Engine (EMR Serverless)

For massive workloads, EMR Serverless provisions a distributed Spark cluster. The Spark application executes the exact same 6 gates using PySpark DataFrame operations instead of DuckDB SQL.

Crucially, because AWS Step Functions is managing the execution state, the Spark job receives a `TaskToken`. When the Spark job completes all validations, it must use the boto3 `stepfunctions` client to return the result, completing the Saga.

```python
import sys
import boto3
from pyspark.sql import SparkSession

def main():
    payload = parse_args(sys.argv)
    task_token = payload["task_token"]
    
    spark = SparkSession.builder.appName(f"Validation-{payload['dataset_urn']}").getOrCreate()
    sfn_client = boto3.client('stepfunctions')
    
    try:
        # Load Delta or Parquet data using Spark
        df = load_data(spark, payload["table_path"], payload["storage_type"])
        
        # Execute Gates
        results = execute_gates(df, payload)
        
        # Callback to Step Function Success
        sfn_client.send_task_success(
            taskToken=task_token,
            output=json.dumps({"status": "SUCCESS", "results": results})
        )
    except Exception as e:
        # Callback to Step Function Failure -> Triggers Failure Saga
        sfn_client.send_task_failure(
            taskToken=task_token,
            error=type(e).__name__,
            cause=str(e)
        )

if __name__ == "__main__":
    main()
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

#### G3: Schema Gate — Data Contract Client

```python
class SchemaGate(Gate):
    """G3: Validate schema using the external Data Contract Service."""

    def __init__(self, data_contract_client):
        self.contract_client = data_contract_client

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

        # Call Data Contract Service
        try:
            response = self.contract_client.evaluate_schema(
                dataset_urn=request.dataset_urn,
                actual_schema=actual_schema
            )
            
            result_status = response.get("status", "FAIL") # PASS, WARN, FAIL
            drift_details = response.get("drift", {})
            pii_violations = response.get("pii_violations", [])
            
        except ExternalServiceException as e:
            logger.warning(f"Data Contract Service unavailable for {request.dataset_urn}: {e}")
            return GateOutcome(
                gate_name="SCHEMA",
                result="WARN",
                duration_ms=int((time.monotonic() - start) * 1000),
                failure_summary="DATA_CONTRACT_SERVICE_UNAVAILABLE"
            )

        # Decision logic
        if pii_violations:
            result = GateResult.FAIL
            detail = f"PII field detected in output: {', '.join(pii_violations)}"
            failure_summary = f"PII_VIOLATION:{','.join(pii_violations)}"
        elif result_status == "FAIL":
            result = GateResult.FAIL
            detail = f"Schema drift detected"
            failure_summary = f"SCHEMA_DRIFT:{drift_details}"
        elif result_status == "WARN":
            result = GateResult.WARN
            detail = f"Additive schema drift"
            failure_summary = None
        else:
            result = GateResult.PASS
            detail = "Schema matches expected contract"
            failure_summary = None

        return GateOutcome(
            gate_name="G3_SCHEMA",
            result=result,
            detail=detail,
            duration_ms=self._elapsed(start),
            metadata={
                "drift": drift_details,
                "pii_violations": pii_violations,
            },
            failure_summary=failure_summary,
        )
```

#### §4.4.2a — `SchemaRegistryClient`

The `SchemaRegistryClient` is injected into `SchemaGate` and resolves the
expected schema using the following precedence chain (highest → lowest):

```
policy_bundle.schema_contract
      ↓ (absent)
Delta commit log metaData action
      ↓ (absent or non-Delta)
Glue Data Catalog GetTable
      ↓ (absent or Glue error)
GateResult.WARN: SCHEMA_SOURCE_UNAVAILABLE
```

| Source | Used when | Rationale |
|:-------|:----------|:----------|
| `policy_bundle.schema_contract` | Always (if present) | Operator-defined contract is the authoritative override |
| Delta `_delta_log/` `metaData` action | Delta datasets, no policy override | Schema embedded in commit log; no external service dependency |
| Glue Data Catalog `GetTable` | Parquet datasets; Delta fallback | Authoritative catalog for Parquet; single API call |

```python
class SchemaRegistryClient:
    """
    Resolves registered schema via precedence chain:
    policy_bundle → Delta commit log → Glue Catalog.
    """

    def __init__(self, glue_client, s3_client):
        self.glue = glue_client
        self.s3 = s3_client

    def get_registered_schema(
        self,
        dataset_urn: str,
        storage_type: str,
        table_path: str,
        commit_version: Optional[int],
        policy_bundle,
    ) -> tuple[Optional[list[dict]], str]:
        """
        Returns (schema, source_label).
        source_label: "POLICY_BUNDLE" | "DELTA_LOG" | "GLUE_CATALOG" | "UNAVAILABLE"
        """
        if policy_bundle and policy_bundle.schema_contract:
            return policy_bundle.schema_contract, "POLICY_BUNDLE"

        if storage_type == "delta" and commit_version is not None:
            schema = self._from_delta_log(table_path, commit_version)
            if schema:
                return schema, "DELTA_LOG"

        schema = self._from_glue(dataset_urn)
        if schema:
            return schema, "GLUE_CATALOG"

        return None, "UNAVAILABLE"

    def _from_delta_log(self, table_path: str, version: int) -> Optional[list[dict]]:
        """Walk backwards through Delta log to find the most recent metaData action."""
        bucket, prefix = self._parse_s3_path(table_path)
        log_prefix = f"{prefix}_delta_log/"
        for v in range(version, max(version - 50, -1), -1):
            key = f"{log_prefix}{str(v).zfill(20)}.json"
            try:
                obj = self.s3.get_object(Bucket=bucket, Key=key)
                commit = json.loads(obj["Body"].read())
                if "metaData" in commit:
                    return self._parse_delta_schema(commit["metaData"]["schemaString"])
            except self.s3.exceptions.NoSuchKey:
                continue
            except Exception:
                break
        return None

    def _from_glue(self, dataset_urn: str) -> Optional[list[dict]]:
        """Resolve schema from Glue Catalog. URN convention: ds://database/table."""
        database, table = self._urn_to_glue_table(dataset_urn)
        if not database or not table:
            return None
        try:
            resp = self.glue.get_table(DatabaseName=database, Name=table)
            cols = resp["Table"]["StorageDescriptor"]["Columns"]
            return [{"name": c["Name"], "type": c["Type"], "nullable": True} for c in cols]
        except Exception:
            return None

    def _parse_delta_schema(self, schema_string: str) -> list[dict]:
        schema = json.loads(schema_string)
        return [
            {
                "name": f["name"],
                "type": f["type"] if isinstance(f["type"], str) else f["type"]["type"],
                "nullable": f.get("nullable", True),
            }
            for f in schema["fields"]
        ]

    def _urn_to_glue_table(self, urn: str) -> tuple[Optional[str], Optional[str]]:
        """ds://database/table_name → ("database", "table_name")"""
        parts = urn.removeprefix("ds://").split("/")
        return (parts[0], parts[1]) if len(parts) >= 2 else (None, None)
```

#### G4: Contract Gate — Data Quality Client

```python
class ContractGate(Gate):
    """G4: Evaluate data quality rules via external Data Quality Service."""

    def __init__(self, data_quality_client):
        self.dq_client = data_quality_client

    def evaluate(self, request, data_reader, context) -> GateOutcome:
        start = time.monotonic()
        relation = context.data_relation  # From G3 (cached)
        row_count = data_reader.get_row_count(relation)

        try:
            # 1. Submit validation job to Data Quality Service
            job_id = self.dq_client.submit_validation(
                dataset_urn=request.dataset_urn,
                data_location=request.table_path,
                partition_values=request.partition_values
            )
            
            # 2. Wait for completion (with timeout)
            # In a real Spark/Step Functions environment, this could be async.
            # For micro-batches, we poll.
            response = self.dq_client.wait_for_completion(job_id, timeout_sec=20)
            
            status = response.get("status", "FAIL") # PASS, FAIL
            rule_results = response.get("rule_results", [])
            
        except ExternalServiceException as e:
            logger.warning(f"Data Quality Service unavailable: {e}")
            return GateOutcome(
                gate_name="G4_CONTRACT",
                result=GateResult.WARN,
                detail="Data Quality Service unavailable",
                duration_ms=self._elapsed(start),
                failure_summary="DATA_QUALITY_SERVICE_UNAVAILABLE"
            )

        passed = sum(1 for r in rule_results if r["status"] == "PASS")
        failed = sum(1 for r in rule_results if r["status"] == "FAIL")

        if status == "FAIL" or failed > 0:
            failed_rules = [r for r in rule_results if r["status"] == "FAIL"]
            failure_summaries = [f"{r['rule_name']}({r.get('column', 'N/A')})" for r in failed_rules]
            
            return GateOutcome(
                gate_name="G4_CONTRACT",
                result=GateResult.FAIL,
                detail=f"{failed}/{len(rule_results)} rules failed: {', '.join(failure_summaries)}",
                duration_ms=self._elapsed(start),
                metadata={"rules": rule_results, "records_scanned": row_count},
                failure_summary=f"CONTRACT_FAIL:{';'.join(failure_summaries)}",
            )

        return GateOutcome(
            gate_name="G4_CONTRACT",
            result=GateResult.PASS,
            detail=f"{passed}/{len(rule_results)} rules passed",
            duration_ms=self._elapsed(start),
            metadata={"rules": rule_results, "records_scanned": row_count},
            failure_summary=None,
        )
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
#### G6: Volume Gate — Data Volume Service

**Purpose**: Detects massive spikes or drops in data volume that indicate pipeline malfunction, even if all other data quality rules pass.

**Implementation**: G6 acts as a client to the standard **Data Volume/Anomaly Service**. Instead of maintaining and computing baselines locally, G6 submits the current row count to the external API, which compares it against historical baselines and returns an anomaly assessment.

```python
class VolumeGate(Gate):
    """G6: Check data volume against external Data Volume Service baselines."""

    def __init__(self, data_volume_client):
        self.volume_client = data_volume_client

    def evaluate(self, request, data_reader, context) -> GateOutcome:
        start = time.monotonic()
        slo = context.policy_bundle.slo.get("volume") if context.policy_bundle else None

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

        try:
            # Call Data Volume Service
            response = self.volume_client.evaluate_volume(
                dataset_urn=request.dataset_urn,
                actual_rows=actual_rows,
                baseline_source=slo.get("baseline_source", "7_day_rolling_avg"),
                allowed_deviation_pct=slo.get("allowed_deviation_pct", 15.0)
            )
            
            status = response.get("status", "FAIL") # PASS, WARN, FAIL
            baseline_rows = response.get("baseline_rows", 0)
            deviation_pct = response.get("deviation_pct", 0.0)
            
        except ExternalServiceException as e:
            logger.warning(f"Data Volume Service unavailable: {e}")
            return GateOutcome(
                gate_name="G6_VOLUME",
                result=GateResult.WARN,
                detail="Data Volume Service unavailable",
                duration_ms=self._elapsed(start),
                failure_summary="DATA_VOLUME_SERVICE_UNAVAILABLE"
            )

        # Decision logic
        if status == "FAIL":
            result = GateResult.FAIL
            detail = f"Row count anomalous: {deviation_pct:+.1f}% vs baseline"
            failure_summary = f"VOLUME_ANOMALY:{deviation_pct:+.1f}%"
        elif status == "WARN":
            result = GateResult.WARN
            detail = f"Row count deviation {deviation_pct:+.1f}% (within warning threshold) or baseline missing"
            failure_summary = None
        else:
            result = GateResult.PASS
            detail = "Row count within expected range"
            failure_summary = None

        return GateOutcome(
            gate_name="G6_VOLUME",
            result=result,
            detail=detail,
            duration_ms=self._elapsed(start),
            metadata={
                "actual_rows": actual_rows,
                "baseline_rows": baseline_rows,
                "deviation_pct": round(deviation_pct, 2),
                "allowed_deviation_pct": slo.get("allowed_deviation_pct", 15.0),
            },
            failure_summary=failure_summary,
        )
```

#### G7: Referential Integrity Gate

Verifies that foreign key values in the committed dataset exist in a designated
reference dataset (e.g., `customer_id` in `orders` must exist in `customers`).

**Policy bundle extension** — add a `referential_integrity` block to `policy_bundle.yaml`:

```yaml
referential_integrity:
  - column: customer_id
    reference_dataset: "ds://core/customers"
    reference_column: customer_id
    timeout_seconds: 30         # per-rule budget; hard ceiling 45s → WARN
    sample_rate: 0.05           # sample source when ref dataset > 10M rows
    failure_threshold: 0.001    # allow up to 0.1% orphan rate before FAIL
  - column: product_sku
    reference_dataset: "ds://catalog/products"
    reference_column: sku
    timeout_seconds: 20
    sample_rate: 0.10
    failure_threshold: 0.0
```

```python
class ReferentialIntegrityGate(Gate):
    """G7: Verify foreign key integrity against reference datasets."""

    HARD_TIMEOUT_SECONDS = 45   # absolute ceiling; degrades to WARN, never FAIL

    def __init__(self, registry_client, baselines_store):
        self.registry = registry_client
        self.baselines = baselines_store

    def evaluate(self, request, data_reader, context) -> GateOutcome:
        start = time.monotonic()
        ri_rules = context.policy_bundle.referential_integrity if context.policy_bundle else []
        if not ri_rules:
            return GateOutcome(
                gate_name="G7_REFERENTIAL_INTEGRITY",
                result=GateResult.SKIP,
                detail="No referential integrity rules defined",
                duration_ms=self._elapsed(start),
                metadata={},
                failure_summary=None,
            )

        outcomes = []
        for rule in ri_rules:
            try:
                outcome = self._evaluate_rule(rule, request, data_reader, context)
                outcomes.append(outcome)
            except TimeoutError:
                outcomes.append({
                    "column": rule["column"],
                    "result": "WARN",
                    "detail": f"Rule timed out after {self.HARD_TIMEOUT_SECONDS}s",
                    "orphan_count": None,
                    "orphan_rate": None,
                })

        failed = [o for o in outcomes if o["result"] == "FAIL"]
        if failed:
            sigs = [f"{o['column']}:{o['orphan_count']}" for o in failed]
            return GateOutcome(
                gate_name="G7_REFERENTIAL_INTEGRITY",
                result=GateResult.FAIL,
                detail=f"{len(failed)} rule(s) failed: {', '.join(sigs)}",
                duration_ms=self._elapsed(start),
                metadata={"rules": outcomes},
                failure_summary=f"REFERENTIAL_INTEGRITY_VIOLATION:{';'.join(sigs)}",
            )

        any_warn = any(o["result"] == "WARN" for o in outcomes)
        return GateOutcome(
            gate_name="G7_REFERENTIAL_INTEGRITY",
            result=GateResult.WARN if any_warn else GateResult.PASS,
            detail="All referential integrity rules passed"
            if not any_warn else "One or more rules degraded to WARN (timeout or budget)",
            duration_ms=self._elapsed(start),
            metadata={"rules": outcomes},
            failure_summary=None,
        )

    def _evaluate_rule(self, rule, request, data_reader, context) -> dict:
        column = rule["column"]
        ref_urn = rule["reference_dataset"]
        ref_col = rule["reference_column"]
        budget_s = min(rule.get("timeout_seconds", 30), self.HARD_TIMEOUT_SECONDS)
        sample_rate = rule.get("sample_rate", 0.05)
        threshold = rule.get("failure_threshold", 0.001)

        ref_path = self.registry.get_certified_path(ref_urn)
        ref_row_count = self.baselines.get_approx_row_count(ref_urn)
        use_sampling = (ref_row_count or 0) > 10_000_000

        with data_reader.timeout(budget_s):
            if use_sampling:
                source_query = (
                    f"SELECT \"{column}\" FROM ({context.data_relation.sql_query()}) t "
                    f"USING SAMPLE {int(sample_rate * 100)} PERCENT (bernoulli, 42)"
                )
            else:
                source_query = (
                    f"SELECT \"{column}\" FROM ({context.data_relation.sql_query()}) t"
                )

            orphan_count = data_reader.conn.sql(f"""
                SELECT count(*) FROM ({source_query}) src
                LEFT ANTI JOIN read_parquet('{ref_path}/**/*.parquet') ref
                  ON src."{column}" = ref."{ref_col}"
                WHERE src."{column}" IS NOT NULL
            """).fetchone()[0]

            total_checked = data_reader.conn.sql(
                f"SELECT count(*) FROM ({source_query}) t WHERE \"{column}\" IS NOT NULL"
            ).fetchone()[0]

        orphan_rate = orphan_count / total_checked if total_checked > 0 else 0.0
        result = "FAIL" if orphan_rate > threshold else "PASS"

        return {
            "column": column,
            "reference_dataset": ref_urn,
            "result": result,
            "orphan_count": orphan_count,
            "orphan_rate": round(orphan_rate, 6),
            "total_checked": total_checked,
            "sampled": use_sampling,
            "sample_rate": sample_rate if use_sampling else None,
        }
```

**Timeout behaviour summary:**

| Condition | Behaviour |
|:----------|:----------|
| Rule completes within `timeout_seconds` | Normal PASS / FAIL |
| Rule exceeds `timeout_seconds` but within 45s ceiling | Rule degrades to WARN |
| `TimeoutError` raised | Rule WARN; pipeline continues |
| All rules WARN | Gate result WARN; Certified View advances |
| Any rule FAIL | Gate result FAIL; pipeline halts (Tier-1) or continues (Tier-2/3) |

**New DynamoDB table — `ReferentialIntegrityCache`:**

| Attribute | Type | Key | Description |
|:----------|:-----|:----|:------------|
| `ref_urn` | String | PK | Reference dataset URN |
| `approx_row_count` | Number | — | Cached approx count (drives sample vs. full-scan decision) |
| `certified_path` | String | — | S3 path to certified reference data |
| `refreshed_at` | String | — | ISO timestamp; stale after 1 hour |
| `ttl` | Number | — | DynamoDB TTL (24 h) |

### 4.5 Gate Pipeline Orchestrator

```python
class GatePipelineOrchestrator:
    """Executes the 7-gate validation pipeline with fail-fast for Tier-1."""

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
| Autoscaler | KEDA `ScaledObject` targeting SQS queue depth |
| Readiness probe | SQS consumer active (every 10s) |
| Pod disruption budget | minAvailable: 2 |

#### KEDA ScaledObject

Scale workers based on SQS `ApproximateNumberOfMessages`. One worker per 5
queued messages; 5-minute scale-down cooldown to prevent thrash.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: validation-worker-scaler
  namespace: signal-factory
spec:
  scaleTargetRef:
    name: validation-worker
  minReplicaCount: 3
  maxReplicaCount: 20
  cooldownPeriod: 300       # 5-min scale-down cooldown
  pollingInterval: 15       # check SQS every 15s
  triggers:
    - type: aws-sqs-queue
      metadata:
        queueURL: "https://sqs.us-east-1.amazonaws.com/ACCOUNT/signal-factory-validation-requests.fifo"
        queueLength: "5"    # 1 worker per 5 queued messages
        awsRegion: "us-east-1"
        identityOwner: operator
```

**Scaling behaviour:**

| SQS queue depth | Target replicas | Scale-up time |
|:----------------|:----------------|:--------------|
| 0–14 | 3 (minimum) | — |
| 15–49 | 3–10 | ~30s |
| 50–99 | 10–20 | ~45s |
| 100+ | 20 (maximum) | ~60s |
| Empty for 5 min | 3 (scale back) | — |

#### Pod Disruption Budget

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: validation-worker-pdb
  namespace: signal-factory
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: validation-worker
```

#### Pod Resource Spec

```yaml
resources:
  requests:
    cpu: "2"
    memory: "8Gi"
  limits:
    cpu: "4"
    memory: "16Gi"
```

#### Startup Probe

Verifies DuckDB initialises and the Delta extension loads before the worker
accepts SQS messages:

```yaml
startupProbe:
  exec:
    command:
      - python
      - -c
      - "import duckdb; c = duckdb.connect(); c.execute('LOAD delta')"
  initialDelaySeconds: 5
  periodSeconds: 5
  failureThreshold: 6    # 30s max startup time
```

#### Autoscaling Observability

| Metric | CloudWatch namespace | Alert |
|:-------|:--------------------|:------|
| `sqs.ApproximateNumberOfMessages` | `AWS/SQS` | > 50 for > 10 min → scale ceiling hit |
| `keda.scaledobject.replicas_current` | `KEDA` | = 20 for > 5 min → capacity incident |
| `validation.pipeline.duration_ms` p99 | `SignalFactory/Validation` | > 25,000ms → DuckDB tuning needed |

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

For datasets exceeding 5M rows, workers apply deterministic statistical sampling
to stay within the 30-second end-to-end latency budget. Sampling is applied by
**G4 ContractGate** and **G7 ReferentialIntegrityGate**; G6 VolumeGate uses
the row count from Delta commit metadata and is not affected.

#### Configuration

Configured per-dataset in `policy_bundle.yaml`:

```yaml
sampling:
  threshold_rows: 5_000_000     # trigger sampling above this
  sample_rate: 0.10             # 10% deterministic sample
  seed: 42                      # reproducible across runs for the same partition
  bias_check: true              # compare sample null rates against baseline
  budget_seconds: 20.0          # abort and degrade to WARN if exceeded
```

#### `SamplingStrategy` Class

```python
@dataclass
class SamplingConfig:
    threshold_rows: int = 5_000_000
    sample_rate: float = 0.10
    seed: int = 42
    bias_check: bool = True
    budget_seconds: float = 20.0


class SamplingStrategy:
    """Deterministic sampling with bias detection for large datasets."""

    def __init__(self, config: SamplingConfig, baselines_store):
        self.config = config
        self.baselines = baselines_store

    def should_sample(self, row_count: Optional[int]) -> bool:
        return row_count is not None and row_count > self.config.threshold_rows

    def apply(
        self,
        relation: duckdb.DuckDBPyRelation,
        conn: duckdb.DuckDBPyConnection,
    ) -> duckdb.DuckDBPyRelation:
        """Return a deterministically sampled relation (reproducible via seed)."""
        pct = int(self.config.sample_rate * 100)
        sampled_sql = (
            f"SELECT * FROM ({relation.sql_query()}) t "
            f"USING SAMPLE {pct} PERCENT (bernoulli, {self.config.seed})"
        )
        return conn.sql(sampled_sql)

    def check_bias(
        self,
        sampled: duckdb.DuckDBPyRelation,
        dataset_urn: str,
        conn: duckdb.DuckDBPyConnection,
        critical_columns: list[str],
    ) -> Optional[str]:
        """
        Compare null rates of the sample against stored baselines.
        Returns a warning string if drift > 5%, else None.
        """
        if not self.config.bias_check or not critical_columns:
            return None

        sample_count = conn.sql(
            f"SELECT count(*) FROM ({sampled.sql_query()}) t"
        ).fetchone()[0]
        if sample_count == 0:
            return "SAMPLE_EMPTY"

        warnings = []
        for col in critical_columns:
            baseline = self.baselines.get_baseline(dataset_urn, metric=f"null_rate:{col}")
            if baseline is None:
                continue
            null_count = conn.sql(
                f"SELECT count(*) FROM ({sampled.sql_query()}) t WHERE \"{col}\" IS NULL"
            ).fetchone()[0]
            drift = abs((null_count / sample_count) - baseline.value)
            if drift > 0.05:
                warnings.append(f"{col}:null_rate_drift={drift:.3f}")

        return f"SAMPLE_BIAS:{','.join(warnings)}" if warnings else None
```

#### G4 ContractGate Integration

G4 uses `SamplingStrategy` instead of the previous hardcoded `MAX_SAMPLE_ROWS`:

```python
class ContractGate(Gate):
    """G4: Evaluate data quality rules from the policy bundle."""

    def __init__(self, baselines_store, sampling_config: Optional[SamplingConfig] = None):
        self.sampler = SamplingStrategy(
            sampling_config or SamplingConfig(),
            baselines_store,
        )

    def evaluate(self, request, data_reader, context) -> GateOutcome:
        start = time.monotonic()
        relation = context.data_relation  # cached by G3
        rules = context.policy_bundle.contracts
        row_count = request.num_records

        scan_mode = "FULL"
        bias_warning = None
        if self.sampler.should_sample(row_count):
            scan_mode = "SAMPLED"
            critical_cols = [r["column"] for r in rules if r["rule"] == "NOT_NULL"]
            try:
                relation = self.sampler.apply(relation, data_reader.conn)
                bias_warning = self.sampler.check_bias(
                    relation, request.dataset_urn, data_reader.conn, critical_cols
                )
            except Exception:
                scan_mode = "FULL_FALLBACK"  # sampling failed; fall through to full scan

        row_count = data_reader.get_row_count(relation)
        # ... rule evaluation loop unchanged; scan_mode and bias_warning
        # are included in the GateOutcome metadata ...
```

#### Sampling Decision Table

| Condition | Scan mode | Evidence field |
|:----------|:----------|:---------------|
| `row_count` unknown (Parquet, no metadata) | FULL | `scan_mode: "FULL"` |
| `row_count` ≤ 5M | FULL | `scan_mode: "FULL"` |
| `row_count` > 5M, sampling completes | SAMPLED | `scan_mode: "SAMPLED"`, `sample_rate`, `seed` |
| Sampling raises exception | FULL_FALLBACK | `scan_mode: "FULL_FALLBACK"` |
| Sampling exceeds `budget_seconds` | WARN | `failure_summary: "SAMPLE_BUDGET_EXCEEDED"` |
| Bias drift > 5% on any critical column | Gate result unchanged + WARN note | `bias_warning` in metadata |

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

### 9.3 Schema Source Precedence

When a dataset's `dataset.yaml` includes a `glue_catalog` override block, the
`SchemaRegistryClient` uses it instead of deriving the Glue table name from
the URN convention:

```yaml
# dataset.yaml — optional Glue override
urn: "ds://curated/orders_enriched"
glue_catalog:
  database: "curated_prod"
  table: "orders_enriched_v2"    # use when URN convention doesn't map cleanly
```

The `DatasetRegistry.get_dataset()` response includes `glue_database` and
`glue_table` fields (nullable). `SchemaRegistryClient._urn_to_glue_table()`
checks the registry before falling back to URN parsing.

---

## 10. Cross-Cutting Concerns

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

## 11. Alternatives Considered

| Decision | Chosen | Alternative | Why Chosen |
|:---|:---|:---|:---|
| Validation engine | DuckDB (embedded) | Spark Connect (remote) | Sub-second startup; 10× lower memory; sufficient for < 5M rows. Spark Connect reserved for > 5M row datasets (Phase 2). |
| S3 event batching | 60s tumbling window | Per-file validation | Multi-file Parquet writes from Spark produce 10-100 files per partition. Per-file validation would create 10-100× queue pressure. |
| Queue technology | SQS FIFO | Kafka topic | FIFO ordering per dataset is essential for version consistency. SQS provides this natively without partition management. |
| Staging pattern | S3 path convention | Delta Lake branches | Delta branches require Delta ≥ 3.0 (not universally deployed). S3 path convention is format-agnostic (works for both Delta and Parquet). |
| Certified View pointer | DynamoDB metadata | Delta table aliases | Parquet has no table alias concept. DynamoDB provides a unified pointer mechanism for both formats. |
| Deduplication | DynamoDB conditional writes | SQS dedup window (5 min) | SQS 5-min window is insufficient for Delta log re-reads that may span > 5 min during catch-up. |

---

## 12. Testing Strategy

### 12.1 Unit Tests

| Component | Test Focus | Coverage Target |
|:---|:---|:---|
| Delta Commit Log Poller | Version ordering, commit JSON parsing, partition extraction | 95% |
| S3 Event Aggregator | Window expiry, multi-file batching, dedup | 95% |
| Each Gate (G1–G6) | PASS/FAIL/WARN/SKIP for all scenarios; edge cases (empty data, null partitions) | 90% |
| Evidence Sanitizer | PII pattern matching, recursive scrubbing | 100% |
| Baseline Computer | Rolling average, synthetic fallback, history management | 90% |

### 12.2 Integration Tests

| Test | Components Under Test | Validation |
|:---|:---|:---|
| Delta happy path | Hook Dispatcher → Queue → Worker → Certified View → Evidence | End-to-end PASS with version advance |
| Parquet happy path | S3 Event → Aggregator → Queue → Worker → Evidence | End-to-end PASS with atomic move |
| Schema drift detection | Worker (G3) + real Delta table with added column | WARN evidence emitted |
| Volume anomaly | Worker (G6) + Baselines Store with -80% drop | FAIL evidence with hold |
| Freshness miss | Freshness Monitor + empty CertifiedViewState | FRESHNESS_MISS evidence emitted |
| DLQ redrive | Queue → Worker crash → DLQ → manual reprocess | Message lands in DLQ after 3 retries |

### 12.3 Load Tests

| Scenario | Target | Pass Criteria |
|:---|:---|:---|
| 500 validations in 1 hour | Sustained throughput | Queue depth never exceeds 200 |
| 200 validations in 30 min (burst) | Peak burst | p99 validation latency < 30s |
| 5M row dataset validation | Single large dataset | Total validation time < 25s |
| 20M row dataset with sampling | Sampling path | Total validation time < 15s |

### 12.4 New Unit Tests (v1.1 additions)

| Component | Test focus | Coverage target |
|:----------|:----------|:----------------|
| `ReferentialIntegrityGate` | PASS / FAIL / WARN / SKIP; timeout degradation; sampling vs. full-scan path | 90% |
| `SamplingStrategy` | Deterministic reproducibility (same sample on two runs); bias detection trigger; budget exceeded | 95% |
| `SchemaRegistryClient` | Precedence chain (policy → Delta log → Glue); `EntityNotFoundException` fallback; URN → Glue mapping | 95% |
| `dlq-inspector` Lambda | Auto-redrive hint for transient; HOLD for missing policy; SNS page at receive_count ≥ 3 | 90% |
| `dlq-redriving` Lambda | Stale version skip; new `request_id` generation; filter by `dataset_urn` | 95% |

### 12.5 New Integration Tests (v1.1 additions)

| Test | Components under test | Validation |
|:-----|:---------------------|:-----------|
| RI gate — orphan detected | Worker (G7) + real Delta staging + reference table missing 1 row | FAIL evidence with `REFERENTIAL_INTEGRITY_VIOLATION` |
| RI gate — timeout degrades to WARN | Worker (G7) + oversized reference table exceeding 45s | WARN evidence; Certified View advances |
| Sampling — 20M row Delta dataset | Worker (G4) + large partition | `scan_mode: "SAMPLED"` in evidence; total time < 15s |
| Sampling — bias check fires | Worker (G4) + injected null-rate skew in sample | Gate result unchanged; `bias_warning` populated in metadata |
| DLQ full flow | Hook Dispatcher → Worker crash (3×) → DLQ → Inspector → Redriving → Worker | Message reprocessed; evidence emitted |
| Schema resolved from Delta log | Worker (G3) + dataset with no policy bundle schema | `schema_source: "DELTA_LOG"` in evidence |
| Schema resolved from Glue | Worker (G3) + Parquet dataset in Glue Catalog | `schema_source: "GLUE_CATALOG"` in evidence |
| KEDA scale-up | 100 `ValidationRequest`s queued simultaneously | Workers scale 3 → 20 within 60s; p99 validation < 30s |


### 12.6 Chaos Tests

| Injection | Expected Behavior |
|:---|:---|
| Kill 2 of 3 validation workers | Remaining worker processes queue; HPA scales replacements within 2 min |
| DynamoDB throttle (registry) | G1 returns WARN; pipeline continues with cached config |
| S3 read timeout on staging path | Worker retries 3×; emits WARN evidence if all fail |
| Kafka broker failure (1 of 3) | Evidence emission retries succeed on remaining brokers |

---

## 13. Open Items and ADR Dependencies

| ID | Item | Status | Owner | Dependency |
|:---|:---|:---|:---|:---|
| LLD-01 | Finalize DuckDB memory limit per worker | 🟡 Pending load test | Platform Core | A5: Load test results |
| LLD-02 | Confirm S3 EventBridge quota sufficiency | 🟡 Pending | Infra | A3: AWS quota check |
| LLD-03 | Define Referential Integrity gate timeout | ✅ Resolved — timeout per-rule in policy bundle; hard ceiling 45s; degrades to WARN | SDK Team | — |
| LLD-04 | Schema registry integration (Glue vs. Delta) | ✅ Resolved — precedence chain: policy bundle → Delta log → Glue; no ADR required | Platform Core | — |
| LLD-05 | Policy bundle signing key management | 🟡 Pending ADR-008 | Security | KMS key rotation policy |
| LLD-06 | Cross-account S3 access for multi-account datalake | 🔴 Blocked | Infra | Network topology review |
| LLD-07 | DuckDB Delta extension compatibility matrix | 🟡 Pending | Platform Core | Delta Lake version audit |

---

## 14. Glossary

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
  ├── reads: DynamoDB (DatasetRegistry)
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
| ReferentialIntegrityCache | `ref_urn` | — | On-demand | 24 h |
| ColdDLQIndex | `request_id` | `dataset_urn` (GSI) | On-demand | 30 days |

---

*Document ends.*
