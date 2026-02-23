# Design: Batch Post-Write Validation LLD — Gap Extensions

**Date:** 2026-02-22
**Status:** Approved
**Target Document:** `docs/Batch/batch_postwrite_validation_lld_v1.md`
**Scope:** Five identified gaps to extend the LLD to v1.1
**Author:** Principal Solutions Architect

---

## Context

The `batch_postwrite_validation_lld_v1.md` covers all nine subsystem components
(Hook Dispatcher → Validation Queue → Validation Service → Certified View Manager
→ Freshness Monitor → OpenLineage Collector → Evidence Emitter → Dataset Registry
→ Baselines Store) across 1,934 lines.

A gap analysis identified five areas requiring extension before the document is
implementation-ready:

| Gap | Source | Severity |
|:----|:-------|:---------|
| G7 Referential Integrity Gate | Open item LLD-03 | Design gap |
| Large-dataset sampling strategy | Test references missing implementation | Design gap |
| DLQ reprocessing workflow | No operational design | Operational gap |
| Worker autoscaling (KEDA) | Cost model unrealized in config | Operational gap |
| Schema registry integration | Open item LLD-04 (pending ADR-003) | Design gap |

---

## Gap 1: G7 Referential Integrity Gate

### Location in LLD

New section **§4.4.5** immediately after the G6 Volume Gate (§4.4.4).
Gate numbering for Freshness and Volume shifts: G5 → G5 (unchanged), G6 → G6
(unchanged). G7 is appended as the seventh and final gate in the pipeline.
`GatePipelineOrchestrator` receives a seventh gate in its `gates` list.

### Policy Bundle Schema Extension

```yaml
# policy_bundle.yaml — new top-level block
referential_integrity:
  - column: customer_id
    reference_dataset: "ds://core/customers"
    reference_column: customer_id
    timeout_seconds: 30           # hard kill at 45s → degrades to WARN
    sample_rate: 0.05             # sample source when ref dataset > 10M rows
    failure_threshold: 0.001      # allow up to 0.1% orphan rate before FAIL
  - column: product_sku
    reference_dataset: "ds://catalog/products"
    reference_column: sku
    timeout_seconds: 20
    sample_rate: 0.10
    failure_threshold: 0.0
```

### Gate Design

```python
class ReferentialIntegrityGate(Gate):
    """G7: Verify foreign key integrity against reference datasets."""

    HARD_TIMEOUT_SECONDS = 45   # absolute ceiling; degrades to WARN, never FAIL

    def evaluate(self, request, data_reader, context) -> GateOutcome:
        start = time.monotonic()
        ri_rules = context.policy_bundle.referential_integrity
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
                outcome = self._evaluate_rule(
                    rule, request, data_reader, context, start
                )
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

    def _evaluate_rule(self, rule, request, data_reader, context, start) -> dict:
        column = rule["column"]
        ref_urn = rule["reference_dataset"]
        ref_col = rule["reference_column"]
        budget_s = min(rule.get("timeout_seconds", 30), self.HARD_TIMEOUT_SECONDS)
        sample_rate = rule.get("sample_rate", 0.05)
        threshold = rule.get("failure_threshold", 0.001)

        # Resolve reference dataset certified path
        ref_path = self.registry.get_certified_path(ref_urn)
        ref_row_count = self.baselines.get_approx_row_count(ref_urn)

        # Decide whether to sample the source
        use_sampling = (ref_row_count or 0) > 10_000_000

        with data_reader.timeout(budget_s):
            if use_sampling:
                # Deterministic sample of source for the JOIN
                source_query = (
                    f"SELECT \"{column}\" FROM ({context.data_relation.sql_query()}) t "
                    f"USING SAMPLE {int(sample_rate * 100)} PERCENT (bernoulli, 42)"
                )
            else:
                source_query = (
                    f"SELECT \"{column}\" FROM ({context.data_relation.sql_query()}) t"
                )

            # Anti-join to find orphans
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

### Timeout Safety

| Condition | Behavior |
|:----------|:---------|
| Rule completes within `timeout_seconds` | Normal PASS / FAIL |
| Rule exceeds `timeout_seconds`, within `HARD_TIMEOUT_SECONDS` (45s) | Rule degrades to WARN |
| Rule exceeds `HARD_TIMEOUT_SECONDS` | TimeoutError caught by gate; rule WARN |
| All rules WARN | Gate result WARN (pipeline continues; Certified View advances) |
| Any rule FAIL | Gate result FAIL (pipeline halts for Tier-1; Certified View held) |

### DynamoDB Table Update

Add `referential_integrity_cache` table to §2.6 (DynamoDB Tables):

| Attribute | Type | Key | Description |
|:----------|:-----|:----|:------------|
| `ref_urn` | String | PK | Reference dataset URN |
| `approx_row_count` | Number | — | Cached approximate count (used for sample/no-sample decision) |
| `certified_path` | String | — | S3 path to certified reference data |
| `refreshed_at` | String | — | ISO timestamp; stale after 1 hour |
| `ttl` | Number | — | DynamoDB TTL (24h) |

---

## Gap 2: Large-Dataset Sampling Strategy (G4 + G7)

### Location in LLD

- New subsection **§4.3.1** — `SamplingStrategy` class (under DataReader, §4.3)
- Extended **§4.4.3** — G4 ContractGate modified to use `SamplingStrategy`
- Referenced by G7 (which inline-implements its own sampling for RI checks)

### `SamplingStrategy` Class

```python
@dataclass
class SamplingConfig:
    threshold_rows: int = 5_000_000    # trigger sampling above this
    sample_rate: float = 0.10          # default 10% sample
    seed: int = 42                     # reproducible across runs
    bias_check: bool = True            # verify sample null rates vs. baseline
    budget_seconds: float = 20.0       # abort and degrade if exceeded


