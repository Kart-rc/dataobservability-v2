# SCA Element-Level Lineage: Services Requirements Specification

**Version:** 1.0  
**Date:** February 11, 2026  
**Status:** Draft for Review  
**Scope:** Microservices (Spring, Go, Node.js, Python) and Serverless (Lambda, Step Functions)

---

## Executive Summary

This specification defines the prioritized functional and non-functional requirements for extracting element-level (attribute/column) lineage from **service-based applications** during deployment. Services represent a distinct lineage challenge compared to batch/streaming: they typically have multiple entry points (endpoints), transform data across protocol boundaries (HTTP → Kafka), and use ORM abstractions that obscure column-level relationships.

### Services Lineage Challenges

| Challenge | Description | Impact on Lineage |
|-----------|-------------|-------------------|
| **Multiple Entry Points** | Single service exposes many REST/GraphQL endpoints | Each endpoint is a potential flow with distinct lineage |
| **Protocol Bridging** | HTTP request → internal transform → Kafka produce | Lineage must span protocol boundaries |
| **ORM Abstraction** | JPA/GORM/Prisma hide database columns behind entities | Must resolve entity fields to database columns |
| **Dynamic Typing** | Node.js/Python lack compile-time type information | Column inference requires runtime hints or annotations |
| **Framework Magic** | Spring annotations, decorators hide data flow | Must understand framework-specific patterns |
| **Polyglot Ecosystem** | Java, Go, Node.js, Python in same organization | Multiple parsers with consistent output |

### Design Principles for Services

| Principle | Description |
|-----------|-------------|
| **Endpoint-as-Flow** | Each API endpoint producing data output is a distinct flow |
| **Protocol-Aware** | Lineage traces through HTTP → internal → Kafka/DB boundaries |
| **Framework-Native** | Parsers understand Spring, Express, Gin, FastAPI idioms |
| **Schema-First** | Leverage OpenAPI, Protobuf, Avro schemas where available |
| **Graceful Degradation** | Partial lineage with LOW confidence preferred over failure |

---

## Service Architecture Context

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           TYPICAL SERVICE DATA FLOW                              │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  ┌──────────────┐    ┌──────────────────────────────────────┐    ┌────────────┐ │
│  │   HTTP       │    │           SERVICE                    │    │   Kafka    │ │
│  │   Request    │───►│                                      │───►│   Topic    │ │
│  │              │    │  ┌────────┐  ┌────────┐  ┌────────┐  │    │            │ │
│  │  {           │    │  │Controller│─►│Service │─►│Producer│  │    │  {         │ │
│  │   "customer_ │    │  │        │  │  Layer │  │        │  │    │   "cust_id"│ │
│  │    id": 123, │    │  └────────┘  └────────┘  └────────┘  │    │   "amount" │ │
│  │   "amount":  │    │       │                      ▲       │    │   "status" │ │
│  │    99.99     │    │       ▼                      │       │    │  }         │ │
│  │  }           │    │  ┌────────┐           ┌────────┐     │    │            │ │
│  └──────────────┘    │  │  ORM   │◄─────────►│Database│     │    └────────────┘ │
│                      │  │ Entity │           │ Table  │     │                   │
│                      │  └────────┘           └────────┘     │                   │
│                      │                                      │                   │
│                      └──────────────────────────────────────┘                   │
│                                                                                  │
│  LINEAGE EXTRACTION POINTS:                                                     │
│  ① HTTP Request Schema (OpenAPI/annotations)                                    │
│  ② Controller → Service transformation                                          │
│  ③ ORM Entity ↔ Database column mapping                                         │
│  ④ Service → Kafka event field mapping                                          │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

# Section 1: Prioritized Functional Requirements

## Priority 0 (P0) — Must Have for MVP

These requirements are essential for minimum viable lineage extraction from services.

