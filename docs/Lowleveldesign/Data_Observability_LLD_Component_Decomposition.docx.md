  
**DATA OBSERVABILITY PLATFORM v2.0**

Low-Level Design Component Decomposition

*Signal Factory Architecture \- Out-of-Band Enforcement Pattern*

Version 1.0 | January 2026

Enterprise Data Platform Architecture

| Document Status | LLD Source Document \- Ready for Component Design |
| :---- | :---- |
| **Target Audience** | Component Owners, Tech Leads, Principal Engineers |
| **Prerequisite** | HLD v2.0 Out-of-Band Enforcement Architecture |
| **Estimated Cost** | \~$21,000/month infrastructure |

# **Table of Contents**

# **1\. Executive Summary**

This document decomposes the Data Observability Platform v2.0 High-Level Design into discrete components suitable for Low-Level Design (LLD) specifications. Each component is defined with clear boundaries, rationale, functionality scope, and interface contracts.

## **1.1 Purpose and Scope**

This decomposition serves as the authoritative source for:

* Assigning component ownership to teams and individuals  
* Establishing clear interface contracts between components  
* Defining the scope boundaries for each LLD document  
* Identifying dependencies and integration points  
* Providing rationale for architectural decisions at the component level

## **1.2 Component Inventory Summary**

The platform decomposes into 12 discrete components across 5 architectural planes:

| Plane | Component | Primary Owner Team |
| :---- | :---- | :---- |
| **Enforcement** | C-01: Policy Enforcer | Platform Core |
|  | C-02: Gateway Control Plane | Platform Core |
|  | C-03: Evidence Bus | Platform Core |
| **Processing** | C-04: Signal Engine Framework | Signal Processing |
|  | C-05: Alerting Engine | Signal Processing |
| **Knowledge** | C-06: Neptune Graph Store | Signal Processing |
|  | C-07: DynamoDB State Store | Signal Processing |
|  | C-08: Lineage Ingestor | AI & Intelligence |
| **Consumption** | C-09: RCA Copilot | AI & Intelligence |
| **Automation** | C-10: Autopilot Orchestrator | Autopilot |
|  | C-11: Scout Agent | Autopilot |
|  | C-12: Author/Review Agents | Autopilot |

# **2\. Architectural Context**

## **2.1 Core Design Principle: Separation of Concerns**

The Out-of-Band architecture introduces a critical separation that must be preserved in all component designs:

| Concern | Owner | Scope | Output |
| :---- | :---- | :---- | :---- |
| **Record Truth** | Policy Enforcer | Atomic (one record) | Evidence (PASS/FAIL) |
| **System Health** | Signal Engines | Aggregated (time windows) | Signals & Incidents |
| **Causal Analysis** | RCA Copilot | Graph traversal | Root Cause Report |

## **2.2 Hidden Assumptions**

Component designers must account for these system-wide assumptions:

* **Zero Producer Changes:** The central streaming platform and producers cannot be modified  
* **Evidence Bus as Single Source of Truth:** Signal Engines MUST NOT consume raw business topics  
* **Configuration-Driven Behavior:** All thresholds, SLOs, and policies managed via Gateway Control Plane  
* **Trace Anchoring:** All evidence preserves trace\_id for deterministic RCA  
* **Bounded Graph Cardinality:** Neptune writes must use FailureSignature deduplication

## **2.3 Non-Functional Requirements**

| Requirement | Target | Applies To |
| :---- | :---- | :---- |
| **Evidence Latency** | \< 2 seconds P99 | Policy Enforcer → Evidence Bus |
| **Signal Freshness** | \< 5 minutes | Signal Engines |
| **RCA Query Latency** | \< 2 minutes | RCA Copilot \+ Neptune |
| **Throughput** | 50K-500K events/sec | Evidence Bus, Enforcer |
| **Availability** | \> 99.5% | All components |
| **False Positive Rate** | \< 20% | Alerting Engine |

# **3\. Enforcement Plane Components**

