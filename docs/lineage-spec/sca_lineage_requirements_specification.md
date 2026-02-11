# SCA Element-Level Lineage Extraction: Requirements Specification

**Version:** 1.0  
**Date:** February 11, 2026  
**Status:** Draft for Review  
**Owner:** Data Platform Architecture Team

---

## Document Context

| Attribute | Value |
|-----------|-------|
| **Service Name** | External Lineage Service (ELS) |
| **Trigger Point** | Deployment Pipeline (post-build, pre-deploy) |
| **Output** | LineageSpec with code flows and attribute-level lineage |
| **Integration** | Signal Factory Knowledge Plane (Neptune + DynamoDB) |
| **Architecture Pattern** | Async with Timeout + Fallback (lineage is RCA enrichment, not a gate) |

---

## Executive Summary

This specification defines the functional and non-functional requirements for an External Lineage Service (ELS) that extracts element-level (attribute/column) lineage from source code during deployment. The service identifies discrete **code flows** within repositories—each representing a distinct data transformation path from source to sink—and produces **LineageSpec** artifacts for integration with the Signal Factory Knowledge Plane.

### Design Principles

| Principle | Description |
|-----------|-------------|
| **Non-Blocking** | Lineage extraction never blocks deployment; graceful degradation on failure |
| **Flow-Centric** | Each logical data path (source→sink) is a separate flow with its own lineage |
| **Confidence-Aware** | All lineage includes confidence scoring; never pretend certainty |
| **Idempotent** | Same input always produces same output; safe for retries |
| **Eventually Consistent** | Lineage available within 5 minutes of deployment |

---

## System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        DEPLOYMENT PIPELINE                                       │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  ┌─────────┐    ┌─────────┐    ┌─────────────────┐    ┌─────────┐    ┌────────┐│
│  │  Build  │───►│  Test   │───►│  SCA Lineage    │───►│ Deploy  │───►│ Verify ││
│  │         │    │         │    │  Extraction     │    │         │    │        ││
│  └─────────┘    └─────────┘    └────────┬────────┘    └─────────┘    └────────┘│
│                                         │                                        │
│                                         │ SYNC/ASYNC CALL                        │
│                                         ▼                                        │
│                              ┌─────────────────────┐                            │
│                              │  External Lineage   │                            │
│                              │  Service (ELS)      │                            │
│                              │                     │                            │
│                              │  • Parse code       │                            │
│                              │  • Identify flows   │                            │
│                              │  • Extract columns  │                            │
│                              │  • Return LineageSpec│                           │
│                              └──────────┬──────────┘                            │
│                                         │                                        │
│                                         ▼                                        │
│                              ┌─────────────────────┐                            │
│                              │  Kafka Topic:       │                            │
│                              │  signal_factory.    │                            │
│                              │  lineage_specs      │                            │
│                              └──────────┬──────────┘                            │
│                                         │                                        │
│                                         ▼                                        │
│                              ┌─────────────────────┐                            │
│                              │  Lineage Ingestor   │──►  Neptune + DynamoDB    │
│                              └─────────────────────┘                            │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

# Section 1: Functional Requirements

## 1.1 Core Lineage Extraction

| ID | Requirement | Description | Acceptance Criteria | Priority | Rationale |
|----|-------------|-------------|---------------------|----------|-----------|
| **FR-CORE-001** | Dataset-Level Lineage | Extract input and output datasets for each code flow | Every flow has ≥1 input OR ≥1 output dataset identified with valid URN | P0 | Minimum viable lineage for RCA blast radius |
| **FR-CORE-002** | Attribute-Level Lineage | Extract column/field references for inputs and outputs | ≥70% of columns identified for HIGH confidence flows | P0 | Enables column-level impact analysis |
| **FR-CORE-003** | Dataset URN Resolution | Map raw table/topic references to canonical Dataset URNs | 100% of known datasets mapped to `urn:dp:<domain>:<dataset>:v<major>` format | P0 | Consistent identity for graph joins |
| **FR-CORE-004** | Column URN Generation | Generate stable column URNs for each identified attribute | Column URNs follow `urn:col:<dataset_urn>:<column_name>` format | P0 | Enables column-level graph edges |
| **FR-CORE-005** | Transform Mapping | Capture input→output column relationships where determinable | Transform hints include `output_column` ← `input_columns[]` for ≥50% of derivations | P1 | Enables "which input caused this output issue" analysis |
| **FR-CORE-006** | LineageSpec Generation | Produce compliant LineageSpec JSON for each analysis | Output validates against LineageSpec v1.0 JSON schema | P0 | Contract compliance with Lineage Ingestor |
| **FR-CORE-007** | Idempotent Spec IDs | Generate deterministic `lineage_spec_id` for deduplication | Same repo + commit + flow → identical `lineage_spec_id` across retries | P0 | Prevents duplicate Neptune edges |
| **FR-CORE-008** | Multi-Flow Detection | Identify multiple distinct code flows within a single repository | Each logical data path (source→sink) identified as separate flow | P0 | Precise blast radius per flow, not per repo |
| **FR-CORE-009** | Incremental Analysis | Analyze only changed files when full repo analysis not required | Changed files provided → analysis time reduced proportionally | P1 | CI/CD time optimization |
| **FR-CORE-010** | Shared Code Attribution | Track lineage through shared modules/libraries | Flows using shared code reference common component; change to shared code flags all dependent flows | P2 | Accurate impact when utilities change |

---

## 1.2 Batch Processing Patterns

### 1.2.1 Apache Spark

| ID | Requirement | Description | Acceptance Criteria | Priority | Rationale |
|----|-------------|-------------|---------------------|----------|-----------|
| **FR-SPARK-001** | DataFrame API Parsing | Extract lineage from Spark DataFrame operations | `select()`, `withColumn()`, `join()`, `groupBy()`, `agg()` operations traced | P0 | Primary Spark API for transformations |
| **FR-SPARK-002** | Spark SQL Parsing | Extract lineage from SQL strings in `spark.sql()` | SQL parsed; SELECT columns, FROM tables, JOIN keys identified | P0 | Common pattern in Spark jobs |
| **FR-SPARK-003** | Catalyst Plan Analysis | Leverage Catalyst logical plan when available | If SparkSession metadata available, use resolved plan for HIGH confidence | P1 | Most accurate column resolution |
| **FR-SPARK-004** | Star Expansion Handling | Handle `SELECT *` patterns appropriately | If schema resolvable → expand to columns (MEDIUM confidence); else mark LOW confidence with flag | P1 | Common pattern; accuracy depends on schema access |
| **FR-SPARK-005** | Config-Driven Tables | Resolve parameterized table names | Config patterns like `${env}.table` identified; mark MEDIUM confidence if unresolvable | P1 | Environment-specific table names common |
| **FR-SPARK-006** | UDF Detection | Identify User Defined Functions and their column usage | UDF inputs identified; outputs marked as derived with LOW confidence for transform | P1 | UDFs are opaque to static analysis |
| **FR-SPARK-007** | Multi-Write Detection | Identify multiple `.write()` calls as separate flows | Each `write()` to distinct sink = separate flow in LineageSpec | P0 | Single job may write to multiple outputs |
| **FR-SPARK-008** | Partition Column Tracking | Track partition columns as implicit inputs | Partition columns in `.partitionBy()` or `WHERE` clauses captured | P2 | Partitions affect data scope |
| **FR-SPARK-009** | Delta Lake Support | Extract lineage for Delta Lake operations | `MERGE`, `UPDATE`, `DELETE` operations traced with affected columns | P1 | Delta is primary lakehouse format |
| **FR-SPARK-010** | Read Format Detection | Identify source format (parquet, delta, jdbc, kafka) | Source format captured in LineageSpec metadata | P2 | Useful for debugging and classification |