| ID | Requirement | Description | Acceptance Criteria | Rationale |
|----|-------------|-------------|---------------------|-----------|
| **FR-SVC-P0-001** | API Endpoint Detection | Identify REST/gRPC endpoints as flow entry points | All annotated endpoints (`@GetMapping`, `@PostMapping`, `router.get()`, `@app.route()`) detected | Endpoints are the primary unit of service lineage |
| **FR-SVC-P0-002** | Kafka Producer Tracing | Trace columns from service logic to Kafka message fields | Kafka `send()` / `produce()` calls identified with topic and payload fields | Kafka is primary data output for event-driven services |
| **FR-SVC-P0-003** | Request Body Schema Extraction | Extract input columns from HTTP request body | Request DTO/model fields captured as input columns | Input schema defines flow inputs |
| **FR-SVC-P0-004** | Response Body Schema Extraction | Extract output columns from HTTP response body | Response DTO/model fields captured as output columns | Response schema defines flow outputs |
| **FR-SVC-P0-005** | Multi-Language Support (Java) | Parse Java/Spring services | Spring Boot annotations, JPA entities, Kafka templates parsed | Java/Spring is dominant enterprise framework |
| **FR-SVC-P0-006** | Multi-Language Support (Node.js) | Parse Node.js/Express/NestJS services | Express routes, TypeScript interfaces, kafkajs producers parsed | Node.js is common for lightweight services |
| **FR-SVC-P0-007** | Multi-Language Support (Python) | Parse Python/FastAPI/Flask services | FastAPI/Flask routes, Pydantic models, kafka-python producers parsed | Python is common for data-adjacent services |
| **FR-SVC-P0-008** | Multi-Language Support (Go) | Parse Go/Gin/Echo services | Gin handlers, struct tags, sarama producers parsed | Go is common for high-performance services |
| **FR-SVC-P0-009** | Flow-per-Endpoint Model | Generate separate flow for each endpoint producing data | Each `POST`/`PUT` endpoint with Kafka/DB output = distinct flow | Precise blast radius per operation |
| **FR-SVC-P0-010** | Topic-to-Dataset URN Mapping | Map Kafka topic names to canonical Dataset URNs | All topic references resolved to `urn:dp:*` format | Consistent identity for graph joins |
| **FR-SVC-P0-011** | Deployment-Commit Correlation | Include commit SHA in LineageSpec | `ref.ref_value` matches deployed commit exactly | Required for runtime Evidence correlation |
| **FR-SVC-P0-012** | Confidence Scoring | Assign HIGH/MEDIUM/LOW confidence to each flow | Every flow has confidence with reasons array | RCA must weight lineage appropriately |

---

## Priority 1 (P1) — Required for Production

These requirements are needed for production-grade lineage extraction.

| ID | Requirement | Description | Acceptance Criteria | Rationale |
|----|-------------|-------------|---------------------|-----------|
| **FR-SVC-P1-001** | ORM Entity Mapping (JPA) | Extract column mappings from JPA annotations | `@Entity`, `@Column`, `@Table` annotations parsed; DB columns mapped to entity fields | JPA is standard Java ORM |
| **FR-SVC-P1-002** | ORM Entity Mapping (GORM) | Extract column mappings from Go GORM structs | GORM struct tags parsed; DB columns mapped | GORM is standard Go ORM |
| **FR-SVC-P1-003** | ORM Entity Mapping (Prisma) | Extract column mappings from Prisma schema | `schema.prisma` parsed; model fields mapped to DB columns | Prisma is popular Node.js ORM |
| **FR-SVC-P1-004** | ORM Entity Mapping (SQLAlchemy) | Extract column mappings from SQLAlchemy models | SQLAlchemy model classes parsed; columns extracted | SQLAlchemy is standard Python ORM |
| **FR-SVC-P1-005** | Database Read Tracing | Trace columns read from database in service logic | `findById()`, `SELECT` queries traced to input columns | DB reads are flow inputs |
| **FR-SVC-P1-006** | Database Write Tracing | Trace columns written to database | `save()`, `INSERT`, `UPDATE` operations traced to output columns | DB writes are flow outputs |
| **FR-SVC-P1-007** | Request-to-Event Field Mapping | Map HTTP request fields to Kafka event fields | Transform hints show `event.field` ← `request.field` | Enables "which input caused this output" analysis |
| **FR-SVC-P1-008** | OpenAPI Schema Integration | Extract schemas from OpenAPI/Swagger definitions | `openapi.yaml` / `swagger.json` parsed for request/response schemas | Schema-first services have explicit column definitions |
| **FR-SVC-P1-009** | Protobuf Message Parsing | Extract field definitions from `.proto` files | Protobuf message fields captured as columns | gRPC services use Protobuf |
| **FR-SVC-P1-010** | Avro Schema Parsing | Extract field definitions from Avro schemas | Avro schema fields captured as columns | Common for Kafka serialization |
| **FR-SVC-P1-011** | Service-to-Service Call Tracing | Identify outbound HTTP/gRPC calls to other services | `RestTemplate`, `WebClient`, `fetch()` calls identified with target service | Cross-service lineage |
| **FR-SVC-P1-012** | Validation Annotation Extraction | Extract field constraints from validation annotations | `@NotNull`, `@Size`, `required` constraints captured | Constraints indicate column semantics |
| **FR-SVC-P1-013** | Container Image to Commit Mapping | Resolve container image tag to commit SHA | Image tag `v3.17` → commit `9f31c2d` mapping | K8s deploys use image tags, not commits |
| **FR-SVC-P1-014** | TypeScript Interface Parsing | Extract column definitions from TypeScript interfaces | Interface properties captured as columns with types | TypeScript provides type information |
| **FR-SVC-P1-015** | Pydantic Model Parsing | Extract column definitions from Pydantic models | Pydantic field definitions captured with types and constraints | FastAPI uses Pydantic for validation |