## **3.1 C-01: Policy Enforcer**

*The cornerstone of the Out-of-Band architecture. Operates as a sidecar observer consuming events from the Central Streaming Platform after publication, running a deterministic pipeline of validation gates to establish per-record truth.*

### **Rationale**

* **Why separate from Gateway:** Original inline gateway design blocked data flow on failures; Out-of-Band pattern ensures Enforcer never blocks production data  
* **Why deterministic:** Every raw event produces exactly one Evidence event \- this is a pure function enabling replay and debugging  
* **Why gate pipeline:** Modular gates allow independent evolution and clear ownership of validation logic

### **Functionality Scope**

| Gate | Name | Function | Output Example |
| :---- | :---- | :---- | :---- |
| **G1** | Resolution | Map topic → dataset URN | urn:dp:orders:created |
| **G2** | Identity | Identify producer service | orders-svc (HIGH confidence) |
| **G3** | Schema | Validate vs Glue Registry | glue:orders.created:17 → PASS |
| **G4** | Contract | Validate vs ODCS contract | dc:orders.created:3 → FAIL |
| **G5** | PII | Scan for PII patterns | PII\_DETECTED / CLEAN |

### **Key Design Constraints**

* **Non-blocking:** NEVER blocks data flow; bad data flows through, Enforcer only creates evidence  
* **Trace-Anchored:** All evidence preserves trace\_id from source events for deterministic RCA  
* **Schema Fingerprint:** Must compute deterministic fingerprint for 'last good vs first bad' RCA

### **Interface Contracts**

**Inputs:**

* Raw Kafka events from business topics  
* Dataset resolution rules from Gateway Control Plane  
* Schema bindings from Glue Registry  
* Contract definitions from Gateway Control Plane

**Outputs:**

* Evidence Events to signal\_factory.evidence topic (canonical schema)

### **LLD Must Define**

1. Gate pipeline implementation with short-circuit behavior  
2. Schema fingerprint canonicalization algorithm  
3. Producer identity inference logic and confidence scoring  
4. PII detection patterns and performance impact  
5. EKS deployment topology and autoscaling policies  
6. Consumer group management and partition assignment  
7. Graceful degradation when Registry/Control Plane unavailable

## **3.2 C-02: Gateway Control Plane**

*The authoritative configuration brain of the system. Provides APIs for managing dataset policies, schema bindings, contract definitions, and enforcement rules. Purely a configuration service \- NOT on the critical data path.*

### **Rationale**

* **Why centralized:** Single source of truth for all dataset configurations prevents inconsistency across Enforcers  
* **Why decoupled from data path:** Control Plane unavailability should not block evidence generation (graceful degradation)  
* **Why API-first:** Enables programmatic management by Autopilot agents and CI/CD pipelines

### **Functionality Scope**

| Capability | Description |
| :---- | :---- |
| **Dataset Registry** | Manages URN mappings, tier classifications (Tier-1/2/3), and ownership metadata |
| **Schema Bindings** | Maps topics to Glue Registry schemas with version policies |
| **Contract Definitions** | ODCS contract specifications with required fields and SLOs |
| **Signal SLOs** | Per-dataset freshness, volume, and quality thresholds |
| **Producer Identity Map** | Topic-to-service mappings for attribution when headers unavailable |
| **Resolution Rules** | Rules mapping (topic, schema\_id, headers) → dataset\_urn |

### **Key Design Constraints**

* **Versioned configurations:** All changes must be auditable with rollback capability  
* **Cacheable:** Enforcers should cache configurations locally with TTL-based refresh  
* **Human approval workflow:** Critical changes (Tier-1 SLOs) require approval

### **LLD Must Define**

8. REST/GraphQL API specifications  
9. DynamoDB table schemas (DatasetRegistry, DatasetResolutionMap)  
10. Configuration versioning and audit trail implementation  
11. Caching strategy and invalidation mechanisms  
12. Approval workflow state machine  
13. Integration with Glue Schema Registry

## **3.3 C-03: Evidence Bus**

