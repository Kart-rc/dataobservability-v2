# CLAUDE.md — Data Observability Platform v2.0

This file provides AI assistants with the context needed to navigate, understand,
and contribute to this repository effectively.

---

## Repository Overview

This is a **documentation-only repository** for the **Signal Factory Data Observability
Platform v2.0**. There is no application source code here. All content consists of
architecture documents, design specifications, product requirements, and implementation
guides for a distributed data observability system.

**Primary purpose:** Serve as the authoritative design reference for a 4-team engineering
organization building a production data observability platform on AWS.

---

## Repository Structure

```
dataobservability-v2/
├── README.md                          # Minimal project title
├── CLAUDE.md                          # This file
└── docs/
    ├── Batch/                         # Batch workflow observability
    │   ├── batch_observability_prd.md         # PRD: Batch Observability Module
    │   ├── batch_observability_hld.md         # HLD: Batch architecture
    │   ├── batch_observability_challenges.md  # Problem analysis
    │   ├── batch_observability_postwrite_hld.md # Post-write validation HLD
    │   ├── batch_bootstrap_hld.md             # Bootstrap phase HLD
    │   ├── batch_bootstrap_lld_v1.md          # Bootstrap LLD v1
    │   └── batch_postwrite_validation_lld_v1.md # Post-write validation LLD v1
    │
    ├── Lowleveldesign/                # Component LLD specifications
    │   ├── Data_Observability_LLD_Component_Decomposition.docx.md  # Master LLD index
    │   ├── Low-Level Design_ Signal Factory Data Observability Platform.md
    │   ├── Low-Level Design_ Signal Processing Engines.md
    │   └── Individual-LLD/            # Per-component LLD documents
    │       ├── C01_Policy_Enforcer_LLD.md
    │       ├── C02_Gateway_Control_Plane_LLD.md
    │       ├── C03_Evidence_Bus_LLD_v1.0.md
    │       ├── C04_Signal_Engine_Framework_LLD_v1.0.md
    │       ├── C05_Alerting_Engine_LLD.md
    │       ├── C-06_Neptune_Graph_Store_LLD.md
    │       └── C07_DynamoDB_State_Store_LLD.md
    │       └── C08_Lineage_Ingestor_LLD.md
    │
    ├── autopilot/                     # Autopilot agent system
    │   ├── autopilot_agent_system_hld_v1.1.md  # HLD for Autopilot (authoritative)
    │   ├── Autopilot enablement.md
    │   ├── Autopilot Push Model_ Enabling Signal Generation at Source-2.md
    │   └── Deep Dive_ Event Schemas & Emit Scenarios.md
    │
    ├── lineage-spec/                  # SCA lineage interface definitions
    │   ├── Lineage Spec.md                        # Interface design doc
    │   ├── sca_lineage_requirements_specification.md  # ELS requirements
    │   ├── sca_lineage_flow.md
    │   ├── sca_lineage_spec.md
    │   ├── sca_quick_reference.md
    │   ├── sca_services_lineage_requirements.md
    │   └── neptune_data_model.md
    │
    ├── outofband-enforcement/         # Core architecture pattern
    │   └── Out-of-Band Enforcement HLD v2.md
    │
    └── roadmap/                       # Implementation planning
        ├── Data_Observability_Roadmap_Detailed.docx.md  # 12-month milestone plan
        ├── Data_Observability_4Team_Implementation_Plan.docx.md
        └── Data_Observability_Implementation_Recommendation.docx.md
```

---

## Platform Architecture

### Core Design Principle: Out-of-Band Enforcement

The platform uses an **Out-of-Band** pattern: validation happens *after* data is published,
never blocking the data flow. Bad data flows through; the Policy Enforcer creates an
evidence record (PASS/FAIL) instead of rejecting messages inline.

### Five Architectural Planes

| Plane | Components | Purpose |
|-------|-----------|---------|
| **Enforcement** | C-01 Policy Enforcer, C-02 Gateway Control Plane, C-03 Evidence Bus | Establish per-record truth |
| **Processing** | C-04 Signal Engine Framework, C-05 Alerting Engine | Aggregate evidence into actionable signals |
| **Knowledge** | C-06 Neptune Graph Store, C-07 DynamoDB State Store, C-08 Lineage Ingestor | Store causal relationships and operational state |
| **Consumption** | C-09 RCA Copilot | AI-powered incident explanation |
| **Automation** | C-10 Autopilot Orchestrator, C-11 Scout Agent, C-12 Author/Review Agents | Auto-instrument source code |

### The 12 Components