---

## Priority 2 (P2) — Enhanced Capabilities

These requirements provide advanced lineage capabilities.

| ID | Requirement | Description | Acceptance Criteria | Rationale |
|----|-------------|-------------|---------------------|-----------|
| **FR-SVC-P2-001** | GraphQL Schema Parsing | Extract types and fields from GraphQL schema | `schema.graphql` parsed; Query/Mutation types captured | GraphQL services have schema-defined fields |
| **FR-SVC-P2-002** | GraphQL Resolver Tracing | Trace data flow through GraphQL resolvers | Resolver functions analyzed for DB/service calls | Resolvers define actual data fetching |
| **FR-SVC-P2-003** | Dynamic Field Selection Handling | Handle GraphQL's dynamic field selection | All possible fields captured; confidence MEDIUM (runtime varies) | GraphQL clients select fields at runtime |
| **FR-SVC-P2-004** | Event Sourcing Pattern Support | Trace columns through Command → Event → Aggregate | Event fields mapped from command inputs | Event sourcing has indirect lineage |
| **FR-SVC-P2-005** | CQRS Pattern Support | Handle separate read/write models | Read model fields traced separately from write model | CQRS splits data models |
| **FR-SVC-P2-006** | Message Queue Consumer Tracing | Trace Kafka/SQS consumer input fields | Consumer `poll()` / message handler input fields captured | Services also consume messages |
| **FR-SVC-P2-007** | Caching Layer Tracing | Identify Redis/Memcached read/write fields | Cache get/set operations traced with key/value fields | Caching affects data flow |
| **FR-SVC-P2-008** | Async Handler Tracing | Trace columns through async/await patterns | Async function chains analyzed for column flow | Modern services use async patterns |
| **FR-SVC-P2-009** | Middleware Column Modification | Detect columns added/modified by middleware | Express/Spring middleware column changes captured | Middleware can modify request/response |
| **FR-SVC-P2-010** | Feature Flag Conditional Flows | Handle feature flag branches as conditional flows | Feature flag conditions identified; both branches analyzed | Feature flags create conditional lineage |
| **FR-SVC-P2-011** | Decorator/Annotation Metadata | Extract lineage hints from custom annotations | `@LineageInput`, `@LineageOutput` annotations respected | Developer hints for complex cases |
| **FR-SVC-P2-012** | Multi-Module Project Support | Handle Maven/Gradle/npm multi-module projects | Cross-module dependencies resolved; shared DTOs traced | Enterprise projects are multi-module |

---

## Priority 3 (P3) — Future Enhancements

| ID | Requirement | Description | Acceptance Criteria | Rationale |
|----|-------------|-------------|---------------------|-----------|
| **FR-SVC-P3-001** | Runtime Schema Discovery | Integrate with runtime schema inference | Runtime-observed fields merged with static analysis | Dynamic languages may need runtime hints |
| **FR-SVC-P3-002** | API Gateway Integration | Trace lineage through API Gateway transformations | Gateway request/response transformations captured | API Gateways modify payloads |
| **FR-SVC-P3-003** | Service Mesh Tracing | Extract lineage from Istio/Linkerd configurations | Service mesh routing rules analyzed | Service mesh affects data flow |

---

# Section 2: Prioritized Functional Requirements — Serverless

## Priority 1 (P1) — Required for Production

