# Batch Post-Write Validation LLD v1.1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extend `docs/Batch/batch_postwrite_validation_lld_v1.md` with five gap sections
to produce a v1.1 that is implementation-ready, resolving open items LLD-03 and LLD-04.

**Architecture:** All changes are documentation edits to a single Markdown file.
Each task inserts or extends one section. No code is executed; verification is
checking that the Markdown renders cleanly and cross-references are consistent.

**Tech Stack:** Markdown (GitHub-flavored), Python code blocks (documentation only),
YAML code blocks (KEDA / policy bundle examples).

**Design source:** `docs/plans/2026-02-22-batch-postwrite-validation-lld-gaps-design.md`

---

## Pre-Flight Check

Before starting any task, confirm:

1. You are on branch `feature/add-docs` — run `git branch --show-current`
2. The target file exists — run `wc -l docs/Batch/batch_postwrite_validation_lld_v1.md`
   Expected: `1934`
3. No uncommitted changes — run `git status`

---

## Task 1: Add G7 Referential Integrity Gate

**Files:**
- Modify: `docs/Batch/batch_postwrite_validation_lld_v1.md:1055-1056`

**Context:**
- The G6 Volume Gate `python` code block closes at line 1055 (` ``` `)
- Line 1057 is `### 4.5 Gate Pipeline Orchestrator`
- G7 is inserted between them as `#### G7: Referential Integrity Gate`

**Step 1: Locate the insertion point**

Run:
```bash
grep -n "4.5 Gate Pipeline Orchestrator" docs/Batch/batch_postwrite_validation_lld_v1.md
```
Expected output: `1057:### 4.5 Gate Pipeline Orchestrator`

If the line number differs, adjust accordingly in the Edit below.

**Step 2: Insert the G7 gate section**

Find the exact string to replace:

```
```

### 4.5 Gate Pipeline Orchestrator
```

Replace it with:

````markdown
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
````

**Step 3: Update the GatePipelineOrchestrator docstring**

Find:
```python
class GatePipelineOrchestrator:
    """Executes the 6-gate validation pipeline with fail-fast for Tier-1."""
```

Replace with:
```python
class GatePipelineOrchestrator:
    """Executes the 7-gate validation pipeline with fail-fast for Tier-1."""
```

**Step 4: Verify section counts**

Run:
```bash
grep -c "^#### G" docs/Batch/batch_postwrite_validation_lld_v1.md
```
Expected: `7`

**Step 5: Commit**

```bash
git add docs/Batch/batch_postwrite_validation_lld_v1.md
git commit -m "docs(lld): add G7 Referential Integrity Gate to post-write validation LLD"
```

---

## Task 2: Add DLQ Reprocessing Workflow (§3.6)

**Files:**
- Modify: `docs/Batch/batch_postwrite_validation_lld_v1.md` — insert after §3.5 Backpressure

**Context:**
- §3.5 Backpressure ends with a table and then a `---` separator
- The new §3.6 is inserted between that `---` and `## 4. C-03`
- Run `grep -n "^## 4\. C-03" docs/Batch/batch_postwrite_validation_lld_v1.md` to get exact line

**Step 1: Locate insertion point**

```bash
grep -n "^---$" docs/Batch/batch_postwrite_validation_lld_v1.md | head -5
grep -n "^## 4\. C-03" docs/Batch/batch_postwrite_validation_lld_v1.md
```

The `---` immediately before `## 4. C-03` is the insertion point.

**Step 2: Insert §3.6**

Find this exact string (the `---` before section 4):

```
| > 500 | **Circuit breaker**: pause non-Tier-1 validation; alert on-call |

---

## 4. C-03: Validation Service (Workers)
```

Replace with:

````markdown
| > 500 | **Circuit breaker**: pause non-Tier-1 validation; alert on-call |

### 3.6 DLQ Reprocessing Workflow

When validation workers crash or fail repeatedly, messages land in the DLQ
(`signal-factory-validation-requests-dlq.fifo`, 14-day retention). This section
specifies how operators triage and safely re-enqueue them.

#### Architecture

```
signal-factory-validation-requests-dlq.fifo
  │
  ├── dlq-inspector  (Lambda, every 5 min)
  │     ├── Peeks up to 10 messages (30s visibility timeout)
  │     ├── Publishes summary to CloudWatch Logs Insights
  │     └── SNS alert if receive_count ≥ 3
  │
  └── dlq-redriving  (Lambda, manual trigger via Function URL + IAM)
        ├── Reads target messages from DLQ
        ├── Checks CertifiedViewState — drops stale validations
        ├── Re-enqueues with new request_id (resets 24h dedup window)
        └── Deletes original DLQ message after successful re-enqueue
```

#### `dlq-inspector` Lambda

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

    logger.info(json.dumps({"dlq_summary": summaries}))

    critical = [s for s in summaries if int(s["receive_count"]) >= 3]
    if critical:
        sns.publish(
            TopicArn=OPS_ALERT_TOPIC,
            Message=json.dumps({"alert": "DLQ_CRITICAL", "messages": critical}),
            Subject="Signal Factory: DLQ messages exhausted retries",
        )


def _classify_failure(body: dict, msg: dict) -> str:
    receive_count = int(msg["Attributes"]["ApproximateReceiveCount"])
    dataset_urn = body.get("dataset_urn", "")

    if receive_count >= 3:
        return "COLD_DLQ: move to cold storage; page on-call"
    if not registry.dataset_exists(dataset_urn):
        return "HOLD: dataset not registered; fix registry before redriving"
    if not registry.policy_bundle_exists(dataset_urn):
        return "HOLD: policy bundle missing; bootstrap dataset first"
    return "AUTO_REDRIVE: transient failure; safe to re-enqueue"
```

#### `dlq-redriving` Lambda

Triggered manually by an operator via Lambda Function URL (IAM auth required).
Accepts `{ "dataset_urn": "ds://...", "max_messages": 10 }`.

```python
def redrive_messages(event, context):
    target_urn = event.get("dataset_urn")
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

            # Safety: skip if the certified view has already advanced past this version
            current_version = certified_view_state.get_version(body["dataset_urn"])
            original_version = body.get("commit_version")
            if original_version and current_version and current_version > original_version:
                logger.warning(
                    f"Skipping stale: version {original_version} superseded by {current_version}"
                )
                sqs.delete_message(QueueUrl=DLQ_URL, ReceiptHandle=msg["ReceiptHandle"])
                continue

            # New request_id resets the 24h dedup window
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

#### Triage Reference

| Failure type | Action | Owner |
|:-------------|:-------|:------|
| Registry lookup failure (transient) | `dlq-inspector` auto-redrive hint | Operator invokes `dlq-redriving` |
| Policy bundle not found | HOLD — bootstrap dataset first | Platform engineer |
| Data read timeout (large partition) | Adjust `sampling.threshold_rows` in policy bundle, then redrive | Platform engineer |
| Receive count ≥ 3 | `dlq-inspector` auto-pages on-call; move to cold DLQ | On-call |
| Certified view already advanced past this version | `dlq-redriving` drops message silently | Automatic |

#### New DynamoDB Table — `ColdDLQIndex`

| Attribute | Type | Key | Description |
|:----------|:-----|:----|:------------|
| `request_id` | String | PK | Original ULID |
| `dataset_urn` | String | GSI-PK | Enables per-dataset cold DLQ queries |
| `receive_count` | Number | — | Receive count at time of cold-DLQ move |
| `failure_snapshot` | String | — | JSON `ValidationRequest` (truncated at 64 KB) |
| `moved_at` | String | — | ISO timestamp |
| `ttl` | Number | — | 30 days |

---

## 4. C-03: Validation Service (Workers)
````

**Step 3: Verify §3 now has 6 subsections**

```bash
grep -n "^### 3\." docs/Batch/batch_postwrite_validation_lld_v1.md
```
Expected: sections 3.1 through 3.6 listed.

**Step 4: Commit**

```bash
git add docs/Batch/batch_postwrite_validation_lld_v1.md
git commit -m "docs(lld): add DLQ reprocessing workflow as §3.6"
```

---

## Task 3: Extend Worker Autoscaling (§4.6)

**Files:**
- Modify: `docs/Batch/batch_postwrite_validation_lld_v1.md` — extend §4.6 Worker Deployment

**Context:**
- §4.6 is a stub table (lines ~1128–1141): min/max replicas and HPA metric are named
  but no KEDA YAML, PDB, or startup probe exists
- The full KEDA spec makes the deployment table actionable

**Step 1: Locate §4.6**

```bash
grep -n "^### 4\.6" docs/Batch/batch_postwrite_validation_lld_v1.md
```

**Step 2: Extend the section**

Find this exact string (the full §4.6 stub):

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
| Readiness probe | SQS consumer active (every 10s) |
| Pod disruption budget | minAvailable: 2 |
```

Replace with:

````markdown
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
````

**Step 3: Verify the section renders correctly**

```bash
grep -n "^#### " docs/Batch/batch_postwrite_validation_lld_v1.md | grep -A5 "4\.6"
```
Expected: headings for `KEDA ScaledObject`, `Pod Disruption Budget`,
`Pod Resource Spec`, `Startup Probe`, `Autoscaling Observability`.

**Step 4: Commit**

```bash
git add docs/Batch/batch_postwrite_validation_lld_v1.md
git commit -m "docs(lld): extend §4.6 with KEDA ScaledObject, PDB, startup probe, and autoscaling observability"
```

---

## Task 4: Extend Sampling Strategy (§4.8)

**Files:**
- Modify: `docs/Batch/batch_postwrite_validation_lld_v1.md` — replace §4.8 stub

**Context:**
- §4.8 exists but only has an `AdaptiveSampler` stub (fixed row sample, no seed,
  no bias check, no budget abort)
- Replace the entire section body with the full `SamplingStrategy` design plus
  updated G4 integration note

**Step 1: Locate §4.8**

```bash
grep -n "^### 4\.8" docs/Batch/batch_postwrite_validation_lld_v1.md
```

**Step 2: Replace §4.8**

Find this string (the entire §4.8 body — from the heading through the closing paragraph):

```
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
```

Replace with:

````markdown
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
````

**Step 3: Verify**

```bash
grep -n "SamplingStrategy\|AdaptiveSampler" docs/Batch/batch_postwrite_validation_lld_v1.md
```
Expected: `SamplingStrategy` appears; `AdaptiveSampler` does **not** appear.

**Step 4: Commit**

```bash
git add docs/Batch/batch_postwrite_validation_lld_v1.md
git commit -m "docs(lld): replace AdaptiveSampler stub with full SamplingStrategy design in §4.8"
```

---

## Task 5: Add Schema Registry Integration

**Files:**
- Modify: `docs/Batch/batch_postwrite_validation_lld_v1.md` — two insertion points:
  1. After the G3 SchemaGate class (add `SchemaRegistryClient` as §4.4.2a)
  2. After §9.2 in Dataset Registry section (add §9.3)

**Context:**
- G3 at line ~734 does `expected_schema = context.policy_bundle.schema_contract` directly
- §9 Dataset Registry starts at line ~1689

**Step 1: Locate G3 schema source line**

```bash
grep -n "expected_schema = context.policy_bundle.schema_contract" \
  docs/Batch/batch_postwrite_validation_lld_v1.md
```

**Step 2: Add `SchemaRegistryClient` after the G3 closing code block**

First find the end of the G3 gate. Look for:
```bash
grep -n "^#### G4: Contract Gate" docs/Batch/batch_postwrite_validation_lld_v1.md
```
The G3 block ends immediately before that line.

Find this exact string (the last line of the G3 block + start of G4):

```
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

Replace with:

````markdown
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

`SchemaGate.__init__` is updated to accept a `SchemaRegistryClient`:

```python
class SchemaGate(Gate):
    def __init__(self, schema_registry: SchemaRegistryClient):
        self.registry = schema_registry

    def evaluate(self, request, data_reader, context) -> GateOutcome:
        start = time.monotonic()
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

        context.schema_source = schema_source   # annotated in evidence
        # ... rest of drift computation unchanged ...
```
````

**Step 3: Add §9.3 to Dataset Registry**

Locate the end of §9 (Dataset Registry):

```bash
grep -n "^## 10\. C-09" docs/Batch/batch_postwrite_validation_lld_v1.md
```

Insert before that line. Find this exact string:

```
---

## 10. C-09: Baselines Store
```

Replace with:

````markdown
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

## 10. C-09: Baselines Store
````

**Step 4: Verify**

```bash
grep -n "SchemaRegistryClient\|schema_source\|GLUE_CATALOG\|DELTA_LOG" \
  docs/Batch/batch_postwrite_validation_lld_v1.md | wc -l
```
Expected: ≥ 10 matches.

```bash
grep -n "expected_schema = context.policy_bundle.schema_contract" \
  docs/Batch/batch_postwrite_validation_lld_v1.md
```
Expected: 0 matches (the direct access is replaced by the registry call).

**Step 5: Commit**

```bash
git add docs/Batch/batch_postwrite_validation_lld_v1.md
git commit -m "docs(lld): add SchemaRegistryClient (§4.4.2a) and schema source precedence (§9.3), resolve LLD-04"
```

---

## Task 6: Update Open Items (§14) and Appendix B

**Files:**
- Modify: `docs/Batch/batch_postwrite_validation_lld_v1.md` — two locations

**Step 1: Mark LLD-03 and LLD-04 resolved**

Find this exact block in §14:

```
| LLD-03 | Define Referential Integrity gate timeout | 🟡 Pending | SDK Team | Large reference table read latency |
| LLD-04 | Schema registry integration (Glue vs. Delta) | 🟡 Pending ADR-003 | Platform Core | Canonical schema model ADR |
```

Replace with:

```
| LLD-03 | Define Referential Integrity gate timeout | ✅ Resolved — timeout per-rule in policy bundle; hard ceiling 45s; degrades to WARN | SDK Team | — |
| LLD-04 | Schema registry integration (Glue vs. Delta) | ✅ Resolved — precedence chain: policy bundle → Delta log → Glue; no ADR required | Platform Core | — |
```

**Step 2: Add new DynamoDB tables to Appendix B**

Find this string (the last row of the Appendix B table):

```
| QuarantineIndex | `dataset_urn` | `partition_value` | On-demand | 30 days |
```

Replace with:

```
| QuarantineIndex | `dataset_urn` | `partition_value` | On-demand | 30 days |
| ReferentialIntegrityCache | `ref_urn` | — | On-demand | 24 h |
| ColdDLQIndex | `request_id` | `dataset_urn` (GSI) | On-demand | 30 days |
```

**Step 3: Verify Appendix B table**

```bash
grep -n "ReferentialIntegrityCache\|ColdDLQIndex" \
  docs/Batch/batch_postwrite_validation_lld_v1.md
```
Expected: 2 matches.

**Step 4: Commit**

```bash
git add docs/Batch/batch_postwrite_validation_lld_v1.md
git commit -m "docs(lld): mark LLD-03 and LLD-04 resolved; add new DynamoDB tables to Appendix B"
```

---

## Task 7: Add New Tests to Testing Strategy (§13)

**Files:**
- Modify: `docs/Batch/batch_postwrite_validation_lld_v1.md` — extend §13

**Step 1: Locate the end of §13.3 Load Tests**

```bash
grep -n "^## 14\." docs/Batch/batch_postwrite_validation_lld_v1.md
```

The `---` immediately before `## 14.` is the insertion point.

**Step 2: Insert new test tables before the `---`**

Find this exact string:

```
| 20M row dataset with sampling | Sampling path | Total validation time < 15s |

```

(That is the last row of the §13.3 load test table, followed by a blank line.)

Replace with:

````markdown
| 20M row dataset with sampling | Sampling path | Total validation time < 15s |

### 13.4 New Unit Tests (v1.1 additions)

| Component | Test focus | Coverage target |
|:----------|:----------|:----------------|
| `ReferentialIntegrityGate` | PASS / FAIL / WARN / SKIP; timeout degradation; sampling vs. full-scan path | 90% |
| `SamplingStrategy` | Deterministic reproducibility (same sample on two runs); bias detection trigger; budget exceeded | 95% |
| `SchemaRegistryClient` | Precedence chain (policy → Delta log → Glue); `EntityNotFoundException` fallback; URN → Glue mapping | 95% |
| `dlq-inspector` Lambda | Auto-redrive hint for transient; HOLD for missing policy; SNS page at receive_count ≥ 3 | 90% |
| `dlq-redriving` Lambda | Stale version skip; new `request_id` generation; filter by `dataset_urn` | 95% |

### 13.5 New Integration Tests (v1.1 additions)

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

````

**Step 3: Verify**

```bash
grep -n "^### 13\." docs/Batch/batch_postwrite_validation_lld_v1.md
```
Expected: sections 13.1 through 13.5.

**Step 4: Final line count check**

```bash
wc -l docs/Batch/batch_postwrite_validation_lld_v1.md
```
Expected: substantially more than 1934 (approximately 2500–2700 lines).

**Step 5: Final commit**

```bash
git add docs/Batch/batch_postwrite_validation_lld_v1.md
git commit -m "docs(lld): add §13.4 and §13.5 unit/integration tests for v1.1 gap sections"
```

---

## Post-Implementation Verification

Run all of these after Task 7 is complete:

```bash
# 1. All 7 gates present
grep -c "^#### G" docs/Batch/batch_postwrite_validation_lld_v1.md
# Expected: 7

# 2. Both open items resolved
grep "LLD-03\|LLD-04" docs/Batch/batch_postwrite_validation_lld_v1.md
# Expected: both show ✅ Resolved

# 3. All new DynamoDB tables present
grep "ReferentialIntegrityCache\|ColdDLQIndex" \
  docs/Batch/batch_postwrite_validation_lld_v1.md
# Expected: 2 matches

# 4. AdaptiveSampler stub removed
grep "AdaptiveSampler" docs/Batch/batch_postwrite_validation_lld_v1.md
# Expected: 0 matches

# 5. SchemaRegistryClient present
grep -c "SchemaRegistryClient" docs/Batch/batch_postwrite_validation_lld_v1.md
# Expected: ≥ 3

# 6. Section 13 has 5 subsections
grep "^### 13\." docs/Batch/batch_postwrite_validation_lld_v1.md
# Expected: 13.1 through 13.5

# 7. Clean git history
git log --oneline -8
```