### 1.2.2 Dask

| ID | Requirement | Description | Acceptance Criteria | Priority | Rationale |
|----|-------------|-------------|---------------------|----------|-----------|
| **FR-DASK-001** | Dask DataFrame Parsing | Extract lineage from Dask DataFrame operations | Bracket notation `ddf['col']`, `.assign()`, column operations traced | P0 | Primary Dask API |
| **FR-DASK-002** | Lazy Graph Analysis | Analyze Dask task graph for column flow | Column references traced through lazy operations before `.compute()` | P1 | Dask defers execution; must trace graph |
| **FR-DASK-003** | Pandas-Like API Support | Handle pandas-compatible operations | `merge()`, `groupby()`, `apply()` with column lambda traced | P1 | Dask mirrors pandas API |
| **FR-DASK-004** | Delayed Function Handling | Trace columns through `@delayed` decorated functions | Function parameters and returns analyzed; mark MEDIUM confidence | P1 | Common Dask pattern for custom logic |
| **FR-DASK-005** | Dask-ML Pipeline Support | Extract lineage from ML pipelines | Transformer inputs/outputs identified where column names explicit | P2 | ML pipelines transform columns implicitly |
| **FR-DASK-006** | Parquet/CSV Source Detection | Identify file-based sources with schema | Source path and inferred columns captured | P1 | File-based inputs common in Dask |
| **FR-DASK-007** | Compute Boundary Detection | Identify `.compute()` calls as materialization points | Each compute with side effects (write) = potential flow boundary | P1 | Compute triggers execution |

### 1.2.3 Airflow / Orchestration

| ID | Requirement | Description | Acceptance Criteria | Priority | Rationale |
|----|-------------|-------------|---------------------|----------|-----------|
| **FR-AIR-001** | DAG Structure Extraction | Parse Airflow DAG definitions for task dependencies | Task graph extracted; dependencies mapped | P1 | DAG defines execution order |
| **FR-AIR-002** | Operator-Level Lineage | Extract dataset lineage from operator configurations | `SparkSubmitOperator`, `BigQueryOperator`, etc. inputs/outputs captured | P1 | Operators define data operations |
| **FR-AIR-003** | Delegated Job Tracing | Follow lineage into submitted jobs (Spark, Python) | If operator submits external job, that job's lineage linked | P1 | Airflow orchestrates; doesn't transform |
| **FR-AIR-004** | XCom Data Flow | Track data passed via XCom between tasks | XCom push/pull identified; data schema captured if determinable | P2 | Inter-task data passing |
| **FR-AIR-005** | Dynamic DAG Support | Handle DAG factories and dynamically generated DAGs | Config-driven DAGs analyzed per generated instance | P2 | Common enterprise pattern |
| **FR-AIR-006** | Sensor Dependency Tracking | Identify sensor-based dependencies on external datasets | Sensors waiting on files/tables captured as inputs | P2 | Sensors define implicit dependencies |

---

## 1.3 Streaming Patterns

### 1.3.1 Apache Flink

| ID | Requirement | Description | Acceptance Criteria | Priority | Rationale |
|----|-------------|-------------|---------------------|----------|-----------|
| **FR-FLINK-001** | Table API Parsing | Extract lineage from Flink Table API operations | SQL-like operations (`select`, `join`, `groupBy`) traced with columns | P0 | Table API has explicit column semantics |
| **FR-FLINK-002** | DataStream API Parsing | Extract lineage from DataStream operations | `map()`, `flatMap()`, `filter()`, `keyBy()` operations analyzed | P1 | DataStream is record-oriented; harder to trace |
| **FR-FLINK-003** | Flink SQL Support | Parse Flink SQL statements for lineage | SQL parsed; tables and columns identified | P0 | Common Flink usage pattern |
| **FR-FLINK-004** | Temporal Join Handling | Track columns in temporal/versioned joins | Join keys and versioned table references captured | P1 | Temporal joins have special semantics |
| **FR-FLINK-005** | Window Column Tracking | Identify window-related columns (rowtime, proctime) | System columns flagged as window-related inputs | P2 | Windows introduce implicit columns |
| **FR-FLINK-006** | State Schema Detection | Identify columns stored in Flink state | `ValueState`, `MapState` key/value types analyzed | P2 | State affects column flow across events |
| **FR-FLINK-007** | Side Output Detection | Track branching via SideOutputTag | Each side output = separate flow branch | P1 | Flink supports multi-output topologies |
| **FR-FLINK-008** | CDC Connector Support | Extract lineage for Debezium/CDC sources | CDC metadata columns (`op`, `ts_ms`, `before`, `after`) identified | P1 | CDC is common streaming source |
| **FR-FLINK-009** | Topology ID Correlation | Include topology/job identifiers for runtime correlation | `topology_id`, `operator_name` included in LineageSpec | P1 | Required for Evidence→Lineage join |

### 1.3.2 Spark Structured Streaming

| ID | Requirement | Description | Acceptance Criteria | Priority | Rationale |
|----|-------------|-------------|---------------------|----------|-----------|
| **FR-SSS-001** | ReadStream/WriteStream Detection | Identify streaming sources and sinks | `readStream` sources and `writeStream` sinks captured | P0 | Core streaming pattern |
| **FR-SSS-002** | Batch vs Stream Differentiation | Distinguish streaming from batch in same codebase | Streaming queries flagged with `is_streaming: true` | P1 | Same APIs; different semantics |
| **FR-SSS-003** | ForEachBatch Tracing | Trace lineage through `foreachBatch` sink functions | Lambda/function body analyzed for write operations | P1 | Common custom sink pattern |
| **FR-SSS-004** | Watermark Column Detection | Identify watermark columns as implicit inputs | `withWatermark()` column captured | P2 | Watermarks affect processing semantics |
| **FR-SSS-005** | Stateful Operation Tracking | Identify grouping keys in stateful operations | `groupBy` keys in streaming aggregations captured | P2 | State keys affect output |
| **FR-SSS-006** | Trigger Configuration Capture | Record trigger type (continuous, micro-batch) | Trigger type in LineageSpec metadata | P3 | Useful for operational context |