| ID | Requirement | Description | Acceptance Criteria | Rationale |
|----|-------------|-------------|---------------------|-----------|
| **FR-LAMBDA-P1-001** | Event Trigger Detection | Identify Lambda trigger type and input schema | S3, DynamoDB, Kafka, API Gateway, SQS triggers identified | Trigger defines input structure |
| **FR-LAMBDA-P1-002** | Handler Function Tracing | Trace columns through handler function | `event` fields → output fields (return/write) mapped | Handler is the transformation logic |
| **FR-LAMBDA-P1-003** | S3 Event Schema | Extract columns from S3 event structure | S3 event fields (`bucket`, `key`, `size`) captured as inputs | Common Lambda trigger |
| **FR-LAMBDA-P1-004** | DynamoDB Stream Schema | Extract columns from DynamoDB stream events | `NewImage`, `OldImage`, `Keys` fields captured | Common Lambda trigger |
| **FR-LAMBDA-P1-005** | API Gateway Event Schema | Extract columns from API Gateway events | `body`, `pathParameters`, `queryStringParameters` captured | REST API trigger |
| **FR-LAMBDA-P1-006** | SQS/SNS Message Schema | Extract columns from SQS/SNS message body | Message body fields captured as inputs | Queue-triggered Lambdas |
| **FR-LAMBDA-P1-007** | Kafka Trigger Schema | Extract columns from MSK/Kafka events | Kafka record fields captured | Event-driven Lambdas |
| **FR-LAMBDA-P1-008** | Environment Variable Resolution | Resolve config from environment variables | Table names, topic names from env vars resolved where determinable | Lambdas use env vars for config |

## Priority 2 (P2) — Enhanced Capabilities

| ID | Requirement | Description | Acceptance Criteria | Rationale |
|----|-------------|-------------|---------------------|-----------|
| **FR-LAMBDA-P2-001** | Lambda Layer Tracing | Follow lineage into Lambda layers | Shared layer code analyzed; flows reference layer functions | Layers contain shared logic |
| **FR-LAMBDA-P2-002** | Step Function Integration | Trace lineage across Step Function states | State machine definition parsed; per-state lineage linked | Step Functions orchestrate Lambdas |
| **FR-LAMBDA-P2-003** | Step Function Input/Output Processing | Extract InputPath/OutputPath/ResultPath transformations | JSONPath transformations captured as column mappings | Step Functions transform data |
| **FR-LAMBDA-P2-004** | EventBridge Rule Parsing | Extract input transformer patterns | EventBridge input templates analyzed | EventBridge routes events |
| **FR-LAMBDA-P2-005** | Lambda Destination Tracing | Trace async invocation destinations | OnSuccess/OnFailure destinations captured | Async Lambda patterns |

---

# Section 3: Prioritized Non-Functional Requirements

## Priority 0 (P0) — Must Have for MVP

| ID | Requirement | Description | Target | Rationale |
|----|-------------|-------------|--------|-----------|
| **NFR-SVC-P0-001** | P99 Response Time | 99th percentile analysis latency | ≤ 30 seconds | Services typically smaller than batch jobs |
| **NFR-SVC-P0-002** | Sync Timeout | Maximum wait for synchronous analysis | 45 seconds | Prevent pipeline blocking |
| **NFR-SVC-P0-003** | Service Uptime | ELS availability | 99.9% | High availability for CI/CD |
| **NFR-SVC-P0-004** | Graceful Degradation | Behavior when analysis fails | Deploy proceeds; emit metric | Never block deployment |
| **NFR-SVC-P0-005** | Circuit Breaker | Prevent cascade failures | Open after 5 failures/60s | Failure isolation |
| **NFR-SVC-P0-006** | Idempotent Processing | Same input = same output | Identical LineageSpec on retry | No duplicate edges |
| **NFR-SVC-P0-007** | Transport Encryption | All communication encrypted | TLS 1.3 | Data protection |
| **NFR-SVC-P0-008** | No Persistent Code Storage | Code deleted after analysis | Code retention = 0 | IP protection |
| **NFR-SVC-P0-009** | Request Metrics | Track rate, errors, duration | RED metrics available | Operational visibility |
| **NFR-SVC-P0-010** | Structured Logging | JSON logs with correlation IDs | `request_id`, `deployment_id` in all logs | Debugging support |

## Priority 1 (P1) — Required for Production