class SamplingStrategy:
    """Determines whether to sample and applies deterministic sampling via DuckDB."""

    def __init__(self, config: SamplingConfig, baselines_store):
        self.config = config
        self.baselines = baselines_store

    def should_sample(self, row_count: Optional[int]) -> bool:
        """True when row count is known and exceeds threshold."""
        return row_count is not None and row_count > self.config.threshold_rows

    def apply(
        self,
        relation: duckdb.DuckDBPyRelation,
        conn: duckdb.DuckDBPyConnection,
    ) -> duckdb.DuckDBPyRelation:
        """Return a deterministically sampled relation."""
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
        Compare null rates of sampled data against stored baselines.
        Returns a warning string if drift > 5%, else None.
        """
        if not self.config.bias_check or not critical_columns:
            return None

        warnings = []
        sample_count = conn.sql(
            f"SELECT count(*) FROM ({sampled.sql_query()}) t"
        ).fetchone()[0]

        if sample_count == 0:
            return "SAMPLE_EMPTY"

        for col in critical_columns:
            baseline = self.baselines.get_baseline(dataset_urn, metric=f"null_rate:{col}")
            if baseline is None:
                continue
            null_count = conn.sql(
                f"SELECT count(*) FROM ({sampled.sql_query()}) t WHERE \"{col}\" IS NULL"
            ).fetchone()[0]
            sample_null_rate = null_count / sample_count
            drift = abs(sample_null_rate - baseline.value)
            if drift > 0.05:
                warnings.append(f"{col}:null_rate_drift={drift:.3f}")

        return f"SAMPLE_BIAS:{','.join(warnings)}" if warnings else None
```

### G4 ContractGate Integration

Replace the hardcoded `MAX_SAMPLE_ROWS` constant with `SamplingStrategy`:

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
        relation = context.data_relation  # From G3 (cached)
        rules = context.policy_bundle.contracts
        row_count = request.num_records  # May be None for Parquet

        # Determine whether to sample
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
        # ... rest of evaluation unchanged ...
```

### Sampling Decision Table

| Condition | Scan Mode | Notes |
|:----------|:----------|:------|
| `row_count` unknown (Parquet, no metadata) | FULL | Row count counted via DuckDB after read |
| `row_count` ≤ 5M | FULL | Standard path; no change to existing behavior |
| `row_count` > 5M and sampling completes | SAMPLED | Deterministic 10% sample; bias check runs |
| Sampling raises exception | FULL_FALLBACK | Degrades silently; evidence records `scan_mode=FULL_FALLBACK` |
| Sampling exceeds `budget_seconds` | WARN: SAMPLE_BUDGET_EXCEEDED | Gate upgrades to WARN; Certified View still advances |
| Bias drift > 5% on any critical column | Gate result unchanged + WARN note | Bias warning appended to evidence `metadata` |

---

## Gap 3: DLQ Reprocessing Workflow

### Location in LLD

New subsection **§3.3** — `DLQ Reprocessing Workflow` (under C-02: Validation Queue, §3).

### Architecture

Two purpose-built Lambda functions:

```
┌──────────────────────────────────────────────────────┐
│  signal-factory-validation-requests-dlq.fifo         │
│  (14-day retention)                                   │
└────────────────┬─────────────────────────────────────┘
                 │
        ┌────────▼────────┐        ┌──────────────────────┐
        │  dlq-inspector   │───────▶│  SNS: ops-alerts     │
        │  (scheduled:     │        │  CloudWatch Logs      │
        │   every 5 min)   │        │  Insights summary     │
        └────────┬────────┘        └──────────────────────┘
                 │ operator decision
        ┌────────▼────────┐
        │  dlq-redriving   │─────▶  Main FIFO Queue
        │  (manual trigger │        (new request_id)
        │  via Lambda URL) │
        └─────────────────┘
```

### `dlq-inspector` Lambda

Reads up to 10 DLQ messages per invocation (without deleting them — using
`ReceiveMessage` with a short visibility timeout of 30s):

```python
def inspect_dlq(event, context):
    messages = sqs.receive_message(
        QueueUrl=DLQ_URL,
        MaxNumberOfMessages=10,
        VisibilityTimeout=30,      # peek without consuming
        WaitTimeSeconds=0,
    ).get("Messages", [])

    summaries = []
    for msg in messages:
        body = json.loads(msg["Body"])
        summaries.append({
            "request_id": body.get("request_id"),
            "dataset_urn": body.get("dataset_urn"),
            "storage_type": body.get("storage_type"),
            "partition_values": body.get("partition_values"),
            "original_timestamp": body.get("timestamp"),
            "receive_count": msg["Attributes"]["ApproximateReceiveCount"],
            "triage_hint": _classify_failure(body, msg),
        })

    # Publish summary to CloudWatch Logs
    logger.info(json.dumps({"dlq_summary": summaries, "total_in_dlq": _get_depth()}))

    # Page on-call if any message has receive_count >= 3
    critical = [s for s in summaries if int(s["receive_count"]) >= 3]
    if critical:
        sns.publish(
            TopicArn=OPS_ALERT_TOPIC,
            Message=json.dumps({"alert": "DLQ_CRITICAL", "messages": critical}),
            Subject="Signal Factory: DLQ messages exhausted retries",
        )
```

### Triage Classification

```python
def _classify_failure(body: dict, msg: dict) -> str:
    receive_count = int(msg["Attributes"]["ApproximateReceiveCount"])
    dataset_urn = body.get("dataset_urn", "")

    if receive_count >= 3:
        return "COLD_DLQ: move to cold storage; page on-call"
    if not registry.dataset_exists(dataset_urn):
        return "HOLD: dataset not registered; fix registry before redriving"
    if not registry.policy_bundle_exists(dataset_urn):
        return "HOLD: policy bundle missing; bootstrap dataset first"
    # Default: transient failure — safe to redrive
    return "AUTO_REDRIVE: transient failure; safe to re-enqueue"
```

### `dlq-redriving` Lambda

Triggered manually by operator (via Lambda Function URL with IAM auth):

```python
def redrive_messages(event, context):
    """
    Moves DLQ messages back to the main FIFO queue.
    Accepts: { "dataset_urn": "ds://...", "max_messages": 10 }
    """
    target_urn = event.get("dataset_urn")   # optional filter
    max_msgs = min(event.get("max_messages", 10), 50)

    redriven = 0
    while redriven < max_msgs:
        messages = sqs.receive_message(
            QueueUrl=DLQ_URL,
            MaxNumberOfMessages=min(10, max_msgs - redriven),
            VisibilityTimeout=120,
        ).get("Messages", [])
        if not messages:
            break

        for msg in messages:
            body = json.loads(msg["Body"])
            if target_urn and body.get("dataset_urn") != target_urn:
                continue

            # Safety check: don't redrive if certified view has advanced
            current_version = certified_view_state.get_version(body["dataset_urn"])
            original_version = body.get("commit_version")
            if original_version and current_version and current_version > original_version:
                logger.warning(f"Skipping stale validation: version {original_version} "
                               f"already superseded by {current_version}")
                sqs.delete_message(QueueUrl=DLQ_URL, ReceiptHandle=msg["ReceiptHandle"])
                continue

            # Re-enqueue with new request_id (resets dedup window)
            body["request_id"] = f"vr-{ulid.new()}"
            sqs.send_message(
                QueueUrl=MAIN_QUEUE_URL,
                MessageBody=json.dumps(body),
                MessageGroupId=body["dataset_urn"],
                MessageDeduplicationId=body["request_id"],
            )
            sqs.delete_message(QueueUrl=DLQ_URL, ReceiptHandle=msg["ReceiptHandle"])
            redriven += 1

    return {"redriven": redriven}
```

### Triage Decision Reference

| Failure type | Triage action | Who |
|:-------------|:--------------|:----|
| Registry lookup failure (transient) | Auto-redrive after 5-min backoff | `dlq-inspector` (auto) |
| Policy bundle not found | HOLD — fix registry first, then redrive | Operator |
| Data read timeout (large partition) | Adjust `memory_limit` or `sampling.threshold_rows` in policy bundle, then redrive | Platform engineer |
| Receive count ≥ 3 | Move to cold DLQ (30-day retention); page on-call | `dlq-inspector` (auto-page) |
| Certified view superseded | Drop silently; log | `dlq-redriving` (auto-skip) |

### New DynamoDB Table: ColdDLQ Index

| Attribute | Type | Key | Description |
|:----------|:-----|:----|:------------|
| `request_id` | String | PK | Original ULID |
| `dataset_urn` | String | GSI-PK | Enables per-dataset cold DLQ query |
| `receive_count` | Number | — | Receive count at time of cold-DLQ move |
| `failure_snapshot` | String | — | JSON-serialized `ValidationRequest` (truncated at 64 KB) |
| `moved_at` | String | — | ISO timestamp |
| `ttl` | Number | — | 30 days |

---

## Gap 4: Worker Autoscaling (KEDA)

### Location in LLD

New subsection **§4.7** — `Worker Autoscaling` (under C-03: Validation Service, §4),
after the existing deployment table.

### KEDA ScaledObject

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
  cooldownPeriod: 300       # 5 min scale-down cooldown (prevent thrash)
  pollingInterval: 15       # check SQS every 15s
  triggers:
    - type: aws-sqs-queue
      metadata:
        queueURL: "https://sqs.us-east-1.amazonaws.com/ACCOUNT/signal-factory-validation-requests.fifo"
        queueLength: "5"    # target: 1 worker per 5 queued messages
        awsRegion: "us-east-1"
        identityOwner: operator
```

### Scaling Behaviour

| SQS Queue Depth | Target Replicas | Expected Scale-Up Time |
|:----------------|:----------------|:-----------------------|
| 0–14 messages | 3 (minimum) | — |
| 15–49 messages | 3–10 | ~30s (KEDA default) |
| 50–99 messages | 10–20 | ~45s |
| 100+ messages | 20 (maximum) | ~60s |
| Queue empty for 5 min | 3 (scale back to min) | — |

### Pod Disruption Budget

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

### Pod Resources

```yaml
# Deployment resource spec
resources:
  requests:
    cpu: "2"
    memory: "8Gi"
  limits:
    cpu: "4"
    memory: "16Gi"
```

### Worker Startup Probe

New workers must pass a startup probe before receiving SQS messages. The probe
verifies DuckDB is initialized and the Delta extension is loaded:

```yaml
startupProbe:
  exec:
    command: ["python", "-c", "import duckdb; c = duckdb.connect(); c.execute('LOAD delta')"]
  initialDelaySeconds: 5
  periodSeconds: 5
  failureThreshold: 6    # 30s max startup time
```

### Autoscaling Observability

| Metric | CloudWatch Namespace | Alert |
|:-------|:--------------------|:------|
| `sqs.ApproximateNumberOfMessages` | `AWS/SQS` | > 50 for > 10 min → scale ceiling hit |
| `keda.scaledobject.replicas_current` | `KEDA` | = maxReplicaCount for > 5 min → capacity incident |
| `worker.validation_duration_ms` p99 | `SignalFactory/Validation` | > 25,000ms → DuckDB tuning needed |

---

## Gap 5: Schema Registry Integration (resolves LLD-04)

### Location in LLD

- New subsection **§4.4.2a** — `SchemaRegistryClient` (under G3 Schema Gate, §4.4.2)
- New subsection **§9.3** — `Schema Source Precedence` (under C-08: Dataset Registry, §9)

### Decision

**Chosen: Delta transaction log as primary, Glue Data Catalog as fallback.**

No new ADR is required. The precedence chain is deterministic and the decision
criteria are unambiguous:

| Schema Source | Used When | Rationale |
|:-------------|:----------|:----------|
| `policy_bundle.yaml` `schema_contract` block | Always (if present) | Operator-defined contract is the authoritative override |
| Delta `_delta_log/` `metaData` action | Delta datasets with no policy override | Schema is embedded in the commit log at write time; no external service dependency |
| Glue Data Catalog (`GetTable` API) | Parquet datasets; Delta fallback when `metaData` absent | Glue is the authoritative catalog for Parquet; single API call |

### Precedence Chain

```
policy_bundle.schema_contract
      ↓ (absent)
Delta commit log metaData action
      ↓ (absent or non-Delta)
Glue Data Catalog GetTable
      ↓ (absent or Glue error)
GateResult.WARN: SCHEMA_SOURCE_UNAVAILABLE
```

### `SchemaRegistryClient`

```python
class SchemaRegistryClient:
    """
    Resolves the registered schema for a dataset using the precedence chain:
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
        Returns (schema, source_label) where source_label is one of:
          "POLICY_BUNDLE" | "DELTA_LOG" | "GLUE_CATALOG" | "UNAVAILABLE"
        """

        # 1. Policy bundle override
        if policy_bundle and policy_bundle.schema_contract:
            return policy_bundle.schema_contract, "POLICY_BUNDLE"

        # 2. Delta commit log
        if storage_type == "delta" and commit_version is not None:
            schema = self._from_delta_log(table_path, commit_version)
            if schema:
                return schema, "DELTA_LOG"

        # 3. Glue Data Catalog
        schema = self._from_glue(dataset_urn)
        if schema:
            return schema, "GLUE_CATALOG"

        return None, "UNAVAILABLE"

    def _from_delta_log(self, table_path: str, version: int) -> Optional[list[dict]]:
        """
        Walk back through Delta commit log from `version` to find the most recent
        `metaData` action containing the schema.
        """
        bucket, prefix = self._parse_s3_path(table_path)
        log_prefix = f"{prefix}_delta_log/"

        # Search backwards from current version (schema changes are infrequent)
        for v in range(version, max(version - 50, -1), -1):
            key = f"{log_prefix}{str(v).zfill(20)}.json"
            try:
                response = self.s3.get_object(Bucket=bucket, Key=key)
                commit = json.loads(response["Body"].read())
                if "metaData" in commit:
                    return self._parse_delta_schema(commit["metaData"]["schemaString"])
            except self.s3.exceptions.NoSuchKey:
                continue
            except Exception:
                break

        return None

    def _from_glue(self, dataset_urn: str) -> Optional[list[dict]]:
        """Resolve schema from Glue Data Catalog using URN → database.table mapping."""
        database, table = self._urn_to_glue_table(dataset_urn)
        if not database or not table:
            return None
        try:
            response = self.glue.get_table(DatabaseName=database, Name=table)
            columns = response["Table"]["StorageDescriptor"]["Columns"]
            return [{"name": c["Name"], "type": c["Type"], "nullable": True}
                    for c in columns]
        except self.glue.exceptions.EntityNotFoundException:
            return None
        except Exception:
            return None

    def _parse_delta_schema(self, schema_string: str) -> list[dict]:
        """Parse Delta Lake JSON schema string into canonical field list."""
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
        """
        Map a dataset URN to a Glue database and table name.
        Convention: "ds://database/table_name" → ("database", "table_name")
        """
        parts = urn.removeprefix("ds://").split("/")
        return (parts[0], parts[1]) if len(parts) >= 2 else (None, None)
```

### G3 SchemaGate Integration

Replace the direct `context.policy_bundle.schema_contract` access with a
`SchemaRegistryClient` call:

```python
class SchemaGate(Gate):
    def __init__(self, schema_registry: SchemaRegistryClient):
        self.registry = schema_registry

    def evaluate(self, request, data_reader, context) -> GateOutcome:
        # ... read actual schema from staged data (unchanged) ...

        expected_schema, schema_source = self.registry.get_registered_schema(
            dataset_urn=request.dataset_urn,
            storage_type=request.storage_type,
            table_path=request.table_path,
            commit_version=request.commit_version,
            policy_bundle=context.policy_bundle,
        )

        if expected_schema is None:
            return GateOutcome(
                gate_name="G3_SCHEMA",
                result=GateResult.WARN,
                detail="Schema source unavailable; drift detection skipped",
                duration_ms=self._elapsed(start),
                metadata={"schema_source": "UNAVAILABLE"},
                failure_summary=None,
            )

        # Annotate evidence with which source was used
        context.schema_source = schema_source
        # ... rest of drift computation unchanged ...
```

### URN → Glue Table Mapping in Dataset Registry

Add `glue_database` and `glue_table` as optional fields in `dataset.yaml` to
support cases where the URN convention does not map cleanly to a Glue table name:

```yaml
# dataset.yaml extension
urn: "ds://curated/orders_enriched"
storage:
  bronze: "s3://lake/bronze/orders/"
  silver: "s3://lake/silver/orders/"
  gold: "s3://lake/gold/orders/"
glue_catalog:                      # optional override
  database: "curated_prod"
  table: "orders_enriched_v2"
```

---

## Open Items Closed by This Design

| ID | Item | Status After This Design |
|:---|:-----|:------------------------|
| LLD-03 | Referential Integrity gate timeout | ✅ Resolved — timeout per-rule in policy bundle; hard ceiling 45s; degrades to WARN |
| LLD-04 | Schema registry integration | ✅ Resolved — precedence chain + `SchemaRegistryClient` designed; no new ADR required |

## Open Items Remaining

| ID | Item | Path Forward |
|:---|:-----|:------------|
| LLD-01 | DuckDB memory limit per worker | Remains pending load test; `SamplingStrategy` reduces memory pressure for large datasets |
| LLD-02 | S3 EventBridge quota | Remains pending infra confirmation |
| LLD-05 | Policy bundle signing key management | Remains pending ADR-008 (KMS key rotation) |
| LLD-06 | Cross-account S3 access | Remains blocked on network topology review |
| LLD-07 | DuckDB Delta extension compatibility | Remains pending Delta Lake version audit |

---

## LLD Section Map — Where Each Gap Lands

| Gap | New/Modified Section | Change Type |
|:----|:--------------------|:------------|
| G7 Referential Integrity Gate | §4.4.5 (new) | New gate class + policy bundle extension + DynamoDB table |
| Large-dataset sampling | §4.3.1 (new) + §4.4.3 (modified) | New `SamplingStrategy` class; G4 refactored |
| DLQ reprocessing workflow | §3.3 (new) | New `dlq-inspector` + `dlq-redriving` Lambdas + DynamoDB table |
| Worker autoscaling | §4.7 (new) | KEDA `ScaledObject` + PDB + startup probe + observability |
| Schema registry integration | §4.4.2a (new) + §9.3 (new) | New `SchemaRegistryClient`; G3 SchemaGate refactored |

---

## Testing Strategy Additions

### New Unit Tests

| Component | Test Focus | Coverage Target |
|:----------|:----------|:----------------|
| `ReferentialIntegrityGate` | PASS/FAIL/WARN/SKIP; timeout degradation to WARN; sampling vs. full-scan path | 90% |
| `SamplingStrategy` | Deterministic reproducibility (same sample on two runs); bias detection trigger; budget exceeded path | 95% |
| `SchemaRegistryClient` | Precedence chain (policy → Delta log → Glue); fallback on Glue `EntityNotFoundException`; URN → Glue mapping | 95% |
| `dlq-inspector` | Auto-redrive hint for transient; HOLD hint for missing policy; page trigger at receive_count ≥ 3 | 90% |
| `dlq-redriving` | Stale version skip; new `request_id` generation; filter by `dataset_urn` | 95% |

### New Integration Tests

| Test | Components Under Test | Validation |
|:-----|:---------------------|:-----------|
| RI gate — orphan detected | Worker (G7) + real Delta staging + reference table missing row | FAIL evidence with `REFERENTIAL_INTEGRITY_VIOLATION` |
| RI gate — timeout degradation | Worker (G7) + large reference table exceeding 45s budget | WARN evidence; Certified View advances |
| Sampling — 20M row dataset | Worker (G4) + large Delta table | SAMPLED scan mode in evidence; total time < 15s |
| Sampling — bias detected | Worker (G4) + sample with injected null-rate skew | Gate result unchanged; bias warning in metadata |
| DLQ — full flow | Hook Dispatcher → Worker crash → DLQ → Inspector → Redriving → Worker | Message successfully reprocessed; evidence emitted |
| Schema from Delta log | Worker (G3) + dataset with no policy bundle schema | `schema_source: DELTA_LOG` in evidence |
| Schema from Glue | Worker (G3) + Parquet dataset registered in Glue | `schema_source: GLUE_CATALOG` in evidence |
| KEDA scale-up | 100 ValidationRequests queued simultaneously | Workers scale from 3 → 20 within 60s |