### 1.3.3 Kafka Streams / ksqlDB

| ID | Requirement | Description | Acceptance Criteria | Priority | Rationale |
|----|-------------|-------------|---------------------|----------|-----------|
| **FR-KAFKA-001** | ksqlDB Query Parsing | Extract lineage from ksqlDB statements | `CREATE STREAM/TABLE AS SELECT` parsed with columns | P1 | SQL-based Kafka processing |
| **FR-KAFKA-002** | KStreams Topology Parsing | Trace columns through KStreams builder operations | `stream()`, `map()`, `filter()`, `to()` chain analyzed | P1 | Java/Scala KStreams API |
| **FR-KAFKA-003** | Serde Schema Extraction | Extract column schema from serde definitions | Avro/JSON/Protobuf serde analyzed for field names | P1 | Schema defines columns |
| **FR-KAFKA-004** | Topic-to-Dataset Mapping | Map Kafka topics to Dataset URNs | Topic names resolved to `urn:dp:*` via registry lookup | P0 | Consistent identity |
| **FR-KAFKA-005** | Join Key Detection | Identify join keys in KTable joins | Join keys captured as correlation columns | P2 | Joins are common pattern |
| **FR-KAFKA-006** | Processor API Handling | Flag custom Processor implementations | Custom processors marked LOW confidence; input/output topics captured | P2 | Processors are opaque |

---

## 1.4 Service Patterns

### 1.4.1 Microservices (Spring, Go, Node.js)

| ID | Requirement | Description | Acceptance Criteria | Priority | Rationale |
|----|-------------|-------------|---------------------|----------|-----------|
| **FR-SVC-001** | API Endpoint Detection | Identify REST/GraphQL endpoints as flow entry points | Each endpoint with data output = potential flow | P0 | Services expose multiple endpoints |
| **FR-SVC-002** | Request/Response Schema | Extract column lineage from request→response transformation | Request body fields → response body fields traced | P1 | Core service transformation |
| **FR-SVC-003** | Kafka Producer Tracing | Trace columns from API request to Kafka message | HTTP payload fields → Kafka event fields mapped | P0 | Common integration pattern |
| **FR-SVC-004** | ORM Mapping Extraction | Extract column mappings from JPA/GORM/Prisma | Database columns ↔ entity fields ↔ API fields traced | P1 | ORM defines column relationships |
| **FR-SVC-005** | GraphQL Field Selection | Handle dynamic field selection in GraphQL | All possible fields captured; mark MEDIUM confidence (runtime varies) | P2 | GraphQL fields are client-selected |
| **FR-SVC-006** | Event Sourcing Support | Trace columns through event/aggregate patterns | Command → Event → Aggregate state field mappings | P2 | Event sourcing has indirect lineage |
| **FR-SVC-007** | Multi-Language Support | Support Java (Spring), Go, Node.js, Python | Framework-specific parsers for each language | P0 | Polyglot services common |
| **FR-SVC-008** | Deployment Version Correlation | Link container image tag to commit SHA | `image:tag` → `commit_sha` mapping included or resolvable | P1 | Required for runtime correlation |

### 1.4.2 Lambda / Serverless

| ID | Requirement | Description | Acceptance Criteria | Priority | Rationale |
|----|-------------|-------------|---------------------|----------|-----------|
| **FR-LAMBDA-001** | Event Trigger Detection | Identify Lambda trigger type and input schema | S3, DynamoDB, Kafka, API Gateway triggers identified with event schema | P1 | Trigger defines input structure |
| **FR-LAMBDA-002** | Handler Tracing | Trace columns through handler function | Event fields → output fields (return/write) mapped | P1 | Handler is the transformation logic |
| **FR-LAMBDA-003** | Layer Dependency Tracing | Follow lineage into Lambda layers | Shared layer code analyzed; flows reference layer functions | P2 | Layers contain shared logic |
| **FR-LAMBDA-004** | Environment Variable Handling | Resolve env-var-driven configuration | Table names, topic names from env vars resolved if determinable | P2 | Lambdas use env vars for config |
| **FR-LAMBDA-005** | Step Function Integration | Trace lineage across Step Function states | State machine definition parsed; per-state lineage linked | P2 | Step Functions orchestrate Lambdas |

---

## 1.5 Flow Identification

| ID | Requirement | Description | Acceptance Criteria | Priority | Rationale |
|----|-------------|-------------|---------------------|----------|-----------|
| **FR-FLOW-001** | Automatic Flow Detection | Identify flows without developer annotation | Flows detected based on sink operations (write, produce, emit) | P0 | Minimize developer burden |
| **FR-FLOW-002** | Flow Naming Convention | Generate consistent, meaningful flow names | Flow names follow `<repo>_<operation>_<sink>` or similar pattern | P1 | Human-readable identification |
| **FR-FLOW-003** | Flow Boundary Heuristics | Define clear rules for flow boundaries | One flow = one logical source→sink path; branches = separate flows | P0 | Consistent flow identification |
| **FR-FLOW-004** | Conditional Flow Handling | Handle if/else branches producing different outputs | Each branch with distinct output = separate flow | P1 | Conditional logic common |
| **FR-FLOW-005** | Loop/Iteration Handling | Handle flows within loops (e.g., foreach table) | Each iteration instance = separate flow if outputs differ | P2 | Dynamic DAGs, table loops |
| **FR-FLOW-006** | Developer Annotation Support | Allow optional annotations to override flow detection | `@LineageFlow(name="...")` or config file respected | P2 | Developer override when heuristics fail |
| **FR-FLOW-007** | Cross-Flow Dependency | Track dependencies between flows in same repo | Flow A writes temp table; Flow B reads it → dependency edge | P2 | Internal data sharing |
| **FR-FLOW-008** | Flow Stability Across Commits | Maintain stable flow identity across minor code changes | Flow ID stable unless flow logic fundamentally changes | P1 | Historical comparison |

---

## 1.6 Confidence & Quality

