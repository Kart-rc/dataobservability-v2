# Signal Factory: Batch Bootstrap & Onboarding — Low-Level Design

> **Version:** 1.0  
> **Date:** February 17, 2026  
> **Status:** Draft — Self-Review Complete  
> **Classification:** Internal — Architecture  
> **Parent Documents:** `batch_bootstrap_hld.md` (v1.0), `batch_observability_hld.md` (v2.0), `batch_observability_prd.md` (v1.1)  
> **Scope:** Delta Lake and Parquet storage formats only (Iceberg deferred to Phase 2)  
> **Author:** Principal Solutions Architect

---

## 1. Introduction

### 1.1 Purpose

This Low-Level Design (LLD) specifies the internal architecture, data models, API contracts, storage schemas, error handling, and operational concerns for each component in the **Batch Bootstrap & Onboarding** subsystem of the Signal Factory platform. It translates the Bootstrap HLD's conceptual architecture into implementation-ready specifications.

The Bootstrap subsystem is the **critical-path enabler** for the entire batch observability platform. Without it, no dataset emits evidence, no signals are computed, and the RCA Copilot has nothing to reason about. This LLD addresses the HLD's target of reducing bootstrap effort from 4,000 person-hours to under 500 person-hours across a 500-dataset fleet through tiered automation.

### 1.2 Scope and Storage Constraint

This LLD covers all components required to bootstrap batch datasets stored in **Delta Lake** and **Parquet** formats on S3. Iceberg catalog integration is explicitly out of scope for this phase.

**5-Whys Analysis — Why Delta + Parquet Only?**

1. **Why limit to Delta + Parquet?** — These two formats cover 94% of the batch fleet (Delta: 62%, Parquet: 32%).
2. **Why not include Iceberg?** — Iceberg's metadata catalog model (Glue Catalog Events) requires a fundamentally different profiling hook. Including it expands the profiling engine's complexity by ~40%.
3. **Why is this relevant to bootstrap specifically?** — The Profiling Engine (Step 2) must introspect storage-layer metadata (Delta commit logs, Parquet file footers) to compute baselines. Each format has a distinct read path.
4. **Why not generalize the profiling interface?** — Premature abstraction across three formats would delay Phase 1 delivery by 3–4 weeks without benefiting 94% of the fleet.
5. **Why does bounding scope matter?** — Bootstrap is the cold-start bottleneck. Shipping Delta + Parquet profiling in Phase 1 unblocks the flywheel for the vast majority of datasets while Iceberg support is developed in parallel.

### 1.3 Hidden Assumptions

| # | Assumption | Risk if Invalid | Validation Method |
|:--|:---|:---|:---|
| A1 | Delta Lake ≥ 2.0.0 is deployed on all production Spark clusters | Commit log schema may differ; profiling engine reads incorrect metadata | Cluster inventory audit |
| A2 | Historical data for ≥ 70% of Tier-1 datasets spans ≥ 7 days | Synthetic baselines dominate; initial signal quality is degraded | Data lake partition survey |
| A3 | GitHub App can be installed on all target repositories | Autopilot Repo Scanner cannot discover datasets | DevSecOps policy review |
| A4 | AWS Step Functions standard workflow quota (25K state transitions/execution) is sufficient | Long-running bootstraps with many retries hit quota limits | Worst-case state transition modeling |
| A5 | DuckDB can profile ≤ 10M row Parquet/Delta partitions in < 5 min on r6g.xlarge | Profiling latency exceeds SLA; worker pool sizing is wrong | Load test in staging |
| A6 | Spark EMR Serverless jobs can be launched programmatically from Step Functions | Custom integration layer required; adds 2-week delivery | EMR Serverless SDK compatibility check |
| A7 | CODEOWNERS files exist in ≥ 80% of repositories | Owner assignment for auto-discovered datasets requires manual intervention | Repository metadata survey |
| A8 | Policy bundle YAML ≤ 64 KB after signing (DynamoDB item size limit for state records) | Policy bundles stored as S3 references only; adds read latency to orchestrator | Sample policy bundle sizing |
| A9 | Single-region deployment is acceptable for Phase 1 | DR requirements for bootstrap state unmet | Architecture Review Board |

### 1.4 Document Structure

This LLD is organized by component, following the bootstrap lifecycle from dataset discovery to signal-ready state:

1. **C-01: Bootstrap Orchestrator** — State machine managing the 4-step lifecycle
2. **C-02: Dataset Registry** — Stores and validates `dataset.yaml` configurations
3. **C-03: Profiling Engine** — Computes statistical baselines from historical data
4. **C-04: Baseline Store** — Persists and refines computed/synthetic baselines
5. **C-05: Policy Generator** — Auto-generates `policy_bundle.yaml` from baselines and templates
6. **C-06: Certified View Initializer** — Creates the initial certified view pointer
7. **C-07: Autopilot Repo Scanner** — Discovers datasets by analyzing repository code
8. **C-08: PR Generator** — Creates instrumentation pull requests
9. **C-09: Fleet Dashboard Exporter** — Emits bootstrap progress metrics

### 1.5 Requirements Traceability

| PRD Goal | HLD Component | LLD Coverage | Section |
|:---|:---|:---|:---|
| G1: MTTD < 15 min | Bootstrap → Run-the-Engine handoff | Deterministic signal-ready gate | §2, §7 |
| G2: RCA Copilot explains 70%+ | Certified View Init + Neptune graph seeding | Graph node creation with lineage edges | §7 |
| G3: 95% contract coverage on Tier-1 | Policy Generator + Gateway signing | Full contract generation for Tier-1 | §6 |
| G4: 80% repo instrumented in 60 days | Autopilot Repo Scanner + PR Generator | Fleet-scale auto-bootstrap pipeline | §8, §9 |
| G5: Unified batch + streaming pane | Evidence schema alignment during bootstrap | Shared `dataset.yaml` schema with batch envelope | §3 |

---

## 2. C-01: Bootstrap Orchestrator

### 2.1 Responsibility

The Bootstrap Orchestrator is a **stateful workflow service** implemented as AWS Step Functions state machines. It manages the sequential 4-step lifecycle (Registration → Profiling → Policy Configuration → Certification Init) for each dataset being onboarded, tracks progress, handles failures with retries, and coordinates human approvals for Tier-1/Tier-2 datasets.

### 2.2 Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                   Bootstrap Orchestrator                        │
│                                                                 │
│  ┌──────────────────────┐    ┌───────────────────────────────┐  │
│  │ API Gateway          │    │ Step Functions                │  │
│  │ (REST + Webhook)     │───▶│ (1 state machine per dataset) │  │
│  └──────────────────────┘    └──────────┬────────────────────┘  │
│                                         │                       │
│       ┌─────────────────────────────────┤                       │
│       │              │                  │                       │
│       ▼              ▼                  ▼                       │
│  ┌─────────┐   ┌──────────┐   ┌──────────────┐                 │
│  │ DynamoDB │   │ SQS FIFO │   │ SNS Topics   │                 │
│  │ (State)  │   │ (Async   │   │ (Approval    │                 │
│  │          │   │  Tasks)  │   │  Callbacks)  │                 │
│  └─────────┘   └──────────┘   └──────────────┘                 │
└─────────────────────────────────────────────────────────────────┘
```

### 2.3 API Contract

#### 2.3.1 Initiate Bootstrap

```
POST /v1/bootstrap/initiate
```

**Request Body:**

```python
@dataclass
class BootstrapInitRequest:
    """Initiates bootstrap for a single dataset."""
    
    dataset_urn: str                        # "ds://curated/orders_enriched"
    tier: str                               # "TIER_1" | "TIER_2" | "TIER_3"
    enforcement_model: str                  # "inline_sdk" | "post_write"
    runtime: str                            # "spark" | "python" | "dask" | "dbt"
    storage_format: str                     # "delta" | "parquet"
    initiated_by: str                       # "autopilot" | "human:<username>"
    dataset_yaml_s3_uri: str                # S3 URI of submitted dataset.yaml
    override_profiling_days: Optional[int]  # Override default 7-day lookback
    skip_profiling: bool = False            # True if synthetic baseline requested
    
    def validate(self) -> list[str]:
        """Returns list of validation errors, empty if valid."""
        errors = []
        if not self.dataset_urn.startswith("ds://"):
            errors.append("dataset_urn must start with 'ds://'")
        if self.tier not in ("TIER_1", "TIER_2", "TIER_3"):
            errors.append(f"Invalid tier: {self.tier}")
        if self.storage_format not in ("delta", "parquet"):
            errors.append(f"Unsupported storage format: {self.storage_format}")
        if self.enforcement_model not in ("inline_sdk", "post_write"):
            errors.append(f"Invalid enforcement model: {self.enforcement_model}")
        return errors
```

**Response:**

```json
{
  "bootstrap_id": "boot-2026-02-17-001",
  "dataset_urn": "ds://curated/orders_enriched",
  "execution_arn": "arn:aws:states:us-east-1:123456:execution:bootstrap:boot-2026-02-17-001",
  "current_step": "REGISTERED",
  "estimated_completion": "2026-02-17T13:00:00Z",
  "status": "IN_PROGRESS"
}
```

**Idempotency:** If a bootstrap is already in progress for the given `dataset_urn`, the API returns `409 Conflict` with the existing `bootstrap_id`. Completed bootstraps can be re-initiated with a `force=true` parameter.

#### 2.3.2 Get Bootstrap Status

```
GET /v1/bootstrap/{bootstrap_id}
```

**Response:** Returns the full `BootstrapStateRecord` (see §2.5).

#### 2.3.3 Approve Policy

```
POST /v1/bootstrap/{bootstrap_id}/approve-policy
```

**Request Body:**

```python
@dataclass
class PolicyApprovalRequest:
    approved_by: str                    # "human:jane.doe" | "autopilot:auto-approve-tier3"
    approval_action: str                # "APPROVE" | "REJECT"
    rejection_reason: Optional[str]     # Required if REJECT
    feedback_for_regeneration: Optional[str]  # Guidance for re-generation