*The sole, non-negotiable API for all downstream systems. The signal\_factory.evidence Kafka topic represents the immutable record of per-event validation results. Signal Engines MUST NOT consume raw business topics \- they operate exclusively on Evidence.*

### **Rationale**

* **Why single topic:** Centralizes all validation state; avoids duplication of gate logic across consumers  
* **Why immutable:** Evidence serves as audit trail and replay source for incident investigation  
* **Why Kafka:** Ordered, durable, partitioned for parallel consumption by multiple engine consumer groups

### **Functionality Scope**

* Receive Evidence events from Policy Enforcer  
* Distribute to Signal Engine consumer groups via fan-out  
* Provide replay capability for incident investigation  
* Archive to S3 for long-term retention and compliance

### **Canonical Evidence Schema (Key Fields)**

| Field | Purpose |
| :---- | :---- |
| **evidence\_id** | ULID-based unique identifier (evd-01HQX...) |
| **dataset\_urn** | Resolved dataset identifier |
| **producer.id \+ confidence** | Attributed service and inference confidence |
| **validation.result** | PASS/FAIL overall result |
| **failed\_gates** | List of gates that failed (e.g., \[CONTRACT\]) |
| **reason\_codes** | Detailed failure reasons (e.g., MISSING\_FIELD:customer\_id) |
| **schema\_fingerprint** | Deterministic fingerprint for drift detection |
| **otel.trace\_id** | Preserved correlation ID for RCA |
| **source.topic/partition/offset** | Raw event location for replay |

### **LLD Must Define**

14. MSK cluster sizing and partition strategy (target: 64 partitions for 500K events/sec)  
15. Retention policies (7-day hot, 30-day warm, S3 cold)  
16. Consumer group naming conventions and offset management  
17. Backpressure handling and lag monitoring  
18. DLQ strategy for malformed evidence  
19. S3 archival format and compaction

# **4\. Processing Plane Components**

## **4.1 C-04: Signal Engine Framework**

*Transforms the firehose of per-record Evidence into high-level, actionable signals about system health. Each engine type runs as an independent EKS deployment with its own consumer group, enabling isolated scaling and deployment.*

### **Rationale**

* **Why separate engines:** Different signal types have different scaling patterns; freshness is time-driven, volume is count-driven  
* **Why windowed:** Per-record alerting creates noise; 5-minute tumbling windows balance responsiveness with signal-to-noise  
* **Why Evidence-only:** Engines see pre-validated data; no duplication of validation logic

### **Engine Types**

| Engine | Function | Output Signal |
| :---- | :---- | :---- |
| **Freshness** | Monitors time since last valid evidence | FRESHNESS\_BREACH |
| **Volume** | Detects anomalies in event throughput | VOLUME\_ANOMALY |
| **Contract** | Computes compliance rate over windows | CONTRACT\_BREACH |
| **Schema Drift** | Tracks schema\_fingerprint changes | DRIFT\_DETECTED |
| **DQ** | Aggregates Deequ/quality results | DQ\_BREACH |
| **Anomaly** | ML-based pattern detection | ANOMALY\_DETECTED |
| **Cost** | Tracks compute/storage costs | COST\_ANOMALY |

### **MVP Scope (Option 2: Contract-Lite Minimum)**

For initial deployment, only these engines are required:

* **Freshness Engine:** Pipeline stoppage detection  
* **Volume Engine:** Drops/spikes detection with 7-day baseline  
* **Contract Compliance Engine:** Structural correctness with schema drift signal

### **LLD Must Define (Per Engine)**

20. Window semantics (tumbling vs sliding, size, grace period)  
21. State management (local RocksDB vs DynamoDB)  
22. Watermarking and late-event handling (2-minute grace period)  
23. Baseline computation algorithms  
24. SLO evaluation logic and threshold configuration  
25. Signal schema and emission patterns  
26. FailureSignature deduplication keys  
27. Neptune write patterns (what to write vs not write)

## **4.2 C-05: Alerting Engine**