| ID | Requirement | Description | Acceptance Criteria | Priority | Rationale |
|----|-------------|-------------|---------------------|----------|-----------|
| **FR-CONF-001** | Confidence Scoring | Assign HIGH/MEDIUM/LOW confidence to each flow | Every flow has confidence level with supporting reasons | P0 | RCA must weight lineage appropriately |
| **FR-CONF-002** | HIGH Confidence Criteria | Define criteria for HIGH confidence | Static SQL, resolved DataFrame plan, explicit column references | P0 | Consistent scoring |
| **FR-CONF-003** | MEDIUM Confidence Criteria | Define criteria for MEDIUM confidence | Star expansion resolved, config-driven tables resolved, partial UDF tracing | P0 | Consistent scoring |
| **FR-CONF-004** | LOW Confidence Criteria | Define criteria for LOW confidence | Dynamic SQL, reflection, unresolvable config, opaque UDFs | P0 | Consistent scoring |
| **FR-CONF-005** | Coverage Metrics | Report column coverage percentages | `input_columns_pct` and `output_columns_pct` in LineageSpec | P1 | Quantify analysis completeness |
| **FR-CONF-006** | Unknown Column Handling | Explicitly flag columns that couldn't be resolved | Unresolved columns marked with `unresolved: true` flag | P1 | Never pretend certainty |
| **FR-CONF-007** | Analysis Error Reporting | Report parsing/analysis errors in LineageSpec | `analysis_errors[]` array with error types and locations | P1 | Debugging and improvement |
| **FR-CONF-008** | Confidence Calibration | Validate confidence against runtime accuracy | HIGH → 95%+ runtime match; MEDIUM → 75%+; LOW → 50%+ | P2 | Confidence must be meaningful |

---

## 1.7 Integration & API

| ID | Requirement | Description | Acceptance Criteria | Priority | Rationale |
|----|-------------|-------------|---------------------|----------|-----------|
| **FR-INT-001** | Synchronous API | Provide sync endpoint for direct response | `POST /v1/analyze` returns LineageSpec within timeout | P0 | Simple integration |
| **FR-INT-002** | Asynchronous API | Provide async endpoint for long-running analysis | `POST /v1/analyze/async` returns job ID; `GET /v1/jobs/{id}` returns result | P1 | Large repos may exceed sync timeout |
| **FR-INT-003** | Webhook Callback | Support callback URL for async completion | On completion, POST LineageSpec to provided callback URL | P2 | Event-driven integration |
| **FR-INT-004** | LineageSpec Publishing | Publish LineageSpec to Kafka topic | Successful analysis → publish to `signal_factory.lineage_specs` | P0 | Primary integration with Signal Factory |
| **FR-INT-005** | Schema Registry Integration | Lookup dataset schemas from Schema Registry | Schema Registry queried for column resolution (with caching) | P1 | Enables star expansion, type resolution |
| **FR-INT-006** | Dataset Registry Integration | Lookup Dataset URNs from Signal Factory registry | Raw table/topic names resolved to canonical URNs | P0 | Consistent identity |
| **FR-INT-007** | Git Repository Access | Clone/fetch repository for analysis | Support HTTPS and SSH git protocols with auth | P0 | Source code access |
| **FR-INT-008** | Changed Files Input | Accept list of changed files for incremental analysis | `changed_files[]` parameter triggers partial analysis | P1 | Optimization for CI/CD |
| **FR-INT-009** | Framework Hints | Accept framework type hints to optimize parsing | `frameworks[]` parameter selects appropriate parsers | P2 | Faster parser selection |
| **FR-INT-010** | Health Check Endpoint | Provide health check for load balancer | `GET /health` returns 200 when ready | P0 | Operational requirement |

---

# Section 2: Non-Functional Requirements

## 2.1 Performance — Latency

| ID | Requirement | Description | Target | Measurement | Priority | Rationale |
|----|-------------|-------------|--------|-------------|----------|-----------|
| **NFR-LAT-001** | P50 Response Time | Median response time for analysis | ≤ 5 seconds | End-to-end API latency | P0 | Most deployments should see minimal impact |
| **NFR-LAT-002** | P90 Response Time | 90th percentile response time | ≤ 15 seconds | End-to-end API latency | P0 | Predictable performance |
| **NFR-LAT-003** | P99 Response Time | 99th percentile response time | ≤ 30 seconds | End-to-end API latency | P0 | Worst-case acceptable delay |
| **NFR-LAT-004** | Sync Timeout | Maximum wait time for synchronous requests | 45 seconds | Client timeout setting | P0 | Prevent indefinite blocking |
| **NFR-LAT-005** | Async Completion Time | Time from request to result availability | ≤ 5 minutes | Job completion timestamp | P1 | Reasonable async SLA |
| **NFR-LAT-006** | Network Transfer Time | Time to upload code / receive response | ≤ 3 seconds for 10MB payload | Network latency measurement | P1 | Bandwidth-dependent |
| **NFR-LAT-007** | Cold Start Latency | Additional latency for first request to new parser | ≤ 10 seconds additional | First request vs subsequent | P2 | Container/parser initialization |
| **NFR-LAT-008** | Incremental Analysis Speedup | Latency reduction for incremental vs full | ≥ 60% faster for <10% changed files | Comparative measurement | P1 | Incremental optimization value |

---

## 2.2 Performance — Throughput

| ID | Requirement | Description | Target | Measurement | Priority | Rationale |
|----|-------------|-------------|--------|-------------|----------|-----------|
| **NFR-THR-001** | Sustained Request Rate | Continuous request handling capacity | 50 requests/second | Load test measurement | P0 | Normal operating capacity |
| **NFR-THR-002** | Burst Request Rate | Peak request handling capacity | 200 requests/second for 60 seconds | Burst load test | P0 | Monorepo/mass deploy scenario |
| **NFR-THR-003** | Daily Deployment Volume | Total deployments supported per day | 10,000 deployments/day | Daily aggregate | P1 | Enterprise scale |
| **NFR-THR-004** | Concurrent Analysis Jobs | Parallel analysis executions | 200 concurrent jobs | Active job count | P0 | Parallelism capacity |
| **NFR-THR-005** | Queue Depth Tolerance | Maximum queued requests before rejection | 1,000 requests | Queue size monitoring | P1 | Backpressure management |
| **NFR-THR-006** | Throughput Scaling Linearity | Throughput increase with added capacity | ≥ 80% linear scaling | Scale-out test | P1 | Efficient horizontal scaling |

---

## 2.3 Scalability