```

**Response:** Returns updated `BootstrapStateRecord` with transition to `POLICY_APPROVED` or `POLICY_REJECTED`.

#### 2.3.4 Cancel Bootstrap

```
POST /v1/bootstrap/{bootstrap_id}/cancel
```

**Behavior:** Transitions the state machine to `CANCELLED`. In-flight profiling jobs are terminated via EMR API. Artifacts are retained for future re-bootstrap.

### 2.4 Step Functions State Machine Definition

```python
BOOTSTRAP_STATE_MACHINE = {
    "Comment": "Batch Bootstrap Lifecycle - 4-Step Pipeline",
    "StartAt": "ValidateRegistration",
    "States": {
        "ValidateRegistration": {
            "Type": "Task",
            "Resource": "arn:aws:lambda:us-east-1:123456:function:bootstrap-validate-registration",
            "Parameters": {
                "bootstrap_id.$": "$.bootstrap_id",
                "dataset_yaml_s3_uri.$": "$.dataset_yaml_s3_uri",
            },
            "ResultPath": "$.registration_result",
            "Retry": [{"ErrorEquals": ["States.TaskFailed"], "MaxAttempts": 2, "BackoffRate": 2}],
            "Catch": [{"ErrorEquals": ["States.ALL"], "Next": "BootstrapFailed", "ResultPath": "$.error"}],
            "Next": "UpdateState_Registered",
        },
        "UpdateState_Registered": {
            "Type": "Task",
            "Resource": "arn:aws:lambda:us-east-1:123456:function:bootstrap-update-state",
            "Parameters": {
                "bootstrap_id.$": "$.bootstrap_id",
                "step": "registration",
                "status": "COMPLETED",
            },
            "Next": "TriggerProfiling",
        },
        "TriggerProfiling": {
            "Type": "Task",
            "Resource": "arn:aws:lambda:us-east-1:123456:function:bootstrap-trigger-profiling",
            "Parameters": {
                "bootstrap_id.$": "$.bootstrap_id",
                "dataset_urn.$": "$.dataset_urn",
                "storage_format.$": "$.storage_format",
                "skip_profiling.$": "$.skip_profiling",
            },
            "ResultPath": "$.profiling_result",
            "TimeoutSeconds": 1800,  # 30 min max for profiling
            "Retry": [
                {
                    "ErrorEquals": ["ProfilingOOM"],
                    "MaxAttempts": 1,
                    "Comment": "Retry with sampling on OOM",
                },
                {
                    "ErrorEquals": ["States.TaskFailed"],
                    "MaxAttempts": 3,
                    "BackoffRate": 2,
                    "IntervalSeconds": 60,
                },
            ],
            "Catch": [
                {
                    "ErrorEquals": ["ProfilingOOM"],
                    "Next": "FallbackToSyntheticBaseline",
                    "ResultPath": "$.error",
                },
                {
                    "ErrorEquals": ["States.ALL"],
                    "Next": "BootstrapFailed",
                    "ResultPath": "$.error",
                },
            ],
            "Next": "UpdateState_Profiled",
        },
        "FallbackToSyntheticBaseline": {
            "Type": "Task",
            "Resource": "arn:aws:lambda:us-east-1:123456:function:bootstrap-synthetic-baseline",
            "Parameters": {
                "bootstrap_id.$": "$.bootstrap_id",
                "dataset_urn.$": "$.dataset_urn",
                "tier.$": "$.tier",
                "reason": "PROFILING_OOM_FALLBACK",
            },
            "Next": "UpdateState_Profiled",
        },
        "UpdateState_Profiled": {
            "Type": "Task",
            "Resource": "arn:aws:lambda:us-east-1:123456:function:bootstrap-update-state",
            "Parameters": {
                "bootstrap_id.$": "$.bootstrap_id",
                "step": "profiling",
                "status": "COMPLETED",
            },
            "Next": "GeneratePolicy",
        },
        "GeneratePolicy": {
            "Type": "Task",
            "Resource": "arn:aws:lambda:us-east-1:123456:function:bootstrap-generate-policy",
            "Parameters": {
                "bootstrap_id.$": "$.bootstrap_id",
                "dataset_urn.$": "$.dataset_urn",
                "tier.$": "$.tier",
            },
            "ResultPath": "$.policy_result",
            "Next": "PolicyApprovalRouter",
        },
        "PolicyApprovalRouter": {
            "Type": "Choice",
            "Choices": [
                {
                    "Variable": "$.tier",
                    "StringEquals": "TIER_3",
                    "Next": "AutoApprovePolicy",
                },
            ],
            "Default": "WaitForHumanApproval",
        },
        "AutoApprovePolicy": {
            "Type": "Wait",
            "Seconds": 172800,  # 48-hour cooling period
            "Next": "ApprovePolicy",
        },
        "WaitForHumanApproval": {
            "Type": "Task",
            "Resource": "arn:aws:states:::sqs:sendMessage.waitForTaskToken",
            "Parameters": {
                "QueueUrl": "${ApprovalQueueUrl}",
                "MessageBody": {
                    "bootstrap_id.$": "$.bootstrap_id",
                    "dataset_urn.$": "$.dataset_urn",
                    "policy_pr_url.$": "$.policy_result.pr_url",
                    "TaskToken.$": "$$.Task.Token",
                },
            },
            "TimeoutSeconds": 604800,  # 7-day approval timeout
            "Catch": [
                {
                    "ErrorEquals": ["States.Timeout"],
                    "Next": "EscalateApproval",
                    "ResultPath": "$.error",
                }
            ],
            "Next": "CheckApprovalResult",
        },
        "CheckApprovalResult": {
            "Type": "Choice",
            "Choices": [
                {
                    "Variable": "$.approval_action",
                    "StringEquals": "REJECT",
                    "Next": "RegeneratePolicy",
                },
            ],
            "Default": "ApprovePolicy",
        },
        "RegeneratePolicy": {
            "Type": "Task",
            "Resource": "arn:aws:lambda:us-east-1:123456:function:bootstrap-regenerate-policy",
            "Parameters": {
                "bootstrap_id.$": "$.bootstrap_id",
                "feedback.$": "$.feedback_for_regeneration",
                "attempt.$": "$.policy_result.attempt",
            },
            "ResultPath": "$.policy_result",
            "Next": "CheckRegenerationLimit",
        },
        "CheckRegenerationLimit": {
            "Type": "Choice",
            "Choices": [
                {
                    "Variable": "$.policy_result.attempt",
                    "NumericGreaterThan": 3,
                    "Next": "EscalateApproval",
                },
            ],
            "Default": "WaitForHumanApproval",
        },
        "EscalateApproval": {
            "Type": "Task",
            "Resource": "arn:aws:lambda:us-east-1:123456:function:bootstrap-escalate",
            "Parameters": {
                "bootstrap_id.$": "$.bootstrap_id",
                "reason": "APPROVAL_TIMEOUT_OR_MAX_REJECTIONS",
            },
            "Next": "WaitForHumanApproval",
        },
        "ApprovePolicy": {
            "Type": "Task",
            "Resource": "arn:aws:lambda:us-east-1:123456:function:bootstrap-sign-policy",
            "Parameters": {
                "bootstrap_id.$": "$.bootstrap_id",
                "dataset_urn.$": "$.dataset_urn",
            },
            "ResultPath": "$.signed_policy",
            "Next": "UpdateState_PolicyApproved",
        },
        "UpdateState_PolicyApproved": {
            "Type": "Task",
            "Resource": "arn:aws:lambda:us-east-1:123456:function:bootstrap-update-state",
            "Parameters": {
                "bootstrap_id.$": "$.bootstrap_id",
                "step": "policy_config",
                "status": "COMPLETED",
            },
            "Next": "InitCertifiedView",
        },
        "InitCertifiedView": {
            "Type": "Task",
            "Resource": "arn:aws:lambda:us-east-1:123456:function:bootstrap-init-certified-view",
            "Parameters": {
                "bootstrap_id.$": "$.bootstrap_id",
                "dataset_urn.$": "$.dataset_urn",
                "enforcement_model.$": "$.enforcement_model",
                "storage_format.$": "$.storage_format",
            },
            "ResultPath": "$.certification_result",
            "Retry": [{"ErrorEquals": ["States.TaskFailed"], "MaxAttempts": 3, "BackoffRate": 2}],
            "Catch": [
                {
                    "ErrorEquals": ["GoldTableNotFound"],
                    "Next": "DeferCertification",
                    "ResultPath": "$.error",
                },
                {
                    "ErrorEquals": ["States.ALL"],
                    "Next": "BootstrapFailed",
                    "ResultPath": "$.error",
                },
            ],
            "Next": "UpdateState_SignalReady",
        },
        "DeferCertification": {
            "Type": "Task",
            "Resource": "arn:aws:lambda:us-east-1:123456:function:bootstrap-defer-certification",
            "Comment": "Gold table doesn't exist yet; set up trigger for first successful write",
            "Next": "UpdateState_CertPending",
        },
        "UpdateState_CertPending": {
            "Type": "Task",
            "Resource": "arn:aws:lambda:us-east-1:123456:function:bootstrap-update-state",
            "Parameters": {
                "bootstrap_id.$": "$.bootstrap_id",
                "step": "certification_init",
                "status": "DEFERRED",
            },
            "Next": "BootstrapCompletePartial",
        },
        "UpdateState_SignalReady": {
            "Type": "Task",
            "Resource": "arn:aws:lambda:us-east-1:123456:function:bootstrap-update-state",
            "Parameters": {
                "bootstrap_id.$": "$.bootstrap_id",
                "step": "certification_init",
                "status": "COMPLETED",
            },
            "Next": "EmitSignalReadyEvent",
        },
        "EmitSignalReadyEvent": {
            "Type": "Task",
            "Resource": "arn:aws:lambda:us-east-1:123456:function:bootstrap-emit-signal-ready",
            "Comment": "Publishes SIGNAL_READY event to Evidence Bus + creates Neptune graph node",
            "End": True,
        },
        "BootstrapCompletePartial": {
            "Type": "Succeed",
            "Comment": "Bootstrap complete except cert deferred until first write",
        },
        "BootstrapFailed": {
            "Type": "Task",
            "Resource": "arn:aws:lambda:us-east-1:123456:function:bootstrap-handle-failure",
            "Next": "BootstrapFailedTerminal",
        },
        "BootstrapFailedTerminal": {
            "Type": "Fail",
            "Cause": "Bootstrap failed after exhausting retries",
        },
    },
}
```

### 2.5 Bootstrap State Record (DynamoDB)

**Table: `BootstrapState`**

| Attribute | Type | Key | Description |
|:---|:---|:---|:---|
| `dataset_urn` | String | PK | Canonical dataset identifier |
| `bootstrap_id` | String | SK | Bootstrap execution ID (`boot-{date}-{seq}`) |
| `tier` | String | — | `TIER_1` / `TIER_2` / `TIER_3` |
| `current_step` | String | — | Current lifecycle state (see enum below) |
| `enforcement_model` | String | — | `inline_sdk` / `post_write` |
| `storage_format` | String | — | `delta` / `parquet` |
| `runtime_detected` | String | — | `spark` / `python` / `dask` / `dbt` |
| `initiated_by` | String | — | `autopilot` / `human:<username>` |
| `started_at` | String (ISO) | — | Bootstrap initiation timestamp |
| `completed_at` | String (ISO) | — | Completion timestamp (null if in progress) |
| `execution_arn` | String | — | Step Functions execution ARN |
| `steps` | Map | — | Per-step status records (see below) |
| `updated_at` | String (ISO) | — | Last state update |
| `ttl` | Number | — | DynamoDB TTL: 365 days after completion |

**Step Status Enum:**

```python
class BootstrapStep(str, Enum):
    REGISTERED = "REGISTERED"
    PROFILING = "PROFILING"
    PROFILING_FAILED = "PROFILING_FAILED"
    PROFILED = "PROFILED"
    POLICY_PENDING = "POLICY_PENDING"
    POLICY_REJECTED = "POLICY_REJECTED"
    POLICY_APPROVED = "POLICY_APPROVED"
    CERTIFYING = "CERTIFYING"
    CERT_DEFERRED = "CERT_DEFERRED"
    SIGNAL_READY = "SIGNAL_READY"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"
```

**Per-Step Detail Map:**

```python
@dataclass
class StepDetail:
    status: str                          # "NOT_STARTED" | "IN_PROGRESS" | "COMPLETED" | "FAILED" | "DEFERRED"
    started_at: Optional[str]            # ISO timestamp
    completed_at: Optional[str]          # ISO timestamp
    artifact_s3_uri: Optional[str]       # S3 URI of step output artifact
    error_message: Optional[str]         # Last error if FAILED
    retry_count: int = 0                 # Number of retries attempted
    metadata: Optional[dict] = None      # Step-specific metadata (profiling job ID, PR URL, etc.)
```

### 2.6 Concurrency Control

The orchestrator limits parallel bootstraps to prevent profiling compute storms:

```python
CONCURRENCY_CONFIG = {
    "max_parallel_bootstraps": 20,
    "max_profiling_jobs_concurrent": 10,      # Subset of above — profiling is compute-heavy
    "per_tier_limits": {
        "TIER_1": 5,                          # Tier-1 gets priority allocation
        "TIER_2": 10,
        "TIER_3": 5,                          # Tier-3 uses synthetic baselines more often
    },
    "queue_overflow_action": "FIFO_WAIT",     # Excess requests wait in SQS FIFO
}
```

**Implementation:** A DynamoDB `BootstrapConcurrency` table tracks active bootstraps per tier. The `ValidateRegistration` Lambda checks this table before accepting a new bootstrap. If at capacity, the request is queued in SQS FIFO (`bootstrap-overflow.fifo`) and polled by an EventBridge scheduler every 60 seconds.

**BootstrapConcurrency Table:**

| Attribute | Type | Key | Description |
|:---|:---|:---|:---|
| `tier` | String | PK | `TIER_1` / `TIER_2` / `TIER_3` / `GLOBAL` |
| `active_count` | Number | — | Current active bootstraps for this tier |
| `active_bootstrap_ids` | StringSet | — | Set of active bootstrap IDs |
| `updated_at` | String (ISO) | — | Last update timestamp |

### 2.7 Timeout Configuration

| Tier | End-to-End Timeout | Profiling Timeout | Approval Timeout | Cert Init Timeout |
|:---|:---|:---|:---|:---|
| TIER_1 | 168 hours (7 days) | 30 min | 120 hours (5 days) | 10 min |
| TIER_2 | 240 hours (10 days) | 30 min | 168 hours (7 days) | 10 min |
| TIER_3 | 72 hours (3 days) | 15 min | 48 hours (auto) | 10 min |

### 2.8 Error Handling

| Failure Scenario | Behavior | Recovery |
|:---|:---|:---|
| Registration validation fails | Reject with detailed errors; no state machine started | Fix `dataset.yaml` and re-submit |
| Profiling OOM (first attempt) | Retry with 10% sampling rate | Automatic via state machine |
| Profiling OOM (retry also fails) | Fallback to synthetic baseline | `FallbackToSyntheticBaseline` state |
| Profiling timeout (30 min) | Mark profiling as FAILED; retry up to 3× | Step Functions retry config |
| Policy generation fails | Emit `bootstrap.policy.generation_failed` metric; retry | Lambda retry with backoff |
| Approval timeout (Tier-1/2) | Escalate to team lead via SNS; extend wait | `EscalateApproval` state |
| 3× policy rejections | Escalate; pause auto-regeneration | Manual intervention required |
| Gold table doesn't exist | Defer certification; create trigger for first write | `DeferCertification` state |
| Schema changes during bootstrap | Re-profile if schema fingerprint changes between Steps 2–4 | Detected in `InitCertifiedView` Lambda |
| Concurrent bootstrap on same URN | Reject duplicate; return existing `bootstrap_id` | API-level idempotency check |
| Step Functions execution quota | Queue overflow in SQS FIFO | Polled by EventBridge scheduler |

### 2.9 Observability

| Metric | Type | Alert Threshold |
|:---|:---|:---|
| `bootstrap.initiated` | Counter (by tier, initiated_by) | — |
| `bootstrap.completed` | Counter (by tier) | — |
| `bootstrap.failed` | Counter (by tier, failure_step) | > 0 for Tier-1 |
| `bootstrap.duration_hours` | Histogram (by tier) | p95 > tier SLA |
| `bootstrap.step_duration_ms` | Histogram (by step, tier) | p99 > step timeout × 0.8 |
| `bootstrap.active_count` | Gauge (by tier) | > per_tier_limit |
| `bootstrap.stuck_count` | Gauge | > 0 in same step for > 24h |
| `bootstrap.approval_wait_hours` | Histogram (by tier) | > approval_timeout × 0.5 |
| `bootstrap.overflow_queue_depth` | Gauge | > 50 |

### 2.10 Deployment

| Property | Value |
|:---|:---|
| API Runtime | API Gateway + Lambda (Python 3.12) |
| State Machine | AWS Step Functions (Standard Workflow) |
| State Store | DynamoDB (on-demand capacity) |
| Overflow Queue | SQS FIFO |
| Approval Notifications | SNS → Slack + Email |
| IAM Roles | `bootstrap-orchestrator-role` (Step Functions, Lambda, DynamoDB, SQS, SNS) |

---

## 3. C-02: Dataset Registry

### 3.1 Responsibility

The Dataset Registry is the **system of record** for all dataset configurations (`dataset.yaml`). It stores, versions, and validates registration manifests. The registry serves as the entry point for the bootstrap pipeline and the runtime configuration source for the Run-the-Engine phase.

### 3.2 API Contract

#### 3.2.1 Register Dataset

```
PUT /v1/registry/datasets/{dataset_urn}
```

**Request Body:** `dataset.yaml` content (application/yaml)

**Validation Rules:**

```python
class DatasetYamlValidator:
    """Validates dataset.yaml before registration."""
    
    REQUIRED_FIELDS = ["urn", "owner_team", "tier", "runtime", "storage", "slo"]
    VALID_FORMATS = ["delta", "parquet"]  # Phase 1 scope
    VALID_RUNTIMES = ["spark", "python", "dask", "dbt"]
    VALID_TIERS = ["TIER_1", "TIER_2", "TIER_3"]
    VALID_ENFORCEMENT = ["inline_sdk", "post_write"]
    
    def validate(self, yaml_content: dict) -> list[str]:
        errors = []
        
        # Required fields
        for field in self.REQUIRED_FIELDS:
            if field not in yaml_content:
                errors.append(f"Missing required field: {field}")
        
        # Storage format check (Phase 1 scope)
        fmt = yaml_content.get("storage", {}).get("format", "")
        if fmt not in self.VALID_FORMATS:
            errors.append(f"Unsupported storage format: {fmt}. Phase 1 supports: {self.VALID_FORMATS}")
        
        # URN format
        urn = yaml_content.get("urn", "")
        if not re.match(r"^ds://[a-z_]+/[a-z0-9_]+$", urn):
            errors.append(f"Invalid URN format: {urn}. Expected: ds://{{zone}}/{{dataset_name}}")
        
        # Storage paths must be S3 URIs
        storage = yaml_content.get("storage", {})
        for path_key in ["bronze", "silver", "gold"]:
            path = storage.get(path_key, "")
            if path and not path.startswith("s3://"):
                errors.append(f"storage.{path_key} must be an S3 URI")
        
        # Delta-specific: gold path required
        if fmt == "delta" and not storage.get("gold"):
            errors.append("Delta format requires storage.gold path")
        
        # Parquet-specific: partition_key recommended
        if fmt == "parquet" and not storage.get("partition_key"):
            errors.append("WARNING: Parquet format without partition_key; profiling may be slow")
        
        # Enforcement model validation
        enforcement = yaml_content.get("enforcement_model", "")
        if enforcement and enforcement not in self.VALID_ENFORCEMENT:
            errors.append(f"Invalid enforcement_model: {enforcement}")
        
        # dbt cannot use inline_sdk
        if yaml_content.get("runtime") == "dbt" and enforcement == "inline_sdk":
            errors.append("dbt runtime is incompatible with inline_sdk enforcement model")
        
        return errors