*Transforms signals into incidents with appropriate routing, grouping, and escalation. Prevents alert fatigue through intelligent deduplication and severity-based routing.*

### **Rationale**

* **Why separate from engines:** Alert routing logic changes independently of signal computation  
* **Why grouping:** 10 signals from 1 root cause should create 1 incident, not 10 pages  
* **Why severity tiers:** SEV-1 (revenue impact) needs PagerDuty; SEV-3 can be Jira

### **Functionality Scope**

* Consume signals from all Signal Engines  
* Create/update Incidents in DynamoDB IncidentIndex  
* Route by severity: SEV-1 → PagerDuty, SEV-2 → Slack, SEV-3 → Jira  
* Group by root cause using FailureSignature correlation  
* Track false positive rate for continuous tuning  
* Implement escalation policies with time-based triggers

### **LLD Must Define**

28. Incident creation state machine  
29. Alert grouping algorithm (5-minute dedup window)  
30. Severity classification rules by dataset tier and signal type  
31. Integration with PagerDuty, Slack, Jira APIs  
32. Rate limiting to prevent alert storms (max 10 alerts/hour/team)  
33. False positive feedback loop and threshold adjustment

# **5\. Knowledge Plane Components**

## **5.1 C-06: Neptune Graph Store**

*Enables causal traversal from incidents back to root causes. The graph stores relationships, not raw data \- optimized for 'Why did this happen?' queries through bounded, deduplicated nodes.*

### **Rationale**

* **Why graph database:** RCA queries are inherently graph traversals: Incident → Signal → FailureSignature → Deployment  
* **Why Neptune:** AWS-managed, HA, integrates with IAM, supports Gremlin  
* **Why bounded cardinality:** Unbounded writes (per-record) would explode costs and query performance

### **Node Types**

| Node | Cardinality Control | TTL |
| :---- | :---- | :---- |
| **Dataset** | Stable (1000s) | Permanent |
| **Service** | Stable (100s) | Permanent |
| **Column** | \~50/dataset | Permanent |
| **Deployment** | \~500/day | 30-90 days |
| **FailureSignature** | Deduplicated by key | Long-lived (recurring patterns) |
| **Signal** | Per dataset/window | 7-30 days (optional) |
| **Incident** | Per breach | 180-365 days (audit) |

### **Critical Causal Edges**

The RCA traversal pattern:

(Deployment) \-\[:INTRODUCED\]→ (FailureSignature) \-\[:CAUSED\]→ (Signal) \-\[:TRIGGERED\]→ (Incident)

Lineage edges (from SCA integration):

(Job) \-\[:READS\]→ (Dataset)   |   (Job) \-\[:WRITES\]→ (Dataset)   |   (Job) \-\[:READS\_COL\]→ (Column)

### **What NOT to Write**

* Every evidence event (use samples only)  
* Every schema version (fingerprint suffices)  
* Per-run execution edges (use per-deployment)  
* Full transform AST (store reference only)

### **LLD Must Define**

34. Complete node and edge schema with properties  
35. FailureSignature deduplication key algorithm  
36. Gremlin query patterns for RCA (incident-centric, blast radius, change correlation)  
37. TTL enforcement mechanism  
38. Cardinality controls (max 10K nodes/dataset, 1K edges/node)  
39. Query latency optimization (\<500ms P99 for blast radius)

## **5.2 C-07: DynamoDB State Store**

*Provides operational truth for fast dashboards and lookups. Answers 'What is the current health?' while Neptune answers 'Why did this happen?' \- complementary storage strategies.*

### **Tables**

| Table | PK | SK | Purpose |
| :---- | :---- | :---- | :---- |
| **SignalState** | asset\_urn | signal\_type | Current signal state per asset |
| **IncidentIndex** | incident\_id | timestamp | Active incidents with context |
| **DatasetRegistry** | dataset\_urn | version | Dataset metadata and policies |
| **EvidenceCache** | evidence\_id | \- | Hot evidence for RCA queries |
| **DatasetToWritersIndex** | dataset\_urn | producer\#id | Lineage: who writes this dataset |
| **DatasetToReadersIndex** | dataset\_urn | consumer\#id | Lineage: who reads this dataset |