| ID | Requirement | Description | Target | Measurement | Priority | Rationale |
|----|-------------|-------------|--------|-------------|----------|-----------|
| **NFR-SCL-001** | Horizontal Scaling | Add capacity via additional instances | 5 to 50 pods dynamically | HPA configuration | P0 | Elastic capacity |
| **NFR-SCL-002** | Auto-Scaling Trigger | Automatic scale-out based on load | Scale at CPU > 70% OR queue > 100 | HPA metrics | P0 | Responsive to demand |
| **NFR-SCL-003** | Scale-Down Responsiveness | Reduce capacity when load decreases | Scale down within 10 minutes of load drop | HPA behavior | P1 | Cost optimization |
| **NFR-SCL-004** | Codebase Size Scaling | Handle varying repository sizes | Support 1KB to 100MB repositories | Max repo size tested | P0 | Diverse repo sizes |
| **NFR-SCL-005** | Flow Count Scaling | Handle repos with many flows | Support 1 to 500 flows per repository | Max flows tested | P1 | Complex repos |
| **NFR-SCL-006** | Column Count Scaling | Handle datasets with many columns | Support datasets with up to 2,000 columns | Max columns tested | P1 | Wide tables common |
| **NFR-SCL-007** | Framework Parser Isolation | Scale parsers independently | Each framework parser scales separately | Parser-specific scaling | P2 | Uneven framework usage |
| **NFR-SCL-008** | Multi-Region Deployment | Deploy across regions for locality | Support 2+ AWS regions | Regional deployment | P2 | Global CI/CD pipelines |
| **NFR-SCL-009** | Schema Cache Scaling | Cache scales with dataset count | Support 100K+ cached schemas | Cache hit rate > 90% | P1 | Avoid repeated lookups |
| **NFR-SCL-010** | Lineage Output Scaling | Handle large LineageSpec outputs | Support LineageSpec up to 10MB | Max output size | P2 | Complex repos with many flows |

---

## 2.4 Availability & Reliability

| ID | Requirement | Description | Target | Measurement | Priority | Rationale |
|----|-------------|-------------|--------|-------------|----------|-----------|
| **NFR-AVL-001** | Service Uptime | ELS availability | 99.9% (8.76 hrs downtime/year) | Uptime monitoring | P0 | High availability for deployments |
| **NFR-AVL-002** | Deployment Pipeline Impact | Pipeline success rate regardless of ELS | 100% deployments proceed | Pipeline success rate | P0 | ELS failure never blocks deploy |
| **NFR-AVL-003** | Graceful Degradation | Behavior when ELS unavailable | Deploy without lineage; emit metric | Fallback activation count | P0 | Resilient pipeline |
| **NFR-AVL-004** | Circuit Breaker | Prevent cascade failures | Open after 5 failures in 60s; reset after 60s | Circuit state changes | P0 | Failure isolation |
| **NFR-AVL-005** | Retry Policy | Automatic retry on transient failures | 3 retries with exponential backoff (1s, 2s, 4s) | Retry metrics | P0 | Handle transient issues |
| **NFR-AVL-006** | Request Timeout Handling | Handle slow/stuck requests | Timeout at 45s; return partial or error | Timeout count | P0 | Prevent blocking |
| **NFR-AVL-007** | Partial Result Acceptance | Accept incomplete analysis gracefully | Partial LineageSpec with coverage metrics preferred over failure | Partial result rate | P1 | Some lineage > no lineage |
| **NFR-AVL-008** | Queue Durability | Async queue survives restarts | SQS/Kafka queue persists requests | Message durability test | P1 | No lost requests |
| **NFR-AVL-009** | Worker Health Checks | Detect and replace unhealthy workers | Liveness probe every 30s; restart unhealthy pods | Pod restart count | P1 | Self-healing |
| **NFR-AVL-010** | Dependency Failure Handling | Handle Schema Registry / Git unavailability | Cache fallback; mark LOW confidence if deps unavailable | Dependency failure handling | P1 | External dependency resilience |
| **NFR-AVL-011** | Data Durability | No loss of completed LineageSpecs | At-least-once delivery to Kafka; idempotent processing | Message loss rate = 0 | P0 | Critical data preserved |
| **NFR-AVL-012** | Disaster Recovery | Recovery from regional failure | RPO < 1 hour; RTO < 4 hours | DR test results | P2 | Business continuity |

---

## 2.5 Consistency & Data Integrity

| ID | Requirement | Description | Target | Measurement | Priority | Rationale |
|----|-------------|-------------|--------|-------------|----------|-----------|
| **NFR-CON-001** | Idempotent Processing | Same input produces same output | Identical LineageSpec for retried requests | Idempotency test | P0 | No duplicate edges |
| **NFR-CON-002** | Lineage-Deployment Correlation | LineageSpec matches deployed commit | `commit_sha` in LineageSpec = deployed commit 100% | Correlation accuracy | P0 | RCA correctness |
| **NFR-CON-003** | Eventual Consistency | Lineage available shortly after deploy | < 5 minutes from deploy to Neptune availability | Lag measurement | P1 | Timely RCA enrichment |
| **NFR-CON-004** | Schema Compatibility | LineageSpec backward/forward compatible | Schema evolution follows Avro compatibility rules | Schema validation | P1 | Consumer compatibility |
| **NFR-CON-005** | Immutable Specs | LineageSpecs never modified after creation | No update operations; new commit = new spec | Audit verification | P0 | Audit trail integrity |
| **NFR-CON-006** | Version Tracking | Track LineageSpec schema versions | `spec_version` field in every spec | Version field presence | P0 | Schema evolution support |
| **NFR-CON-007** | URN Consistency | URNs consistent with Signal Factory registry | 100% of URNs validate against registry | URN validation rate | P0 | Graph join correctness |

---

## 2.6 Security

| ID | Requirement | Description | Target | Measurement | Priority | Rationale |
|----|-------------|-------------|--------|-------------|----------|-----------|
| **NFR-SEC-001** | Transport Encryption | All communication encrypted | TLS 1.3 for all endpoints | TLS version check | P0 | Data in transit protection |
| **NFR-SEC-002** | Authentication | Verify caller identity | mTLS or IAM role-based authentication | Auth failure rate | P0 | Prevent unauthorized access |
| **NFR-SEC-003** | Authorization | Verify caller permissions | Callers authorized for specific repos only | Authz check | P1 | Least privilege |
| **NFR-SEC-004** | Code Confidentiality | Protect source code during analysis | Code encrypted at rest; deleted after analysis | Code retention = 0 | P0 | IP protection |
| **NFR-SEC-005** | No Persistent Code Storage | ELS does not retain source code | Code exists only in memory during analysis | Storage audit | P0 | Compliance requirement |
| **NFR-SEC-006** | Secrets Detection | Prevent accidental secret exposure | Detected secrets redacted from logs/output | Secret scan test | P1 | Prevent credential leaks |
| **NFR-SEC-007** | Memory Isolation | Isolate analysis jobs | Each analysis in separate container/memory space | Isolation verification | P1 | Prevent cross-contamination |
| **NFR-SEC-008** | Audit Logging | Log all access and operations | All requests logged with caller identity | Log completeness | P0 | Compliance and forensics |
| **NFR-SEC-009** | API Key Rotation | Regular credential rotation | 90-day rotation; no hardcoded credentials | Rotation compliance | P1 | Security hygiene |
| **NFR-SEC-010** | Vulnerability Scanning | Regular security scanning | Weekly container scans; zero critical CVEs | Scan results | P1 | Security posture |
| **NFR-SEC-011** | Network Segmentation | Restrict network access | ELS only accessible from CI/CD VPC | Network policy test | P1 | Attack surface reduction |