| ID | Requirement | Description | Target | Rationale |
|----|-------------|-------------|--------|-----------|
| **NFR-SVC-P1-001** | P50 Response Time | Median analysis latency | ≤ 5 seconds | Most requests fast |
| **NFR-SVC-P1-002** | Sustained Throughput | Continuous request capacity | 50 RPS | Normal operation |
| **NFR-SVC-P1-003** | Burst Throughput | Peak request capacity | 200 RPS for 60s | Mass deploy scenario |
| **NFR-SVC-P1-004** | Horizontal Scaling | Add capacity via instances | 5-50 pods (HPA) | Elastic capacity |
| **NFR-SVC-P1-005** | Auto-Scaling Trigger | Scale based on load | CPU > 70% OR queue > 100 | Responsive scaling |
| **NFR-SVC-P1-006** | Retry Policy | Retry transient failures | 3 retries, exponential backoff | Handle transient issues |
| **NFR-SVC-P1-007** | Partial Result Acceptance | Accept incomplete analysis | Partial spec preferred over failure | Some lineage > none |
| **NFR-SVC-P1-008** | Dependency Failure Handling | Handle Schema Registry unavailability | Cache fallback; LOW confidence | External dependency resilience |
| **NFR-SVC-P1-009** | Lineage-Deployment Correlation | LineageSpec matches deployed commit | 100% correlation accuracy | RCA correctness |
| **NFR-SVC-P1-010** | Eventual Consistency | Lineage available after deploy | < 5 minutes lag | Timely RCA enrichment |
| **NFR-SVC-P1-011** | Authentication | Verify caller identity | mTLS or IAM auth | Prevent unauthorized access |
| **NFR-SVC-P1-012** | Audit Logging | Log all access | All requests logged with identity | Compliance |
| **NFR-SVC-P1-013** | Latency Histograms | Detailed latency metrics | P50/P90/P95/P99 | Performance analysis |
| **NFR-SVC-P1-014** | Error Rate Tracking | Track errors by type | Dashboards by error type | Problem detection |
| **NFR-SVC-P1-015** | Zero-Downtime Deployment | Update without interruption | Rolling updates, zero failures | Continuous delivery |
| **NFR-SVC-P1-016** | Rollback Capability | Quick revert | < 5 minutes rollback | Rapid recovery |
| **NFR-SVC-P1-017** | Framework-Specific Metrics | Metrics by language/framework | Breakdown by Spring/Express/FastAPI/Gin | Framework-specific issues |
| **NFR-SVC-P1-018** | Coverage Tracking | Track lineage coverage | % services with lineage | Adoption tracking |

## Priority 2 (P2) — Enhanced Capabilities

| ID | Requirement | Description | Target | Rationale |
|----|-------------|-------------|--------|-----------|
| **NFR-SVC-P2-001** | Incremental Analysis | Analyze only changed files | 60% faster for <10% changes | CI/CD optimization |
| **NFR-SVC-P2-002** | Cost per Analysis | Unit economics | ≤ $0.03 per service analysis | Services smaller than batch |
| **NFR-SVC-P2-003** | Schema Cache Hit Rate | Cache effectiveness | ≥ 90% hit rate | Avoid redundant lookups |
| **NFR-SVC-P2-004** | Multi-Region Deployment | Regional proximity | 2+ AWS regions | Global CI/CD |
| **NFR-SVC-P2-005** | Canary Releases | Gradual rollout | 5% → 25% → 100% | Safe releases |
| **NFR-SVC-P2-006** | Feature Flags | Toggle without deploy | Per-framework toggles | Operational flexibility |
| **NFR-SVC-P2-007** | Distributed Tracing | End-to-end tracing | Trace context propagation | Performance debugging |
| **NFR-SVC-P2-008** | Chaos Testing | Failure validation | Monthly chaos tests | Resilience validation |
| **NFR-SVC-P2-009** | Accuracy Validation | Lineage correctness | Weekly accuracy tests | Output quality |

---

# Section 4: Framework-Specific Parsing Requirements

## 4.1 Java/Spring Boot

| ID | Requirement | Priority | Description |
|----|-------------|----------|-------------|
| **FR-SPRING-001** | `@RestController` Detection | P0 | Identify REST controllers as flow containers |
| **FR-SPRING-002** | `@RequestMapping` Parsing | P0 | Extract endpoint paths and HTTP methods |
| **FR-SPRING-003** | `@RequestBody` Schema | P0 | Extract request body DTO fields |
| **FR-SPRING-004** | `@ResponseBody` Schema | P0 | Extract response body DTO fields |
| **FR-SPRING-005** | `@PathVariable` / `@RequestParam` | P1 | Extract path and query parameters |
| **FR-SPRING-006** | JPA `@Entity` Mapping | P1 | Map entity fields to database columns |
| **FR-SPRING-007** | `@Column` Annotation | P1 | Extract explicit column name mappings |
| **FR-SPRING-008** | `KafkaTemplate.send()` | P0 | Trace Kafka producer calls with topic and payload |
| **FR-SPRING-009** | `@KafkaListener` | P2 | Trace Kafka consumer input fields |
| **FR-SPRING-010** | Spring Data Repository | P1 | Trace `findBy*`, `save()`, `delete()` operations |
| **FR-SPRING-011** | `@Validated` / `@Valid` | P1 | Extract validation constraints |
| **FR-SPRING-012** | Lombok `@Data` / `@Getter` | P1 | Resolve Lombok-generated accessors |
| **FR-SPRING-013** | Record Classes | P1 | Parse Java record fields |
| **FR-SPRING-014** | `RestTemplate` / `WebClient` | P1 | Trace outbound HTTP calls |