### **LLD Must Define**

40. Complete attribute schemas for each table  
41. GSI definitions for common access patterns  
42. Capacity planning (on-demand vs provisioned)  
43. TTL policies by table  
44. Consistency requirements (eventual vs strong)

## **5.3 C-08: Lineage Ingestor**

*Bridge component consuming LineageSpec events from SCA (Static Code Analysis) and writing topology edges to Neptune. Integrates design-time intent (what code should read/write) with runtime truth (what actually happened).*

### **Rationale**

* **Why separate from Enforcer:** Lineage is design-time metadata, not runtime validation; different cadence and source  
* **Why asynchronous:** Stale lineage should never block alerting or incident creation  
* **Why column-level:** Precision RCA: 'which specific field change broke which specific consumers?'

### **Interface with SCA Team**

SCA team produces LineageSpec artifacts containing:

* producer: service/job identifier  
* inputs: dataset URNs \+ column URNs  
* outputs: dataset URNs \+ column URNs  
* confidence: HIGH/MED/LOW with reasons  
* code\_ref: commit SHA, file paths

### **LLD Must Define**

45. LineageSpec JSON schema validation  
46. URN normalization rules  
47. Neptune edge creation patterns (READS, WRITES, READS\_COL, WRITES\_COL)  
48. DynamoDB index updates (DatasetToWriters/Readers)  
49. Confidence threshold handling (LOW confidence edges marked)  
50. Versioning strategy (keep multiple specs per commit)

# **6\. Consumption Plane Components**

## **6.1 C-09: RCA Copilot**

*AI-powered assistant that explains incidents using evidence from the Knowledge Graph. The primary value delivery mechanism \- reducing MTTR from hours to minutes through deterministic, evidence-backed root cause analysis.*

### **Rationale**

* **Why LLM-powered:** Natural language explanations are more actionable than raw graph data  
* **Why evidence-first:** Copilot ONLY reasons over deterministic graph data; every claim cites Evidence IDs  
* **Why no hallucination:** If the graph doesn't have an edge, Copilot says 'unknown' \- never fabricates

### **Functionality Scope**

* Accept incident\_id as input  
* Query Neptune for causal chain (Incident → Signal → FailureSignature → Deployment)  
* Query lineage for blast radius (downstream consumers)  
* Retrieve sample evidence for first-bad/last-good boundaries  
* Generate natural language explanation with citations  
* Suggest mitigation actions (rollback, hotfix, quarantine)

### **Output Contract**

RCA report must include:

* **Root cause statement:** 'Deployment v3.17 introduced MISSING\_FIELD:customer\_id'  
* **Evidence IDs:** Links to first-bad and last-good evidence  
* **Blast radius:** Ranked list of impacted downstream consumers with confidence  
* **Timeline:** When change was introduced, when detected, time to impact  
* **Suggested actions:** Rollback to v3.16, contact orders-svc owner

### **LLD Must Define**

51. LLM integration (Claude API via Bedrock)  
52. Prompt engineering for incident context  
53. Gremlin query patterns for upstream/downstream traversal  
54. Evidence citation format  
55. Confidence scoring for conclusions  
56. Graceful degradation when lineage unavailable  
57. Rate limiting and caching (100 queries/min, 60% cache hit target)  
58. Accuracy validation program (≥70% top-3 accuracy for 50 ground-truth incidents)

# **7\. Automation Plane Components**

The Autopilot Agent System solves the bootstrap problem: you cannot have intelligent RCA without signals, and teams won't invest in signals without demonstrated value. These agents proactively instrument services to establish baseline observability.

## **7.1 C-10: Autopilot Orchestrator Agent**

*Central coordination agent managing the instrumentation workflow. Uses LLM reasoning for priority decisions, human escalation, and progress tracking across all repositories.*