---

## 2.7 Observability

| ID | Requirement | Description | Target | Measurement | Priority | Rationale |
|----|-------------|-------------|--------|-------------|----------|-----------|
| **NFR-OBS-001** | Request Metrics | Track request rate, errors, duration | RED metrics for all endpoints | Metric availability | P0 | Operational visibility |
| **NFR-OBS-002** | Latency Histograms | Detailed latency distribution | P50, P90, P95, P99 latency metrics | Histogram buckets | P0 | Performance analysis |
| **NFR-OBS-003** | Error Rate Tracking | Track error types and rates | Error rate by type (timeout, 4xx, 5xx, analysis) | Error dashboards | P0 | Problem detection |
| **NFR-OBS-004** | Queue Metrics | Track async queue depth and lag | Queue depth, oldest message age, processing rate | Queue monitoring | P1 | Backlog visibility |
| **NFR-OBS-005** | Analysis Metrics | Track analysis-specific metrics | Flows detected, columns extracted, confidence distribution | Analysis dashboards | P1 | Quality visibility |
| **NFR-OBS-006** | Framework Breakdown | Metrics by framework type | Request rate/latency by Spark/Dask/Flink/etc. | Framework dashboards | P2 | Framework-specific issues |
| **NFR-OBS-007** | Structured Logging | JSON-formatted logs with correlation | All logs include `request_id`, `deployment_id`, `trace_id` | Log format validation | P0 | Log analysis |
| **NFR-OBS-008** | Log Retention | Retain logs for analysis | INFO: 30 days; WARN/ERROR: 90 days | Retention policy | P1 | Historical analysis |
| **NFR-OBS-009** | Distributed Tracing | End-to-end request tracing | Trace context propagated from CI/CD through ELS | Trace completeness | P1 | Performance debugging |
| **NFR-OBS-010** | Alerting | Automated alerting on anomalies | Alerts for: P99 > 30s, error rate > 5%, queue > 500 | Alert configuration | P0 | Proactive detection |
| **NFR-OBS-011** | SLO Dashboard | Track SLO compliance | Dashboard showing latency, availability, coverage SLOs | Dashboard availability | P1 | SLO visibility |
| **NFR-OBS-012** | Coverage Tracking | Track lineage coverage across deployments | % deployments with lineage; % HIGH confidence | Coverage metrics | P1 | Adoption tracking |

---

## 2.8 Cost Efficiency

| ID | Requirement | Description | Target | Measurement | Priority | Rationale |
|----|-------------|-------------|--------|-------------|----------|-----------|
| **NFR-COST-001** | Baseline Infrastructure Cost | Monthly cost for standard capacity | ≤ $3,000/month for 1,000 deploys/day | AWS cost report | P1 | Budget compliance |
| **NFR-COST-002** | Cost per Analysis | Unit economics per request | ≤ $0.05 per analysis | Cost / request count | P1 | Predictable cost |
| **NFR-COST-003** | Spot Instance Usage | Use spot instances for workers | ≥ 70% of worker capacity on spot | Spot vs on-demand ratio | P2 | Cost optimization |
| **NFR-COST-004** | Auto-Scale Down | Reduce capacity during low usage | Scale to minimum during off-hours (10 PM - 6 AM) | Off-hours capacity | P2 | Cost optimization |
| **NFR-COST-005** | Cache Efficiency | Reduce repeated computations | Schema cache hit rate ≥ 90% | Cache metrics | P1 | Avoid redundant work |
| **NFR-COST-006** | Incremental Analysis Savings | Reduce analysis cost for small changes | ≥ 50% cost reduction for incremental analysis | Comparative cost | P1 | Optimization value |
| **NFR-COST-007** | Egress Cost Management | Minimize data transfer costs | Code transfer optimized (changed files only where possible) | Egress costs | P2 | Network cost control |
| **NFR-COST-008** | Right-Sizing | Appropriate instance sizes | Worker memory utilization 60-80% | Resource utilization | P2 | No over-provisioning |

---

## 2.9 Operational Requirements

| ID | Requirement | Description | Target | Measurement | Priority | Rationale |
|----|-------------|-------------|--------|-------------|----------|-----------|
| **NFR-OPS-001** | Zero-Downtime Deployment | Update ELS without service interruption | Rolling updates with zero failed requests | Deployment success | P0 | Continuous delivery |
| **NFR-OPS-002** | Rollback Capability | Quickly revert bad deployments | Rollback complete within 5 minutes | Rollback time | P0 | Rapid recovery |
| **NFR-OPS-003** | Canary Releases | Gradual rollout of changes | 5% → 25% → 100% traffic progression | Canary metrics | P1 | Safe releases |
| **NFR-OPS-004** | Feature Flags | Enable/disable features without deploy | Framework parsers, flow detection modes toggleable | Flag management | P1 | Operational flexibility |
| **NFR-OPS-005** | Configuration Management | Externalized configuration | All config via environment/ConfigMap; no hardcoded values | Config audit | P1 | Environment flexibility |
| **NFR-OPS-006** | Runbook Documentation | Operational procedures documented | Runbooks for: scale-up, incident response, rollback | Doc completeness | P1 | Operational readiness |
| **NFR-OPS-007** | On-Call Support | Support model defined | PagerDuty integration; escalation path defined | On-call rotation | P1 | Incident response |
| **NFR-OPS-008** | Capacity Planning | Proactive capacity management | Quarterly capacity review; 6-month forecast | Capacity reports | P2 | Avoid surprises |
| **NFR-OPS-009** | Dependency Updates | Keep dependencies current | Monthly dependency updates; zero critical CVEs | Update cadence | P1 | Security and stability |
| **NFR-OPS-010** | Backup and Recovery | Protect critical state | Cache state recoverable; queue durable | Recovery test | P2 | Data protection |

---

## 2.10 Compliance & Governance