```

#### 3.2.2 Get Dataset

```
GET /v1/registry/datasets/{dataset_urn}?version={version}
```

Returns the `dataset.yaml` content for the specified version (latest if omitted).

#### 3.2.3 List Datasets

```
GET /v1/registry/datasets?tier={tier}&status={status}&format={format}&page_token={token}
```

Returns paginated list of registered datasets with filtering.

### 3.3 DynamoDB Table — DatasetRegistry

| Attribute | Type | Key | Description |
|:---|:---|:---|:---|
| `dataset_urn` | String | PK | Canonical URN (`ds://zone/name`) |
| `version` | Number | SK | Monotonically increasing version |
| `yaml_content` | Map | — | Parsed dataset.yaml as DynamoDB map |
| `yaml_s3_uri` | String | — | S3 URI of raw YAML file |
| `status` | String | — | `REGISTERED` / `BOOTSTRAPPING` / `SIGNAL_READY` / `DECOMMISSIONED` |
| `tier` | String | — | `TIER_1` / `TIER_2` / `TIER_3` |
| `storage_format` | String | — | `delta` / `parquet` |
| `runtime` | String | — | `spark` / `python` / `dask` / `dbt` |
| `enforcement_model` | String | — | `inline_sdk` / `post_write` |
| `owner_team` | String | — | Owning team name |
| `registered_by` | String | — | `autopilot` / `human:<username>` |
| `registered_at` | String (ISO) | — | Registration timestamp |
| `bootstrap_id` | String | — | Active bootstrap execution ID |
| `updated_at` | String (ISO) | — | Last update timestamp |

**GSI-1: `tier-status-index`** — PK: `tier`, SK: `status` — for fleet dashboard queries.

**GSI-2: `owner-team-index`** — PK: `owner_team`, SK: `registered_at` — for team-level queries.

### 3.4 S3 Storage Layout

```
s3://sf-config/
  └── datasets/
      └── {dataset_name}/
          ├── dataset.yaml              # Latest version
          ├── dataset.yaml.v1           # Version history
          ├── dataset.yaml.v2
          ├── baseline.json             # Latest baseline
          ├── baseline.json.history/    # Baseline version history
          │   ├── baseline.v1.json
          │   └── baseline.v2.json
          └── policy_bundle.yaml        # Latest signed policy
```

### 3.5 Error Handling

| Failure Scenario | Behavior | Recovery |
|:---|:---|:---|
| Invalid YAML syntax | Return 400 with parse error | Fix and re-submit |
| Validation rule failure | Return 400 with specific field errors | Fix and re-submit |
| Duplicate URN (different version) | Create new version; return 200 | Normal versioning behavior |
| S3 write failure | Retry 3×; return 503 if exhausted | Automatic retry |
| DynamoDB conditional check fails | Concurrent write conflict; retry with fresh version | Optimistic concurrency |

### 3.6 Observability

| Metric | Type | Alert Threshold |
|:---|:---|:---|
| `registry.datasets.registered` | Counter (by tier, format) | — |
| `registry.datasets.total` | Gauge (by tier, status) | — |
| `registry.validation.failures` | Counter (by error_type) | > 50% of submissions |
| `registry.api.latency_ms` | Histogram | p99 > 500ms |

---

## 4. C-03: Profiling Engine

### 4.1 Responsibility

The Profiling Engine computes statistical baselines from historical data for newly registered datasets. It samples recent partitions, computes volume, schema, null-rate, timing, and PII statistics, and outputs a `baseline.json` artifact. This is the **most compute-intensive** step in the bootstrap pipeline.

### 4.2 Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                       Profiling Engine                        │
│                                                               │
│  ┌──────────────────────┐                                     │
│  │ Profiling Dispatcher │  ← Invoked by Bootstrap Orchestrator│
│  │ (Lambda)             │                                     │
│  └──────────┬───────────┘                                     │
│             │                                                 │
│             ├─── < 1M rows × 7 days ──▶ DuckDB Profiler      │
│             │                           (Lambda, in-memory)   │
│             │                                                 │
│             └─── ≥ 1M rows × 7 days ──▶ Spark Profiler       │
│                                         (EMR Serverless)      │
│                                                               │
│  Both paths produce:                                          │
│  ┌─────────────────────┐                                      │
│  │ baseline.json        │  → S3 + Baseline Store (DynamoDB)   │
│  └─────────────────────┘                                      │
└──────────────────────────────────────────────────────────────┘
```

### 4.3 Profiling Dispatcher

The dispatcher inspects metadata to choose the profiling engine:

```python
class ProfilingDispatcher:
    """Routes profiling jobs to DuckDB or Spark based on data volume."""
    
    DUCKDB_ROW_THRESHOLD = 1_000_000  # 1M rows per partition × 7 partitions = 7M total
    DUCKDB_BYTE_THRESHOLD = 1 * 1024 * 1024 * 1024  # 1 GB total across sampled partitions
    DEFAULT_LOOKBACK_DAYS = 7
    MIN_LOOKBACK_DAYS = 3
    
    def dispatch(self, request: ProfilingRequest) -> ProfilingJob:
        partitions = self._discover_partitions(request)
        
        if len(partitions) < self.MIN_LOOKBACK_DAYS:
            return ProfilingJob(
                engine="synthetic",
                reason=f"Insufficient history: {len(partitions)} partitions (need ≥ {self.MIN_LOOKBACK_DAYS})",
                partitions=partitions,
            )
        
        # Sample most recent N partitions
        sampled = sorted(partitions, key=lambda p: p.partition_value, reverse=True)[
            : self.DEFAULT_LOOKBACK_DAYS
        ]
        total_bytes = sum(p.total_bytes for p in sampled)
        estimated_rows = self._estimate_row_count(sampled, request.storage_format)
        
        if estimated_rows <= self.DUCKDB_ROW_THRESHOLD and total_bytes <= self.DUCKDB_BYTE_THRESHOLD:
            return ProfilingJob(engine="duckdb", partitions=sampled, estimated_rows=estimated_rows)
        else:
            sample_rate = min(1.0, self.DUCKDB_ROW_THRESHOLD / estimated_rows)
            return ProfilingJob(
                engine="spark",
                partitions=sampled,
                estimated_rows=estimated_rows,
                sample_rate=sample_rate if estimated_rows > 100_000_000 else 1.0,
            )
    
    def _discover_partitions(self, request: ProfilingRequest) -> list[PartitionInfo]:
        """Discover available partitions for Delta or Parquet datasets."""
        if request.storage_format == "delta":
            return self._discover_delta_partitions(request)
        elif request.storage_format == "parquet":
            return self._discover_parquet_partitions(request)
        else:
            raise ValueError(f"Unsupported format: {request.storage_format}")
    
    def _discover_delta_partitions(self, request: ProfilingRequest) -> list[PartitionInfo]:
        """Read Delta transaction log to discover partitions and their stats."""
        import json
        log_path = f"{request.gold_path}/_delta_log/"
        
        # Read latest checkpoint + subsequent commits for partition info
        partitions = {}
        for commit in self._read_delta_commits(log_path):
            for add_action in commit.get("add", []):
                partition_values = add_action.get("partitionValues", {})
                partition_key = json.dumps(partition_values, sort_keys=True)
                if partition_key not in partitions:
                    partitions[partition_key] = PartitionInfo(
                        partition_value=partition_values.get(request.partition_key, ""),
                        total_bytes=0,
                        file_count=0,
                    )
                partitions[partition_key].total_bytes += add_action.get("size", 0)
                partitions[partition_key].file_count += 1
        
        return list(partitions.values())
    
    def _discover_parquet_partitions(self, request: ProfilingRequest) -> list[PartitionInfo]:
        """List S3 prefixes to discover Hive-style partitions."""
        partitions = []
        prefix = request.gold_path
        partition_key = request.partition_key or "dt"
        
        # List S3 objects matching partition pattern: gold_path/{partition_key}=*/
        response = self.s3.list_objects_v2(
            Bucket=self._bucket(prefix),
            Prefix=self._key(prefix),
            Delimiter="/",
        )
        
        for common_prefix in response.get("CommonPrefixes", []):
            dir_name = common_prefix["Prefix"].rstrip("/").split("/")[-1]
            if "=" in dir_name:
                key, value = dir_name.split("=", 1)
                if key == partition_key:
                    # Get total size of partition
                    size_response = self.s3.list_objects_v2(
                        Bucket=self._bucket(prefix),
                        Prefix=common_prefix["Prefix"],
                    )
                    total_bytes = sum(
                        obj["Size"] for obj in size_response.get("Contents", [])
                        if obj["Key"].endswith(".parquet")
                    )
                    partitions.append(PartitionInfo(
                        partition_value=value,
                        total_bytes=total_bytes,
                        file_count=len(size_response.get("Contents", [])),
                    ))
        
        return partitions
    
    def _estimate_row_count(self, partitions: list, storage_format: str) -> int:
        """Estimate row count from file sizes using format-specific heuristics."""
        total_bytes = sum(p.total_bytes for p in partitions)
        if storage_format == "delta":
            return int(total_bytes / 200)   # ~200 bytes per row (compressed Parquet in Delta)
        elif storage_format == "parquet":
            return int(total_bytes / 180)   # ~180 bytes per row (standalone Parquet)
        return 0
```

### 4.4 DuckDB Profiler (Small Datasets)

```python
class DuckDBProfiler:
    """Profiles small datasets (< 1M rows × 7 partitions) using embedded DuckDB."""
    
    MEMORY_LIMIT = "1GB"
    THREADS = 4
    
    def __init__(self):
        self.conn = duckdb.connect(":memory:")
        self.conn.execute(f"SET memory_limit = '{self.MEMORY_LIMIT}'")
        self.conn.execute(f"SET threads = {self.THREADS}")
        # Install Delta extension for Delta Lake support
        self.conn.execute("INSTALL delta; LOAD delta;")
    
    def profile(self, job: ProfilingJob, request: ProfilingRequest) -> BaselineJson:
        """Run full profiling pipeline and produce baseline.json."""
        
        # Step 1: Read data
        df = self._read_data(request, job.partitions)
        
        # Step 2: Compute statistics
        volume_stats = self._compute_volume_stats(df, job.partitions, request)
        schema_stats = self._compute_schema_stats(df, request)
        null_stats = self._compute_null_stats(df)
        pii_scan = self._scan_for_pii(df)
        
        # Step 3: Assemble baseline
        return BaselineJson(
            dataset_urn=request.dataset_urn,
            bootstrap_id=request.bootstrap_id,
            profiling_metadata=ProfilingMetadata(
                profiled_at=datetime.now(timezone.utc).isoformat(),
                partitions_sampled=len(job.partitions),
                date_range=[
                    min(p.partition_value for p in job.partitions),
                    max(p.partition_value for p in job.partitions),
                ],
                total_rows_sampled=volume_stats.total_rows,
                profiling_engine="duckdb",
                is_synthetic=False,
                confidence="HIGH" if len(job.partitions) >= 7 else "MEDIUM",
            ),
            volume=volume_stats,
            schema=schema_stats,
            null_rates=null_stats,
            pii_scan=pii_scan,
        )
    
    def _read_data(self, request: ProfilingRequest, partitions: list) -> str:
        """Register data source in DuckDB and return table reference."""
        if request.storage_format == "delta":
            table_path = request.gold_path
            self.conn.execute(
                f"CREATE VIEW profiling_data AS SELECT * FROM delta_scan('{table_path}')"
            )
        elif request.storage_format == "parquet":
            # Build partition filter for Hive-style partitions
            partition_values = [p.partition_value for p in partitions]
            parquet_glob = f"{request.gold_path}/**/*.parquet"
            self.conn.execute(
                f"CREATE VIEW profiling_data AS SELECT * FROM read_parquet('{parquet_glob}', "
                f"hive_partitioning=true)"
            )
        return "profiling_data"
    
    def _compute_volume_stats(
        self, table_ref: str, partitions: list, request: ProfilingRequest
    ) -> VolumeStats:
        """Compute per-partition row counts and volume statistics."""
        partition_key = request.partition_key or "dt"
        
        result = self.conn.execute(f"""
            SELECT 
                {partition_key} as partition_value,
                COUNT(*) as row_count
            FROM {table_ref}
            GROUP BY {partition_key}
            ORDER BY {partition_key}
        """).fetchall()
        
        row_counts = [row[1] for row in result]
        
        avg_count = statistics.mean(row_counts) if row_counts else 0
        stddev_count = statistics.stdev(row_counts) if len(row_counts) >= 2 else 0
        
        return VolumeStats(
            avg_row_count=int(avg_count),
            stddev_row_count=int(stddev_count),
            min_row_count=min(row_counts) if row_counts else 0,
            max_row_count=max(row_counts) if row_counts else 0,
            anomaly_lower_bound=int(max(0, avg_count - 2 * stddev_count)),
            anomaly_upper_bound=int(avg_count + 2 * stddev_count),
            total_rows=sum(row_counts),
            partition_row_counts={str(r[0]): r[1] for r in result},
        )
    
    def _compute_schema_stats(self, table_ref: str, request: ProfilingRequest) -> SchemaStats:
        """Compute schema fingerprint and column metadata."""
        columns_info = self.conn.execute(f"""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = '{table_ref}'
            ORDER BY ordinal_position
        """).fetchall()
        
        columns = []
        schema_string_parts = []
        for col_name, col_type, nullable in columns_info:
            columns.append(ColumnInfo(
                name=col_name,
                type=self._normalize_type(col_type),
                nullable=nullable == "YES",
            ))
            schema_string_parts.append(f"{col_name}:{self._normalize_type(col_type)}:{nullable}")
        
        # Canonical fingerprint: SHA-256 of sorted, normalized column definitions
        canonical_string = "|".join(sorted(schema_string_parts))
        fingerprint = hashlib.sha256(canonical_string.encode()).hexdigest()
        
        return SchemaStats(
            column_count=len(columns),
            canonical_fingerprint=f"sha256:{fingerprint}",
            columns=columns,
        )
    
    def _compute_null_stats(self, table_ref: str) -> list[NullRateInfo]:
        """Compute null rates per column."""
        columns_info = self.conn.execute(f"""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = '{table_ref}'
        """).fetchall()
        
        null_rates = []
        total_rows = self.conn.execute(f"SELECT COUNT(*) FROM {table_ref}").fetchone()[0]
        
        if total_rows == 0:
            return null_rates
        
        for (col_name,) in columns_info:
            null_count = self.conn.execute(
                f'SELECT COUNT(*) FROM {table_ref} WHERE "{col_name}" IS NULL'
            ).fetchone()[0]
            null_rate = null_count / total_rows
            null_rates.append(NullRateInfo(
                column=col_name,
                null_rate=round(null_rate, 6),
                null_count=null_count,
            ))
        
        return null_rates
    
    def _scan_for_pii(self, table_ref: str) -> PiiScanResult:
        """Detect PII patterns by sampling string columns."""
        PII_PATTERNS = {
            "EMAIL": r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$",
            "PHONE": r"^[\+]?[\d\s\-\(\)]{7,15}$",
            "SSN": r"^\d{3}-\d{2}-\d{4}$",
            "CREDIT_CARD": r"^\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}$",
            "IP_ADDRESS": r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$",
        }
        
        # Get string columns
        string_cols = self.conn.execute(f"""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = '{table_ref}' 
            AND data_type IN ('VARCHAR', 'TEXT', 'STRING')
        """).fetchall()
        
        pii_columns = []
        pii_patterns = {}
        
        for (col_name,) in string_cols:
            # Sample 1000 non-null values
            samples = self.conn.execute(
                f'SELECT DISTINCT "{col_name}" FROM {table_ref} '
                f'WHERE "{col_name}" IS NOT NULL LIMIT 1000'
            ).fetchall()
            
            sample_values = [str(s[0]) for s in samples]
            
            for pattern_name, regex in PII_PATTERNS.items():
                matches = sum(1 for v in sample_values if re.match(regex, v))
                confidence = matches / len(sample_values) if sample_values else 0
                
                if confidence > 0.5:  # > 50% of samples match pattern
                    pii_columns.append(col_name)
                    pii_patterns[col_name] = {
                        "pattern": pattern_name,
                        "confidence": round(confidence, 2),
                    }
                    break  # One PII pattern per column is sufficient
        
        return PiiScanResult(
            columns_with_pii=list(set(pii_columns)),
            pii_patterns_detected=pii_patterns,
        )
    
    @staticmethod
    def _normalize_type(duckdb_type: str) -> str:
        """Normalize DuckDB types to canonical Signal Factory types."""
        TYPE_MAP = {
            "BIGINT": "LONG", "INTEGER": "INT", "SMALLINT": "SHORT",
            "DOUBLE": "DOUBLE", "FLOAT": "FLOAT", "DECIMAL": "DECIMAL",
            "VARCHAR": "STRING", "TEXT": "STRING",
            "BOOLEAN": "BOOLEAN", "DATE": "DATE",
            "TIMESTAMP": "TIMESTAMP", "TIMESTAMP WITH TIME ZONE": "TIMESTAMP_TZ",
        }
        return TYPE_MAP.get(duckdb_type.upper(), duckdb_type.upper())