## 4.2 Node.js/Express/NestJS

| ID | Requirement | Priority | Description |
|----|-------------|----------|-------------|
| **FR-NODE-001** | Express `router.get/post` | P0 | Identify route handlers |
| **FR-NODE-002** | NestJS `@Controller` | P0 | Identify NestJS controllers |
| **FR-NODE-003** | NestJS `@Get/@Post` Decorators | P0 | Extract endpoint definitions |
| **FR-NODE-004** | TypeScript Interface Parsing | P0 | Extract interface properties as columns |
| **FR-NODE-005** | Request Body Type | P0 | Extract `req.body` type from TypeScript |
| **FR-NODE-006** | Response Type | P0 | Extract response type from return/`res.json()` |
| **FR-NODE-007** | Kafkajs Producer | P0 | Trace `producer.send()` with topic and message |
| **FR-NODE-008** | Prisma Client | P1 | Trace `prisma.model.create/findMany` |
| **FR-NODE-009** | TypeORM Entity | P1 | Parse TypeORM entity decorators |
| **FR-NODE-010** | Sequelize Model | P1 | Parse Sequelize model definitions |
| **FR-NODE-011** | Zod Schema | P1 | Extract Zod schema field definitions |
| **FR-NODE-012** | Class-Validator Decorators | P1 | Extract validation decorators |
| **FR-NODE-013** | Axios/Fetch Calls | P1 | Trace outbound HTTP calls |

## 4.3 Python/FastAPI/Flask

| ID | Requirement | Priority | Description |
|----|-------------|----------|-------------|
| **FR-PYTHON-001** | FastAPI `@app.get/post` | P0 | Identify route handlers |
| **FR-PYTHON-002** | Flask `@app.route` | P0 | Identify Flask routes |
| **FR-PYTHON-003** | Pydantic Model Parsing | P0 | Extract Pydantic field definitions |
| **FR-PYTHON-004** | Type Hints | P0 | Extract function parameter/return types |
| **FR-PYTHON-005** | Request Body Model | P0 | Extract request body Pydantic model |
| **FR-PYTHON-006** | Response Model | P0 | Extract response Pydantic model |
| **FR-PYTHON-007** | kafka-python Producer | P0 | Trace `producer.send()` calls |
| **FR-PYTHON-008** | confluent-kafka Producer | P0 | Trace confluent producer calls |
| **FR-PYTHON-009** | SQLAlchemy Model | P1 | Parse SQLAlchemy model columns |
| **FR-PYTHON-010** | Django Model | P1 | Parse Django model fields |
| **FR-PYTHON-011** | Dataclass Parsing | P1 | Extract dataclass fields |
| **FR-PYTHON-012** | `attrs` Class Parsing | P2 | Extract attrs class fields |
| **FR-PYTHON-013** | httpx/requests Calls | P1 | Trace outbound HTTP calls |

## 4.4 Go/Gin/Echo

| ID | Requirement | Priority | Description |
|----|-------------|----------|-------------|
| **FR-GO-001** | Gin `router.GET/POST` | P0 | Identify Gin route handlers |
| **FR-GO-002** | Echo `e.GET/POST` | P0 | Identify Echo route handlers |
| **FR-GO-003** | Struct Tag Parsing | P0 | Extract `json:""` tags for field names |
| **FR-GO-004** | Request Binding Struct | P0 | Extract `c.ShouldBindJSON(&req)` struct |
| **FR-GO-005** | Response Struct | P0 | Extract `c.JSON(200, resp)` struct |
| **FR-GO-006** | Sarama Producer | P0 | Trace sarama `SendMessage` calls |
| **FR-GO-007** | Confluent Go Producer | P0 | Trace confluent-kafka-go producer |
| **FR-GO-008** | GORM Model | P1 | Parse GORM struct tags for columns |
| **FR-GO-009** | sqlx Struct | P1 | Parse sqlx `db:""` tags |
| **FR-GO-010** | Protobuf Struct | P1 | Parse generated protobuf structs |
| **FR-GO-011** | net/http Client | P1 | Trace outbound HTTP calls |
| **FR-GO-012** | Validator Tags | P1 | Extract `validate:""` constraints |

---

# Section 5: Confidence Scoring for Services

## 5.1 Confidence Level Definitions

| Level | Criteria | Expected Accuracy | Example Scenarios |
|-------|----------|-------------------|-------------------|
| **HIGH** | Explicit type annotations; schema files present; direct field mapping | ≥ 95% | TypeScript with interfaces; FastAPI with Pydantic; OpenAPI spec |
| **MEDIUM** | Partial type info; ORM without explicit columns; inferred mapping | ≥ 75% | JavaScript with JSDoc; Python without type hints; implicit JPA columns |
| **LOW** | Dynamic typing; runtime construction; reflection-based | ≥ 50% | Plain JavaScript objects; dynamic attribute access; `**kwargs` |

