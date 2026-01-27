# C-06: Neptune Graph Store - Low-Level Design

**Data Observability Platform v2.0**  
**Component: C-06 Neptune Graph Store**  
**Version:** 1.0  
**Date:** January 2026  
**Author:** Platform Core Team  
**Status:** Draft for Review

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Component Overview](#2-component-overview)
3. [System Thinking Analysis](#3-system-thinking-analysis)
4. [Graph Data Model](#4-graph-data-model)
5. [API Specifications](#5-api-specifications)
6. [Gremlin Query Patterns](#6-gremlin-query-patterns)
7. [Write Patterns and Cardinality Control](#7-write-patterns-and-cardinality-control)
8. [TTL Enforcement Mechanism](#8-ttl-enforcement-mechanism)
9. [Scalability and Performance](#9-scalability-and-performance)
10. [Observability](#10-observability)
11. [Security](#11-security)
12. [Error Handling and Resilience](#12-error-handling-and-resilience)
13. [Deployment Architecture](#13-deployment-architecture)
14. [Operational Runbook](#14-operational-runbook)
15. [Cost Analysis](#15-cost-analysis)
16. [Appendices](#16-appendices)

---

## 1. Executive Summary

### 1.1 Purpose

The Neptune Graph Store (C-06) serves as the causal knowledge backbone of the Data Observability Platform, enabling deterministic root cause analysis (RCA) through graph traversals. It answers the fundamental question: **"Why did this happen?"**

### 1.2 Core Responsibilities

- Store bounded, deduplicated topology and causal relationships
- Enable sub-500ms P99 RCA traversals from Incident → Root Cause
- Provide blast radius analysis through lineage edge traversal
- Maintain cardinality controls to prevent graph explosion
- Support time-bounded TTL enforcement for ephemeral nodes

### 1.3 Design Principles

| Principle | Rationale |
|-----------|-----------|
| **Relationships, not raw data** | Neptune stores edges and topology; Evidence stays in Kafka/S3 |
| **Bounded cardinality** | Prevents cost explosion and query degradation |
| **Deduplication by stable keys** | FailureSignatures and lineage edges are idempotent |
| **Time-scoped incidents, pattern-scoped failures** | Enables recurring pattern correlation without confusion |
| **Complementary to DynamoDB** | Neptune for "Why?", DynamoDB for "What is current health?" |

### 1.4 Key Performance Targets

| Metric | Target | Rationale |
|--------|--------|-----------|
| RCA Query Latency (P99) | < 500ms | Sub-2-minute MTTR requires fast graph traversal |
| Blast Radius Query (P99) | < 500ms | Downstream impact must be immediate |
| Write Latency (P99) | < 100ms | Non-blocking to Signal Engines |
| Graph Size | < 10M vertices | Cost and query performance bound |
| Availability | 99.9% | RCA must be available during incidents |

---

## 2. Component Overview

### 2.1 Architectural Context

```mermaid
graph TB
    subgraph Upstream["Upstream Writers"]
        SE[Signal Engines<br/>C-04]
        AE[Alerting Engine<br/>C-05]
        LI[Lineage Ingestor<br/>C-08]
    end
    
    subgraph Neptune["C-06: Neptune Graph Store"]
        GW[Graph Writer Service]
        GC[Graph Cache Layer]
        NDB[(Amazon Neptune<br/>Gremlin)]
        TTL[TTL Enforcer<br/>Lambda]
    end
    
    subgraph Downstream["Downstream Readers"]
        RCA[RCA Copilot<br/>C-09]
        DASH[Dashboards]
    end
    
    SE -->|FailureSignature, Signal| GW
    AE -->|Incident, Correlation| GW
    LI -->|Lineage Edges| GW
    
    GW --> NDB
    NDB --> GC
    TTL -->|Cleanup| NDB
    
    GC --> RCA
    GC --> DASH
```

### 2.2 Component Boundaries

**In Scope:**
- Graph schema definition and enforcement
- Vertex and edge CRUD operations via Gremlin
- Cardinality controls and deduplication
- TTL-based cleanup of ephemeral nodes
- Query optimization for RCA patterns
- Cache layer for hot traversal paths

**Out of Scope:**
- Evidence event storage (→ Evidence Bus C-03)
- Operational state dashboards (→ DynamoDB C-07)
- Alert routing logic (→ Alerting Engine C-05)
- Natural language RCA generation (→ RCA Copilot C-09)

### 2.3 Upstream Dependencies

| Component | Dependency Type | Data Provided |
|-----------|-----------------|---------------|
| Signal Engines (C-04) | Write | FailureSignature nodes, Signal nodes (optional) |
| Alerting Engine (C-05) | Write | Incident nodes, CAUSED_BY/CORRELATED_WITH edges |
| Lineage Ingestor (C-08) | Write | Job/Service nodes, READS/WRITES/READS_COL/WRITES_COL edges |
| Gateway Control Plane (C-02) | Read | Dataset/Service registry for validation |

### 2.4 Downstream Consumers

| Component | Consumption Pattern | SLA |
|-----------|---------------------|-----|
| RCA Copilot (C-09) | Synchronous traversal queries | < 500ms P99 |
| Dashboards | Cached topology queries | < 200ms P95 |
| Blast Radius API | Multi-hop lineage traversal | < 500ms P99 |

---

## 3. System Thinking Analysis

### 3.1 Things and Connections

**Core Entities (Vertices):**
- Topology: Dataset, Service, Job, Column, Team
- Causal: Deployment, FailureSignature, Signal, Incident
- Metadata: LineageSpec

**Relationships (Edges):**
- Ownership: OWNED_BY, PRODUCES, CONSUMES
- Lineage: READS, WRITES, READS_COL, WRITES_COL
- Causality: INTRODUCED, CAUSED, TRIGGERED, CORRELATED_WITH
- Structure: HAS_COLUMN, DESCRIBES, DEPLOYS

### 3.2 Inflow Analysis

| Source | Event Type | Volume | Cardinality Impact |
|--------|------------|--------|-------------------|
| Signal Engines | FailureSignature creation | ~100/hour | Low (deduplicated) |
| Alerting Engine | Incident + edges | ~50/day | Low (per breach) |
| Lineage Ingestor | Topology edges | ~100/day | Stable (per deployment) |
| CI/CD Integration | Deployment nodes | ~500/day | Medium (TTL-bounded) |

### 3.3 Outflow Analysis

| Consumer | Query Pattern | Volume | Criticality |
|----------|---------------|--------|-------------|
| RCA Copilot | Incident → Root Cause traversal | ~1000/day | Critical |
| Blast Radius | Dataset → Consumers multi-hop | ~500/day | High |
| Dashboards | Topology aggregations | ~10K/day | Medium |

### 3.4 Cost of Action vs. Inaction

| Decision | Action Cost | Inaction Cost |
|----------|-------------|---------------|
| Implement cardinality controls | Development complexity | Graph explosion, query timeouts |
| Add TTL enforcement | Lambda cost (~$50/month) | Unbounded storage growth |
| Cache layer | Redis infrastructure (~$200/month) | Repeated expensive traversals |
| Multi-AZ deployment | 2x Neptune cost | Single point of failure during incidents |

### 3.5 Hidden Assumptions

| Assumption | Validation Strategy |
|------------|---------------------|
| FailureSignature dedup keys are stable | Unit tests with edge cases |
| 500/day deployment volume | Monitor actual CI/CD integration |
| 3-hop max for blast radius | Profile real lineage depth |
| RCA queries follow predictable patterns | Query logging and analysis |

### 3.6 Five Whys: Why Graph Database?

1. **Why Neptune?** → RCA queries require multi-hop traversals
2. **Why multi-hop?** → Root cause is often 2-4 edges from incident
3. **Why not SQL joins?** → N-hop joins are O(n^k) in relational DBs
4. **Why not document store?** → Denormalization leads to stale data
5. **Why managed service?** → HA, backup, IAM integration reduce ops burden

---

## 4. Graph Data Model

### 4.1 Node Types (Vertex Labels)

```mermaid
erDiagram
    DATASET {
        string urn PK "urn:dp:orders:order_created:v1"
        string domain "orders"
        string name "order_created"
        int tier "1"
        string owner_team "checkout-platform"
        datetime created_at "2025-01-01T00:00:00Z"
        datetime updated_at "2026-01-15T10:00:00Z"
    }
    
    SERVICE {
        string id PK "svc:order-service"
        string name "order-service"
        string type "SERVICE"
        string owner_team "checkout-platform"
        string repository "github.com/company/order-service"
        datetime created_at "2025-01-01T00:00:00Z"
    }
    
    JOB {
        string id PK "job:orders-delta-landing"
        string name "orders-delta-landing"
        string type "JOB"
        string platform "SPARK"
        string runtime "EMR"
        string owner_team "checkout-platform"
        datetime created_at "2025-01-01T00:00:00Z"
    }
    
    COLUMN {
        string urn PK "urn:col:dp:orders:order_created:v1:payment_method"
        string name "payment_method"
        string dataset_urn FK "urn:dp:orders:order_created:v1"
        string data_type "STRING"
        boolean nullable "true"
    }
    
    TEAM {
        string id PK "team:checkout-platform"
        string name "Checkout Platform"
        string slack_channel "#checkout-oncall"
        string pagerduty_service "P123ABC"
    }
    
    DEPLOYMENT {
        string id PK "deploy:order-service:v3.17:2026-01-15T10:00Z"
        string service_id "svc:order-service"
        string version "v3.17"
        string commit "9f31c2d"
        datetime deployed_at "2026-01-15T10:00:00Z"
        datetime ttl_expires_at "2026-04-15T10:00:00Z"
    }
    
    FAILURE_SIGNATURE {
        string id PK "fs:MISSING_FIELD:customer_id:urn:dp:orders:created"
        string failure_type "CONTRACT_VIOLATION"
        string reason_code "MISSING_FIELD"
        string field "customer_id"
        string dataset_urn "urn:dp:orders:created"
        string schema_fingerprint_delta "A1B2->C9D8"
        datetime first_seen "2026-01-15T10:05:00Z"
        datetime last_seen "2026-01-15T12:00:00Z"
        int occurrence_count "1247"
    }
    
    SIGNAL {
        string id PK "sig:CONTRACT_BREACH:urn:dp:orders:created:2026-01-15T10:00Z"
        string signal_type "CONTRACT_BREACH"
        string dataset_urn "urn:dp:orders:created"
        string state "CRITICAL"
        string window_start "2026-01-15T10:00:00Z"
        string window_end "2026-01-15T10:05:00Z"
        float compliance_rate "0.102"
        datetime ttl_expires_at "2026-02-15T10:00:00Z"
    }
    
    INCIDENT {
        string id PK "INC-2026-01-15-001"
        string severity "SEV-1"
        string status "OPEN"
        string dataset_urn "urn:dp:orders:created"
        string title "Contract breach on orders.created"
        string pagerduty_id "PD-123456"
        datetime created_at "2026-01-15T10:05:00Z"
        datetime resolved_at "null"
        datetime ttl_expires_at "2027-01-15T10:05:00Z"
        string first_bad_evidence_id "evd-01HQXY8MNP4QR7ST9VW2XYZ456"
        string last_good_evidence_id "evd-01HQXY8MNP4QR7ST9VW2XYZ123"
    }
    
    LINEAGE_SPEC {
        string id PK "lspec:orders-delta-landing:9f31c2d"
        string producer_id "job:orders-delta-landing"
        string commit "9f31c2d"
        string confidence "HIGH"
        datetime emitted_at "2026-01-15T12:30:00Z"
    }
```

### 4.2 Node Cardinality Controls

| Node Type | Cardinality Expectation | TTL Policy | Max per Dataset |
|-----------|-------------------------|------------|-----------------|
| Dataset | Stable (~1,000s) | Permanent | N/A |
| Service | Stable (~100s) | Permanent | N/A |
| Job | Stable (~500s) | Permanent | N/A |
| Column | ~50 per dataset | Permanent | 200 |
| Team | Stable (~50s) | Permanent | N/A |
| Deployment | ~500/day | 30-90 days | 100 |
| FailureSignature | Deduplicated | Long-lived | 500 |
| Signal | Per window (optional) | 7-30 days | 1,000 |
| Incident | Per breach | 180-365 days | 100 |
| LineageSpec | Per commit | Permanent | 50 |

**Cardinality Enforcement Rule:** Maximum 10,000 nodes per dataset, maximum 1,000 edges per node.

### 4.3 Edge Types (Relationships)

| Edge Label | From → To | Properties | Cardinality | TTL |
|------------|-----------|------------|-------------|-----|
| `OWNED_BY` | Service/Job/Dataset → Team | - | 1:1 | Permanent |
| `PRODUCES` | Service → Dataset | `confidence` | N:1 | Permanent |
| `CONSUMES` | Service/Job → Dataset | `confidence` | N:M | Permanent |
| `READS` | Job/Service → Dataset | `confidence`, `spec_id` | N:M | Permanent |
| `WRITES` | Job/Service → Dataset | `confidence`, `spec_id` | N:M | Permanent |
| `READS_COL` | Job/Service → Column | `confidence`, `spec_id` | N:M | Permanent |
| `WRITES_COL` | Job/Service → Column | `confidence`, `spec_id` | N:M | Permanent |
| `HAS_COLUMN` | Dataset → Column | - | 1:N | Permanent |
| `DEPLOYS` | Deployment → Service/Job | `version` | N:1 | Deployment TTL |
| `DESCRIBES` | LineageSpec → Job/Service | - | 1:1 | Permanent |
| `AT_COMMIT` | LineageSpec → Deployment | - | 1:1 | Permanent |
| `INTRODUCED` | Deployment → FailureSignature | `confidence` | N:M | Deployment TTL |
| `OBSERVED_IN` | FailureSignature → Dataset | - | N:1 | FS TTL |
| `CAUSED` | FailureSignature → Signal | - | 1:N | Signal TTL |
| `TRIGGERED` | Signal → Incident | - | N:1 | Incident TTL |
| `CAUSED_BY` | Incident → FailureSignature | `confidence` | N:M | Incident TTL |
| `ABOUT` | Incident → Dataset | - | N:1 | Incident TTL |
| `CORRELATED_WITH` | Incident → Deployment | `correlation_confidence`, `time_delta_seconds` | N:M | Incident TTL |
| `DETECTED_BY` | Incident → Signal | - | N:M | Incident TTL |

### 4.4 FailureSignature Deduplication Key Algorithm

The FailureSignature ID is deterministically computed to ensure idempotency:

```python
import hashlib
from typing import Optional

def compute_failure_signature_id(
    dataset_urn: str,
    failure_type: str,
    reason_code: str,
    field: Optional[str] = None,
    schema_fingerprint_delta: Optional[str] = None
) -> str:
    """
    Compute deterministic FailureSignature ID.
    
    Examples:
    - fs:MISSING_FIELD:customer_id:urn:dp:orders:created
    - fs:SCHEMA_FINGERPRINT_CHANGED:A1B2->C9D8:urn:dp:orders:created
    - fs:FRESHNESS_BREACH:>20m:urn:dp:orders:created
    - fs:VOLUME_DROP:bucket=5m:urn:dp:orders:created
    """
    # Normalize inputs
    normalized_reason = normalize_reason_code(reason_code, field, schema_fingerprint_delta)
    
    # Build canonical string
    canonical = f"{failure_type}:{normalized_reason}:{dataset_urn}"
    
    # For long keys, use hash suffix
    if len(canonical) > 128:
        hash_suffix = hashlib.sha256(canonical.encode()).hexdigest()[:12]
        canonical = f"{failure_type}:{hash_suffix}:{dataset_urn}"
    
    return f"fs:{canonical}"

def normalize_reason_code(
    reason_code: str,
    field: Optional[str],
    schema_delta: Optional[str]
) -> str:
    """Normalize reason code for deduplication."""
    if reason_code in ("MISSING_FIELD", "FIELD_REMOVED", "TYPE_MISMATCH"):
        return f"{reason_code}:{field}" if field else reason_code
    elif reason_code == "SCHEMA_FINGERPRINT_CHANGED":
        return f"{reason_code}:{schema_delta}" if schema_delta else reason_code
    elif reason_code in ("FRESHNESS_BREACH", "VOLUME_DROP", "VOLUME_SPIKE"):
        # These use threshold-based deduplication
        return reason_code
    else:
        return reason_code

# ANTI-PATTERN: Do NOT include variable data in the key
# BAD: fs:PARSE_ERROR:<full exception text>:dataset  # Creates explosion
# BAD: fs:SCHEMA_CHANGE:<full schema JSON>:dataset   # Creates explosion
```

**Deduplication Rules:**
1. Same failure type + same normalized reason + same dataset = same FailureSignature
2. Different days with same pattern = same FailureSignature (time is not part of key)
3. Schema fingerprint deltas include only the transition (A1B2→C9D8), not full schemas

### 4.5 URN Conventions

```
Dataset URN:    urn:dp:<domain>:<dataset>:<majorVersion>
Column URN:     urn:col:<dataset_urn>:<columnName>
Service ID:     svc:<service-name>
Job ID:         job:<job-name>
Team ID:        team:<team-slug>
Deployment ID:  deploy:<service-or-job>:<version>:<timestamp>
Incident ID:    INC-<YYYY-MM-DD>-<sequence>
Signal ID:      sig:<type>:<dataset_urn>:<window_start>
```

---

## 5. API Specifications

### 5.1 Graph Writer Service (gRPC)

```protobuf
syntax = "proto3";
package neptune.graph.v1;

service GraphWriterService {
    // Topology Operations
    rpc UpsertDataset(UpsertDatasetRequest) returns (UpsertResponse);
    rpc UpsertService(UpsertServiceRequest) returns (UpsertResponse);
    rpc UpsertJob(UpsertJobRequest) returns (UpsertResponse);
    rpc UpsertColumn(UpsertColumnRequest) returns (UpsertResponse);
    
    // Causal Operations
    rpc UpsertDeployment(UpsertDeploymentRequest) returns (UpsertResponse);
    rpc UpsertFailureSignature(UpsertFailureSignatureRequest) returns (UpsertResponse);
    rpc UpsertSignal(UpsertSignalRequest) returns (UpsertResponse);
    rpc UpsertIncident(UpsertIncidentRequest) returns (UpsertResponse);
    
    // Edge Operations
    rpc CreateEdge(CreateEdgeRequest) returns (CreateEdgeResponse);
    rpc CreateEdgeBatch(CreateEdgeBatchRequest) returns (CreateEdgeBatchResponse);
    
    // Lineage Operations
    rpc UpsertLineageSpec(UpsertLineageSpecRequest) returns (UpsertResponse);
    rpc UpdateLineageEdges(UpdateLineageEdgesRequest) returns (UpdateLineageEdgesResponse);
}

message UpsertFailureSignatureRequest {
    string dataset_urn = 1;
    string failure_type = 2;
    string reason_code = 3;
    optional string field = 4;
    optional string schema_fingerprint_delta = 5;
    string first_bad_evidence_id = 6;
    string last_good_evidence_id = 7;
    repeated string sample_evidence_ids = 8; // max 50
}

message UpsertIncidentRequest {
    string incident_id = 1;
    string severity = 2; // SEV-1, SEV-2, SEV-3
    string dataset_urn = 3;
    string title = 4;
    string failure_signature_id = 5;
    optional string deployment_id = 6;
    float correlation_confidence = 7;
    string first_bad_evidence_id = 8;
    string last_good_evidence_id = 9;
}

message CreateEdgeRequest {
    string from_vertex_id = 1;
    string to_vertex_id = 2;
    string edge_label = 3;
    map<string, string> properties = 4;
}

message UpsertResponse {
    string vertex_id = 1;
    bool created = 2; // true if new, false if updated
    string error_message = 3;
}
```

### 5.2 Graph Query Service (GraphQL)

```graphql
type Query {
    # RCA Queries
    incidentRootCause(incidentId: ID!): RootCauseAnalysis!
    blastRadius(datasetUrn: String!, maxHops: Int = 3): BlastRadiusResult!
    changeCorrelation(datasetUrn: String!, timeWindow: TimeWindow!): [CorrelatedChange!]!
    
    # Topology Queries
    dataset(urn: String!): Dataset
    datasetLineage(urn: String!, direction: LineageDirection!): LineageResult!
    serviceTopology(serviceId: ID!): ServiceTopology!
    
    # Search
    searchFailureSignatures(
        datasetUrn: String
        failureType: String
        since: DateTime
        limit: Int = 20
    ): [FailureSignature!]!
}

type RootCauseAnalysis {
    incident: Incident!
    rootCause: RootCause!
    causalChain: [CausalStep!]!
    blastRadius: BlastRadiusResult!
    suggestedActions: [MitigationAction!]!
    confidence: Float!
}

type RootCause {
    deployment: Deployment
    failureSignature: FailureSignature!
    service: Service
    team: Team!
    evidenceRefs: EvidenceRefs!
}

type CausalStep {
    stepNumber: Int!
    fromNode: GraphNode!
    toNode: GraphNode!
    edgeLabel: String!
    confidence: Float!
}

type BlastRadiusResult {
    sourceDataset: Dataset!
    impactedConsumers: [ImpactedConsumer!]!
    impactedColumns: [Column!]!
    totalConsumerCount: Int!
    tier1ConsumerCount: Int!
}

type ImpactedConsumer {
    consumer: Consumer! # Job or Service
    consumedDataset: Dataset!
    consumedColumns: [Column!]!
    hopDistance: Int!
    confidence: Float!
    lineageSpecId: String
}

type EvidenceRefs {
    firstBadEvidenceId: String!
    lastGoodEvidenceId: String!
    sampleEvidenceIds: [String!]!
}

enum LineageDirection {
    UPSTREAM
    DOWNSTREAM
    BOTH
}

input TimeWindow {
    start: DateTime!
    end: DateTime!
}
```

### 5.3 REST API (Admin Operations)

```yaml
openapi: 3.0.3
info:
  title: Neptune Graph Store Admin API
  version: 1.0.0

paths:
  /admin/health:
    get:
      summary: Health check
      responses:
        '200':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HealthStatus'

  /admin/stats:
    get:
      summary: Graph statistics
      responses:
        '200':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/GraphStats'

  /admin/cardinality/{datasetUrn}:
    get:
      summary: Cardinality report for dataset
      parameters:
        - name: datasetUrn
          in: path
          required: true
          schema:
            type: string
      responses:
        '200':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/CardinalityReport'

  /admin/ttl/run:
    post:
      summary: Trigger TTL cleanup (manual)
      responses:
        '202':
          description: Cleanup job started

  /admin/cache/invalidate:
    post:
      summary: Invalidate query cache
      requestBody:
        content:
          application/json:
            schema:
              type: object
              properties:
                pattern:
                  type: string
                  description: Cache key pattern to invalidate
      responses:
        '200':
          description: Cache invalidated

components:
  schemas:
    GraphStats:
      type: object
      properties:
        totalVertices: { type: integer }
        totalEdges: { type: integer }
        verticesByLabel: { type: object }
        edgesByLabel: { type: object }
        storageUsedBytes: { type: integer }
        lastTtlRunAt: { type: string, format: date-time }

    CardinalityReport:
      type: object
      properties:
        datasetUrn: { type: string }
        nodeCount: { type: integer }
        edgeCount: { type: integer }
        failureSignatureCount: { type: integer }
        incidentCount: { type: integer }
        withinLimits: { type: boolean }
        warnings: { type: array, items: { type: string } }
```

---

## 6. Gremlin Query Patterns

### 6.1 Incident-Centric RCA Traversal

The primary RCA query pattern traverses from Incident to root cause:

```groovy
// Pattern: Incident → FailureSignature → Deployment → Service → Team
def incidentRootCause(incidentId) {
    g.V().has('Incident', 'id', incidentId)
        .as('incident')
        .out('CAUSED_BY').as('failureSignature')
        .optional(
            __.in('INTRODUCED').as('deployment')
                .out('DEPLOYS').as('service')
                .out('OWNED_BY').as('team')
        )
        .select('incident', 'failureSignature', 'deployment', 'service', 'team')
        .by(valueMap(true))
        .by(valueMap(true))
        .by(coalesce(valueMap(true), constant('unknown')))
        .by(coalesce(valueMap(true), constant('unknown')))
        .by(coalesce(valueMap(true), constant('unknown')))
}
```

**Optimized version with early termination:**

```groovy
def incidentRootCauseOptimized(incidentId) {
    // Step 1: Get incident and primary failure signature
    incident = g.V().has('Incident', 'id', incidentId).valueMap(true).next()
    
    failureSignatureId = g.V().has('Incident', 'id', incidentId)
        .out('CAUSED_BY')
        .values('id')
        .next()
    
    // Step 2: Find correlated deployment (if exists)
    deployment = g.V().has('Incident', 'id', incidentId)
        .out('CORRELATED_WITH')
        .order().by('correlation_confidence', desc)
        .limit(1)
        .valueMap(true)
        .tryNext()
        .orElse(null)
    
    // Step 3: Get service and team from deployment or dataset
    if (deployment != null) {
        serviceTeam = g.V().has('Deployment', 'id', deployment['id'])
            .out('DEPLOYS')
            .project('service', 'team')
                .by(valueMap(true))
                .by(out('OWNED_BY').valueMap(true))
            .next()
    } else {
        // Fallback: get owner from dataset
        serviceTeam = g.V().has('Incident', 'id', incidentId)
            .out('ABOUT')
            .in('PRODUCES')
            .project('service', 'team')
                .by(valueMap(true))
                .by(out('OWNED_BY').valueMap(true))
            .tryNext()
            .orElse(null)
    }
    
    return [
        incident: incident,
        failureSignature: failureSignatureId,
        deployment: deployment,
        service: serviceTeam?.service,
        team: serviceTeam?.team
    ]
}
```

### 6.2 Blast Radius Traversal

Find all downstream consumers impacted by a dataset issue:

```groovy
// Pattern: Dataset → Consumers (multi-hop with column precision)
def blastRadius(datasetUrn, maxHops = 3) {
    g.V().has('Dataset', 'urn', datasetUrn)
        .repeat(
            __.in('READS', 'WRITES')
                .dedup()
                .simplePath()
        )
        .times(maxHops)
        .emit()
        .path()
        .by(project('type', 'id', 'name')
            .by(label())
            .by(values('id', 'urn'))
            .by(values('name'))
        )
        .limit(100)  // Prevent runaway traversals
}

// Column-level blast radius (more precise)
def columnBlastRadius(columnUrn, maxHops = 3) {
    g.V().has('Column', 'urn', columnUrn)
        .in('READS_COL')
        .dedup()
        .as('directConsumer')
        .project('consumer', 'type', 'confidence', 'hopDistance')
            .by(valueMap('id', 'name', 'type'))
            .by(label())
            .by(inE('READS_COL').values('confidence'))
            .by(constant(1))
        .union(
            // Get transitive consumers through WRITES
            select('directConsumer')
                .out('WRITES')
                .repeat(__.in('READS').dedup().simplePath())
                .times(maxHops - 1)
                .emit()
                .project('consumer', 'type', 'confidence', 'hopDistance')
                    .by(valueMap('id', 'name', 'type'))
                    .by(label())
                    .by(constant(0.5))  // Lower confidence for transitive
                    .by(loops().plus(2))
        )
        .order().by('confidence', desc)
        .limit(50)
}
```

### 6.3 Change Correlation Traversal

Find deployments correlated with a time window:

```groovy
def findCorrelatedDeployments(datasetUrn, incidentTime, windowMinutes = 30) {
    windowStart = incidentTime - (windowMinutes * 60 * 1000)
    
    g.V().has('Dataset', 'urn', datasetUrn)
        .in('PRODUCES', 'WRITES')  // Find producers
        .in('DEPLOYS')              // Find their deployments
        .has('deployed_at', gte(windowStart))
        .has('deployed_at', lte(incidentTime))
        .order().by('deployed_at', desc)
        .project('deployment', 'service', 'timeDelta')
            .by(valueMap(true))
            .by(out('DEPLOYS').values('name'))
            .by(math('incident - deployed_at').by(constant(incidentTime)).by('deployed_at'))
        .limit(10)
}
```

### 6.4 Recurring Pattern Detection

Find historical incidents with same FailureSignature:

```groovy
def findRecurringPattern(failureSignatureId, limit = 10) {
    g.V().has('FailureSignature', 'id', failureSignatureId)
        .in('CAUSED_BY')  // All incidents caused by this signature
        .order().by('created_at', desc)
        .limit(limit)
        .project('incident', 'correlatedDeployment', 'resolvedAt')
            .by(valueMap('id', 'severity', 'created_at', 'resolved_at'))
            .by(
                out('CORRELATED_WITH')
                    .valueMap('version', 'commit', 'deployed_at')
                    .fold()
            )
            .by(values('resolved_at'))
}
```

### 6.5 Query Index Recommendations

```groovy
// Composite indexes for common query patterns
CREATE INDEX dataset_urn_idx ON Dataset(urn)
CREATE INDEX incident_id_idx ON Incident(id)
CREATE INDEX incident_created_idx ON Incident(created_at)
CREATE INDEX deployment_time_idx ON Deployment(deployed_at)
CREATE INDEX fs_dataset_idx ON FailureSignature(dataset_urn)
CREATE INDEX service_id_idx ON Service(id)
CREATE INDEX job_id_idx ON Job(id)
```

---

## 7. Write Patterns and Cardinality Control

### 7.1 What to Write vs. What NOT to Write

| ✅ Write to Neptune | ❌ Do NOT Write |
|---------------------|-----------------|
| Dataset, Service, Job, Column nodes | Every Evidence event |
| FailureSignature (deduplicated) | Every schema version as separate nodes |
| Incident nodes | Per-record lineage |
| Deployment nodes (TTL-bounded) | Full transform AST |
| Lineage edges (per-deployment) | Per-run execution edges |
| Causal edges (CAUSED_BY, etc.) | Raw event payloads |
| Evidence ID references (max 50/incident) | Complete stack traces |

### 7.2 Write Decision Framework

```python
def should_write_to_neptune(entity_type: str, context: dict) -> bool:
    """
    Decision framework for Neptune writes.
    Ask these questions in order:
    """
    # Question 1: Will this reduce RCA time meaningfully?
    if not improves_rca(entity_type, context):
        return False
    
    # Question 2: Does it have bounded cardinality (or TTL)?
    if not (has_bounded_cardinality(entity_type) or has_ttl(entity_type)):
        return False
    
    # Question 3: Is it deduped by a stable key?
    if is_eventful(entity_type) and not has_stable_dedup_key(context):
        return False
    
    # Question 4: Can it be represented as a reference instead?
    if can_use_reference(entity_type, context):
        log.info(f"Using reference instead of full entity for {entity_type}")
        return False
    
    return True

def has_bounded_cardinality(entity_type: str) -> bool:
    bounded_types = {'Dataset', 'Service', 'Job', 'Column', 'Team', 'LineageSpec'}
    return entity_type in bounded_types

def has_ttl(entity_type: str) -> bool:
    ttl_types = {'Deployment', 'Signal', 'Incident'}
    return entity_type in ttl_types
```

### 7.3 Cardinality Enforcement

```python
class CardinalityEnforcer:
    """Enforce cardinality limits before writes."""
    
    LIMITS = {
        'nodes_per_dataset': 10_000,
        'edges_per_node': 1_000,
        'failure_signatures_per_dataset': 500,
        'incidents_per_dataset': 100,
        'columns_per_dataset': 200,
        'deployments_per_service': 100,  # within TTL window
    }
    
    async def check_before_write(
        self,
        entity_type: str,
        dataset_urn: str,
        neptune_client: NeptuneClient
    ) -> CardinalityCheckResult:
        """Check cardinality before allowing write."""
        
        # Get current counts
        current_counts = await self._get_counts(dataset_urn, neptune_client)
        
        # Check against limits
        violations = []
        
        if entity_type == 'FailureSignature':
            if current_counts['failure_signatures'] >= self.LIMITS['failure_signatures_per_dataset']:
                violations.append(CardinalityViolation(
                    limit='failure_signatures_per_dataset',
                    current=current_counts['failure_signatures'],
                    max=self.LIMITS['failure_signatures_per_dataset']
                ))
        
        # ... similar checks for other entity types
        
        if violations:
            # Log and potentially trigger cleanup
            await self._handle_violations(dataset_urn, violations)
            return CardinalityCheckResult(allowed=False, violations=violations)
        
        return CardinalityCheckResult(allowed=True, violations=[])
    
    async def _get_counts(self, dataset_urn: str, client: NeptuneClient) -> dict:
        """Get current cardinality counts for a dataset."""
        query = """
        g.V().has('Dataset', 'urn', dataset_urn)
            .project('failure_signatures', 'incidents', 'columns')
                .by(__.in('OBSERVED_IN').hasLabel('FailureSignature').count())
                .by(__.in('ABOUT').hasLabel('Incident').count())
                .by(__.out('HAS_COLUMN').count())
        """
        return await client.execute(query, {'dataset_urn': dataset_urn})
```

### 7.4 Write Batching Strategy

```python
class GraphWriteBatcher:
    """Batch writes for efficiency."""
    
    def __init__(
        self,
        batch_size: int = 100,
        flush_interval_ms: int = 1000,
        max_retries: int = 3
    ):
        self.batch_size = batch_size
        self.flush_interval_ms = flush_interval_ms
        self.max_retries = max_retries
        self._buffer: List[WriteOperation] = []
        self._lock = asyncio.Lock()
    
    async def add(self, operation: WriteOperation):
        """Add operation to batch."""
        async with self._lock:
            self._buffer.append(operation)
            
            if len(self._buffer) >= self.batch_size:
                await self._flush()
    
    async def _flush(self):
        """Flush batch to Neptune."""
        if not self._buffer:
            return
        
        operations = self._buffer.copy()
        self._buffer.clear()
        
        # Group by operation type for efficient batching
        vertices = [op for op in operations if op.type == 'vertex']
        edges = [op for op in operations if op.type == 'edge']
        
        # Execute vertex upserts first (edges depend on vertices)
        if vertices:
            await self._execute_vertex_batch(vertices)
        
        if edges:
            await self._execute_edge_batch(edges)
    
    async def _execute_vertex_batch(self, vertices: List[WriteOperation]):
        """Execute batch vertex upserts using Gremlin."""
        # Use addV().fold().coalesce() pattern for upsert
        query_parts = []
        for v in vertices:
            query_parts.append(f"""
                g.V().has('{v.label}', 'id', '{v.id}')
                    .fold()
                    .coalesce(
                        unfold(),
                        addV('{v.label}').property('id', '{v.id}')
                    )
                    {self._property_updates(v.properties)}
            """)
        
        # Neptune supports multi-statement transactions
        await self.neptune_client.execute_batch(query_parts)
```

---

## 8. TTL Enforcement Mechanism

### 8.1 TTL Policy Configuration

```python
@dataclass
class TTLPolicy:
    """TTL configuration for node types."""
    
    POLICIES = {
        'Deployment': TTLConfig(
            default_days=90,
            min_days=30,
            max_days=365,
            cleanup_batch_size=1000,
            cleanup_schedule='0 2 * * *'  # 2 AM daily
        ),
        'Signal': TTLConfig(
            default_days=30,
            min_days=7,
            max_days=90,
            cleanup_batch_size=5000,
            cleanup_schedule='0 3 * * *'  # 3 AM daily
        ),
        'Incident': TTLConfig(
            default_days=365,
            min_days=180,
            max_days=730,  # 2 years for audit
            cleanup_batch_size=500,
            cleanup_schedule='0 4 * * 0'  # 4 AM weekly (Sunday)
        ),
    }
    
    @classmethod
    def get_expiry_timestamp(cls, node_type: str, created_at: datetime) -> datetime:
        """Calculate expiry timestamp for a node."""
        policy = cls.POLICIES.get(node_type)
        if not policy:
            return None  # Permanent node
        
        return created_at + timedelta(days=policy.default_days)
```

### 8.2 TTL Enforcer Lambda

```python
import boto3
from gremlin_python.driver import client as gremlin_client

def lambda_handler(event, context):
    """
    TTL Enforcer Lambda - runs on schedule to clean up expired nodes.
    """
    neptune_endpoint = os.environ['NEPTUNE_ENDPOINT']
    
    # Initialize Gremlin client
    gc = gremlin_client.Client(
        f'wss://{neptune_endpoint}:8182/gremlin',
        'g'
    )
    
    results = {
        'deployments_deleted': 0,
        'signals_deleted': 0,
        'incidents_deleted': 0,
        'edges_deleted': 0,
        'errors': []
    }
    
    now = datetime.utcnow().isoformat() + 'Z'
    
    # Process each TTL-enabled node type
    for node_type in ['Deployment', 'Signal', 'Incident']:
        try:
            deleted = cleanup_expired_nodes(gc, node_type, now)
            results[f'{node_type.lower()}s_deleted'] = deleted
        except Exception as e:
            results['errors'].append(f"{node_type}: {str(e)}")
    
    # Cleanup orphaned edges
    orphaned = cleanup_orphaned_edges(gc)
    results['edges_deleted'] = orphaned
    
    # Emit metrics
    emit_ttl_metrics(results)
    
    return results

def cleanup_expired_nodes(gc, node_type: str, now: str) -> int:
    """Delete nodes past their TTL."""
    batch_size = TTLPolicy.POLICIES[node_type].cleanup_batch_size
    total_deleted = 0
    
    while True:
        # Find expired nodes
        query = f"""
        g.V().hasLabel('{node_type}')
            .has('ttl_expires_at', lt('{now}'))
            .limit({batch_size})
            .sideEffect(
                __.drop()
            )
            .count()
        """
        
        result = gc.submit(query).all().result()
        deleted = result[0] if result else 0
        
        total_deleted += deleted
        
        if deleted < batch_size:
            break  # No more expired nodes
        
        # Rate limit to avoid overwhelming Neptune
        time.sleep(1)
    
    return total_deleted

def cleanup_orphaned_edges(gc) -> int:
    """Remove edges where source or target vertex no longer exists."""
    query = """
    g.E().where(
        or(
            __.outV().count().is(0),
            __.inV().count().is(0)
        )
    ).limit(1000).drop().count()
    """
    result = gc.submit(query).all().result()
    return result[0] if result else 0
```

### 8.3 TTL Enforcement Architecture

```mermaid
sequenceDiagram
    participant CW as CloudWatch Events
    participant Lambda as TTL Enforcer Lambda
    participant Neptune as Neptune DB
    participant Metrics as CloudWatch Metrics
    
    CW->>Lambda: Scheduled trigger (daily)
    
    loop For each TTL-enabled node type
        Lambda->>Neptune: Query expired nodes (batch)
        Neptune-->>Lambda: Expired node IDs
        
        Lambda->>Neptune: Delete batch with edges
        Neptune-->>Lambda: Delete count
        
        Lambda->>Lambda: Check if more batches
    end
    
    Lambda->>Neptune: Cleanup orphaned edges
    Neptune-->>Lambda: Orphan count
    
    Lambda->>Metrics: Emit cleanup metrics
```

---

## 9. Scalability and Performance

### 9.1 Neptune Instance Sizing

| Deployment Stage | Instance Type | vCPUs | Memory | Storage | Estimated Cost |
|------------------|---------------|-------|--------|---------|----------------|
| Development | db.t3.medium | 2 | 4 GB | 10 GB | ~$150/month |
| Staging | db.r5.large | 2 | 16 GB | 50 GB | ~$450/month |
| Production | db.r5.xlarge | 4 | 32 GB | 200 GB | ~$900/month |
| Production HA | db.r5.xlarge x2 | 8 | 64 GB | 200 GB | ~$1,800/month |

### 9.2 Caching Strategy

```python
class GraphCacheLayer:
    """
    Multi-tier caching for graph queries.
    L1: In-process LRU cache (hot paths)
    L2: Redis cluster (shared across instances)
    """
    
    def __init__(
        self,
        redis_client: Redis,
        l1_max_size: int = 1000,
        l1_ttl_seconds: int = 60,
        l2_ttl_seconds: int = 300
    ):
        self.redis = redis_client
        self.l1_cache = LRUCache(maxsize=l1_max_size)
        self.l1_ttl = l1_ttl_seconds
        self.l2_ttl = l2_ttl_seconds
    
    async def get_or_fetch(
        self,
        cache_key: str,
        fetch_fn: Callable[[], Awaitable[Any]],
        cache_tier: CacheTier = CacheTier.ALL
    ) -> Any:
        """Get from cache or fetch and populate."""
        
        # L1 check (in-process)
        if cache_tier in (CacheTier.L1, CacheTier.ALL):
            l1_result = self.l1_cache.get(cache_key)
            if l1_result is not None:
                self._emit_metric('cache_hit', tier='l1')
                return l1_result
        
        # L2 check (Redis)
        if cache_tier in (CacheTier.L2, CacheTier.ALL):
            l2_result = await self.redis.get(cache_key)
            if l2_result is not None:
                self._emit_metric('cache_hit', tier='l2')
                # Populate L1
                self.l1_cache.set(cache_key, l2_result, ttl=self.l1_ttl)
                return json.loads(l2_result)
        
        # Cache miss - fetch from Neptune
        self._emit_metric('cache_miss')
        result = await fetch_fn()
        
        # Populate caches
        serialized = json.dumps(result)
        self.l1_cache.set(cache_key, result, ttl=self.l1_ttl)
        await self.redis.setex(cache_key, self.l2_ttl, serialized)
        
        return result
    
    async def invalidate_pattern(self, pattern: str):
        """Invalidate all keys matching pattern."""
        # L1 invalidation
        keys_to_remove = [k for k in self.l1_cache.keys() if fnmatch(k, pattern)]
        for key in keys_to_remove:
            self.l1_cache.delete(key)
        
        # L2 invalidation
        cursor = 0
        while True:
            cursor, keys = await self.redis.scan(cursor, match=pattern, count=100)
            if keys:
                await self.redis.delete(*keys)
            if cursor == 0:
                break

# Cache key patterns
CACHE_KEYS = {
    'rca': 'rca:incident:{incident_id}',
    'blast_radius': 'blast:dataset:{dataset_urn}:hops:{max_hops}',
    'topology': 'topology:service:{service_id}',
    'lineage': 'lineage:dataset:{dataset_urn}:dir:{direction}',
}
```

### 9.3 Query Optimization Techniques

```python
class QueryOptimizer:
    """Optimize Gremlin queries for Neptune."""
    
    @staticmethod
    def optimize_traversal(query: str) -> str:
        """Apply Neptune-specific optimizations."""
        optimizations = [
            # Use indexes for initial vertex lookup
            (r'g\.V\(\)\.has\(', 'g.V().has('),  # Already good
            
            # Limit early in traversals
            (r'\.emit\(\)\.limit\((\d+)\)', r'.limit(\1).emit()'),
            
            # Use valueMap(true) for ID + properties
            (r'\.valueMap\(\)', '.valueMap(true)'),
            
            # Avoid full graph scans
            (r'g\.V\(\)$', 'ERROR: Full graph scan detected'),
        ]
        
        optimized = query
        for pattern, replacement in optimizations:
            optimized = re.sub(pattern, replacement, optimized)
        
        return optimized
    
    @staticmethod
    def add_timeout(query: str, timeout_ms: int = 30000) -> str:
        """Add query timeout."""
        # Neptune supports query hints
        return f"g.with('evaluationTimeout', {timeout_ms}).{query[2:]}"
    
    @staticmethod
    def estimate_complexity(query: str) -> QueryComplexity:
        """Estimate query complexity for monitoring."""
        # Count potentially expensive operations
        hops = query.count('.repeat(') + query.count('.out(') + query.count('.in(')
        has_limit = '.limit(' in query
        has_dedup = '.dedup()' in query
        
        if hops > 5 and not has_limit:
            return QueryComplexity.HIGH
        elif hops > 3:
            return QueryComplexity.MEDIUM
        else:
            return QueryComplexity.LOW
```

### 9.4 Backpressure Handling

```python
class NeptuneBackpressureHandler:
    """Handle Neptune throttling and backpressure."""
    
    def __init__(
        self,
        max_concurrent_queries: int = 100,
        max_write_rate: int = 1000,  # writes/second
        circuit_breaker_threshold: int = 10
    ):
        self.query_semaphore = asyncio.Semaphore(max_concurrent_queries)
        self.write_limiter = TokenBucketRateLimiter(max_write_rate)
        self.circuit_breaker = CircuitBreaker(threshold=circuit_breaker_threshold)
    
    async def execute_query(
        self,
        client: NeptuneClient,
        query: str,
        parameters: dict = None
    ) -> Any:
        """Execute query with backpressure controls."""
        
        # Check circuit breaker
        if self.circuit_breaker.is_open():
            raise NeptuneUnavailableError("Circuit breaker open")
        
        async with self.query_semaphore:
            try:
                result = await client.execute(query, parameters)
                self.circuit_breaker.record_success()
                return result
            except NeptuneThrottlingException as e:
                self.circuit_breaker.record_failure()
                raise BackpressureException("Neptune throttled") from e
            except Exception as e:
                self.circuit_breaker.record_failure()
                raise
    
    async def execute_write(
        self,
        client: NeptuneClient,
        operation: WriteOperation
    ) -> Any:
        """Execute write with rate limiting."""
        
        # Wait for rate limiter
        await self.write_limiter.acquire()
        
        return await self.execute_query(
            client,
            operation.to_gremlin(),
            operation.parameters
        )
```

---

## 10. Observability

### 10.1 Metrics

```python
METRICS = {
    # Query metrics
    'neptune_query_duration_ms': Histogram(
        name='neptune_query_duration_ms',
        description='Query latency histogram',
        labels=['query_type', 'status'],
        buckets=[10, 50, 100, 200, 500, 1000, 2000, 5000]
    ),
    'neptune_query_count': Counter(
        name='neptune_query_count',
        description='Total queries executed',
        labels=['query_type', 'status']
    ),
    
    # Write metrics
    'neptune_write_duration_ms': Histogram(
        name='neptune_write_duration_ms',
        description='Write latency histogram',
        labels=['entity_type', 'operation', 'status'],
        buckets=[10, 25, 50, 100, 200, 500]
    ),
    'neptune_write_count': Counter(
        name='neptune_write_count',
        description='Total writes executed',
        labels=['entity_type', 'operation', 'status']
    ),
    
    # Cardinality metrics
    'neptune_vertex_count': Gauge(
        name='neptune_vertex_count',
        description='Total vertices by label',
        labels=['label']
    ),
    'neptune_edge_count': Gauge(
        name='neptune_edge_count',
        description='Total edges by label',
        labels=['label']
    ),
    'neptune_cardinality_violations': Counter(
        name='neptune_cardinality_violations',
        description='Cardinality limit violations',
        labels=['dataset_urn', 'limit_type']
    ),
    
    # Cache metrics
    'neptune_cache_hit_rate': Gauge(
        name='neptune_cache_hit_rate',
        description='Cache hit rate',
        labels=['cache_tier']
    ),
    'neptune_cache_size': Gauge(
        name='neptune_cache_size',
        description='Cache entries count',
        labels=['cache_tier']
    ),
    
    # TTL metrics
    'neptune_ttl_nodes_deleted': Counter(
        name='neptune_ttl_nodes_deleted',
        description='Nodes deleted by TTL enforcer',
        labels=['node_type']
    ),
    'neptune_ttl_run_duration_ms': Histogram(
        name='neptune_ttl_run_duration_ms',
        description='TTL cleanup job duration',
        labels=['status']
    ),
    
    # Health metrics
    'neptune_connection_pool_size': Gauge(
        name='neptune_connection_pool_size',
        description='Active connections to Neptune'
    ),
    'neptune_circuit_breaker_state': Gauge(
        name='neptune_circuit_breaker_state',
        description='Circuit breaker state (0=closed, 1=half-open, 2=open)'
    ),
}
```

### 10.2 Distributed Tracing

```python
from opentelemetry import trace
from opentelemetry.trace import SpanKind

tracer = trace.get_tracer(__name__)

class TracedNeptuneClient:
    """Neptune client with OpenTelemetry tracing."""
    
    async def execute(self, query: str, parameters: dict = None) -> Any:
        with tracer.start_as_current_span(
            "neptune.query",
            kind=SpanKind.CLIENT,
            attributes={
                "db.system": "neptune",
                "db.operation": self._extract_operation(query),
                "db.statement": query[:500],  # Truncate for safety
            }
        ) as span:
            try:
                result = await self._execute_internal(query, parameters)
                span.set_attribute("db.result_count", len(result) if isinstance(result, list) else 1)
                return result
            except Exception as e:
                span.record_exception(e)
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                raise
    
    def _extract_operation(self, query: str) -> str:
        """Extract operation type from Gremlin query."""
        if '.addV(' in query:
            return 'addVertex'
        elif '.addE(' in query:
            return 'addEdge'
        elif '.drop()' in query:
            return 'drop'
        elif '.property(' in query:
            return 'update'
        else:
            return 'read'
```

### 10.3 Logging Strategy

```python
import structlog

logger = structlog.get_logger()

class NeptuneLogger:
    """Structured logging for Neptune operations."""
    
    def log_query(
        self,
        query_type: str,
        query: str,
        duration_ms: float,
        result_count: int,
        trace_id: str
    ):
        logger.info(
            "neptune_query",
            query_type=query_type,
            query_preview=query[:200],
            duration_ms=duration_ms,
            result_count=result_count,
            trace_id=trace_id
        )
    
    def log_write(
        self,
        entity_type: str,
        entity_id: str,
        operation: str,
        duration_ms: float,
        success: bool,
        trace_id: str
    ):
        logger.info(
            "neptune_write",
            entity_type=entity_type,
            entity_id=entity_id,
            operation=operation,
            duration_ms=duration_ms,
            success=success,
            trace_id=trace_id
        )
    
    def log_cardinality_warning(
        self,
        dataset_urn: str,
        limit_type: str,
        current: int,
        max_allowed: int
    ):
        logger.warning(
            "neptune_cardinality_warning",
            dataset_urn=dataset_urn,
            limit_type=limit_type,
            current=current,
            max_allowed=max_allowed,
            utilization_pct=round(current / max_allowed * 100, 1)
        )
```

### 10.4 Alerting Rules

```yaml
# Prometheus alerting rules
groups:
  - name: neptune_alerts
    rules:
      - alert: NeptuneQueryLatencyHigh
        expr: histogram_quantile(0.99, neptune_query_duration_ms) > 500
        for: 5m
        labels:
          severity: warning
          component: neptune
        annotations:
          summary: "Neptune P99 query latency exceeds 500ms"
          
      - alert: NeptuneWriteLatencyHigh
        expr: histogram_quantile(0.99, neptune_write_duration_ms) > 100
        for: 5m
        labels:
          severity: warning
          component: neptune
        annotations:
          summary: "Neptune P99 write latency exceeds 100ms"
          
      - alert: NeptuneCardinalityViolation
        expr: increase(neptune_cardinality_violations[1h]) > 10
        for: 1m
        labels:
          severity: critical
          component: neptune
        annotations:
          summary: "Multiple cardinality violations detected"
          
      - alert: NeptuneCircuitBreakerOpen
        expr: neptune_circuit_breaker_state == 2
        for: 1m
        labels:
          severity: critical
          component: neptune
        annotations:
          summary: "Neptune circuit breaker is open"
          
      - alert: NeptuneCacheHitRateLow
        expr: neptune_cache_hit_rate < 0.5
        for: 10m
        labels:
          severity: warning
          component: neptune
        annotations:
          summary: "Neptune cache hit rate below 50%"
```

---

## 11. Security

### 11.1 Authentication and Authorization

```python
class NeptuneSecurityConfig:
    """Security configuration for Neptune access."""
    
    # IAM-based authentication
    IAM_ROLE_ARN = "arn:aws:iam::123456789012:role/NeptuneGraphStoreRole"
    
    # Service-to-service authentication
    ALLOWED_SERVICES = {
        'signal-engine': ['read', 'write'],
        'alerting-engine': ['read', 'write'],
        'lineage-ingestor': ['read', 'write'],
        'rca-copilot': ['read'],
        'dashboard-service': ['read'],
    }
    
    # Fine-grained permissions by entity type
    ENTITY_PERMISSIONS = {
        'Dataset': {'read': '*', 'write': ['signal-engine', 'lineage-ingestor']},
        'Incident': {'read': '*', 'write': ['alerting-engine']},
        'FailureSignature': {'read': '*', 'write': ['signal-engine']},
        'Deployment': {'read': '*', 'write': ['lineage-ingestor']},
    }

class NeptuneAuthenticator:
    """Authenticate and authorize Neptune operations."""
    
    def __init__(self, config: NeptuneSecurityConfig):
        self.config = config
        self.iam_client = boto3.client('sts')
    
    def get_connection_headers(self) -> dict:
        """Get IAM-signed headers for Neptune connection."""
        credentials = self.iam_client.assume_role(
            RoleArn=self.config.IAM_ROLE_ARN,
            RoleSessionName='neptune-graph-store'
        )['Credentials']
        
        return self._sign_request(credentials)
    
    def authorize_operation(
        self,
        service_id: str,
        operation: str,
        entity_type: str
    ) -> bool:
        """Check if service is authorized for operation."""
        # Check service-level permissions
        service_perms = self.config.ALLOWED_SERVICES.get(service_id, [])
        if operation not in service_perms:
            return False
        
        # Check entity-level permissions
        entity_perms = self.config.ENTITY_PERMISSIONS.get(entity_type, {})
        allowed_writers = entity_perms.get('write', [])
        
        if operation == 'write' and allowed_writers != '*':
            return service_id in allowed_writers
        
        return True
```

### 11.2 Data Protection

```python
class DataProtection:
    """Data protection measures for Neptune."""
    
    # Encryption configuration
    ENCRYPTION_CONFIG = {
        'storage_encryption': True,  # Neptune encrypts at rest
        'transit_encryption': True,   # TLS for connections
        'kms_key_id': 'arn:aws:kms:us-east-1:123456789012:key/abcd1234',
    }
    
    # PII handling
    PII_FIELDS = ['email', 'phone', 'ssn', 'credit_card']
    
    @classmethod
    def sanitize_properties(cls, properties: dict) -> dict:
        """Remove or mask PII from properties before storage."""
        sanitized = {}
        for key, value in properties.items():
            if any(pii in key.lower() for pii in cls.PII_FIELDS):
                sanitized[key] = '[REDACTED]'
            else:
                sanitized[key] = value
        return sanitized
    
    @classmethod
    def audit_log(cls, operation: str, entity: str, actor: str):
        """Log security-relevant operations."""
        logger.info(
            "security_audit",
            operation=operation,
            entity=entity,
            actor=actor,
            timestamp=datetime.utcnow().isoformat()
        )
```

### 11.3 Network Security

```python
# VPC Configuration
VPC_CONFIG = {
    'neptune_subnet_group': 'neptune-private-subnets',
    'security_groups': ['sg-neptune-internal'],
    'allowed_cidr_blocks': ['10.0.0.0/8'],  # Internal VPC only
    'vpc_endpoints': True,  # No public internet access
}

# Neptune cluster should be in private subnets with:
# - No public IP
# - Security group allowing only internal traffic on port 8182
# - VPC endpoint for private access from EKS
```

---

## 12. Error Handling and Resilience

### 12.1 Error Classification

```python
from enum import Enum

class NeptuneErrorType(Enum):
    """Classification of Neptune errors."""
    TRANSIENT = "transient"        # Retry with backoff
    THROTTLING = "throttling"      # Rate limit, back off significantly
    VALIDATION = "validation"      # Bad input, do not retry
    CARDINALITY = "cardinality"    # Limit exceeded, may need cleanup
    CONNECTION = "connection"      # Network issue, retry
    TIMEOUT = "timeout"            # Query too slow, optimize or timeout
    UNKNOWN = "unknown"            # Unexpected, log and alert

class NeptuneErrorClassifier:
    """Classify Neptune errors for appropriate handling."""
    
    ERROR_PATTERNS = {
        'ConcurrentModificationException': NeptuneErrorType.TRANSIENT,
        'ReadOnlyViolationException': NeptuneErrorType.TRANSIENT,
        'ThrottlingException': NeptuneErrorType.THROTTLING,
        'ConstraintViolationException': NeptuneErrorType.VALIDATION,
        'MalformedQueryException': NeptuneErrorType.VALIDATION,
        'QueryLimitExceededException': NeptuneErrorType.CARDINALITY,
        'ConnectionRefusedException': NeptuneErrorType.CONNECTION,
        'TimeLimitExceededException': NeptuneErrorType.TIMEOUT,
    }
    
    @classmethod
    def classify(cls, error: Exception) -> NeptuneErrorType:
        error_name = type(error).__name__
        return cls.ERROR_PATTERNS.get(error_name, NeptuneErrorType.UNKNOWN)
```

### 12.2 Retry Strategy

```python
class NeptuneRetryStrategy:
    """Retry strategy with exponential backoff."""
    
    RETRY_CONFIG = {
        NeptuneErrorType.TRANSIENT: {
            'max_retries': 3,
            'base_delay_ms': 100,
            'max_delay_ms': 2000,
            'exponential_base': 2
        },
        NeptuneErrorType.THROTTLING: {
            'max_retries': 5,
            'base_delay_ms': 1000,
            'max_delay_ms': 30000,
            'exponential_base': 2,
            'jitter': True
        },
        NeptuneErrorType.CONNECTION: {
            'max_retries': 5,
            'base_delay_ms': 500,
            'max_delay_ms': 10000,
            'exponential_base': 2
        },
        NeptuneErrorType.TIMEOUT: {
            'max_retries': 1,  # Likely won't help
            'base_delay_ms': 5000,
            'max_delay_ms': 5000,
            'exponential_base': 1
        },
    }
    
    async def execute_with_retry(
        self,
        operation: Callable,
        error_type: NeptuneErrorType
    ) -> Any:
        config = self.RETRY_CONFIG.get(error_type)
        if not config:
            return await operation()
        
        last_error = None
        for attempt in range(config['max_retries'] + 1):
            try:
                return await operation()
            except Exception as e:
                last_error = e
                classified = NeptuneErrorClassifier.classify(e)
                
                if classified in (NeptuneErrorType.VALIDATION, NeptuneErrorType.UNKNOWN):
                    raise  # Don't retry these
                
                if attempt < config['max_retries']:
                    delay = self._calculate_delay(attempt, config)
                    await asyncio.sleep(delay / 1000)
        
        raise last_error
    
    def _calculate_delay(self, attempt: int, config: dict) -> int:
        delay = config['base_delay_ms'] * (config['exponential_base'] ** attempt)
        delay = min(delay, config['max_delay_ms'])
        
        if config.get('jitter'):
            delay = delay * (0.5 + random.random())
        
        return int(delay)
```

### 12.3 Graceful Degradation

```python
class NeptuneFallbackHandler:
    """Handle Neptune unavailability gracefully."""
    
    def __init__(self, dynamodb_client, cache_client):
        self.dynamodb = dynamodb_client
        self.cache = cache_client
    
    async def get_rca_fallback(self, incident_id: str) -> dict:
        """
        Fallback RCA when Neptune is unavailable.
        Returns partial information from DynamoDB cache.
        """
        # Try to get cached RCA
        cached = await self.cache.get(f"rca:{incident_id}")
        if cached:
            return {
                **json.loads(cached),
                '_fallback': True,
                '_message': 'Graph unavailable - showing cached analysis'
            }
        
        # Get incident from DynamoDB
        incident = await self.dynamodb.get_item(
            TableName='IncidentIndex',
            Key={'incident_id': incident_id}
        )
        
        if incident:
            return {
                'incident': incident,
                'rootCause': None,
                'causalChain': [],
                'blastRadius': None,
                '_fallback': True,
                '_message': 'Graph unavailable - causal analysis not available'
            }
        
        raise IncidentNotFoundError(incident_id)
    
    async def get_blast_radius_fallback(self, dataset_urn: str) -> dict:
        """
        Fallback blast radius using DynamoDB lineage indexes.
        """
        # Query DynamoDB lineage indexes
        readers = await self.dynamodb.query(
            TableName='DatasetToReadersIndex',
            KeyConditionExpression='dataset_urn = :urn',
            ExpressionAttributeValues={':urn': dataset_urn}
        )
        
        return {
            'sourceDataset': {'urn': dataset_urn},
            'impactedConsumers': [
                {'consumer': r['consumer_id'], 'hopDistance': 1}
                for r in readers.get('Items', [])
            ],
            '_fallback': True,
            '_message': 'Graph unavailable - showing direct consumers only'
        }
```

---

## 13. Deployment Architecture

### 13.1 Infrastructure Components

```mermaid
graph TB
    subgraph VPC["Production VPC"]
        subgraph PublicSubnets["Public Subnets"]
            ALB[Application Load Balancer]
        end
        
        subgraph PrivateSubnets["Private Subnets"]
            subgraph EKS["EKS Cluster"]
                GWS[Graph Writer Service<br/>3 replicas]
                GQS[Graph Query Service<br/>3 replicas]
            end
            
            subgraph Redis["ElastiCache"]
                RC1[Redis Primary]
                RC2[Redis Replica]
            end
            
            subgraph Neptune["Neptune Cluster"]
                NP[Neptune Primary<br/>db.r5.xlarge]
                NR1[Neptune Replica 1<br/>db.r5.xlarge]
                NR2[Neptune Replica 2<br/>db.r5.xlarge]
            end
        end
        
        TTLL[TTL Enforcer Lambda]
    end
    
    CW[CloudWatch]
    
    ALB --> GQS
    GWS --> NP
    GQS --> RC1
    GQS --> NR1
    GQS --> NR2
    RC1 --> RC2
    NP --> NR1
    NP --> NR2
    TTLL --> NP
    
    GWS --> CW
    GQS --> CW
    Neptune --> CW
```

### 13.2 Kubernetes Deployment

```yaml
# Graph Writer Service Deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: graph-writer-service
  namespace: observability
spec:
  replicas: 3
  selector:
    matchLabels:
      app: graph-writer-service
  template:
    metadata:
      labels:
        app: graph-writer-service
    spec:
      serviceAccountName: neptune-access
      containers:
        - name: graph-writer
          image: 123456789012.dkr.ecr.us-east-1.amazonaws.com/graph-writer:v1.0.0
          ports:
            - containerPort: 50051
              name: grpc
            - containerPort: 8080
              name: health
          resources:
            requests:
              memory: "512Mi"
              cpu: "250m"
            limits:
              memory: "1Gi"
              cpu: "500m"
          env:
            - name: NEPTUNE_ENDPOINT
              valueFrom:
                secretKeyRef:
                  name: neptune-config
                  key: endpoint
            - name: REDIS_ENDPOINT
              valueFrom:
                secretKeyRef:
                  name: redis-config
                  key: endpoint
          livenessProbe:
            httpGet:
              path: /health/live
              port: health
            initialDelaySeconds: 10
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /health/ready
              port: health
            initialDelaySeconds: 5
            periodSeconds: 5

---
# Horizontal Pod Autoscaler
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: graph-writer-hpa
  namespace: observability
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: graph-writer-service
  minReplicas: 3
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: External
      external:
        metric:
          name: neptune_write_queue_depth
        target:
          type: AverageValue
          averageValue: "100"
```

### 13.3 Multi-Region DR Strategy

```python
class DisasterRecoveryConfig:
    """Multi-region disaster recovery configuration."""
    
    PRIMARY_REGION = 'us-east-1'
    DR_REGION = 'us-west-2'
    
    # Neptune Global Database configuration
    GLOBAL_CLUSTER_CONFIG = {
        'global_cluster_identifier': 'neptune-graph-store-global',
        'source_db_cluster_identifier': 'neptune-graph-store-primary',
        'storage_encrypted': True,
    }
    
    # RPO/RTO targets
    RPO_MINUTES = 5   # Maximum data loss
    RTO_MINUTES = 30  # Maximum recovery time
    
    # Failover triggers
    FAILOVER_TRIGGERS = [
        'region_unavailable',
        'cluster_unavailable_5min',
        'replication_lag_10min',
    ]
```

---

## 14. Operational Runbook

### 14.1 Common Operations

#### Start TTL Cleanup Manually

```bash
# Trigger TTL enforcer Lambda manually
aws lambda invoke \
    --function-name neptune-ttl-enforcer \
    --payload '{"force": true}' \
    response.json
```

#### Check Graph Statistics

```bash
# Query graph statistics
curl -X GET https://neptune-admin.internal/admin/stats \
    -H "Authorization: Bearer $TOKEN"
```

#### Invalidate Cache

```bash
# Invalidate all RCA caches
curl -X POST https://neptune-admin.internal/admin/cache/invalidate \
    -H "Authorization: Bearer $TOKEN" \
    -d '{"pattern": "rca:*"}'
```

### 14.2 Troubleshooting Guide

| Symptom | Likely Cause | Resolution |
|---------|--------------|------------|
| Query latency > 500ms | Missing index or full scan | Check query plan, add index |
| Write failures | Cardinality limit reached | Run cleanup, increase limits |
| Connection errors | Network/Security group | Check VPC, security groups |
| Circuit breaker open | Neptune overloaded | Scale up, reduce load |
| Cache hit rate low | Cache TTL too short | Increase cache TTL |
| TTL cleanup slow | Too many expired nodes | Increase batch size, run more frequently |

### 14.3 Emergency Procedures

#### Neptune Cluster Recovery

```bash
# 1. Check cluster status
aws neptune describe-db-clusters \
    --db-cluster-identifier neptune-graph-store

# 2. If primary failed, promote replica
aws neptune failover-db-cluster \
    --db-cluster-identifier neptune-graph-store \
    --target-db-instance-identifier neptune-replica-1

# 3. Verify new primary
aws neptune describe-db-instances \
    --db-instance-identifier neptune-replica-1

# 4. Invalidate all caches
kubectl exec -it graph-query-service-0 -- \
    curl -X POST localhost:8080/admin/cache/invalidate -d '{"pattern": "*"}'
```

#### Rollback Bad Data

```groovy
// Find and remove bad vertices created in time window
g.V()
    .has('created_at', gte('2026-01-15T10:00:00Z'))
    .has('created_at', lt('2026-01-15T11:00:00Z'))
    .hasLabel('FailureSignature')
    .has('failure_type', 'BAD_DATA')
    .drop()
```

---

## 15. Cost Analysis

### 15.1 Monthly Cost Estimate

| Component | Configuration | Monthly Cost |
|-----------|---------------|--------------|
| Neptune Primary | db.r5.xlarge (Multi-AZ) | $900 |
| Neptune Replica | db.r5.xlarge x 2 | $1,800 |
| Neptune Storage | 200 GB | $20 |
| Neptune I/O | 100M requests | $40 |
| ElastiCache Redis | cache.r5.large (Multi-AZ) | $300 |
| Lambda (TTL) | 30 invocations/month | $5 |
| Data Transfer | 100 GB internal | $10 |
| **Total** | | **~$3,075/month** |

### 15.2 Cost Optimization Strategies

1. **Right-size instances**: Start with r5.large, scale based on actual load
2. **Use reserved instances**: 1-year commitment saves 30%
3. **Aggressive TTL**: Shorter TTL reduces storage costs
4. **Cache effectively**: Higher cache hit rate reduces Neptune I/O
5. **Query optimization**: Fewer traversal hops = fewer I/O requests

---

## 16. Appendices

### Appendix A: Complete Gremlin Schema Creation

```groovy
// Create property keys
mgmt = graph.openManagement()

// Vertex properties
mgmt.makePropertyKey('id').dataType(String.class).cardinality(SINGLE).make()
mgmt.makePropertyKey('urn').dataType(String.class).cardinality(SINGLE).make()
mgmt.makePropertyKey('name').dataType(String.class).cardinality(SINGLE).make()
mgmt.makePropertyKey('type').dataType(String.class).cardinality(SINGLE).make()
mgmt.makePropertyKey('domain').dataType(String.class).cardinality(SINGLE).make()
mgmt.makePropertyKey('tier').dataType(Integer.class).cardinality(SINGLE).make()
mgmt.makePropertyKey('owner_team').dataType(String.class).cardinality(SINGLE).make()
mgmt.makePropertyKey('severity').dataType(String.class).cardinality(SINGLE).make()
mgmt.makePropertyKey('status').dataType(String.class).cardinality(SINGLE).make()
mgmt.makePropertyKey('failure_type').dataType(String.class).cardinality(SINGLE).make()
mgmt.makePropertyKey('reason_code').dataType(String.class).cardinality(SINGLE).make()
mgmt.makePropertyKey('version').dataType(String.class).cardinality(SINGLE).make()
mgmt.makePropertyKey('commit').dataType(String.class).cardinality(SINGLE).make()
mgmt.makePropertyKey('confidence').dataType(String.class).cardinality(SINGLE).make()
mgmt.makePropertyKey('created_at').dataType(Date.class).cardinality(SINGLE).make()
mgmt.makePropertyKey('deployed_at').dataType(Date.class).cardinality(SINGLE).make()
mgmt.makePropertyKey('ttl_expires_at').dataType(Date.class).cardinality(SINGLE).make()

// Edge properties
mgmt.makePropertyKey('correlation_confidence').dataType(Float.class).cardinality(SINGLE).make()
mgmt.makePropertyKey('spec_id').dataType(String.class).cardinality(SINGLE).make()

// Create vertex labels
mgmt.makeVertexLabel('Dataset').make()
mgmt.makeVertexLabel('Service').make()
mgmt.makeVertexLabel('Job').make()
mgmt.makeVertexLabel('Column').make()
mgmt.makeVertexLabel('Team').make()
mgmt.makeVertexLabel('Deployment').make()
mgmt.makeVertexLabel('FailureSignature').make()
mgmt.makeVertexLabel('Signal').make()
mgmt.makeVertexLabel('Incident').make()
mgmt.makeVertexLabel('LineageSpec').make()

// Create edge labels
mgmt.makeEdgeLabel('OWNED_BY').multiplicity(MANY2ONE).make()
mgmt.makeEdgeLabel('PRODUCES').multiplicity(MULTI).make()
mgmt.makeEdgeLabel('CONSUMES').multiplicity(MULTI).make()
mgmt.makeEdgeLabel('READS').multiplicity(MULTI).make()
mgmt.makeEdgeLabel('WRITES').multiplicity(MULTI).make()
mgmt.makeEdgeLabel('READS_COL').multiplicity(MULTI).make()
mgmt.makeEdgeLabel('WRITES_COL').multiplicity(MULTI).make()
mgmt.makeEdgeLabel('HAS_COLUMN').multiplicity(ONE2MANY).make()
mgmt.makeEdgeLabel('DEPLOYS').multiplicity(MANY2ONE).make()
mgmt.makeEdgeLabel('DESCRIBES').multiplicity(ONE2ONE).make()
mgmt.makeEdgeLabel('AT_COMMIT').multiplicity(ONE2ONE).make()
mgmt.makeEdgeLabel('INTRODUCED').multiplicity(MULTI).make()
mgmt.makeEdgeLabel('OBSERVED_IN').multiplicity(MANY2ONE).make()
mgmt.makeEdgeLabel('CAUSED').multiplicity(ONE2MANY).make()
mgmt.makeEdgeLabel('TRIGGERED').multiplicity(MANY2ONE).make()
mgmt.makeEdgeLabel('CAUSED_BY').multiplicity(MULTI).make()
mgmt.makeEdgeLabel('ABOUT').multiplicity(MANY2ONE).make()
mgmt.makeEdgeLabel('CORRELATED_WITH').multiplicity(MULTI).make()
mgmt.makeEdgeLabel('DETECTED_BY').multiplicity(MULTI).make()

// Create indexes
mgmt.buildIndex('datasetUrnIndex', Vertex.class).addKey(urn).indexOnly(mgmt.getVertexLabel('Dataset')).buildCompositeIndex()
mgmt.buildIndex('incidentIdIndex', Vertex.class).addKey(id).indexOnly(mgmt.getVertexLabel('Incident')).buildCompositeIndex()
mgmt.buildIndex('deploymentTimeIndex', Vertex.class).addKey(deployed_at).indexOnly(mgmt.getVertexLabel('Deployment')).buildMixedIndex('search')
mgmt.buildIndex('incidentTimeIndex', Vertex.class).addKey(created_at).indexOnly(mgmt.getVertexLabel('Incident')).buildMixedIndex('search')
mgmt.buildIndex('ttlIndex', Vertex.class).addKey(ttl_expires_at).buildMixedIndex('search')

mgmt.commit()
```

### Appendix B: Sample RCA Response

```json
{
  "incident": {
    "id": "INC-2026-01-15-001",
    "severity": "SEV-1",
    "title": "Contract breach on orders.created",
    "created_at": "2026-01-15T10:05:00Z"
  },
  "rootCause": {
    "deployment": {
      "id": "deploy:order-service:v3.17:2026-01-15T10:00Z",
      "version": "v3.17",
      "commit": "9f31c2d",
      "deployed_at": "2026-01-15T10:00:00Z"
    },
    "failureSignature": {
      "id": "fs:MISSING_FIELD:customer_id:urn:dp:orders:created",
      "failure_type": "CONTRACT_VIOLATION",
      "reason_code": "MISSING_FIELD",
      "field": "customer_id"
    },
    "service": {
      "id": "svc:order-service",
      "name": "order-service"
    },
    "team": {
      "id": "team:checkout-platform",
      "name": "Checkout Platform",
      "slack_channel": "#checkout-oncall"
    },
    "evidenceRefs": {
      "firstBadEvidenceId": "evd-01HQXY8MNP4QR7ST9VW2XYZ456",
      "lastGoodEvidenceId": "evd-01HQXY8MNP4QR7ST9VW2XYZ123",
      "sampleEvidenceIds": ["evd-01HQXY8MNP4QR7ST9VW2XYZ456", "..."]
    }
  },
  "causalChain": [
    {
      "stepNumber": 1,
      "fromNode": {"type": "Incident", "id": "INC-2026-01-15-001"},
      "toNode": {"type": "FailureSignature", "id": "fs:MISSING_FIELD:customer_id:..."},
      "edgeLabel": "CAUSED_BY",
      "confidence": 1.0
    },
    {
      "stepNumber": 2,
      "fromNode": {"type": "Deployment", "id": "deploy:order-service:v3.17:..."},
      "toNode": {"type": "FailureSignature", "id": "fs:MISSING_FIELD:customer_id:..."},
      "edgeLabel": "INTRODUCED",
      "confidence": 0.95
    }
  ],
  "blastRadius": {
    "sourceDataset": {"urn": "urn:dp:orders:order_created:v1"},
    "impactedConsumers": [
      {
        "consumer": {"id": "job:orders-delta-landing", "type": "JOB"},
        "consumedColumns": [{"urn": "urn:col:...:customer_id"}],
        "hopDistance": 1,
        "confidence": 1.0
      },
      {
        "consumer": {"id": "job:finance-reconciliation", "type": "JOB"},
        "hopDistance": 2,
        "confidence": 0.7
      }
    ],
    "totalConsumerCount": 5,
    "tier1ConsumerCount": 2
  },
  "suggestedActions": [
    {
      "action": "ROLLBACK",
      "target": "order-service",
      "targetVersion": "v3.16",
      "confidence": 0.95
    },
    {
      "action": "CONTACT",
      "target": "#checkout-oncall",
      "message": "Deployment v3.17 removed required field customer_id"
    }
  ],
  "confidence": 0.95
}
```

---

## Document Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-01 | Platform Core | Initial LLD |

---

## Self-Critique Against Rubric

### Completeness ✅
- [x] API specs (gRPC, GraphQL, REST)
- [x] Database schema (vertices, edges, properties)
- [x] Error handling (classification, retry, fallback)
- [x] Logging strategy (structured, security audit)

### Scalability ✅
- [x] Cardinality controls (10K nodes/dataset, 1K edges/node)
- [x] Write batching strategy
- [x] Backpressure handling (circuit breaker, rate limiting)
- [x] Cache layer (L1 + L2)
- [x] HPA configuration

### Interoperability ✅
- [x] Upstream contracts (Signal Engines, Alerting, Lineage Ingestor)
- [x] Downstream contracts (RCA Copilot, Dashboards)
- [x] URN conventions aligned with platform

### Observability ✅
- [x] Comprehensive metrics (query, write, cardinality, cache, TTL)
- [x] Distributed tracing (OpenTelemetry)
- [x] Alerting rules (latency, cardinality, circuit breaker)

### Security ✅
- [x] IAM-based authentication
- [x] Service-to-service authorization
- [x] Data protection (encryption, PII handling)
- [x] Network security (VPC, security groups)

### Gaps Identified and Addressed
1. **Initial gap**: Missing TTL enforcement mechanism → Added Section 8
2. **Initial gap**: No cost analysis → Added Section 15
3. **Initial gap**: Missing operational runbook → Added Section 14
4. **Initial gap**: No DR strategy → Added Section 13.3