```

### 4.5 Spark Profiler (Large Datasets)

```python
class SparkProfilerJobConfig:
    """Configuration for EMR Serverless profiling job."""
    
    APPLICATION_ID = "emr-serverless-profiling-app"
    ENTRY_POINT = "s3://sf-artifacts/profiling/spark_profiler.py"
    SPARK_SUBMIT_PARAMS = {
        "--conf": [
            "spark.executor.memory=8g",
            "spark.executor.cores=4",
            "spark.dynamicAllocation.enabled=true",
            "spark.dynamicAllocation.minExecutors=1",
            "spark.dynamicAllocation.maxExecutors=10",
            "spark.sql.extensions=io.delta.sql.DeltaSparkSessionExtension",
            "spark.sql.catalog.spark_catalog=org.apache.spark.sql.delta.catalog.DeltaCatalog",
        ],
    }
    MAX_RUNTIME_SECONDS = 1800  # 30 min

class SparkProfilerLauncher:
    """Launches EMR Serverless profiling jobs."""
    
    def __init__(self, emr_client):
        self.emr = emr_client
    
    def launch(self, request: ProfilingRequest, job: ProfilingJob) -> str:
        """Launch Spark profiling job; returns job_run_id."""
        response = self.emr.start_job_run(
            applicationId=SparkProfilerJobConfig.APPLICATION_ID,
            executionRoleArn="arn:aws:iam::123456:role/emr-profiling-role",
            jobDriver={
                "sparkSubmit": {
                    "entryPoint": SparkProfilerJobConfig.ENTRY_POINT,
                    "entryPointArguments": [
                        "--dataset-urn", request.dataset_urn,
                        "--bootstrap-id", request.bootstrap_id,
                        "--storage-format", request.storage_format,
                        "--gold-path", request.gold_path,
                        "--partition-key", request.partition_key,
                        "--lookback-days", str(len(job.partitions)),
                        "--sample-rate", str(job.sample_rate),
                        "--output-s3-uri", f"s3://sf-config/datasets/{request.dataset_name}/baseline.json",
                    ],
                    "sparkSubmitParameters": " ".join(
                        f"{k} {v}" for k, vs in SparkProfilerJobConfig.SPARK_SUBMIT_PARAMS.items()
                        for v in vs
                    ),
                },
            },
            configurationOverrides={
                "monitoringConfiguration": {
                    "s3MonitoringConfiguration": {
                        "logUri": f"s3://sf-logs/profiling/{request.bootstrap_id}/",
                    },
                },
            },
            executionTimeoutInMinutes=30,
            tags={
                "bootstrap_id": request.bootstrap_id,
                "dataset_urn": request.dataset_urn,
                "component": "profiling-engine",
            },
        )
        return response["jobRunId"]
```

**Spark Profiler Entry Point (`spark_profiler.py`):**

The Spark job follows the same statistical computation logic as DuckDB but operates on distributed DataFrames. Key differences:

| Aspect | DuckDB Path | Spark Path |
|:---|:---|:---|
| Data read | `delta_scan()` / `read_parquet()` | `spark.read.format("delta")` / `spark.read.parquet()` |
| Sampling | No sampling (small data) | `df.sample(rate)` for datasets > 100M rows |
| Schema introspection | `information_schema.columns` | `df.schema.fields` |
| PII scan | Regex on sampled values | `df.select(regexp_extract(...))` on sampled partition |
| Output | Direct write to S3 | Write to S3 via Spark |

### 4.6 Synthetic Baseline Generator

```python
class SyntheticBaselineGenerator:
    """Generates temporary baselines from organizational tier averages."""
    
    # Organizational defaults by tier (derived from profiling 50+ real datasets)
    TIER_DEFAULTS = {
        "TIER_1": {
            "avg_row_count": 500_000,
            "stddev_row_count": 150_000,
            "anomaly_multiplier": 3.0,   # 3σ — wide thresholds for synthetic
        },
        "TIER_2": {
            "avg_row_count": 100_000,
            "stddev_row_count": 50_000,
            "anomaly_multiplier": 3.0,
        },
        "TIER_3": {
            "avg_row_count": 10_000,
            "stddev_row_count": 5_000,
            "anomaly_multiplier": 3.0,
        },
    }
    AUTO_REFINE_AFTER_RUNS = 7
    
    def generate(self, dataset_urn: str, tier: str, bootstrap_id: str, 
                 reason: str) -> BaselineJson:
        defaults = self.TIER_DEFAULTS[tier]
        avg = defaults["avg_row_count"]
        stddev = defaults["stddev_row_count"]
        multiplier = defaults["anomaly_multiplier"]
        
        return BaselineJson(
            dataset_urn=dataset_urn,
            bootstrap_id=bootstrap_id,
            profiling_metadata=ProfilingMetadata(
                profiled_at=datetime.now(timezone.utc).isoformat(),
                partitions_sampled=0,
                date_range=[],
                total_rows_sampled=0,
                profiling_engine="synthetic",
                is_synthetic=True,
                confidence="LOW",
                synthetic_reason=reason,
                auto_refine_after_runs=self.AUTO_REFINE_AFTER_RUNS,
            ),
            volume=VolumeStats(
                avg_row_count=avg,
                stddev_row_count=stddev,
                min_row_count=max(0, avg - int(multiplier * stddev)),
                max_row_count=avg + int(multiplier * stddev),
                anomaly_lower_bound=max(0, avg - int(multiplier * stddev)),
                anomaly_upper_bound=avg + int(multiplier * stddev),
                total_rows=0,
                partition_row_counts={},
            ),
            schema=SchemaStats(
                column_count=0,
                canonical_fingerprint="sha256:SYNTHETIC_PENDING",
                columns=[],
            ),
            null_rates=[],
            pii_scan=PiiScanResult(columns_with_pii=[], pii_patterns_detected={}),
        )
```

### 4.7 Error Handling

| Failure Scenario | Behavior | Recovery |
|:---|:---|:---|
| DuckDB OOM (Lambda memory exceeded) | Lambda returns `ProfilingOOM` error | Orchestrator retries with Spark path |
| Spark job OOM | EMR returns FAILED status | Orchestrator retries with 10% sample; then synthetic fallback |
| Delta commit log unreadable | Cannot discover partitions | Return error; orchestrator retries or uses synthetic |
| No partitions found | Zero-length partition list | Generate synthetic baseline with reason `NO_HISTORY` |
| Parquet file footer corrupt | DuckDB/Spark read fails for specific file | Skip corrupt file; log warning; proceed with remaining |
| EMR Serverless quota exceeded | Job launch fails | Queue and retry after 5 min (up to 3 retries) |
| PII scan regex timeout | Single column scan exceeds 30s | Skip column; mark as `PII_SCAN_TIMEOUT` |

### 4.8 Observability

| Metric | Type | Alert Threshold |
|:---|:---|:---|
| `profiling.jobs.launched` | Counter (by engine: duckdb/spark/synthetic) | — |
| `profiling.jobs.completed` | Counter (by engine) | — |
| `profiling.jobs.failed` | Counter (by engine, error_type) | > 5% failure rate |
| `profiling.duration_ms` | Histogram (by engine) | p99 > 1800000ms (30 min) |
| `profiling.rows_profiled` | Counter | — |
| `profiling.partitions_sampled` | Histogram | — |
| `profiling.pii_columns_detected` | Counter | — |
| `profiling.synthetic_fallback` | Counter | > 30% of total profiles |

### 4.9 Deployment

| Property | Value |
|:---|:---|
| DuckDB Profiler Runtime | AWS Lambda (Python 3.12, 2048 MB, 15 min timeout) |
| Spark Profiler Runtime | EMR Serverless (Spark 3.5, Delta 2.4) |
| Profiling Dispatcher | AWS Lambda (Python 3.12, 512 MB, 60s timeout) |
| Output Storage | S3 (`s3://sf-config/datasets/{name}/baseline.json`) |

---

## 5. C-04: Baseline Store

### 5.1 Responsibility

The Baseline Store persists computed and synthetic baselines in DynamoDB for fast runtime access by Signal Engines during the Run-the-Engine phase. It also manages the **auto-refinement** lifecycle where synthetic baselines are replaced by computed ones after 7 real runs.

### 5.2 DynamoDB Table — Baselines

| Attribute | Type | Key | Description |
|:---|:---|:---|:---|
| `dataset_urn` | String | PK | Canonical dataset identifier |
| `metric_key` | String | SK | `volume` / `schema` / `null_rate:{col}` / `pii` / `timing` |
| `baseline_value` | Map | — | Metric-specific statistics (avg, stddev, bounds) |
| `confidence` | String | — | `HIGH` / `MEDIUM` / `LOW` |
| `is_synthetic` | Boolean | — | True if generated from tier averages |
| `source_bootstrap_id` | String | — | Bootstrap that created this baseline |
| `source_engine` | String | — | `duckdb` / `spark` / `synthetic` |
| `partitions_sampled` | Number | — | Number of historical partitions used |
| `created_at` | String (ISO) | — | Initial creation timestamp |
| `updated_at` | String (ISO) | — | Last refinement timestamp |
| `auto_refine_runs_remaining` | Number | — | Runs remaining before auto-refine (0 = stable) |
| `run_history` | List<Map> | — | Last 7 actual run metrics for refinement |

### 5.3 Auto-Refinement Logic

```python
class BaselineAutoRefiner:
    """Replaces synthetic baselines with computed baselines after N real runs."""
    
    REQUIRED_RUNS = 7
    NARROW_MULTIPLIER = 2.0    # 2σ for computed baselines
    WIDE_MULTIPLIER = 3.0      # 3σ for synthetic baselines
    
    def record_run(self, dataset_urn: str, run_metrics: RunMetrics) -> Optional[BaselineUpdate]:
        """Record a real run's metrics; trigger refinement if threshold met."""
        
        # Append to run_history in DynamoDB
        self.dynamodb.update_item(
            TableName="Baselines",
            Key={"dataset_urn": {"S": dataset_urn}, "metric_key": {"S": "volume"}},
            UpdateExpression="""
                SET run_history = list_append(if_not_exists(run_history, :empty_list), :new_run),
                    auto_refine_runs_remaining = auto_refine_runs_remaining - :one,
                    updated_at = :now
            """,
            ExpressionAttributeValues={
                ":new_run": {"L": [{"M": self._serialize_run(run_metrics)}]},
                ":empty_list": {"L": []},
                ":one": {"N": "1"},
                ":now": {"S": datetime.now(timezone.utc).isoformat()},
            },
        )
        
        # Check if refinement is due
        item = self.dynamodb.get_item(
            TableName="Baselines",
            Key={"dataset_urn": {"S": dataset_urn}, "metric_key": {"S": "volume"}},
        )
        
        runs_remaining = int(item["Item"]["auto_refine_runs_remaining"]["N"])
        
        if runs_remaining <= 0 and item["Item"].get("is_synthetic", {}).get("BOOL", False):
            return self._recompute_baseline(dataset_urn, item["Item"]["run_history"]["L"])
        
        return None
    
    def _recompute_baseline(self, dataset_urn: str, run_history: list) -> BaselineUpdate:
        """Recompute baseline from real run data."""
        row_counts = [int(r["M"]["row_count"]["N"]) for r in run_history[-self.REQUIRED_RUNS:]]
        
        avg = statistics.mean(row_counts)
        stddev = statistics.stdev(row_counts)
        
        new_baseline = {
            "avg_row_count": int(avg),
            "stddev_row_count": int(stddev),
            "min_row_count": min(row_counts),
            "max_row_count": max(row_counts),
            "anomaly_lower_bound": int(max(0, avg - self.NARROW_MULTIPLIER * stddev)),
            "anomaly_upper_bound": int(avg + self.NARROW_MULTIPLIER * stddev),
        }
        
        # Update baseline with computed values
        self.dynamodb.update_item(
            TableName="Baselines",
            Key={"dataset_urn": {"S": dataset_urn}, "metric_key": {"S": "volume"}},
            UpdateExpression="""
                SET baseline_value = :new_baseline,
                    confidence = :high,
                    is_synthetic = :false,
                    source_engine = :computed,
                    updated_at = :now
            """,
            ExpressionAttributeValues={
                ":new_baseline": {"M": self._serialize_volume(new_baseline)},
                ":high": {"S": "HIGH"},
                ":false": {"BOOL": False},
                ":computed": {"S": "auto-refined"},
                ":now": {"S": datetime.now(timezone.utc).isoformat()},
            },
        )
        
        return BaselineUpdate(
            dataset_urn=dataset_urn,
            metric_key="volume",
            old_confidence="LOW",
            new_confidence="HIGH",
            transition="SYNTHETIC → COMPUTED",
        )
```