| ID | Component | Team | Status |
|----|-----------|------|--------|
| C-01 | Policy Enforcer | Platform Core | LLD authored |
| C-02 | Gateway Control Plane | Platform Core | LLD authored |
| C-03 | Evidence Bus | Platform Core | LLD authored |
| C-04 | Signal Engine Framework | Signal Processing | LLD authored |
| C-05 | Alerting Engine | Signal Processing | LLD authored |
| C-06 | Neptune Graph Store | Signal Processing | LLD authored |
| C-07 | DynamoDB State Store | Signal Processing | LLD authored |
| C-08 | Lineage Ingestor | AI & Intelligence | LLD authored |
| C-09 | RCA Copilot | AI & Intelligence | HLD defined |
| C-10 | Autopilot Orchestrator | Autopilot | HLD defined |
| C-11 | Scout Agent | Autopilot | HLD defined |
| C-12 | Author & Review Agents | Autopilot | HLD defined |

### Key Data Flow (Streaming)

```
Raw Kafka Event
    → Policy Enforcer (G1→G5 gates, <2s)
    → Evidence Bus (signal_factory.evidence topic)
    → Signal Engines (5-min tumbling windows)
    → Alerting Engine (incident creation)
    → Neptune Graph (causal edges)
    → RCA Copilot (AI explanation)
```

### Key Data Flow (Batch)

```
Spark/Airflow Job
    → Autopilot Inline SDK (per medallion stage)
    → Evidence Events (Bronze/Silver/Gold gates)
    → Evidence Bus (shared topic)
    → Freshness/Volume/Contract/DQ/Schema Engines
    → Certified View (advances only on PASS)
    OR Quarantine Table (on FAIL)
```

---

## Critical Conventions

### URN Naming Standards

All platform assets use stable URNs as join keys across all systems. **Never use
free-form strings where a URN is expected.**

| Asset Type | Pattern | Example |
|-----------|---------|---------|
| Dataset | `urn:dp:<domain>:<name>` | `urn:dp:orders:created` |
| Service | `urn:svc:<env>:<name>` | `urn:svc:prod:order-service` |
| Column | `urn:col:<parent_urn>:<column>` | `urn:col:urn:dp:orders:created:customer_id` |
| Kafka Topic | `urn:kafka:<env>:<cluster>:<topic>` | `urn:kafka:prod:main:orders-created` |
| Schema | `urn:schema:<registry>:<subject>:<ver>` | `urn:schema:glue:orders-created:42` |
| Evidence | `evd-<ulid>` | `evd-01HQXYZ...` |

### Evidence Gate Names

The Policy Enforcer runs exactly 5 gates in sequence. Use these canonical names in all docs:

| Gate | Name | Validates |
|------|------|-----------|
| G1 | Resolution | Topic → Dataset URN mapping |
| G2 | Identity | Producer service attribution |
| G3 | Schema | Glue Registry schema conformance |
| G4 | Contract | ODCS contract required fields/SLOs |
| G5 | PII | PII pattern detection |

For batch, stage-level gates are prefixed: `G3_SCHEMA`, `G4_CONTRACT`, `G5_PII`.

### FailureSignature Format

FailureSignatures are the deduplication key in Neptune. Format:
```
<GATE>:<REASON>:<DETAIL>
```
Examples:
- `CONTRACT:MISSING_FIELD:customer_id`
- `SCHEMA:TYPE_MISMATCH:order_total`
- `SCHEMA_BREAK:order_total:DECIMAL→STRING`
- `UNKNOWN_ENUM:order_type:FLASH_SALE`

### Reason Codes

Standard reason codes used in evidence events:
- `MISSING_FIELD:<field_name>`
- `TYPE_MISMATCH:<field_name>`
- `NULL_VIOLATION:<field_name>`
- `PII_DETECTED:<pattern_type>`
- `VOLUME_ANOMALY:<direction>` (UP/DOWN)
- `FRESHNESS_BREACH:<breach_type>` (JOB_NOT_TRIGGERED, JOB_FAILED, etc.)

### Progressive Gate Enforcement Levels

Enforcement rollout follows a 4-stage progression. Always specify which gate applies:

| Gate Level | Behavior |
|-----------|---------|
| G0 — Visibility | Telemetry only; no alerts, no blocks |
| G1 — Warn | CI warnings only |
| G2 — Soft-Fail | Block in staging; alert in production |
| G3 — Hard-Fail | Block in production for Tier-1 |

### Dataset Tiers

| Tier | Meaning | SLA Treatment |
|------|---------|--------------|
| TIER_1 | Revenue-critical; executive-facing | Hard-fail enforcement; PagerDuty alerts |
| TIER_2 | Operational; team-facing | Soft-fail; Slack alerts |
| TIER_3 | Exploratory; low impact | Warn only; Jira tickets |

---

## Batch-Specific Conventions

### Medallion Architecture Stages

Batch validation runs at each layer boundary. Evidence is emitted per stage:

- **Bronze**: Raw ingestion — G1 (Resolution) + G2 (Identity) + G3 (Schema fingerprint)
- **Silver**: Cleaned data — G4 (Contract-Lite) + G5 (PII) + DQ checks
- **Gold**: Aggregated/enriched — G3 (Schema compat) + G4 (Full contract) + Certification

### Certified View Pattern

- A Certified View always points to the last known good version
- Advances **only** when all Gold-layer gates pass
- On failure: data routes to quarantine, Certified View holds at previous version
- Certification state tracked in DynamoDB: `last_certified_version`, `last_certified_at`, `certification_status`

### Bootstrap vs. Run-the-Engine

New batch datasets follow a one-time **Bootstrap** phase before entering daily **Run-the-Engine** operation:

1. **Bootstrap**: Registration (`dataset.yaml`) → Profiling (`baseline.json`) → Policy config (`policy_bundle.yaml`) → Certification init
2. **Run-the-Engine**: Lightweight SDK evaluates pre-approved policy bundle at each stage boundary

### Batch Correlation IDs

| Field | Batch Equivalent Of | Purpose |
|-------|-------------------|---------|
| `run_id` | `trace_id` (streaming) | Links Spark executions to datasets/failures |
| `dag_run_id` | N/A | Links tasks to parent Airflow DAG run |
| `deploy_ref` | Deployment event | Links CI/CD events to code changes |

---

## Team Ownership

| Team | Planes Owned | Components |
|------|-------------|-----------|
| **Team 1 — Platform Core** | Enforcement | C-01 Policy Enforcer, C-02 Gateway Control Plane, C-03 Evidence Bus |
| **Team 2 — Signal Processing** | Processing + Knowledge | C-04 Signal Engines, C-05 Alerting Engine, C-06 Neptune, C-07 DynamoDB, C-08 Lineage Ingestor |
| **Team 3 — Autopilot** | Automation | C-10 Orchestrator, C-11 Scout, C-12 Author/Review |
| **Team 4 — AI & Intelligence** | Consumption | C-09 RCA Copilot, dashboards, self-service UI |

---

## Infrastructure & Technology

### AWS Services Used

| Service | Role |
|---------|------|
| Amazon MSK (Kafka) | Evidence Bus (`signal_factory.evidence`, 64 partitions) |
| Amazon EKS | Policy Enforcer, Signal Engines, Autopilot agents |
| Amazon Neptune | Causal graph store (Gremlin query language) |
| Amazon DynamoDB | Operational state (SignalState, IncidentIndex, DatasetRegistry, EvidenceCache) |
| AWS Glue Schema Registry | Schema validation for G3 gate |
| Amazon S3 | Evidence archive (hot 24h → warm 7d → cold 90d) |
| AWS Bedrock (Claude API) | RCA Copilot LLM integration |
| AWS Secrets Manager | All credentials (no secrets in code) |

### DynamoDB Tables

| Table | PK | SK | Purpose |
|-------|----|----|---------|
| SignalState | `asset_urn` | `signal_type` | Current signal state per dataset |
| IncidentIndex | `incident_id` | `timestamp` | Active incidents |
| DatasetRegistry | `dataset_urn` | `version` | Dataset metadata and policies |
| EvidenceCache | `evidence_id` | — | Hot evidence for RCA |
| DatasetToWritersIndex | `dataset_urn` | `producer#id` | Lineage: writers |
| DatasetToReadersIndex | `dataset_urn` | `consumer#id` | Lineage: readers |

### Security Model

- **Auth (service-to-service):** IAM roles via IRSA (IAM Roles for Service Accounts)
- **Authorization:** Least-privilege per component; Neptune IAM auth
- **Encryption in transit:** TLS 1.3 on all internal connections
- **Encryption at rest:** KMS for Neptune and DynamoDB
- **Secrets:** AWS Secrets Manager only — no credentials in code or config files
- **PII:** Detected at G5 gate; flagged in evidence; never stored raw in graph

---

## Non-Functional Requirements (SLOs)

| Metric | Target |
|--------|--------|
| Evidence latency (P99) | < 2 seconds |
| Signal freshness | < 5 minutes |
| RCA query latency | < 2 minutes |
| Streaming throughput | 50K–500K events/sec |
| Platform availability | > 99.5% |
| False positive alert rate | < 20% |
| Batch freshness breach detection | < 5 min after SLA window |
| Neptune graph query (P95) | < 500ms (blast radius); < 3s (batch) |
| Evidence Bus availability | 99.9% |
| Infrastructure cost | ~$21,000/month |

---

## Document Conventions

### Document Types Used in This Repo