| ID | Requirement | Description | Target | Measurement | Priority | Rationale |
|----|-------------|-------------|--------|-------------|----------|-----------|
| **NFR-GOV-001** | API Versioning | Maintain backward compatibility | Deprecated APIs supported for 6 months | Version support window | P1 | Consumer stability |
| **NFR-GOV-002** | SLA Definition | Formal SLA with consumers | Published SLA for latency, availability, coverage | SLA document | P1 | Clear expectations |
| **NFR-GOV-003** | Change Management | Controlled changes to ELS | All changes via PR review; staging validation | Change process | P1 | Change control |
| **NFR-GOV-004** | Incident Reporting | Document and learn from incidents | Post-incident review within 48 hours | PIR completion rate | P1 | Continuous improvement |
| **NFR-GOV-005** | Data Retention Policy | Define LineageSpec retention | LineageSpecs retained indefinitely; analysis logs 90 days | Retention compliance | P2 | Storage management |
| **NFR-GOV-006** | Access Control Review | Regular access audits | Quarterly access review; remove unused permissions | Audit completion | P2 | Security hygiene |

---

## 2.11 Testing Requirements

| ID | Requirement | Description | Target | Measurement | Priority | Rationale |
|----|-------------|-------------|--------|-------------|----------|-----------|
| **NFR-TEST-001** | Unit Test Coverage | Code coverage for parsers | ≥ 80% line coverage | Coverage report | P1 | Code quality |
| **NFR-TEST-002** | Integration Test Suite | End-to-end API tests | All endpoints tested; framework combinations covered | Test pass rate | P1 | Integration quality |
| **NFR-TEST-003** | Performance Test Suite | Regular load testing | Weekly performance tests; before major releases | Test execution | P1 | Performance regression detection |
| **NFR-TEST-004** | Chaos Testing | Failure mode validation | Monthly chaos tests (dependency failure, network partition) | Chaos test results | P2 | Resilience validation |
| **NFR-TEST-005** | Accuracy Validation | Lineage correctness testing | Weekly accuracy tests against known repositories | Accuracy metrics | P1 | Output quality |
| **NFR-TEST-006** | Contract Testing | API contract validation | LineageSpec schema validation in CI | Contract test pass rate | P1 | Consumer compatibility |
| **NFR-TEST-007** | Regression Test Suite | Prevent regressions | Golden file tests for each framework parser | Regression detection | P1 | Stability |

---

# Section 3: Summary & Traceability

## 3.1 Priority Distribution

| Priority | Functional | Non-Functional | Total | Description |
|----------|------------|----------------|-------|-------------|
| **P0** | 38 | 42 | 80 | Must have for MVP |
| **P1** | 45 | 48 | 93 | Required for production readiness |
| **P2** | 28 | 22 | 50 | Enhanced capabilities |
| **P3** | 1 | 0 | 1 | Nice to have |
| **Total** | 112 | 112 | 224 | — |

---

## 3.2 Requirement Categories Summary

| Category | Count | Key Focus Areas |
|----------|-------|-----------------|
| **Core Lineage** | 10 | URN resolution, column extraction, flow detection |
| **Batch (Spark)** | 10 | DataFrame, SQL, UDF, Delta |
| **Batch (Dask)** | 7 | Lazy evaluation, pandas API |
| **Batch (Airflow)** | 6 | DAG structure, operators |
| **Streaming (Flink)** | 9 | Table/DataStream API, state, CDC |
| **Streaming (Spark)** | 6 | Structured Streaming, foreachBatch |
| **Streaming (Kafka)** | 6 | ksqlDB, KStreams, serdes |
| **Services** | 13 | REST, ORM, GraphQL, Lambda |
| **Flow Identification** | 8 | Boundaries, naming, stability |
| **Confidence** | 8 | Scoring, coverage, calibration |
| **Integration** | 10 | API, publishing, registries |
| **Performance** | 16 | Latency, throughput |
| **Scalability** | 10 | Horizontal scaling, limits |
| **Availability** | 12 | Uptime, degradation, recovery |
| **Consistency** | 7 | Idempotency, correlation |
| **Security** | 11 | Encryption, auth, code handling |
| **Observability** | 12 | Metrics, logging, tracing |
| **Cost** | 8 | Infrastructure, optimization |
| **Operations** | 10 | Deployment, rollback, on-call |
| **Governance** | 6 | SLA, versioning, compliance |
| **Testing** | 7 | Coverage, performance, accuracy |

---

## 3.3 Confidence Level Definitions

| Level | Criteria | Expected Runtime Accuracy | Use in RCA |
|-------|----------|---------------------------|------------|
| **HIGH** | Static SQL with explicit columns; resolved DataFrame plan; explicit column references in code | ≥ 95% match with runtime | Full weight in blast radius calculation |
| **MEDIUM** | Star expansion resolved via schema; config-driven tables resolved; partial UDF input tracing | ≥ 75% match with runtime | Included with moderate weight; flagged in UI |
| **LOW** | Dynamic SQL; reflection-based schema; unresolvable config; opaque UDFs; analysis errors | ≥ 50% match with runtime | Included with low weight; explicit warning in UI |

---

## 3.4 Integration Points

| Integration | Direction | Protocol | Data Format | Frequency |
|-------------|-----------|----------|-------------|-----------|
| **CI/CD Pipeline** | Inbound | HTTPS | JSON (request) | Per deployment |
| **Git Repository** | Outbound | HTTPS/SSH | Git protocol | Per analysis |
| **Schema Registry** | Outbound | HTTPS | Avro/JSON Schema | Per dataset (cached) |
| **Dataset Registry** | Outbound | HTTPS | JSON | Per table/topic (cached) |
| **Kafka (LineageSpec)** | Outbound | Kafka | JSON (LineageSpec) | Per successful analysis |
| **Lineage Ingestor** | Downstream | Kafka | JSON (LineageSpec) | Async consumption |
| **Neptune** | Downstream | Gremlin | Graph edges | Via Ingestor |
| **DynamoDB** | Downstream | AWS SDK | Index records | Via Ingestor |

---

## 3.5 SLA Summary

| Metric | Target | Measurement Window |
|--------|--------|-------------------|
| **Availability** | 99.9% | Monthly |
| **P99 Latency** | ≤ 30 seconds | Rolling 7 days |
| **Deployment Success Rate** | 100% (with or without lineage) | Daily |
| **Lineage Coverage** | ≥ 90% of deployments | Weekly |
| **HIGH Confidence Rate** | ≥ 60% of flows | Weekly |
| **Lineage-to-Neptune Lag** | < 5 minutes | Continuous |

---

## 3.6 Failure Mode Summary