## 5.2 Confidence Scoring Rules

| Scenario | Confidence | Reason |
|----------|------------|--------|
| TypeScript interface with all fields typed | HIGH | Explicit type information |
| Pydantic model with Field() definitions | HIGH | Schema-defined fields |
| OpenAPI/Swagger spec matches implementation | HIGH | Contract-first design |
| JPA Entity with @Column annotations | HIGH | Explicit column mapping |
| JPA Entity without @Column (convention-based) | MEDIUM | Inferred column names |
| JavaScript object literal `{ field: value }` | MEDIUM | Inferred from usage |
| Python dict without type hints | LOW | Dynamic typing |
| `req.body[dynamicKey]` | LOW | Runtime key access |
| Reflection-based serialization | LOW | Runtime field discovery |
| Third-party library DTO (no source) | LOW | External dependency |

---

# Section 6: Priority Summary

## 6.1 Implementation Phases

### Phase 1: MVP (P0 Requirements)

| Category | Requirements | Effort Estimate |
|----------|--------------|-----------------|
| Core Detection | 12 functional | 4 weeks |
| Framework Parsers (Basic) | 4 languages × 5 core features | 6 weeks |
| Non-Functional | 10 critical | 2 weeks |
| **Total Phase 1** | **32 requirements** | **12 weeks** |

### Phase 2: Production (P1 Requirements)

| Category | Requirements | Effort Estimate |
|----------|--------------|-----------------|
| ORM Integration | 4 ORMs × 3 features | 4 weeks |
| Schema Integration | OpenAPI, Protobuf, Avro | 3 weeks |
| Lambda Support | 8 trigger types | 3 weeks |
| Non-Functional | 18 production | 2 weeks |
| **Total Phase 2** | **45 requirements** | **12 weeks** |

### Phase 3: Enhanced (P2 Requirements)

| Category | Requirements | Effort Estimate |
|----------|--------------|-----------------|
| GraphQL Support | Schema + Resolvers | 3 weeks |
| Advanced Patterns | Event Sourcing, CQRS | 2 weeks |
| Step Functions | State machine lineage | 2 weeks |
| Non-Functional | 9 enhanced | 2 weeks |
| **Total Phase 3** | **21 requirements** | **9 weeks** |

## 6.2 Requirement Count by Priority

| Priority | Functional | Non-Functional | Total | Phase |
|----------|------------|----------------|-------|-------|
| **P0** | 12 | 10 | 22 | MVP |
| **P1** | 23 | 18 | 41 | Production |
| **P2** | 17 | 9 | 26 | Enhanced |
| **P3** | 3 | 0 | 3 | Future |
| **Total** | 55 | 37 | 92 | — |

## 6.3 Framework Parser Priority

| Framework | Language | Priority | Rationale |
|-----------|----------|----------|-----------|
| Spring Boot | Java | P0 | Dominant enterprise framework |
| Express/NestJS | Node.js | P0 | Common for lightweight services |
| FastAPI | Python | P0 | Growing adoption for data services |
| Gin | Go | P0 | Common for high-performance services |
| Flask | Python | P1 | Legacy Python services |
| Echo | Go | P1 | Alternative Go framework |
| Django | Python | P1 | Full-stack Python framework |
| Koa | Node.js | P2 | Alternative Node.js framework |

---

# Section 7: Success Criteria

## 7.1 MVP Success Criteria

| Metric | Target | Measurement |
|--------|--------|-------------|
| Endpoint Detection Rate | ≥ 95% of annotated endpoints | Sampling against known services |
| Kafka Producer Detection | ≥ 90% of producer calls | Sampling against known services |
| HIGH Confidence Rate | ≥ 50% of flows | Confidence distribution |
| P99 Latency | ≤ 30 seconds | Latency metrics |
| Availability | ≥ 99.9% | Uptime monitoring |

## 7.2 Production Success Criteria

| Metric | Target | Measurement |
|--------|--------|-------------|
| ORM Column Accuracy | ≥ 90% match with actual DB columns | Validation against schema |
| Request→Event Mapping | ≥ 80% of transforms traced | Manual validation sample |
| HIGH Confidence Rate | ≥ 60% of flows | Confidence distribution |
| Coverage | ≥ 80% of Tier-1 services | Service inventory comparison |

## 7.3 Enhanced Success Criteria