### **Functionality Scope**

* Coordinate Scout, Author, Review agents  
* Priority scoring and sequencing of repositories  
* Human escalation decisions based on confidence thresholds  
* Rate limiting during incidents (max 10 PRs during SEV-1/2)  
* Progress reporting and metrics collection

### **Guardrails**

| Action | Allowed? | Guardrail |
| :---- | :---- | :---- |
| Create instrumentation PRs | ✓ | Max 2 PRs/repo/week |
| Auto-merge high-confidence PRs | ✓ | Confidence ≥0.8, tests pass |
| Modify contracts | ✓ | Always requires human review |
| Rollback producer deployments | ✗ | Never automated; propose only |
| Auto-mute alerts | ✗ | Never automated |
| Create incidents | ✗ | Signal Engines only |

### **LLD Must Define**

59. Workflow state machine (Push Phase → Pull Phase transition)  
60. Priority scoring algorithm  
61. Rate limiter implementation with incident detection  
62. LLM cost controls (max $500/day)  
63. Inter-agent communication protocol

## **7.2 C-11: Scout Agent**

*Repository analysis and gap detection. Clones repositories, detects technology stack, identifies observability gaps, and calculates confidence scores for automated instrumentation.*

### **Analysis Workflow**

64. **Tech Stack Detection:** Language, framework, build system  
65. **Archetype Matching:** Kafka producer, Spark job, REST API, etc.  
66. **Observability Assessment:** Current OTel coverage, existing instrumentation  
67. **Gap Identification:** Missing trace propagation, temporal signals, contracts  
68. **Confidence Scoring:** Based on signal clarity, dependency versions, patterns, test coverage

### **LLD Must Define**

69. AST parsing libraries (tree-sitter for Python/Java/Scala)  
70. Archetype detection rules by language/framework  
71. Gap detection heuristics for each instrumentation type  
72. Confidence scoring formula with weights  
73. GapReport schema

## **7.3 C-12: Author & Review Agents**

*Code generation and PR validation. Author Agent generates instrumentation code and creates PRs. Review Agent validates PRs, executes tests, and manages human liaison.*

### **Author Agent Scope**

* Generate instrumentation code from templates  
* Create PRs with clear descriptions and test instructions  
* Draft contract definitions based on observed payloads  
* Apply language-specific templates (Spring starter, OpenLineage for Spark)

### **Review Agent Scope**

* Validate generated code against safety rules  
* Execute automated tests  
* Route for human review when confidence \< 0.8  
* Track PR lifecycle and collect feedback

### **LLD Must Define**

74. Instrumentation templates by archetype  
75. PR creation workflow with GitHub App integration  
76. Safety validation rules  
77. Human review routing criteria  
78. Feedback loop for confidence tuning

# **8\. Cross-Cutting Concerns**

## **8.1 URN Conventions (All Components)**

| Asset Type | URN Pattern | Example |
| :---- | :---- | :---- |
| Service | urn:svc:\<env\>:\<name\> | urn:svc:prod:order-service |
| Dataset | urn:dp:\<domain\>:\<name\> | urn:dp:orders:created |
| Column | urn:col:\<parent\_urn\>:\<column\> | urn:col:...:customer\_id |
| Kafka Topic | urn:kafka:\<env\>:\<cluster\>:\<topic\> | urn:kafka:prod:main:orders-created |
| Schema | urn:schema:\<registry\>:\<subject\>:\<ver\> | urn:schema:glue:orders-created:42 |
| Evidence | evd-\<ulid\> | evd-01HQXYZ... |

## **8.2 Security Model**

| Domain | Approach | Implementation |
| :---- | :---- | :---- |
| **Authentication** | Service-to-service: IAM roles | IRSA (IAM Roles for Service Accounts) |
| **Authorization** | Least-privilege per component | Scoped IAM policies; Neptune IAM auth |
| **Encryption (Transit)** | TLS 1.3 everywhere | Internal ALBs with ACM certs |
| **Encryption (Rest)** | KMS for all data stores | Neptune KMS; DynamoDB managed keys |
| **Secrets** | No credentials in code | AWS Secrets Manager |
| **PII Protection** | Field-level detection | Enforcer PII gate; evidence flags |