### 5.4 Error Handling

| Failure Scenario | Behavior | Recovery |
|:---|:---|:---|
| DynamoDB write throttled | Retry with exponential backoff | Auto-recovers; alert if > 5 min |
| Baseline not found for dataset | Return synthetic defaults for tier | Log `baseline.missing` metric |
| Corrupt run_history list | Skip refinement; log warning | Manual investigation required |
| Auto-refine computes invalid stats (stddev = 0) | Keep synthetic baseline; flag for review | Manual profiling re-run |

### 5.5 Observability

| Metric | Type | Alert Threshold |
|:---|:---|:---|
| `baseline.reads` | Counter (by is_synthetic) | — |
| `baseline.writes` | Counter (by source_engine) | — |
| `baseline.auto_refine.triggered` | Counter | — |
| `baseline.auto_refine.completed` | Counter | — |
| `baseline.synthetic_active` | Gauge | > 30% of fleet after 60 days |

---

## 6. C-05: Policy Generator

### 6.1 Responsibility

The Policy Generator auto-generates `policy_bundle.yaml` files from `baseline.json` and organizational templates. It produces tier-appropriate policies: Contract-Lite for Tier-3, auto-generated full contracts for Tier-2, and draft templates for Tier-1 human authoring. Generated policies are submitted to the Gateway Control Plane for signing.

### 6.2 Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                      Policy Generator                         │
│                                                               │
│  ┌─────────────┐   ┌──────────────┐   ┌───────────────────┐  │
│  │ baseline.json│──▶│ Rule Engine  │──▶│ policy_bundle.yaml│  │
│  └─────────────┘   │ (Heuristics  │   │ (unsigned)        │  │
│  ┌─────────────┐   │  + Templates │   └────────┬──────────┘  │
│  │ Org Policy  │──▶│  + AI Assist)│            │              │
│  │ Templates   │   └──────────────┘            │              │
│  └─────────────┘                               ▼              │
│                                    ┌───────────────────────┐  │
│                                    │ Gateway Control Plane  │  │
│                                    │ (Signs policy bundle)  │  │
│                                    └───────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

### 6.3 Policy Generation Logic

```python
class PolicyGenerator:
    """Generates policy_bundle.yaml from baseline.json and org templates."""
    
    def generate(self, baseline: BaselineJson, dataset_yaml: dict, 
                 tier: str) -> PolicyBundle:
        """Generate policy bundle appropriate for the dataset tier."""
        
        enrichment_level = self._determine_enrichment_level(tier)
        
        policy = PolicyBundle(
            version="2.0",
            dataset_urn=baseline.dataset_urn,
            bootstrap_id=baseline.bootstrap_id,
            generated_by="autopilot",
            enrichment_level=enrichment_level,
        )
        
        # Security section (always required)
        policy.security = self._build_security_section(tier)
        
        # Schema section (all tiers)
        policy.schema = self._build_schema_section(baseline)
        
        # Contract-Lite (all tiers get at minimum)
        policy.contract_lite = self._build_contract_lite(baseline)
        
        if enrichment_level in ("volume_baseline", "full_contract", "advanced"):
            policy.volume = self._build_volume_section(baseline, dataset_yaml)
        
        if enrichment_level in ("full_contract", "advanced"):
            policy.contract = self._build_full_contract(baseline, dataset_yaml)
            policy.pii = self._build_pii_section(baseline)
        
        # Freshness (from dataset.yaml SLO, all tiers)
        policy.freshness = self._build_freshness_section(dataset_yaml)
        
        # Performance budget
        policy.performance = self._build_performance_budget(tier)
        
        # Bootstrap metadata
        policy.bootstrap = self._build_bootstrap_metadata(baseline, enrichment_level)
        
        return policy
    
    def _determine_enrichment_level(self, tier: str) -> str:
        """Determine initial policy enrichment based on tier."""
        TIER_ENRICHMENT = {
            "TIER_1": "full_contract",     # Human will author; generate as starting point
            "TIER_2": "volume_baseline",   # Auto-generated, human-approved
            "TIER_3": "contract_lite",     # Auto-generated, auto-approved
        }
        return TIER_ENRICHMENT[tier]
    
    def _build_schema_section(self, baseline: BaselineJson) -> dict:
        return {
            "mode": "strict",
            "registry": "auto",
            "baseline_fingerprint": baseline.schema.canonical_fingerprint,
            "constraints": [
                {
                    "field": col.name,
                    "type": col.type,
                    "nullable": col.nullable,
                }
                for col in baseline.schema.columns
            ],
        }
    
    def _build_contract_lite(self, baseline: BaselineJson) -> dict:
        """Contract-Lite: schema fingerprint + required fields."""
        # Required fields = columns with null_rate < 0.001 (0.1%)
        required_fields = [
            nr.column for nr in baseline.null_rates if nr.null_rate < 0.001
        ]
        
        return {
            "required_fields": required_fields,
            "invariants": [],  # No invariants in Contract-Lite
        }
    
    def _build_full_contract(self, baseline: BaselineJson, dataset_yaml: dict) -> dict:
        """Full contract: required fields + invariants derived from profiling."""
        required_fields = [
            nr.column for nr in baseline.null_rates if nr.null_rate < 0.001
        ]
        
        invariants = []
        for col in baseline.schema.columns:
            # Numeric columns get range invariants
            if col.type in ("INT", "LONG", "DOUBLE", "FLOAT", "DECIMAL"):
                invariants.append(f"{col.name} IS NOT NULL" if not col.nullable else None)
            # Non-nullable string columns get NOT NULL invariants
            if col.type == "STRING" and not col.nullable:
                invariants.append(f"{col.name} IS NOT NULL")
        
        invariants = [i for i in invariants if i is not None]
        
        return {
            "required_fields": required_fields,
            "invariants": invariants,
        }
    
    def _build_pii_section(self, baseline: BaselineJson) -> dict:
        """PII detection and remediation from profiling scan."""
        ORG_DEFAULT_ACTIONS = {
            "EMAIL": "tokenize",
            "PHONE": "mask",
            "SSN": "redact",
            "CREDIT_CARD": "redact",
            "IP_ADDRESS": "mask",
            "ADDRESS": "mask",
        }
        
        detection_rules = []
        for col_name, pii_info in baseline.pii_scan.pii_patterns_detected.items():
            pattern = pii_info["pattern"]
            detection_rules.append({
                "pattern": pattern,
                "action": ORG_DEFAULT_ACTIONS.get(pattern, "mask"),
            })
        
        return {
            "detection": detection_rules,
            "scan_columns": baseline.pii_scan.columns_with_pii,
        }
    
    def _build_freshness_section(self, dataset_yaml: dict) -> dict:
        slo = dataset_yaml.get("slo", {}).get("freshness", {})
        return {
            "expected_update_by": slo.get("expected_update_by", "06:00 ET daily"),
            "grace_period": slo.get("grace_period", "30m"),
            "partition_key": dataset_yaml.get("storage", {}).get("partition_key", "dt"),
        }
    
    def _build_volume_section(self, baseline: BaselineJson, dataset_yaml: dict) -> dict:
        slo = dataset_yaml.get("slo", {}).get("volume", {})
        return {
            "min_rows_per_partition": slo.get(
                "min_rows_per_partition", baseline.volume.anomaly_lower_bound
            ),
            "anomaly_threshold_pct": slo.get("anomaly_threshold_pct", 40),
            "baseline_avg": baseline.volume.avg_row_count,
            "baseline_stddev": baseline.volume.stddev_row_count,
        }
    
    def _build_performance_budget(self, tier: str) -> dict:
        TIER_BUDGETS = {
            "TIER_1": {"gate_timeout_ms": 10_000, "total_budget_pct": 5, "pii_timeout_ms": 10_000},
            "TIER_2": {"gate_timeout_ms": 15_000, "total_budget_pct": 7, "pii_timeout_ms": 15_000},
            "TIER_3": {"gate_timeout_ms": 20_000, "total_budget_pct": 10, "pii_timeout_ms": 20_000},
        }
        budget = TIER_BUDGETS[tier]
        return {
            "gate_timeout_ms": budget["gate_timeout_ms"],
            "total_validation_budget_pct": budget["total_budget_pct"],
            "pii_scan_timeout_ms": budget["pii_timeout_ms"],
            "sampling_rate": 1.0,
        }
    
    def _build_security_section(self, tier: str) -> dict:
        return {
            "signature": "UNSIGNED_PENDING_GATEWAY",
            "minimum_enforcement": {
                "pii_detection": "required",
                "schema_validation": "required",
            },
            "validation_enabled": True,
        }
    
    def _build_bootstrap_metadata(self, baseline: BaselineJson, 
                                   enrichment_level: str) -> dict:
        PROGRESSIVE_SCHEDULES = {
            "contract_lite": {
                "week_1": ["G1_RESOLUTION", "G2_IDENTITY", "G3_SCHEMA"],
                "week_2": ["G6_VOLUME"],
                "week_3": ["G5_FRESHNESS"],
                "week_4": [],
            },
            "volume_baseline": {
                "week_1": ["G1_RESOLUTION", "G2_IDENTITY", "G3_SCHEMA", "G6_VOLUME"],
                "week_2": ["G5_FRESHNESS"],
                "week_3": ["G4_CONTRACT"],
                "week_4": ["G5_PII", "DQ_CHECKS"],
            },
            "full_contract": {
                "week_1": ["G1_RESOLUTION", "G2_IDENTITY", "G3_SCHEMA", "G6_VOLUME",
                           "G4_CONTRACT", "G5_FRESHNESS", "G5_PII", "DQ_CHECKS"],
            },
        }
        
        auto_refine_date = None
        if baseline.profiling_metadata.is_synthetic:
            auto_refine_date = (
                datetime.now(timezone.utc) + timedelta(days=baseline.profiling_metadata.auto_refine_after_runs or 7)
            ).isoformat()
        
        return {
            "baseline_source": baseline.bootstrap_id,
            "baseline_confidence": baseline.profiling_metadata.confidence,
            "auto_refine_until": auto_refine_date,
            "progressive_schedule": PROGRESSIVE_SCHEDULES.get(enrichment_level, {}),
        }
```

### 6.4 Gateway Control Plane Integration

After generation, the policy bundle is submitted to the Gateway Control Plane for cryptographic signing:

```python
class GatewayPolicySigner:
    """Submits policy bundles to Gateway Control Plane for signing."""
    
    GATEWAY_URL = "https://gateway.signal-factory.internal/v1/policies/sign"
    
    def sign_policy(self, policy_yaml: str, dataset_urn: str, 
                    bootstrap_id: str) -> SignedPolicy:
        response = requests.post(
            self.GATEWAY_URL,
            json={
                "dataset_urn": dataset_urn,
                "bootstrap_id": bootstrap_id,
                "policy_content": policy_yaml,
                "signing_authority": "bootstrap-policy-generator",
            },
            headers={"Authorization": f"Bearer {self._get_service_token()}"},
            timeout=10,
        )
        response.raise_for_status()
        
        result = response.json()
        return SignedPolicy(
            signed_yaml=result["signed_content"],
            signature=result["signature"],
            signed_at=result["signed_at"],
            signer_identity=result["signer_identity"],
        )
```

### 6.5 Error Handling

| Failure Scenario | Behavior | Recovery |
|:---|:---|:---|
| Baseline missing required fields | Generate Contract-Lite only; log warning | Profiling data may be incomplete |
| Gateway signing service unavailable | Retry 3× with backoff; mark as `UNSIGNED` | Manual re-sign via CLI |
| Template not found for tier | Use default template; emit `policy.template_missing` | Org admin creates template |
| AI-assisted invariant generation fails | Fall back to heuristic-only invariants | No AI enrichment; human reviews |

### 6.6 Observability

| Metric | Type | Alert Threshold |
|:---|:---|:---|
| `policy.generated` | Counter (by tier, enrichment_level) | — |
| `policy.signed` | Counter | — |
| `policy.signing_failed` | Counter | > 0 |
| `policy.generation_duration_ms` | Histogram | p99 > 30000ms |
| `policy.invariants_generated` | Histogram | — |
| `policy.pii_rules_generated` | Counter | — |

---

## 7. C-06: Certified View Initializer

### 7.1 Responsibility

The Certified View Initializer creates the **initial certified view pointer** for a dataset at the end of the bootstrap lifecycle. This pointer marks the dataset as "signal-ready" and establishes the consumption surface that downstream consumers will use. It also seeds the Neptune graph with the dataset node and ownership edges.

### 7.2 Initialization Logic