| Abbreviation | Meaning | Scope |
|-------------|---------|-------|
| **PRD** | Product Requirements Document | What and why |
| **HLD** | High-Level Design | Architecture and component interactions |
| **LLD** | Low-Level Design | Implementation specifications for a single component |
| **Spec** | Interface/contract specification | API or data schemas between teams |

### Document Status Lifecycle

`Draft for Review` → `Ready for Component Design` → `Approved` → `Implemented`

### Writing Style Guidance

When authoring or updating documents in this repository:

1. **Tables over prose** — Use Markdown tables for structured comparisons, requirements, and
   milestones. The existing docs set this precedent strongly.
2. **Mermaid diagrams** — Use `mermaid` fenced code blocks for flowcharts and sequence
   diagrams. This is the standard throughout the repo.
3. **Callout blocks** — Use `> [!NOTE]`, `> [!IMPORTANT]`, and `> [!TIP]` for emphasis.
4. **Rationale sections** — Every design decision should include a "Why" subsection explaining
   the tradeoff. See existing LLD docs for the pattern.
5. **Numbered "LLD Must Define" lists** — Each component section ends with a numbered list
   of open items the LLD author must address.
6. **Version headers** — Include version, date, status, and owner team in every document header.

---

## Key Design Decisions (Do Not Reverse Without Consensus)

These decisions are load-bearing across multiple components. Changing them requires
updating all dependent documents:

1. **Evidence Bus is the single source of truth** — Signal Engines MUST NOT consume raw
   business topics. They operate exclusively on `signal_factory.evidence`.

2. **Non-blocking enforcement** — The Policy Enforcer never blocks data flow. Evidence
   records bad data; it does not prevent it from flowing downstream.

3. **Trace anchoring** — All evidence preserves `trace_id` (streaming) or `run_id` (batch)
   for deterministic RCA. This is non-negotiable.

4. **Bounded Neptune cardinality** — Graph writes use FailureSignature deduplication.
   Per-record graph nodes are explicitly prohibited (would explode cost and query perf).

5. **Lineage is enrichment, not a gate** — SCA lineage never blocks alerting or incident
   creation. It enriches RCA with blast-radius context asynchronously.

6. **Certified View immutability** — A Certified View only advances on a Gold-layer PASS.
   It is never rolled forward speculatively.

---

## Glossary

| Term | Definition |
|------|-----------|
| **Signal Factory** | Architectural paradigm treating telemetry as a manufactured product with quality controls |
| **Out-of-Band Enforcement** | Validation occurs after data publication, not inline |
| **Evidence** | Immutable PASS/FAIL record for a single event validation |
| **Evidence Bus** | Kafka topic `signal_factory.evidence` — all evidence flows here |
| **FailureSignature** | Deduplicated failure pattern stored as a Neptune node |
| **Record Truth** | Per-record validation state from Policy Enforcer |
| **System Health** | Aggregated signal state from Signal Engines over time windows |
| **Bootstrap Problem** | Chicken-and-egg: need signals for RCA value, need value to justify signal investment |
| **Certified View** | Consumption surface always pointing to last known good batch version |
| **Quarantine** | Isolation table for data that fails Gold-layer gates |
| **Policy Bundle** | YAML config defining schema constraints, contracts, PII rules for a dataset |
| **Contract-Lite** | Minimum viable contract: producer attribution + schema fingerprint |
| **LineageSpec** | Versioned artifact from SCA team containing column-level lineage |
| **Steel Thread** | End-to-end validation through one pipeline from producer to RCA |
| **Push Phase** | Autopilot proactively instruments repos to establish baseline signals |
| **Pull Phase** | Evidence failures trigger reactive Autopilot PRs |
| **Medallion Architecture** | Bronze (raw) → Silver (cleaned) → Gold (aggregated) layers |
| **MTTD** | Mean Time to Detect |
| **MTTR** | Mean Time to Resolution |
| **ODCS** | Open Data Contract Standard |
| **IRSA** | IAM Roles for Service Accounts (EKS) |
| **ELS** | External Lineage Service (SCA team's component) |

---

## Implementation Roadmap Summary

The platform is implemented over 12 months across 4 phases:

| Phase | Months | Focus |
|-------|--------|-------|
| **Phase 1 — Foundation** | M1–M2 | Neptune, DynamoDB, Evidence Bus, Gateway Control Plane |
| **Phase 2 — Core Processing** | M2–M4 | Policy Enforcer (all 5 gates), MVP Signal Engines, Alerting |
| **Phase 3 — Intelligence** | M3–M5 | RCA Copilot, Lineage Ingestor |
| **Phase 4 — Automation** | M5–M8 | Scout Agent, Author/Review Agents, Autopilot Orchestrator |

Batch observability runs in parallel with a separate 12-month plan (see `docs/Batch/`).

---

*Last updated: February 2026 | Version: 1.0*