| Metric | Target | Measurement |
|--------|--------|-------------|
| GraphQL Field Accuracy | ≥ 85% of schema fields captured | Schema comparison |
| Lambda Trigger Coverage | ≥ 90% of trigger types supported | Trigger type inventory |
| Step Function Tracing | End-to-end state lineage | Manual validation |

---

# Appendix A: Example LineageSpec for Service

```json
{
  "spec_version": "1.0",
  "lineage_spec_id": "lspec:orders-service:create_order_flow:git:9f31c2d",
  "emitted_at": "2026-02-11T10:30:00Z",
  
  "producer": {
    "type": "SERVICE",
    "name": "orders-service",
    "platform": "SPRING",
    "runtime": "EKS",
    "owner_team": "checkout-platform",
    "repo": "github:acme/orders-service",
    "ref": {
      "ref_type": "GIT_SHA",
      "ref_value": "9f31c2d"
    }
  },
  
  "flow": {
    "flow_id": "create_order_flow",
    "flow_name": "POST /api/v1/orders → orders.created",
    "entry_point": "com.acme.orders.controller.OrderController.createOrder",
    "http_method": "POST",
    "http_path": "/api/v1/orders"
  },
  
  "lineage": {
    "inputs": [
      {
        "source_type": "HTTP_REQUEST",
        "description": "CreateOrderRequest body",
        "columns": ["customer_id", "items", "shipping_address", "payment_method"],
        "column_urns": [
          "urn:col:http:orders-service:/api/v1/orders:request:customer_id",
          "urn:col:http:orders-service:/api/v1/orders:request:items",
          "urn:col:http:orders-service:/api/v1/orders:request:shipping_address",
          "urn:col:http:orders-service:/api/v1/orders:request:payment_method"
        ]
      },
      {
        "source_type": "DATABASE",
        "dataset_urn": "urn:dp:orders:customers:v1",
        "description": "Customer lookup",
        "columns": ["customer_id", "email", "tier"],
        "column_urns": [
          "urn:col:urn:dp:orders:customers:v1:customer_id",
          "urn:col:urn:dp:orders:customers:v1:email",
          "urn:col:urn:dp:orders:customers:v1:tier"
        ]
      }
    ],
    "outputs": [
      {
        "sink_type": "KAFKA",
        "dataset_urn": "urn:dp:orders:order_created:v1",
        "topic": "orders.created",
        "columns": ["order_id", "customer_id", "customer_email", "total_amount", "status"],
        "column_urns": [
          "urn:col:urn:dp:orders:order_created:v1:order_id",
          "urn:col:urn:dp:orders:order_created:v1:customer_id",
          "urn:col:urn:dp:orders:order_created:v1:customer_email",
          "urn:col:urn:dp:orders:order_created:v1:total_amount",
          "urn:col:urn:dp:orders:order_created:v1:status"
        ]
      },
      {
        "sink_type": "DATABASE",
        "dataset_urn": "urn:dp:orders:orders:v1",
        "description": "Orders table insert",
        "columns": ["order_id", "customer_id", "total_amount", "status", "created_at"],
        "column_urns": [
          "urn:col:urn:dp:orders:orders:v1:order_id",
          "urn:col:urn:dp:orders:orders:v1:customer_id",
          "urn:col:urn:dp:orders:orders:v1:total_amount",
          "urn:col:urn:dp:orders:orders:v1:status",
          "urn:col:urn:dp:orders:orders:v1:created_at"
        ]
      }
    ],
    "transforms": [
      {
        "output_column": "urn:col:urn:dp:orders:order_created:v1:customer_email",
        "input_columns": ["urn:col:urn:dp:orders:customers:v1:email"],
        "operation": "COPY"
      },
      {
        "output_column": "urn:col:urn:dp:orders:order_created:v1:total_amount",
        "input_columns": ["urn:col:http:orders-service:/api/v1/orders:request:items"],
        "operation": "AGGREGATE_SUM"
      }
    ]
  },
  
  "confidence": {
    "overall": "HIGH",
    "reasons": ["SPRING_ANNOTATIONS", "JPA_ENTITY_MAPPING", "TYPED_DTO"],
    "coverage": {
      "input_columns_pct": 1.0,
      "output_columns_pct": 1.0
    }
  },
  
  "analysis_metadata": {
    "analysis_duration_ms": 1850,
    "parser_version": "1.2.0",
    "framework_detected": "SPRING_BOOT_3",
    "orm_detected": "JPA_HIBERNATE",
    "errors": []
  }
}
```

---

# Appendix B: Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-02-11 | Data Platform Architecture | Initial draft - Services focus |

---

*End of Document*