```python
class CertifiedViewInitializer:
    """Creates initial certified view pointer during bootstrap."""
    
    def initialize(self, request: CertInitRequest) -> CertInitResult:
        """Create certified view for a bootstrapped dataset."""
        
        # Step 1: Verify gold table exists and has data
        has_data = self._verify_gold_table(request)
        if not has_data:
            raise GoldTableNotFound(
                f"Gold table at {request.gold_path} has no data. "
                "Certification will be deferred until first successful write."
            )
        
        # Step 2: Determine initial certified version
        if request.storage_format == "delta":
            version = self._get_delta_latest_version(request.gold_path)
            certified_pointer = {
                "type": "delta_version",
                "version": version,
                "table_path": request.gold_path,
            }
        elif request.storage_format == "parquet":
            latest_partition = self._get_latest_parquet_partition(
                request.gold_path, request.partition_key
            )
            certified_pointer = {
                "type": "parquet_partition",
                "partition_value": latest_partition,
                "partition_path": f"{request.gold_path}/{request.partition_key}={latest_partition}/",
            }
        
        # Step 3: Write certification state to DynamoDB
        cert_record = {
            "dataset_urn": request.dataset_urn,
            "certified_view_name": f"gold_certified.{request.dataset_name}",
            "current_certified_version": "v0",
            "certified_pointer": certified_pointer,
            "last_certified_at": datetime.now(timezone.utc).isoformat(),
            "certification_status": "CERTIFIED",
            "staleness_sla_hours": self._staleness_by_tier(request.tier),
            "bootstrap_id": request.bootstrap_id,
            "enforcement_model": request.enforcement_model,
            "policy_bundle_version": "1.0",
            "policy_bundle_location": f"s3://sf-config/datasets/{request.dataset_name}/policy_bundle.yaml",
        }
        
        self.dynamodb.put_item(
            TableName="CertifiedViewState",
            Item=self._serialize_item(cert_record),
        )
        
        # Step 4: Seed Neptune graph
        self._seed_neptune_graph(request, cert_record)
        
        return CertInitResult(
            dataset_urn=request.dataset_urn,
            certified_version="v0",
            certified_pointer=certified_pointer,
            graph_node_created=True,
        )
    
    def _verify_gold_table(self, request: CertInitRequest) -> bool:
        """Verify gold table exists and contains data."""
        if request.storage_format == "delta":
            # Check for _delta_log directory
            try:
                response = self.s3.list_objects_v2(
                    Bucket=self._bucket(request.gold_path),
                    Prefix=f"{self._key(request.gold_path)}/_delta_log/",
                    MaxKeys=1,
                )
                return response.get("KeyCount", 0) > 0
            except Exception:
                return False
        
        elif request.storage_format == "parquet":
            # Check for any .parquet files
            try:
                response = self.s3.list_objects_v2(
                    Bucket=self._bucket(request.gold_path),
                    Prefix=self._key(request.gold_path),
                    MaxKeys=1,
                )
                files = response.get("Contents", [])
                return any(f["Key"].endswith(".parquet") for f in files)
            except Exception:
                return False
    
    def _get_delta_latest_version(self, table_path: str) -> int:
        """Get the latest commit version from Delta transaction log."""
        log_prefix = f"{self._key(table_path)}/_delta_log/"
        response = self.s3.list_objects_v2(
            Bucket=self._bucket(table_path),
            Prefix=log_prefix,
        )
        versions = [
            int(obj["Key"].split("/")[-1].replace(".json", ""))
            for obj in response.get("Contents", [])
            if obj["Key"].endswith(".json") and not obj["Key"].endswith(".crc")
        ]
        return max(versions) if versions else 0
    
    def _get_latest_parquet_partition(self, gold_path: str, partition_key: str) -> str:
        """Get the most recent partition value from Hive-style layout."""
        prefix = self._key(gold_path)
        response = self.s3.list_objects_v2(
            Bucket=self._bucket(gold_path),
            Prefix=prefix,
            Delimiter="/",
        )
        
        partition_values = []
        for cp in response.get("CommonPrefixes", []):
            dir_name = cp["Prefix"].rstrip("/").split("/")[-1]
            if "=" in dir_name:
                key, value = dir_name.split("=", 1)
                if key == partition_key:
                    partition_values.append(value)
        
        return sorted(partition_values)[-1] if partition_values else "unknown"
    
    def _seed_neptune_graph(self, request: CertInitRequest, cert_record: dict):
        """Create dataset node and edges in Neptune."""
        gremlin_queries = [
            # Create Dataset node
            f"""
            g.addV('BatchDataset')
                .property('dataset_urn', '{request.dataset_urn}')
                .property('tier', '{request.tier}')
                .property('storage_format', '{request.storage_format}')
                .property('enforcement_model', '{request.enforcement_model}')
                .property('runtime', '{request.runtime}')
                .property('certification_status', 'CERTIFIED')
                .property('bootstrap_id', '{request.bootstrap_id}')
                .property('bootstrapped_at', '{cert_record["last_certified_at"]}')
            """,
            # Create OWNS edge (team → dataset)
            f"""
            g.V().has('Team', 'name', '{request.owner_team}')
                .as('team')
                .V().has('BatchDataset', 'dataset_urn', '{request.dataset_urn}')
                .as('dataset')
                .select('team').addE('OWNS').to(select('dataset'))
                .property('since', '{cert_record["last_certified_at"]}')
            """,
        ]
        
        for query in gremlin_queries:
            self.neptune.submit(query)
    
    @staticmethod
    def _staleness_by_tier(tier: str) -> int:
        STALENESS_MAP = {"TIER_1": 6, "TIER_2": 24, "TIER_3": 48}
        return STALENESS_MAP.get(tier, 24)
```

### 7.3 Deferred Certification

When the gold table doesn't exist yet (brand new dataset), certification is deferred:

```python
class DeferredCertificationManager:
    """Manages datasets awaiting first successful write for certification."""
    
    def defer(self, request: CertInitRequest) -> DeferResult:
        """Set up trigger for first write to complete certification."""
        
        # Write deferred state
        self.dynamodb.put_item(
            TableName="CertifiedViewState",
            Item=self._serialize_item({
                "dataset_urn": request.dataset_urn,
                "certification_status": "DEFERRED",
                "deferred_at": datetime.now(timezone.utc).isoformat(),
                "deferred_reason": "GOLD_TABLE_NOT_FOUND",
                "bootstrap_id": request.bootstrap_id,
                "trigger_path": request.gold_path,
            }),
        )
        
        # Register EventBridge rule to detect first write
        if request.storage_format == "delta":
            # Watch for first Delta commit log entry
            self._create_delta_watch_rule(request)
        elif request.storage_format == "parquet":
            # Watch for first Parquet file creation
            self._create_s3_watch_rule(request)
        
        return DeferResult(
            dataset_urn=request.dataset_urn,
            status="DEFERRED",
            watch_rule_created=True,
        )
```

### 7.4 DynamoDB Table — CertifiedViewState

| Attribute | Type | Key | Description |
|:---|:---|:---|:---|
| `dataset_urn` | String | PK | Canonical dataset identifier |
| `certified_view_name` | String | — | Logical name (e.g., `gold_certified.orders`) |
| `current_certified_version` | String | — | `v0`, `v1`, etc. |
| `certified_pointer` | Map | — | Format-specific pointer (Delta version or Parquet partition) |
| `last_certified_at` | String (ISO) | — | Last certification timestamp |
| `certification_status` | String | — | `CERTIFIED` / `DEFERRED` / `STALE` |
| `staleness_sla_hours` | Number | — | Max hours before staleness alert |
| `bootstrap_id` | String | — | Source bootstrap ID |
| `enforcement_model` | String | — | `inline_sdk` / `post_write` |
| `policy_bundle_version` | String | — | Currently active policy version |
| `policy_bundle_location` | String | — | S3 URI of signed policy bundle |
| `updated_at` | String (ISO) | — | Last update timestamp |

### 7.5 Error Handling

| Failure Scenario | Behavior | Recovery |
|:---|:---|:---|
| Gold table path exists but empty | Treat as no data; defer certification | EventBridge trigger on first write |
| Neptune connection failure | Retry 3×; cert succeeds without graph node | Background reconciler seeds Neptune later |
| DynamoDB write failure | Retry 3×; fail bootstrap step | Orchestrator retries full step |
| S3 listing timeout | Retry with reduced MaxKeys | Exponential backoff |

### 7.6 Observability

| Metric | Type | Alert Threshold |
|:---|:---|:---|
| `certification.initialized` | Counter (by format) | — |
| `certification.deferred` | Counter | > 20% of bootstraps |
| `certification.neptune_seed_failed` | Counter | > 0 |
| `certification.init_duration_ms` | Histogram | p99 > 60000ms |

---

## 8. C-07: Autopilot Repo Scanner

### 8.1 Responsibility

The Autopilot Repo Scanner discovers batch datasets by analyzing repository source code. It detects runtimes (Spark, Python, Dask, dbt), extracts write targets, classifies tiers, and generates `dataset.yaml` proposals for the bootstrap pipeline.

### 8.2 Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    Autopilot Repo Scanner                      │
│                                                               │
│  Triggers:                                                    │
│  ┌──────────────┐  ┌───────────────┐  ┌──────────────┐       │
│  │ GitHub App   │  │ Weekly Cron   │  │ CLI / API    │       │
│  │ (Webhook)    │  │ (Full Scan)   │  │ (Manual)     │       │
│  └──────┬───────┘  └───────┬───────┘  └──────┬───────┘       │
│         │                  │                  │               │
│         ▼                  ▼                  ▼               │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │                  Scanner Orchestrator                     │ │
│  │  1. Clone repo (shallow, depth=1)                        │ │
│  │  2. Detect runtime(s)                                    │ │
│  │  3. Extract write targets via AST analysis               │ │
│  │  4. Classify tier                                        │ │
│  │  5. Generate dataset.yaml                                │ │
│  └──────────────────────────────────────────────────────────┘ │
│                              │                                │
│                              ▼                                │
│                    ┌────────────────────┐                     │
│                    │ PR Generator (C-08) │                     │
│                    └────────────────────┘                     │
└──────────────────────────────────────────────────────────────┘
```

### 8.3 Runtime Detection

```python
class RuntimeDetector:
    """Detects batch processing runtimes from repository code."""
    
    RUNTIME_SIGNATURES = {
        "spark": {
            "imports": ["pyspark", "from pyspark", "org.apache.spark"],
            "files": ["spark-defaults.conf"],
            "patterns": [r"SparkSession\.builder", r"spark\.read", r"DataFrame\.write"],
        },
        "python": {
            "imports": ["pandas", "from pandas"],
            "files": [],
            "patterns": [r"\.to_parquet\(", r"\.to_csv\(", r"pd\.read_"],
        },
        "dask": {
            "imports": ["dask", "from dask", "dask.dataframe"],
            "files": [],
            "patterns": [r"dd\.read_parquet", r"\.to_parquet\("],
        },
        "dbt": {
            "imports": [],
            "files": ["dbt_project.yml", "dbt_project.yaml"],
            "patterns": [],
        },
    }
    
    def detect(self, repo_path: str) -> list[RuntimeDetection]:
        """Scan repository and detect runtimes used."""
        detections = []
        
        for runtime, signatures in self.RUNTIME_SIGNATURES.items():
            confidence = 0.0
            evidence = []
            
            # Check marker files
            for marker_file in signatures["files"]:
                if self._file_exists(repo_path, marker_file):
                    confidence += 0.4
                    evidence.append(f"Found {marker_file}")
            
            # Check Python imports
            python_files = self._find_python_files(repo_path)
            for py_file in python_files:
                content = self._read_file(py_file)
                for import_pattern in signatures["imports"]:
                    if import_pattern in content:
                        confidence += 0.3
                        evidence.append(f"Import '{import_pattern}' in {py_file}")
                        break
                
                # Check code patterns
                for pattern in signatures["patterns"]:
                    if re.search(pattern, content):
                        confidence += 0.3
                        evidence.append(f"Pattern '{pattern}' in {py_file}")
                        break
            
            if confidence >= 0.3:
                detections.append(RuntimeDetection(
                    runtime=runtime,
                    confidence=min(confidence, 1.0),
                    evidence=evidence,
                ))
        
        return sorted(detections, key=lambda d: d.confidence, reverse=True)
```

### 8.4 Write Target Extraction (AST Analysis)

```python
class WriteTargetExtractor:
    """Extracts data write targets from Python AST for Delta and Parquet."""
    
    def extract(self, repo_path: str, runtime: str) -> list[WriteTarget]:
        """Extract write targets from source code using AST analysis."""
        targets = []
        
        python_files = self._find_python_files(repo_path)
        for py_file in python_files:
            try:
                tree = ast.parse(self._read_file(py_file))
                visitor = WriteCallVisitor(runtime)
                visitor.visit(tree)
                targets.extend(visitor.targets)
            except SyntaxError:
                continue  # Skip files that can't be parsed
        
        # Deduplicate by path
        seen_paths = set()
        unique_targets = []
        for target in targets:
            if target.path not in seen_paths:
                seen_paths.add(target.path)
                unique_targets.append(target)
        
        return unique_targets


class WriteCallVisitor(ast.NodeVisitor):
    """AST visitor that extracts write targets for Delta and Parquet."""
    
    # Method names that indicate write operations
    SPARK_WRITE_METHODS = ["save", "saveAsTable", "parquet", "format"]
    PANDAS_WRITE_METHODS = ["to_parquet", "to_csv"]
    DASK_WRITE_METHODS = ["to_parquet", "to_csv"]
    
    def __init__(self, runtime: str):
        self.runtime = runtime
        self.targets = []
    
    def visit_Call(self, node: ast.Call):
        """Detect write calls and extract target paths."""
        if isinstance(node.func, ast.Attribute):
            method_name = node.func.attr
            
            if self.runtime == "spark" and method_name in self.SPARK_WRITE_METHODS:
                self._extract_spark_target(node)
            elif self.runtime == "python" and method_name in self.PANDAS_WRITE_METHODS:
                self._extract_pandas_target(node)
            elif self.runtime == "dask" and method_name in self.DASK_WRITE_METHODS:
                self._extract_dask_target(node)
        
        self.generic_visit(node)
    
    def _extract_spark_target(self, node: ast.Call):
        """Extract path from Spark DataFrame write calls."""
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                path = arg.value
                if path.startswith("s3://"):
                    fmt = self._detect_format_from_chain(node)
                    self.targets.append(WriteTarget(
                        path=path,
                        storage_format=fmt,
                        source_line=node.lineno,
                    ))
    
    def _extract_pandas_target(self, node: ast.Call):
        """Extract path from Pandas to_parquet/to_csv calls."""
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                path = arg.value
                if path.startswith("s3://"):
                    fmt = "parquet" if "parquet" in node.func.attr else "csv"
                    if fmt in ("parquet",):  # Phase 1: Delta + Parquet only
                        self.targets.append(WriteTarget(
                            path=path,
                            storage_format=fmt,
                            source_line=node.lineno,
                        ))
    
    def _detect_format_from_chain(self, node: ast.Call) -> str:
        """Detect storage format from Spark write chain (e.g., .format("delta"))."""
        # Walk up the method chain to find .format() calls
        current = node
        while isinstance(current, ast.Call) and isinstance(current.func, ast.Attribute):
            if current.func.attr == "format" and current.args:
                fmt_arg = current.args[0]
                if isinstance(fmt_arg, ast.Constant):
                    return fmt_arg.value  # "delta" or "parquet"
            # Move to the object the method was called on
            current = current.func.value if isinstance(current.func, ast.Attribute) else None
            if isinstance(current, ast.Call):
                continue
            break
        return "parquet"  # Default assumption