| Failure Mode | Detection | Handling | Recovery |
|--------------|-----------|----------|----------|
| **ELS Timeout** | No response within 45s | Proceed without lineage; emit metric | Async retry via queue |
| **ELS 5xx Error** | HTTP 500/502/503 | Retry once; if fail, proceed without lineage | Circuit breaker after 5 failures |
| **ELS 4xx Error** | HTTP 400/422 | Log error; proceed without lineage | Manual investigation |
| **Network Partition** | Connection refused | Immediate fallback; no retry | Wait for circuit breaker reset |
| **ELS Overload** | HTTP 429 | Exponential backoff; max 3 retries | Queue-based smoothing |
| **Partial Analysis** | Response with errors | Accept partial lineage with LOW confidence | Log for SCA team review |
| **Schema Registry Down** | Connection timeout | Use cached schema; mark MEDIUM confidence | Retry on next request |
| **Git Clone Failure** | Clone error | Fail request; do not retry | Alert; manual investigation |

---

# Appendix A: LineageSpec Schema Reference

```json
{
  "spec_version": "1.0",
  "lineage_spec_id": "lspec:<producer>:<flow_id>:git:<commit_sha>",
  "emitted_at": "ISO8601 timestamp",
  
  "producer": {
    "type": "JOB|SERVICE|PIPELINE",
    "name": "orders-delta-landing",
    "platform": "SPARK|DASK|FLINK|KSTREAMS|SPRING|NODEJS|CUSTOM",
    "runtime": "EMR|EKS|GLUE|DATABRICKS|LAMBDA|OTHER",
    "owner_team": "checkout-platform",
    "repo": "github:org/repo",
    "ref": {
      "ref_type": "GIT_SHA",
      "ref_value": "9f31c2d"
    }
  },
  
  "flow": {
    "flow_id": "orders_daily_aggregation",
    "flow_name": "Orders Daily Aggregation",
    "is_streaming": false,
    "entry_point": "src/jobs/orders_agg.py:main"
  },
  
  "lineage": {
    "inputs": [{
      "dataset_urn": "urn:dp:orders:order_created:v1",
      "columns": ["customer_id", "order_id", "amount"],
      "column_urns": [
        "urn:col:urn:dp:orders:order_created:v1:customer_id",
        "urn:col:urn:dp:orders:order_created:v1:order_id",
        "urn:col:urn:dp:orders:order_created:v1:amount"
      ]
    }],
    "outputs": [{
      "dataset_urn": "urn:dp:orders:daily_summary:v1",
      "columns": ["customer_id", "daily_total", "order_count"],
      "column_urns": [
        "urn:col:urn:dp:orders:daily_summary:v1:customer_id",
        "urn:col:urn:dp:orders:daily_summary:v1:daily_total",
        "urn:col:urn:dp:orders:daily_summary:v1:order_count"
      ]
    }],
    "transforms": [{
      "output_column": "urn:col:urn:dp:orders:daily_summary:v1:daily_total",
      "input_columns": ["urn:col:urn:dp:orders:order_created:v1:amount"],
      "operation": "SUM"
    }]
  },
  
  "confidence": {
    "overall": "HIGH",
    "reasons": ["STATIC_SQL", "SPARK_DF_ANALYSIS"],
    "coverage": {
      "input_columns_pct": 0.92,
      "output_columns_pct": 0.88
    }
  },
  
  "analysis_metadata": {
    "analysis_duration_ms": 2340,
    "parser_version": "1.2.0",
    "incremental": false,
    "errors": []
  }
}
```

---

# Appendix B: API Contract Reference

## B.1 Synchronous Analysis Endpoint

**Request:**
```http
POST /v1/analyze
Content-Type: application/json
Authorization: Bearer <token>

{
  "repo_url": "https://github.com/org/orders-analytics.git",
  "commit_sha": "9f31c2d",
  "deployment_id": "deploy-2026-02-11-001",
  "changed_files": ["src/jobs/orders_agg.py"],
  "frameworks": ["spark"],
  "timeout_seconds": 30
}
```

**Response (Success):**
```http
HTTP/1.1 200 OK
Content-Type: application/json

{
  "status": "success",
  "flows": [
    { "lineage_spec": { ... } },
    { "lineage_spec": { ... } }
  ],
  "summary": {
    "flows_detected": 2,
    "high_confidence": 1,
    "medium_confidence": 1,
    "low_confidence": 0
  }
}
```

**Response (Timeout):**
```http
HTTP/1.1 408 Request Timeout
Content-Type: application/json

{
  "status": "timeout",
  "message": "Analysis exceeded timeout; deploy may proceed without lineage",
  "partial_results": { ... }
}
```

## B.2 Asynchronous Analysis Endpoint

**Request:**
```http
POST /v1/analyze/async
Content-Type: application/json

{
  "repo_url": "https://github.com/org/orders-analytics.git",
  "commit_sha": "9f31c2d",
  "deployment_id": "deploy-2026-02-11-001",
  "callback_url": "https://ci.example.com/lineage-callback"
}
```

**Response:**
```http
HTTP/1.1 202 Accepted
Location: /v1/jobs/job-abc123

{
  "job_id": "job-abc123",
  "status": "pending",
  "poll_url": "/v1/jobs/job-abc123"
}
```

## B.3 Health Check Endpoint

**Request:**
```http
GET /health
```

**Response:**
```http
HTTP/1.1 200 OK

{
  "status": "healthy",
  "version": "1.2.0",
  "dependencies": {
    "schema_registry": "healthy",
    "dataset_registry": "healthy",
    "kafka": "healthy"
  }
}
```

---

# Appendix C: Metrics Reference

| Metric Name | Type | Labels | Description |
|-------------|------|--------|-------------|
| `els_requests_total` | Counter | `endpoint`, `status` | Total requests received |
| `els_request_duration_seconds` | Histogram | `endpoint`, `framework` | Request latency distribution |
| `els_analysis_duration_seconds` | Histogram | `framework` | Analysis time (excluding network) |
| `els_flows_detected_total` | Counter | `framework`, `confidence` | Flows detected by confidence level |
| `els_columns_extracted_total` | Counter | `direction` (input/output) | Columns successfully extracted |
| `els_errors_total` | Counter | `type` | Errors by type |
| `els_circuit_breaker_state` | Gauge | — | 0=closed, 0.5=half-open, 1=open |
| `els_queue_depth` | Gauge | — | Async queue depth |
| `els_cache_hit_ratio` | Gauge | `cache_type` | Cache effectiveness |
| `els_active_jobs` | Gauge | — | Currently running analyses |

---

# Appendix D: Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-02-11 | Data Platform Architecture | Initial draft |

---

*End of Document*