## **8.3 Observability of Observability**

Each component must emit metrics for platform health:

* Evidence flow rate, lag, error breakdown  
* Per-engine processing latency and signal states  
* Autopilot PR creation rate, merge rate, queue depth  
* Daily cost by component with projections

# **9\. Component Dependency Matrix**

This matrix shows which components depend on which others. Use this to plan implementation sequencing and identify integration test scope.

| Component | Depends On |
| :---- | :---- |
| **C-01 Policy Enforcer** | C-02 Gateway Control Plane, C-03 Evidence Bus, Glue Schema Registry |
| **C-02 Gateway Control Plane** | C-07 DynamoDB State Store |
| **C-03 Evidence Bus** | MSK (external) |
| **C-04 Signal Engines** | C-03 Evidence Bus, C-06 Neptune, C-07 DynamoDB |
| **C-05 Alerting Engine** | C-04 Signal Engines, C-07 DynamoDB, PagerDuty/Slack (external) |
| **C-06 Neptune Graph** | None (foundation) |
| **C-07 DynamoDB** | None (foundation) |
| **C-08 Lineage Ingestor** | C-06 Neptune, C-07 DynamoDB, SCA team (external) |
| **C-09 RCA Copilot** | C-06 Neptune, C-07 DynamoDB, Bedrock (external) |
| **C-10 Orchestrator** | C-11 Scout, C-12 Author/Review, C-03 Evidence Bus (read-only) |
| **C-11 Scout Agent** | GitHub API (external) |
| **C-12 Author/Review** | GitHub API, CI/CD (external) |

# **10\. Recommended LLD Sequencing**

Based on dependencies and value delivery, the following sequence is recommended for LLD development:

## **Phase 1: Foundation (Months 1-2)**

79. **C-06 Neptune Graph Store:** Foundation for all RCA queries  
80. **C-07 DynamoDB State Store:** Foundation for operational state  
81. **C-03 Evidence Bus:** Core integration backbone  
82. **C-02 Gateway Control Plane:** Configuration foundation

## **Phase 2: Core Processing (Months 2-4)**

83. **C-01 Policy Enforcer:** Cornerstone component \- enables evidence generation  
84. **C-04 Signal Engines (Freshness, Volume, Contract):** MVP signal set  
85. **C-05 Alerting Engine:** Incident creation and routing

## **Phase 3: Intelligence (Months 3-5)**

86. **C-09 RCA Copilot:** Primary value delivery \- sub-2-minute RCA  
87. **C-08 Lineage Ingestor:** Blast radius enrichment

## **Phase 4: Automation (Months 5-8)**

88. **C-11 Scout Agent:** Repository analysis  
89. **C-12 Author/Review Agents:** PR generation and validation  
90. **C-10 Autopilot Orchestrator:** Coordination layer

# **Appendix A: Glossary**

| Term | Definition |
| :---- | :---- |
| **Signal Factory** | Architectural paradigm treating telemetry as manufactured product with quality controls |
| **Out-of-Band Enforcement** | Pattern where validation occurs after data publication, not inline |
| **Evidence** | Immutable record of per-event validation result (PASS/FAIL with reason codes) |
| **Record Truth** | Per-record validation state established by Policy Enforcer |
| **System Health** | Aggregated signal state computed by Signal Engines over time windows |
| **FailureSignature** | Unique pattern of failure (gate \+ reason) used for graph deduplication |
| **Bootstrap Problem** | Chicken-egg: need signals for RCA value, need RCA value for signal investment |
| **Push Phase** | Proactive instrumentation to establish baseline signals |
| **Pull Phase** | Reactive improvement driven by evidence failures |
| **MTTR** | Mean Time to Resolution: average time from incident detection to resolution |

*— End of Document —*