```

### 8.5 Tier Classification

```python
class TierClassifier:
    """Classifies datasets into tiers based on criticality signals."""
    
    def classify(self, dataset_urn: str, repo_metadata: RepoMetadata,
                 neptune_client=None) -> TierClassification:
        
        # Signal 1: Explicit critical-datasets list
        if self._in_critical_datasets_list(dataset_urn, repo_metadata):
            return TierClassification(tier="TIER_1", reason="In critical-datasets.yaml", confidence=1.0)
        
        # Signal 2: Consumer count (from Neptune, if available)
        consumer_count = 0
        if neptune_client:
            try:
                consumer_count = neptune_client.submit(
                    f"g.V().has('dataset_urn', '{dataset_urn}').in('CONSUMES').count()"
                ).one()
            except Exception:
                pass  # Neptune may not have this dataset yet
        
        if consumer_count > 3:
            return TierClassification(
                tier="TIER_2",
                reason=f"Referenced by {consumer_count} consumers (> 3 threshold)",
                confidence=0.8,
            )
        
        # Signal 3: Repository signals (CODEOWNERS, test coverage, CI pipeline)
        if repo_metadata.has_codeowners and repo_metadata.has_ci:
            return TierClassification(
                tier="TIER_2",
                reason="Has CODEOWNERS + CI pipeline (indicates team ownership)",
                confidence=0.6,
            )
        
        # Default: TIER_3
        return TierClassification(
            tier="TIER_3",
            reason="No critical signals detected; default tier",
            confidence=0.5,
        )
```

### 8.6 Dataset YAML Generator

```python
class DatasetYamlGenerator:
    """Generates dataset.yaml from scanner findings."""
    
    def generate(self, write_target: WriteTarget, runtime: RuntimeDetection,
                 tier: TierClassification, repo_metadata: RepoMetadata) -> dict:
        
        dataset_name = self._derive_name(write_target.path)
        zone = self._derive_zone(write_target.path)
        
        # Determine enforcement model
        enforcement = self._select_enforcement(runtime.runtime, tier.tier)
        
        return {
            "urn": f"ds://{zone}/{dataset_name}",
            "owner_team": repo_metadata.codeowners_team or "unknown",
            "tier": tier.tier,
            "runtime": runtime.runtime,
            "storage": {
                "format": write_target.storage_format,
                "gold": write_target.path,
                "staging": self._derive_staging_path(write_target.path),
                "quarantine": self._derive_quarantine_path(write_target.path),
                "partition_key": self._detect_partition_key(write_target.path),
            },
            "orchestration": {
                "platform": self._detect_orchestrator(repo_metadata),
                "dag_id": repo_metadata.dag_id,
                "schedule": repo_metadata.schedule or "0 2 * * *",  # Default: 2 AM daily
            },
            "slo": {
                "freshness": {
                    "expected_update_by": "06:00 ET daily",
                    "grace_period": "30m",
                    "max_staleness_hours": self._staleness_by_tier(tier.tier),
                },
                "volume": {
                    "min_rows_per_partition": 100,  # Conservative default
                    "anomaly_threshold_pct": 40,
                },
            },
            "enforcement_model": enforcement,
            "metadata": {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "created_by": "autopilot",
                "scanner_confidence": min(runtime.confidence, tier.confidence),
            },
        }
    
    @staticmethod
    def _select_enforcement(runtime: str, tier: str) -> str:
        if runtime == "dbt":
            return "post_write"
        if tier == "TIER_1" and runtime in ("spark", "python", "dask"):
            return "inline_sdk"
        return "post_write"
```

### 8.7 Error Handling

| Failure Scenario | Behavior | Recovery |
|:---|:---|:---|
| Repository clone fails | Skip repo; emit `scanner.clone_failed` | Retry on next scheduled scan |
| AST parsing error | Skip file; continue scanning | Log file path for manual review |
| No write targets found | Skip repo; no dataset.yaml generated | Normal — not all repos have batch data |
| Neptune unavailable for tier classification | Default to TIER_3 | Tier upgraded after Neptune is available |
| GitHub API rate limited | Exponential backoff; respect `Retry-After` header | Auto-recovers |

### 8.8 Observability

| Metric | Type | Alert Threshold |
|:---|:---|:---|
| `scanner.repos_scanned` | Counter | — |
| `scanner.datasets_discovered` | Counter (by runtime, format) | — |
| `scanner.runtimes_detected` | Counter (by runtime) | — |
| `scanner.clone_failures` | Counter | > 10% of repos |
| `scanner.scan_duration_ms` | Histogram | p99 > 300000ms (5 min) |
| `scanner.ast_parse_errors` | Counter | > 20% of Python files |

### 8.9 Deployment

| Property | Value |
|:---|:---|
| Runtime | ECS Fargate (Python 3.12) |
| Memory | 4 GB (repository cloning + AST parsing) |
| Triggers | GitHub App Webhook, EventBridge Schedule (weekly), API Gateway (manual) |
| GitHub Integration | GitHub App with `contents: read` permission |
| Concurrency | Max 5 concurrent repo scans |

---

## 9. C-08: PR Generator

### 9.1 Responsibility

The PR Generator creates GitHub Pull Requests containing `dataset.yaml`, `policy_bundle.yaml`, SDK integration code, staging profiling reports, and risk assessments. It manages the PR lifecycle from creation through merge acceleration for Tier-3 auto-approve flows.

### 9.2 PR Contents

Each generated PR includes:

```python
@dataclass
class BootstrapPR:
    """Pull Request contents for Autopilot-generated bootstrap."""
    
    repo: str                           # "org/data-pipelines"
    branch_name: str                    # "autopilot/bootstrap/orders_enriched"
    title: str                          # "[Autopilot] Bootstrap observability for orders_enriched"
    
    files: list  # Files to add/modify:
    # 1. observability/datasets/{name}/dataset.yaml
    # 2. observability/datasets/{name}/policy_bundle.yaml
    # 3. SDK integration patch (runtime-specific)
    # 4. observability/reports/{name}/staging_profiling_report.md
    # 5. observability/reports/{name}/risk_assessment.md
    # 6. observability/reports/{name}/rollback_instructions.md
    
    labels: list[str]                   # ["autopilot", "observability", "tier-3"]
    reviewers: list[str]                # Derived from CODEOWNERS
    auto_merge_after_hours: Optional[int]  # 48 for Tier-3; None for Tier-1/2
```

### 9.3 Risk Assessment Generator

```python
class RiskAssessmentGenerator:
    """Generates risk assessment for bootstrap PRs."""
    
    def assess(self, dataset_yaml: dict, policy_bundle: dict, 
               enforcement_model: str) -> RiskAssessment:
        risk_level = "LOW"
        risk_factors = []
        mitigations = []
        
        # Enforcement model risk
        if enforcement_model == "inline_sdk":
            risk_factors.append("Inline SDK adds validation overhead to production job")
            mitigations.append("Kill-switch enabled; performance budget enforced at 5%")
            risk_level = "MEDIUM"
        else:
            risk_factors.append("Post-write model: no production code changes")
            mitigations.append("Write path redirect via orchestrator config only")
        
        # Policy complexity risk
        enrichment = policy_bundle.get("enrichment_level", "contract_lite")
        if enrichment == "contract_lite":
            risk_factors.append("Contract-Lite only: schema fingerprint + required fields")
            mitigations.append("Minimal validation overhead; no inline DQ checks")
        elif enrichment == "full_contract":
            risk_factors.append("Full contract with invariants and PII scanning")
            risk_level = "HIGH" if enforcement_model == "inline_sdk" else "MEDIUM"
        
        # Tier-based risk
        tier = dataset_yaml.get("tier", "TIER_3")
        if tier == "TIER_1":
            risk_level = max(risk_level, "MEDIUM")  # Tier-1 always at least MEDIUM
        
        return RiskAssessment(
            risk_level=risk_level,
            risk_factors=risk_factors,
            mitigations=mitigations,
            rollback_command=f"git revert <commit-sha>",
            kill_switch_command=f"sf bootstrap kill-switch --urn {dataset_yaml['urn']}",
        )
```

### 9.4 Auto-Merge Workflow (Tier-3)

```python
class AutoMergeManager:
    """Manages auto-merge for Tier-3 bootstrap PRs after 48h cooling period."""
    
    COOLING_PERIOD_HOURS = 48
    
    def schedule_auto_merge(self, pr_number: int, repo: str, created_at: datetime):
        """Schedule auto-merge via EventBridge timer."""
        merge_at = created_at + timedelta(hours=self.COOLING_PERIOD_HOURS)
        
        self.eventbridge.put_rule(
            Name=f"auto-merge-pr-{pr_number}",
            ScheduleExpression=f"at({merge_at.strftime('%Y-%m-%dT%H:%M:%S')})",
            State="ENABLED",
        )
        
        self.eventbridge.put_targets(
            Rule=f"auto-merge-pr-{pr_number}",
            Targets=[{
                "Id": f"merge-{pr_number}",
                "Arn": "arn:aws:lambda:us-east-1:123456:function:autopilot-auto-merge",
                "Input": json.dumps({
                    "repo": repo,
                    "pr_number": pr_number,
                    "merge_method": "squash",
                }),
            }],
        )
    
    def execute_auto_merge(self, repo: str, pr_number: int):
        """Merge PR if no blocking reviews or CI failures."""
        pr = self.github.get_repo(repo).get_pull(pr_number)
        
        # Pre-merge checks
        if pr.get_reviews().totalCount > 0:
            # Human interacted — skip auto-merge
            return {"status": "SKIPPED", "reason": "Human review detected"}
        
        if not pr.mergeable:
            return {"status": "SKIPPED", "reason": "PR has conflicts"}
        
        # Check CI status
        commit = pr.get_commits().reversed[0]
        ci_status = commit.get_combined_status()
        if ci_status.state != "success":
            return {"status": "SKIPPED", "reason": f"CI status: {ci_status.state}"}
        
        # Merge
        pr.merge(merge_method="squash", commit_title=f"[Autopilot] {pr.title}")
        return {"status": "MERGED", "merged_at": datetime.now(timezone.utc).isoformat()}
```

### 9.5 Error Handling

| Failure Scenario | Behavior | Recovery |
|:---|:---|:---|
| GitHub API rate limited | Backoff with `Retry-After` header | Auto-recovers |
| Branch conflict | Log conflict; skip PR | Retry on next scan or manual resolution |
| CI check fails on PR | Do not auto-merge; notify team | Human reviews and fixes |
| PR rejected by human reviewer | Feed rejection reason back to Policy Generator for re-gen | Max 3 re-generations |

### 9.6 Observability

| Metric | Type | Alert Threshold |
|:---|:---|:---|
| `pr.created` | Counter (by tier, enforcement_model) | — |
| `pr.merged` | Counter (by tier, merge_method: auto/human) | — |
| `pr.rejected` | Counter (by tier) | Tier-3 rejection rate > 10% |
| `pr.time_to_merge_hours` | Histogram (by tier) | Tier-3 > 72h; Tier-2 > 240h |
| `pr.auto_merge_skipped` | Counter (by reason) | — |

---

## 10. C-09: Fleet Dashboard Exporter

### 10.1 Responsibility

The Fleet Dashboard Exporter aggregates bootstrap progress metrics and emits them to CloudWatch and the Signal Factory's internal dashboard (Grafana). It provides fleet-level visibility into bootstrap coverage, velocity, and bottlenecks.

### 10.2 Key Metrics

```python
class FleetMetricsExporter:
    """Exports fleet-level bootstrap metrics to CloudWatch."""
    
    EXPORT_INTERVAL_SECONDS = 300  # 5 minutes
    
    def export_metrics(self):
        """Compute and publish fleet metrics."""
        
        # Query DynamoDB for fleet-wide stats
        registry_items = self._scan_table("DatasetRegistry")
        bootstrap_items = self._scan_table("BootstrapState")
        
        metrics = {
            "fleet.total_datasets": len(registry_items),
            "fleet.bootstrapped": sum(1 for b in bootstrap_items if b["current_step"] == "SIGNAL_READY"),
            "fleet.in_progress": sum(1 for b in bootstrap_items if b["current_step"] not in ("SIGNAL_READY", "FAILED", "CANCELLED")),
            "fleet.failed": sum(1 for b in bootstrap_items if b["current_step"] == "FAILED"),
            "fleet.stuck_in_approval": sum(
                1 for b in bootstrap_items 
                if b["current_step"] == "POLICY_PENDING" 
                and self._hours_since(b["updated_at"]) > 168
            ),
            "fleet.coverage_pct": 0,
        }
        
        if metrics["fleet.total_datasets"] > 0:
            metrics["fleet.coverage_pct"] = round(
                metrics["fleet.bootstrapped"] / metrics["fleet.total_datasets"] * 100, 1
            )
        
        # Per-tier breakdown
        for tier in ("TIER_1", "TIER_2", "TIER_3"):
            tier_items = [b for b in bootstrap_items if b.get("tier") == tier]
            metrics[f"fleet.{tier.lower()}.total"] = len(tier_items)
            metrics[f"fleet.{tier.lower()}.signal_ready"] = sum(
                1 for b in tier_items if b["current_step"] == "SIGNAL_READY"
            )
        
        # Publish to CloudWatch
        for metric_name, value in metrics.items():
            self.cloudwatch.put_metric_data(
                Namespace="SignalFactory/Bootstrap",
                MetricData=[{
                    "MetricName": metric_name,
                    "Value": value,
                    "Unit": "Count" if "pct" not in metric_name else "Percent",
                    "Timestamp": datetime.now(timezone.utc),
                }],
            )
```

### 10.3 Dashboard Alerts

| Alert | Condition | Severity | Action |
|:---|:---|:---|:---|
| Bootstrap coverage below pace | `fleet.coverage_pct` < expected for week | WARN | Weekly report to leadership |
| Dataset stuck in approval > 10 days | `fleet.stuck_in_approval` > 0 | HIGH | Escalate to team lead |
| Profiling failure rate spike | `profiling.jobs.failed` / total > 5% | HIGH | Investigate profiling infra |
| Tier-3 PR rejection rate | `pr.rejected(tier=TIER_3)` / total > 10% | WARN | Review auto-generation quality |
| Fleet-wide bootstrap failure | > 5 bootstraps failed in 24h | CRITICAL | On-call alert |

### 10.4 Deployment

| Property | Value |
|:---|:---|
| Runtime | EventBridge Scheduler → Lambda (Python 3.12) |
| Schedule | Every 5 minutes |
| Dashboard | Grafana (CloudWatch data source) |
| Alerting | CloudWatch Alarms → SNS → PagerDuty + Slack |

---

## 11. Security

### 11.1 Authentication & Authorization

| Component | Auth Method | Authorization |
|:---|:---|:---|
| Bootstrap API | IAM + API Gateway authorizer | Role-based: `bootstrap:initiate`, `bootstrap:approve`, `bootstrap:cancel` |
| Repo Scanner | GitHub App (installation token) | Repository `contents:read` permission |
| PR Generator | GitHub App (installation token) | Repository `pull_requests:write` permission |
| Profiling Engine | IAM roles (EMR Serverless execution role) | Read-only S3 access to data lake buckets |
| Policy Signing | Service-to-service mTLS | Gateway Control Plane signing authority |
| Neptune | IAM database authentication | Read-write for bootstrap components |

### 11.2 Data Protection

| Concern | Mitigation |
|:---|:---|
| PII in profiled data | PII scan produces pattern names, not actual values; no raw data stored in baseline.json |
| Policy bundle tampering | Cryptographic signing via Gateway Control Plane (ADR-008) |
| Baseline manipulation | DynamoDB item-level encryption; write access restricted to profiling service role |
| Repository credentials | GitHub App tokens rotated hourly; stored in Secrets Manager |
| Cross-account data access | VPC endpoints for S3; no public internet access from profiling workers |

### 11.3 Audit Trail

All bootstrap actions are logged to an immutable audit table:

| Attribute | Type | Key | Description |
|:---|:---|:---|:---|
| `audit_id` | String | PK | ULID |
| `bootstrap_id` | String | GSI-PK | Bootstrap execution ID |
| `action` | String | — | `INITIATED`, `PROFILED`, `POLICY_GENERATED`, `APPROVED`, `SIGNED`, `CERTIFIED`, `CANCELLED`, `ROLLED_BACK` |
| `actor` | String | — | `autopilot` / `human:<username>` / `system:<component>` |
| `timestamp` | String (ISO) | SK | Action timestamp |
| `details` | Map | — | Action-specific details |
| `ttl` | Number | — | 730 days (2 years) |

---

## 12. Architectural Decision Records

### 12.1 ADR: DuckDB vs. Spark for Small Dataset Profiling

| Factor | DuckDB | Spark |
|:---|:---|:---|
| Startup latency | < 1 second (embedded) | 30–60 seconds (cluster provisioning) |
| Memory footprint | ≤ 1 GB (Lambda) | ≥ 4 GB (driver + executor) |
| Cost per profile | ~$0.003 (Lambda 2048MB × 2 min) | ~$0.50 (EMR Serverless 1 executor × 5 min) |
| Delta support | Via `delta` extension (DuckDB ≥ 0.10) | Native |
| Parquet support | Native | Native |
| Row limit (practical) | ~10M rows in 1 GB memory | Virtually unlimited |

**Decision:** Use DuckDB for datasets ≤ 1M rows × 7 partitions; Spark for larger datasets. This reduces profiling costs by ~99% for small datasets while maintaining full capability for large ones.

### 12.2 ADR: Step Functions vs. Airflow for Bootstrap Orchestration

| Factor | Step Functions | Airflow |
|:---|:---|:---|
| Human approval integration | Native `waitForTaskToken` | Custom sensor + external trigger |
| Per-execution state | Built-in execution history | Requires XCom or external state |
| Cost | $0.025 / 1K state transitions | Managed Airflow: ~$300/month |
| Max execution duration | 1 year | Depends on scheduler |
| Serverless | Yes | No (MWAA is managed but not serverless) |

**Decision:** Step Functions for bootstrap orchestration. The `waitForTaskToken` pattern for human approvals is a natural fit, and per-execution state eliminates the need for external orchestration state. The 7-day approval timeout for Tier-1 datasets is well within Step Functions' 1-year execution limit.

### 12.3 ADR: Synthetic Baselines with Wide Thresholds

**Context:** New datasets with < 3 days of history cannot produce reliable statistical baselines. Without baselines, Signal Engines cannot detect anomalies.

**Decision:** Generate synthetic baselines from organizational tier averages with 3σ thresholds (vs. 2σ for computed baselines). Auto-refine to computed baselines after 7 real runs.

**Rationale:** Wide thresholds (3σ) minimize false positives during the synthetic phase, avoiding alert fatigue that would damage adoption. The 7-run refinement window is based on empirical observation that 7 daily batches provide sufficient statistical stability for volume patterns.

**Trade-off:** Some real anomalies will be missed during the synthetic phase. This is acceptable because the primary goal of bootstrap is adoption velocity, not detection sensitivity. Sensitivity improves naturally as baselines mature.

---

## 13. Testing Strategy

### 13.1 Unit Tests

| Component | Test Focus | Coverage Target |
|:---|:---|:---|
| BootstrapInitRequest.validate() | URN format, tier values, format validation | 95% |
| ProfilingDispatcher.dispatch() | Engine selection logic, partition discovery | 95% |
| DuckDBProfiler | Volume stats, schema fingerprint, PII regex | 90% |
| SyntheticBaselineGenerator | Tier defaults, confidence tagging | 95% |
| PolicyGenerator | Tier-appropriate enrichment levels, progressive schedules | 90% |
| RuntimeDetector | Import detection, pattern matching | 90% |
| WriteTargetExtractor | AST extraction for Spark/Pandas/Dask write calls | 85% |
| TierClassifier | Critical-datasets list, consumer count, defaults | 95% |
| CertifiedViewInitializer | Delta version detection, Parquet partition detection | 90% |

### 13.2 Integration Tests

| Test | Components Under Test | Validation |
|:---|:---|:---|
| Tier-1 full bootstrap | Orchestrator → Registry → Profiling → Policy → Human Approval → Cert Init | End-to-end SIGNAL_READY with computed baseline |
| Tier-3 auto bootstrap | Scanner → Registry → Profiling → Auto-Policy → Auto-Approve → Cert Init | End-to-end SIGNAL_READY with no human interaction |
| Synthetic fallback | Orchestrator → Profiling (no history) → Synthetic Baseline | baseline.json with `is_synthetic: true`, `confidence: LOW` |
| Delta profiling | Profiling Engine → Delta table with 7 partitions | Correct volume stats, schema fingerprint |
| Parquet profiling | Profiling Engine → Parquet files with Hive partitions | Correct volume stats, null rates |
| Policy rejection → re-gen | Orchestrator → Policy Gen → Human Reject → Re-gen (with feedback) | Updated policy bundle after feedback |
| Deferred certification | Cert Init → Gold table missing → Deferred state + EventBridge rule | Certification completes on first write |
| Concurrent bootstrap guard | Two bootstrap requests for same URN | Second request returns 409 with existing bootstrap_id |

### 13.3 Load Tests

| Scenario | Target | Pass Criteria |
|:---|:---|:---|
| 50 concurrent bootstraps | Phase 1 pilot | All complete within tier SLA; no throttling |
| 200 bootstraps in 1 week | Phase 2 scale | < 5% failure rate; profiling queue never > 20 |
| 500 bootstraps fleet-wide | Phase 3 target | Total completion < 60 days; < 500 person-hours |
| DuckDB profile on 1M row Delta | Single profiler | < 120 seconds, < 1 GB memory |
| Spark profile on 100M row Delta with 10% sampling | Single profiler | < 15 minutes, EMR stable |

### 13.4 Chaos Tests

| Injection | Expected Behavior |
|:---|:---|
| Kill profiling Lambda mid-execution | Step Functions retry; profiling re-runs |
| DynamoDB throttle (BootstrapState) | State update retries with backoff; bootstrap not lost |
| EMR Serverless quota exhausted | Profiling queued; retries after 5 min; alert emitted |
| GitHub API outage | Scanner pauses; PR creation queued; resumes on recovery |
| Neptune down during cert init | Certification succeeds (DynamoDB record created); graph seeded by reconciler |

---

## 14. Open Items and ADR Dependencies

| ID | Item | Status | Owner | Dependency |
|:---|:---|:---|:---|:---|
| LLD-B01 | DuckDB Delta extension compatibility matrix for Delta 2.0–2.4 | 🟡 Pending | Platform Core | A5: Load test results |
| LLD-B02 | Confirm Step Functions quota (25K transitions) is sufficient for worst-case bootstrap | 🟡 Pending | Platform Core | A4: State transition modeling |
| LLD-B03 | GitHub App installation approval from DevSecOps | 🟡 Pending | Autopilot | A3: Security review |
| LLD-B04 | Define organizational tier average baselines from existing fleet profiling | 🟡 Pending | Signal Processing | A2: Data lake survey |
| LLD-B05 | Gateway Control Plane signing API contract finalization | 🟡 Pending ADR-008 | Platform Core | Security team sign-off |
| LLD-B06 | EMR Serverless cross-account access for multi-account data lake | 🔴 Blocked | Infra | Network topology review |
| LLD-B07 | Autopilot PR template review and approval by Engineering leads | 🟡 Pending | Autopilot | Template review meeting |
| LLD-B08 | Fleet Dashboard Grafana workspace provisioning | 🟡 Pending | AI & Intelligence | Infra team capacity |

---

## 15. Glossary

| Term | Definition |
|:---|:---|
| **Bootstrap** | One-time onboarding process: registration, profiling, policy config, certification init |
| **Signal-Ready** | A dataset that has completed all 4 bootstrap steps and can be monitored by Signal Engines |
| **Profiling Engine** | Service that samples historical data to compute statistical baselines (DuckDB for small, Spark for large) |
| **Synthetic Baseline** | Temporary baseline using org-wide tier averages for new datasets with < 3 days history |
| **Auto-Refinement** | Automatic replacement of synthetic baselines with computed ones after 7 real runs |
| **Contract-Lite** | Minimum viable contract: schema fingerprint + required fields (no invariants) |
| **Policy Bundle** | Signed YAML config defining schema, contract, PII, freshness, and volume rules |
| **Certified View** | Governed consumption surface pointing to last-known-good data version |
| **Progressive Enrichment** | Strategy of starting with minimal policies and adding richer checks over time |
| **Bootstrap Orchestrator** | Step Functions state machine managing the 4-step bootstrap lifecycle |
| **Dataset Registry** | DynamoDB-backed system of record for `dataset.yaml` configurations |
| **Autopilot Repo Scanner** | Service that discovers batch datasets by analyzing repository source code via AST |
| **PR Generator** | Service that creates GitHub Pull Requests with instrumentation code and policies |
| **Fleet Bootstrap** | The process of onboarding all 500+ batch datasets in an organization |
| **Kill-Switch** | Mechanism to disable validation without code redeployment (job, cluster, or fleet level) |
| **Deferred Certification** | Certification postponed until gold table receives its first successful write |
| **Gateway Control Plane** | Service that cryptographically signs policy bundles (ADR-008) |

---

## Appendix A: Full Component Dependency Matrix

```
Bootstrap Orchestrator (C-01)
  ├── reads: DynamoDB (BootstrapState, BootstrapConcurrency)
  ├── writes: DynamoDB (BootstrapState, BootstrapConcurrency)
  ├── invokes: Lambda (registration, profiling, policy, certification)
  ├── sends: SQS FIFO (overflow queue, approval queue)
  ├── sends: SNS (approval notifications)
  └── publishes: Kafka (SIGNAL_READY event to Evidence Bus)

Dataset Registry (C-02)
  ├── reads/writes: DynamoDB (DatasetRegistry)
  ├── reads/writes: S3 (sf-config/datasets/)
  └── validates: dataset.yaml content

Profiling Engine (C-03)
  ├── reads: S3 (data lake — gold tables)
  ├── reads: S3 (_delta_log/ for Delta, file listing for Parquet)
  ├── writes: S3 (sf-config/datasets/{name}/baseline.json)
  ├── launches: EMR Serverless (for large datasets)
  └── writes: DynamoDB (Baselines table via Baseline Store)

Baseline Store (C-04)
  ├── reads/writes: DynamoDB (Baselines)
  └── receives: run metrics from Run-the-Engine for auto-refinement

Policy Generator (C-05)
  ├── reads: S3 (baseline.json, dataset.yaml)
  ├── reads: Org policy templates
  ├── calls: Gateway Control Plane (signing)
  └── writes: S3 (policy_bundle.yaml)

Certified View Initializer (C-06)
  ├── reads: S3 (gold table verification)
  ├── writes: DynamoDB (CertifiedViewState)
  ├── writes: Neptune (BatchDataset node, OWNS edge)
  └── creates: EventBridge rules (deferred certification triggers)

Autopilot Repo Scanner (C-07)
  ├── reads: GitHub repositories (via GitHub App)
  ├── reads: Neptune (consumer count for tier classification)
  └── produces: WriteTargets, RuntimeDetections, TierClassifications

PR Generator (C-08)
  ├── writes: GitHub (branches, PRs)
  ├── creates: EventBridge rules (auto-merge timers)
  └── reads: Autopilot Scanner results

Fleet Dashboard Exporter (C-09)
  ├── reads: DynamoDB (DatasetRegistry, BootstrapState)
  └── writes: CloudWatch (fleet metrics)
```

---

## Appendix B: DynamoDB Table Summary

| Table | PK | SK | Capacity | TTL |
|:---|:---|:---|:---|:---|
| BootstrapState | `dataset_urn` | `bootstrap_id` | On-demand | 365 days |
| BootstrapConcurrency | `tier` | — | On-demand | None |
| DatasetRegistry | `dataset_urn` | `version` | On-demand | None |
| Baselines | `dataset_urn` | `metric_key` | On-demand | None |
| CertifiedViewState | `dataset_urn` | — | On-demand | None |
| BootstrapAudit | `audit_id` | `timestamp` | On-demand | 730 days |

---

## Appendix C: Latency Budget

| Phase | Component | Target Latency | Notes |
|:---|:---|:---|:---|
| Registration | API + validation + DynamoDB write | < 2 seconds | Synchronous |
| Profiling (small) | DuckDB Lambda | < 2 minutes | < 1M rows × 7 partitions |
| Profiling (large) | Spark EMR Serverless | < 15 minutes | Up to 100M rows with sampling |
| Profiling (synthetic) | Lambda computation | < 5 seconds | No data read |
| Policy generation | Lambda + Gateway signing | < 30 seconds | Includes signing round-trip |
| Approval (auto) | Step Functions wait | 48 hours | Tier-3 cooling period |
| Approval (human) | Async | 5–10 business days | Tier-1/2 SLA |
| Certification init | Lambda + DynamoDB + Neptune | < 60 seconds | Includes graph seeding |
| **Total (Tier-3, auto)** | **End-to-end** | **~48 hours** | **Dominated by approval wait** |
| **Total (Tier-1, human)** | **End-to-end** | **4–7 days** | **Dominated by human review** |

---

*Document ends.*
