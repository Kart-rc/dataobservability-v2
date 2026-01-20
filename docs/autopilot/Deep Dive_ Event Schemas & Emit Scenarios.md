# **Deep Dive: Event Schemas & Emit Scenarios**

## **Systems Thinking Framework**

# **Before diving into schemas, let me frame this through the lens you've outlined:**

# **Things & Connections**

* # **Raw Events → Policy Enforcer → Evidence Events → Signal Engines → Signals**

* # **Each boundary is a potential correlation break point**

# **Inflows: Raw business events, OTel spans, OpenLineage facets, deployment markers Outflows: Evidence (per-record truth), Signals (aggregated health), Lineage graphs**

# **Hidden Assumptions I'm Surfacing:**

1. # **All services can inject correlation headers (many legacy services cannot)**

2. # **Batch jobs emit OpenLineage consistently (Spark yes, custom Python often no)**

3. # **Schema evolution is backward-compatible (breaks Gate 3\)**

4. # **Kafka is the sole ingestion point (what about direct S3 writes from vendors?)**

# ---

## **1\. Service Emit Scenarios (Microservices → Kafka)**

### **1.1 Raw Event Schema (Producer Output)**

# **{**

#   **"$schema": "http://json-schema.org/draft-07/schema\#",**

#   **"$id": "urn:schema:raw-event-envelope:1",**

#   **"type": "object",**

#   **"required": \["event\_id", "event\_type", "timestamp", "payload"\],**

#   **"properties": {**

#     **"event\_id": {**

#       **"type": "string",**

#       **"format": "ulid",**

#       **"description": "Globally unique event identifier"**

#     **},**

#     **"event\_type": {**

#       **"type": "string",**

#       **"pattern": "^\[a-z\]+\\\\.\[a-z\]+\\\\.\[a-z\]+$",**

#       **"examples": \["orders.created.v1", "payments.completed.v1"\]**

#     **},**

#     **"timestamp": {**

#       **"type": "string",**

#       **"format": "date-time"**

#     **},**

#     **"payload": {**

#       **"type": "object",**

#       **"description": "Domain-specific payload validated by Gate 3/4"**

#     **},**

#     **"metadata": {**

#       **"type": "object",**

#       **"properties": {**

#         **"correlation\_id": { "type": "string" },**

#         **"causation\_id": { "type": "string" },**

#         **"producer\_service": { "type": "string" },**

#         **"producer\_version": { "type": "string" }**

#       **}**

#     **}**

#   **}**

# **}**

# 

### **1.2 Emit Scenarios for Services**

# **Scenario A: Fully Instrumented Service (Ideal State)**

# **┌─────────────────────────────────────────────────────────────────┐**

# **│ orders-svc (OTel SDK instrumented)                              │**

# **├─────────────────────────────────────────────────────────────────┤**

# **│                                                                 │**

# **│  HTTP Request ──► Business Logic ──► Kafka Producer             │**

# **│       │                                      │                  │**

# **│       ▼                                      ▼                  │**

# **│  trace\_id: abc123              Header: x-obs-trace-id: abc123   │**

# **│  span\_id: def456               Header: x-obs-producer: orders   │**

# **│                                Header: x-obs-version: v3.17     │**

# **│                                                                 │**

# **└─────────────────────────────────────────────────────────────────┘**

# 

# **Kafka Record Headers (ideal):**

# **x-obs-trace-id: abc123def456...**

# **x-obs-producer-service: orders-svc**

# **x-obs-producer-version: v3.17**

# **x-obs-schema-id: glue:orders.created:17**

# 

# **Scenario B: Partially Instrumented (Common Reality)**

# **┌─────────────────────────────────────────────────────────────────┐**

# **│ legacy-inventory-svc (no OTel)                                  │**

# **├─────────────────────────────────────────────────────────────────┤**

# **│                                                                 │**

# **│  HTTP Request ──► Business Logic ──► Kafka Producer             │**

# **│       │                                      │                  │**

# **│       ▼                                      ▼                  │**

# **│  (no trace)                    NO HEADERS (bare record)         │**

# **│                                                                 │**

# **└─────────────────────────────────────────────────────────────────┘**

# 

# **Policy Enforcer Handling for Scenario B:**

# **\# Gate 2: Identity Resolution with Fallback**

# **def resolve\_producer\_identity(record: KafkaRecord) \-\> ProducerIdentity:**

#     **\# Attempt 1: Check Kafka headers**

#     **if header := record.headers.get('x-obs-producer-service'):**

#         **return ProducerIdentity(id=header, confidence='HIGH')**

#     

#     **\# Attempt 2: Topic-to-service mapping (Control Plane config)**

#     **if mapping := control\_plane.get\_topic\_mapping(record.topic):**

#         **return ProducerIdentity(id=mapping.service, confidence='MEDIUM')**

#     

#     **\# Attempt 3: Parse payload for service hints**

#     **if producer\_hint := extract\_producer\_hint(record.value):**

#         **return ProducerIdentity(id=producer\_hint, confidence='LOW')**

#     

#     **return ProducerIdentity(id='UNKNOWN', confidence='NONE')**

# 

### **1.3 Evidence Schema (Enforcer Output)**

# **{**

#   **"$schema": "http://json-schema.org/draft-07/schema\#",**

#   **"$id": "urn:schema:evidence:2",**

#   **"type": "object",**

#   **"required": \["evidence\_id", "timestamp", "dataset\_urn", "validation", "source"\],**

#   **"properties": {**

#     **"evidence\_id": {**

#       **"type": "string",**

#       **"pattern": "^evd-\[0-9A-HJKMNP-TV-Z\]{26}$",**

#       **"description": "ULID prefixed with evd-"**

#     **},**

#     **"timestamp": {**

#       **"type": "string",**

#       **"format": "date-time"**

#     **},**

#     **"dataset\_urn": {**

#       **"type": "string",**

#       **"pattern": "^urn:dp:\[a-z\_\]+:\[a-z\_\]+$"**

#     **},**

#     **"producer": {**

#       **"type": "object",**

#       **"properties": {**

#         **"id": { "type": "string" },**

#         **"confidence": { "enum": \["HIGH", "MEDIUM", "LOW", "NONE"\] },**

#         **"version": { "type": "string" }**

#       **}**

#     **},**

#     **"validation": {**

#       **"type": "object",**

#       **"properties": {**

#         **"result": { "enum": \["PASS", "FAIL", "WARN"\] },**

#         **"gates": {**

#           **"type": "array",**

#           **"items": {**

#             **"type": "object",**

#             **"properties": {**

#               **"gate": { "enum": \["G1\_RESOLUTION", "G2\_IDENTITY", "G3\_SCHEMA", "G4\_CONTRACT", "G5\_PII"\] },**

#               **"result": { "enum": \["PASS", "FAIL", "SKIP", "WARN"\] },**

#               **"reason\_code": { "type": "string" },**

#               **"details": { "type": "object" }**

#             **}**

#           **}**

#         **}**

#       **}**

#     **},**

#     **"source": {**

#       **"type": "object",**

#       **"properties": {**

#         **"topic": { "type": "string" },**

#         **"partition": { "type": "integer" },**

#         **"offset": { "type": "integer" },**

#         **"timestamp\_type": { "enum": \["CREATE\_TIME", "LOG\_APPEND\_TIME"\] }**

#       **}**

#     **},**

#     **"otel": {**

#       **"type": "object",**

#       **"properties": {**

#         **"trace\_id": { "type": "string", "pattern": "^\[a-f0-9\]{32}$" },**

#         **"span\_id": { "type": "string", "pattern": "^\[a-f0-9\]{16}$" },**

#         **"trace\_flags": { "type": "integer" }**

#       **}**

#     **},**

#     **"lineage": {**

#       **"type": "object",**

#       **"properties": {**

#         **"upstream\_urns": { "type": "array", "items": { "type": "string" } },**

#         **"job\_urn": { "type": "string" }**

#       **}**

#     **}**

#   **}**

# **}**

# 

# ---

## **2\. Batch Emit Scenarios (Spark/Airflow → Delta/S3)**

### **2.1 The Correlation Challenge**

# **Batch is where correlation breaks. Here's the 5 Whys:**

1. # **Why does RCA fail for batch? → Can't trace from failed Delta write back to source**

2. # **Why can't we trace? → No correlation ID spans the boundary**

3. # **Why no correlation ID? → Spark doesn't propagate OTel across shuffles**

4. # **Why doesn't Spark propagate? → Distributed execution model; executors are isolated**

5. # **Why are executors isolated? → Spark's fundamental architecture**

# **Alternative: OpenLineage as the Batch Correlation Mechanism**

# **┌───────────────────────────────────────────────────────────────────────────┐**

# **│                        AIRFLOW DAG: orders\_daily\_agg                       │**

# **├───────────────────────────────────────────────────────────────────────────┤**

# **│                                                                           │**

# **│  Task 1: extract        Task 2: transform       Task 3: load              │**

# **│  ┌─────────────┐        ┌─────────────┐        ┌─────────────┐            │**

# **│  │ Read Kafka  │───────►│ Spark Job   │───────►│ Write Delta │            │**

# **│  │ (bronze)    │        │ (silver)    │        │ (gold)      │            │**

# **│  └─────────────┘        └─────────────┘        └─────────────┘            │**

# **│        │                       │                      │                   │**

# **│        ▼                       ▼                      ▼                   │**

# **│  OpenLineage:            OpenLineage:           OpenLineage:              │**

# **│  RunEvent(START)         RunEvent(START)        RunEvent(COMPLETE)        │**

# **│  inputs: \[kafka:raw\]     inputs: \[s3:bronze\]    inputs: \[s3:silver\]       │**

# **│  outputs: \[s3:bronze\]    outputs: \[s3:silver\]   outputs: \[delta:gold\]     │**

# **│                                                                           │**

# **│  dag\_run\_id: run-2024-01-15-001 (COMMON ACROSS ALL TASKS)                │**

# **└───────────────────────────────────────────────────────────────────────────┘**

# 

### **2.2 OpenLineage Event Schema (Batch Lineage)**

# **{**

#   **"$schema": "https://openlineage.io/spec/2-0-2/OpenLineage.json",**

#   **"eventType": "COMPLETE",**

#   **"eventTime": "2024-01-15T08:30:00Z",**

#   **"run": {**

#     **"runId": "run-2024-01-15-001",**

#     **"facets": {**

#       **"spark\_version": { "version": "3.5.0" },**

#       **"spark.logicalPlan": { "plan": "..." },**

#       **"parent": {**

#         **"job": { "namespace": "airflow", "name": "orders\_daily\_agg" },**

#         **"run": { "runId": "dag-run-xyz" }**

#       **},**

#       **"observability": {**

#         **"\_producer": "https://github.com/your-org/signal-factory",**

#         **"\_schemaURL": "urn:schema:ol-obs-facet:1",**

#         **"evidence\_summary": {**

#           **"records\_processed": 1247000,**

#           **"records\_passed": 1240000,**

#           **"records\_failed": 7000,**

#           **"failure\_signatures": \[**

#             **{ "reason": "MISSING\_FIELD:customer\_id", "count": 6800 },**

#             **{ "reason": "INVALID\_FORMAT:email", "count": 200 }**

#           **\]**

#         **}**

#       **}**

#     **}**

#   **},**

#   **"job": {**

#     **"namespace": "spark",**

#     **"name": "orders\_silver\_transform",**

#     **"facets": {**

#       **"sql": { "query": "SELECT ... FROM bronze WHERE ..." }**

#     **}**

#   **},**

#   **"inputs": \[**

#     **{**

#       **"namespace": "s3://data-lake",**

#       **"name": "bronze/orders/2024-01-15",**

#       **"facets": {**

#         **"dataSource": { "name": "s3", "uri": "s3://data-lake/bronze/orders" },**

#         **"schema": {**

#           **"fields": \[**

#             **{ "name": "order\_id", "type": "STRING" },**

#             **{ "name": "customer\_id", "type": "STRING" },**

#             **{ "name": "total\_amount", "type": "DECIMAL(10,2)" }**

#           **\]**

#         **}**

#       **}**

#     **}**

#   **\],**

#   **"outputs": \[**

#     **{**

#       **"namespace": "delta://unity-catalog",**

#       **"name": "sales.orders\_silver",**

#       **"facets": {**

#         **"outputStatistics": {**

#           **"rowCount": 1240000,**

#           **"size": 45000000**

#         **},**

#         **"columnLineage": {**

#           **"fields": \[**

#             **{**

#               **"name": "customer\_id",**

#               **"inputFields": \[**

#                 **{ "namespace": "s3://data-lake", "name": "bronze/orders", "field": "customer\_id" }**

#               **\]**

#             **}**

#           **\]**

#         **}**

#       **}**

#     **}**

#   **\]**

# **}**

# 

### **2.3 Batch Evidence Emit Pattern**

# **The Policy Enforcer doesn't directly observe Spark. Instead, we inject validation into the Spark job itself:**

# **\# spark\_job\_with\_evidence.py**

# **from pyspark.sql import SparkSession**

# **from pyspark.sql.functions import col, lit, when, struct, to\_json**

# **from openlineage.spark import OpenLineageSparkListener**

# 

# **spark \= SparkSession.builder \\**

#     **.appName("orders\_silver\_transform") \\**

#     **.config("spark.extraListeners", "io.openlineage.spark.agent.OpenLineageSparkListener") \\**

#     **.getOrCreate()**

# 

# **\# Read bronze**

# **bronze\_df \= spark.read.parquet("s3://data-lake/bronze/orders/2024-01-15")**

# 

# **\# Validate and create evidence inline**

# **validated\_df \= bronze\_df.withColumn(**

#     **"evidence",**

#     **struct(**

#         **lit("evd-").alias("prefix"),**

#         **col("order\_id").alias("source\_id"),**

#         **when(col("customer\_id").isNull(), "FAIL").otherwise("PASS").alias("result"),**

#         **when(col("customer\_id").isNull(), "MISSING\_FIELD:customer\_id").otherwise(None).alias("reason")**

#     **)**

# **)**

# 

# **\# Split: good records to silver, evidence to evidence topic**

# **good\_records \= validated\_df.filter(col("evidence.result") \== "PASS")**

# **failed\_evidence \= validated\_df.filter(col("evidence.result") \== "FAIL") \\**

#     **.select(to\_json(col("evidence")).alias("value"))**

# 

# **\# Write good records to Delta**

# **good\_records.drop("evidence").write \\**

#     **.format("delta") \\**

#     **.mode("append") \\**

#     **.saveAsTable("sales.orders\_silver")**

# 

# **\# Emit evidence to Kafka (for Signal Engines)**

# **failed\_evidence.write \\**

#     **.format("kafka") \\**

#     **.option("kafka.bootstrap.servers", "msk.internal:9092") \\**

#     **.option("topic", "signal\_factory.evidence") \\**

#     **.save()**

# 

### **2.4 Batch-to-Graph Linkage**

# **Neptune Graph Edges for Batch:**

# 

# **(DAGRun:run-2024-01-15-001) \--\[EXECUTED\]--\> (SparkJob:orders\_silver\_transform)**

# **(SparkJob:orders\_silver\_transform) \--\[READ\]--\> (Dataset:s3://data-lake/bronze/orders)**

# **(SparkJob:orders\_silver\_transform) \--\[WROTE\]--\> (Dataset:delta://sales.orders\_silver)**

# **(SparkJob:orders\_silver\_transform) \--\[PRODUCED\]--\> (FailureSignature:MISSING\_FIELD:customer\_id)**

# **(FailureSignature:MISSING\_FIELD:customer\_id) \--\[CAUSED\]--\> (Signal:DQBreach:orders\_silver)**

# 

# ---

## **3\. Stream Emit Scenarios (Kafka Streams / Flink)**

### **3.1 Stream Processing Architecture**

# **┌─────────────────────────────────────────────────────────────────────────┐**

# **│                    STREAMING TOPOLOGY: enrichment-stream                 │**

# **├─────────────────────────────────────────────────────────────────────────┤**

# **│                                                                         │**

# **│  raw.orders.events                                                      │**

# **│        │                                                                │**

# **│        ▼                                                                │**

# **│  ┌───────────┐     ┌───────────┐     ┌───────────┐                     │**

# **│  │  Filter   │────►│  Enrich   │────►│  Validate │                     │**

# **│  │ (schema)  │     │ (lookup)  │     │ (contract)│                     │**

# **│  └───────────┘     └───────────┘     └───────────┘                     │**

# **│        │                 │                 │                            │**

# **│        ▼                 ▼                 ▼                            │**

# **│   EMIT: schema      EMIT: enriched    EMIT: validated                  │**

# **│   evidence          evidence          evidence                          │**

# **│        │                 │                 │                            │**

# **│        └────────────────┴────────────┬────┘                            │**

# **│                                      ▼                                  │**

# **│                          signal\_factory.evidence                        │**

# **│                                      │                                  │**

# **│                                      ▼                                  │**

# **│                          enriched.orders.events                         │**

# **│                                                                         │**

# **└─────────────────────────────────────────────────────────────────────────┘**

# 

### **3.2 Stream Evidence Schema (Extended)**

# **For streams, we need additional facets to track windowing and processing state:**

# **{**

#   **"$id": "urn:schema:stream-evidence:1",**

#   **"allOf": \[**

#     **{ "$ref": "urn:schema:evidence:2" }**

#   **\],**

#   **"properties": {**

#     **"stream": {**

#       **"type": "object",**

#       **"properties": {**

#         **"topology\_id": {** 

#           **"type": "string",**

#           **"description": "Kafka Streams application.id or Flink job ID"**

#         **},**

#         **"processor\_node": {**

#           **"type": "string",**

#           **"description": "Which processor in the topology emitted this"**

#         **},**

#         **"window": {**

#           **"type": "object",**

#           **"properties": {**

#             **"type": { "enum": \["TUMBLING", "HOPPING", "SESSION", "NONE"\] },**

#             **"start": { "type": "string", "format": "date-time" },**

#             **"end": { "type": "string", "format": "date-time" }**

#           **}**

#         **},**

#         **"watermark": {**

#           **"type": "string",**

#           **"format": "date-time",**

#           **"description": "Event-time watermark when evidence was emitted"**

#         **},**

#         **"processing\_time": {**

#           **"type": "string",**

#           **"format": "date-time"**

#         **},**

#         **"late\_data": {**

#           **"type": "boolean",**

#           **"description": "Was this record late (arrived after watermark)?"**

#         **}**

#       **}**

#     **}**

#   **}**

# **}**

# 

### **3.3 Flink Evidence Emitter (Example)**

# **public class EvidenceEmittingValidator extends ProcessFunction\<OrderEvent, EnrichedOrder\> {**

#     

#     **private final OutputTag\<Evidence\> evidenceOutput \= new OutputTag\<\>("evidence") {};**

#     

#     **@Override**

#     **public void processElement(OrderEvent event, Context ctx, Collector\<EnrichedOrder\> out) {**

#         

#         **ValidationResult validation \= validateContract(event);**

#         

#         **// Always emit evidence (PASS or FAIL)**

#         **Evidence evidence \= Evidence.builder()**

#             **.evidenceId(generateULID())**

#             **.timestamp(Instant.now())**

#             **.datasetUrn("urn:dp:orders:enriched")**

#             **.producer(ProducerIdentity.builder()**

#                 **.id("enrichment-stream")**

#                 **.confidence(Confidence.HIGH)**

#                 **.build())**

#             **.validation(validation)**

#             **.source(SourceRef.builder()**

#                 **.topic(event.getSourceTopic())**

#                 **.partition(event.getPartition())**

#                 **.offset(event.getOffset())**

#                 **.build())**

#             **.otel(OtelContext.builder()**

#                 **.traceId(event.getTraceId())**

#                 **.spanId(generateSpanId())**

#                 **.build())**

#             **.stream(StreamContext.builder()**

#                 **.topologyId(getRuntimeContext().getJobId().toString())**

#                 **.processorNode("contract-validator")**

#                 **.watermark(ctx.timerService().currentWatermark())**

#                 **.processingTime(ctx.timerService().currentProcessingTime())**

#                 **.lateData(event.getTimestamp() \< ctx.timerService().currentWatermark())**

#                 **.build())**

#             **.build();**

#         

#         **ctx.output(evidenceOutput, evidence);**

#         

#         **// Only emit enriched record if validation passed**

#         **if (validation.isPassed()) {**

#             **out.collect(enrich(event));**

#         **}**

#     **}**

# **}**

# 

### **3.4 Stream Correlation Strategy**

# **Problem: In streaming, a single source event might trigger multiple downstream events (fan-out) or multiple source events aggregate into one (fan-in).**

# **Solution: Correlation Chain**

# **{**

#   **"evidence\_id": "evd-01HQX...",**

#   **"correlation\_chain": {**

#     **"root\_trace\_id": "abc123...",**

#     **"causal\_chain": \[**

#       **{**

#         **"step": 1,**

#         **"source\_evidence\_id": "evd-01HQW...",**

#         **"relationship": "DERIVED\_FROM"**

#       **},**

#       **{**

#         **"step": 2,**

#         **"source\_evidence\_id": "evd-01HQV...",**

#         **"relationship": "AGGREGATED\_WITH"**

#       **}**

#     **\]**

#   **}**

# **}**

# 

# ---

## **4\. Cross-Cutting: Signal Engine Consumption Patterns**

### **4.1 Signal Schema (Engine Output)**

# **{**

#   **"$id": "urn:schema:signal:1",**

#   **"type": "object",**

#   **"required": \["signal\_id", "signal\_type", "dataset\_urn", "state", "window"\],**

#   **"properties": {**

#     **"signal\_id": { "type": "string", "pattern": "^sig-\[0-9A-Z\]{26}$" },**

#     **"signal\_type": {**

#       **"enum": \[**

#         **"FRESHNESS\_BREACH",**

#         **"VOLUME\_ANOMALY",**

#         **"CONTRACT\_BREACH",**

#         **"DQ\_BREACH",**

#         **"DRIFT\_DETECTED",**

#         **"COST\_ANOMALY"**

#       **\]**

#     **},**

#     **"dataset\_urn": { "type": "string" },**

#     **"state": { "enum": \["OK", "WARNING", "CRITICAL", "UNKNOWN"\] },**

#     **"window": {**

#       **"type": "object",**

#       **"properties": {**

#         **"start": { "type": "string", "format": "date-time" },**

#         **"end": { "type": "string", "format": "date-time" },**

#         **"type": { "enum": \["TUMBLING\_5MIN", "TUMBLING\_1HR", "SLIDING\_15MIN"\] }**

#       **}**

#     **},**

#     **"metrics": {**

#       **"type": "object",**

#       **"properties": {**

#         **"evidence\_count": { "type": "integer" },**

#         **"pass\_count": { "type": "integer" },**

#         **"fail\_count": { "type": "integer" },**

#         **"compliance\_rate": { "type": "number", "minimum": 0, "maximum": 1 },**

#         **"slo\_threshold": { "type": "number" }**

#       **}**

#     **},**

#     **"top\_failures": {**

#       **"type": "array",**

#       **"maxItems": 5,**

#       **"items": {**

#         **"type": "object",**

#         **"properties": {**

#           **"signature": { "type": "string" },**

#           **"count": { "type": "integer" },**

#           **"first\_seen": { "type": "string", "format": "date-time" }**

#         **}**

#       **}**

#     **},**

#     **"evidence\_refs": {**

#       **"type": "array",**

#       **"description": "Sample of evidence IDs for drill-down",**

#       **"maxItems": 10,**

#       **"items": { "type": "string" }**

#     **}**

#   **}**

# **}**

# 

# ---

## **5\. Summary: Emit Decision Matrix**

| Scenario | Who Emits Evidence? | Correlation Mechanism | Graph Linkage |
| ----- | ----- | ----- | ----- |
| **Service → Kafka** | **Policy Enforcer (sidecar)** | **OTel trace\_id in headers** | **Deployment → FailureSignature** |
| **Batch (Spark)** | **Spark job inline** | **OpenLineage run\_id** | **DAGRun → SparkJob → Dataset** |
| **Batch (Airflow)** | **Airflow callbacks** | **dag\_run\_id** | **DAG → Task → Dataset** |
| **Stream (KStreams)** | **Processor node** | **trace\_id \+ topology\_id** | **Topology → Processor → Evidence** |
| **Stream (Flink)** | **ProcessFunction** | **trace\_id \+ job\_id** | **FlinkJob → Operator → Evidence** |
| **Direct S3 Write** | **S3 Event trigger → Lambda** | **Object key \+ metadata** | **S3Object → Evidence** |

# ---

## **6\. Hidden Assumptions & Alternatives**

# **Assumption 1: All events fit in a single Kafka record**

* # **Alternative: For large payloads, emit evidence with `payload_ref: s3://evidence-archive/{id}` and async hydration**

# **Assumption 2: Evidence Bus can handle the volume**

* # **5 Whys: Why might it fail? → High cardinality topics → Many partitions needed → Consumer lag → Signal staleness**

* # **Alternative: Tiered evidence (sample at 10% for Tier-3, 100% for Tier-1)**

# **Assumption 3: Schema Registry is always available**

* # **Alternative: Enforcer caches last-known-good schema; emits `WARN` with `REGISTRY_STALE` flag**

# **Cost of Action: \~2ms per record for full gate pipeline Cost of Inaction: Blind spots in Tier-3 assets until incident occurs**

# **Would you like me to dive deeper into any specific emit scenario, or explore the Neptune graph model for causal traversal?**

# 

# 

# **Two Common Emit Scenarios: Step-by-Step Walkthrough**

I'll trace through two real-world scenarios end-to-end, showing the actual payloads at each step.

---

## **Scenario 1: Service Deployment Breaks Contract**

**Context**: Orders Service deploys hotfix v3.17 at 09:58 AM. A developer accidentally removed the line that populates `customer_id`. This field is required by the downstream Finance pipeline.

---

### **Step 1: Producer Emits to Kafka**

**What Happens**: Orders Service handles an HTTP request and publishes to Kafka.

Timeline: 09:58:02.127 AM

**HTTP Request Received by orders-svc**:

POST /api/v1/orders HTTP/1.1  
Host: orders.internal  
X-Request-Id: req-7721  
traceparent: 00-ab91f3c2d4e5f6a7b8c9d0e1f2a3b4c5-1234567890abcdef-01

{  
  "customer\_id": "cust-98765",  
  "items": \[{"sku": "WIDGET-001", "qty": 2, "price": 74.99}\],  
  "shipping\_address": {...}  
}

**Application Code (the bug)**:

\# orders-svc/handlers/create\_order.py

async def handle\_create\_order(request: OrderRequest) \-\> OrderResponse:  
    order \= Order(  
        order\_id=generate\_order\_id(),  
        \# BUG: Developer commented this out during debugging and forgot to restore  
        \# customer\_id=request.customer\_id,    
        total\_amount=calculate\_total(request.items),  
        currency="USD",  
        created\_at=datetime.utcnow()  
    )  
      
    \# Publish to Kafka  
    event \= OrderCreatedEvent(  
        event\_id=generate\_ulid(),  
        event\_type="orders.created.v1",  
        timestamp=datetime.utcnow().isoformat(),  
        payload=order.dict(),  
        metadata={  
            "correlation\_id": request.trace\_id,  
            "producer\_service": "orders-svc",  
            "producer\_version": os.getenv("SERVICE\_VERSION")  \# "v3.17"  
        }  
    )  
      
    await kafka\_producer.send(  
        topic="raw.orders.events",  
        value=event.json().encode(),  
        headers=\[  
            ("x-obs-trace-id", request.trace\_id.encode()),  
            ("x-obs-producer-service", b"orders-svc"),  
            ("x-obs-producer-version", b"v3.17"),  
            ("x-obs-schema-id", b"glue:orders.created:17")  
        \]  
    )  
      
    return OrderResponse(order\_id=order.order\_id, status="CREATED")

**Kafka Record Published**:

Topic: raw.orders.events  
Partition: 4  
Offset: 9918273  
Timestamp: 2024-01-15T09:58:02.127Z

Headers:  
  x-obs-trace-id: ab91f3c2d4e5f6a7b8c9d0e1f2a3b4c5  
  x-obs-producer-service: orders-svc  
  x-obs-producer-version: v3.17  
  x-obs-schema-id: glue:orders.created:17

Value (JSON):  
{  
  "event\_id": "01HQX7YMKP3QR5ST6VW8XYZ123",  
  "event\_type": "orders.created.v1",  
  "timestamp": "2024-01-15T09:58:02.127Z",  
  "payload": {  
    "order\_id": "ORD-2024-0115-99123",  
    "total\_amount": 149.98,  
    "currency": "USD",  
    "created\_at": "2024-01-15T09:58:02.100Z"  
  },  
  "metadata": {  
    "correlation\_id": "ab91f3c2d4e5f6a7b8c9d0e1f2a3b4c5",  
    "producer\_service": "orders-svc",  
    "producer\_version": "v3.17"  
  }  
}

**Notice**: The `customer_id` field is completely missing from the payload.

---

### **Step 2: Policy Enforcer Consumes and Validates**

**What Happens**: The Policy Enforcer (running as a sidecar consumer) picks up the record and runs it through the 5-gate pipeline.

Timeline: 09:58:02.312 AM (185ms after publish)

**Enforcer Processing**:

\# policy\_enforcer/pipeline.py

class GatePipeline:  
    def process(self, record: KafkaRecord) \-\> Evidence:  
        evidence\_builder \= EvidenceBuilder(  
            evidence\_id=f"evd-{generate\_ulid()}",  
            timestamp=datetime.utcnow()  
        )  
          
        \# ═══════════════════════════════════════════════════════  
        \# GATE 1: Resolution (Topic → Dataset URN)  
        \# ═══════════════════════════════════════════════════════  
        g1\_result \= self.gate\_resolution.run(record)  
        \# Lookup: raw.orders.events → urn:dp:orders:created  
        \# Result: PASS  
          
        evidence\_builder.add\_gate\_result(  
            gate="G1\_RESOLUTION",  
            result="PASS",  
            details={"dataset\_urn": "urn:dp:orders:created"}  
        )  
        evidence\_builder.set\_dataset\_urn("urn:dp:orders:created")  
          
        \# ═══════════════════════════════════════════════════════  
        \# GATE 2: Identity (Who sent this?)  
        \# ═══════════════════════════════════════════════════════  
        g2\_result \= self.gate\_identity.run(record)  
        \# Found header: x-obs-producer-service \= orders-svc  
        \# Confidence: HIGH (explicit header present)  
          
        evidence\_builder.add\_gate\_result(  
            gate="G2\_IDENTITY",  
            result="PASS",  
            details={"producer": "orders-svc", "confidence": "HIGH", "version": "v3.17"}  
        )  
        evidence\_builder.set\_producer("orders-svc", "HIGH", "v3.17")  
          
        \# ═══════════════════════════════════════════════════════  
        \# GATE 3: Schema Validation (vs Glue Registry)  
        \# ═══════════════════════════════════════════════════════  
        g3\_result \= self.gate\_schema.run(record)  
        \# Fetch schema: glue:orders.created:17  
        \# Schema defines customer\_id as OPTIONAL (nullable: true)  
        \# Result: PASS (schema allows missing optional fields)  
          
        evidence\_builder.add\_gate\_result(  
            gate="G3\_SCHEMA",  
            result="PASS",  
            details={"schema\_id": "glue:orders.created:17", "schema\_version": 17}  
        )  
          
        \# ═══════════════════════════════════════════════════════  
        \# GATE 4: Contract Validation (vs ODCS Contract)  
        \# ═══════════════════════════════════════════════════════  
        g4\_result \= self.gate\_contract.run(record)  
        \# Fetch contract: dc:orders.created:3  
        \# Contract specifies: customer\_id is REQUIRED for downstream consumers  
        \# Check payload... customer\_id is MISSING  
        \# Result: FAIL  
          
        evidence\_builder.add\_gate\_result(  
            gate="G4\_CONTRACT",  
            result="FAIL",  
            reason\_code="MISSING\_FIELD:customer\_id",  
            details={  
                "contract\_id": "dc:orders.created:3",  
                "contract\_version": 3,  
                "violated\_rule": {  
                    "field": "customer\_id",  
                    "constraint": "required",  
                    "actual": "null"  
                }  
            }  
        )  
          
        \# ═══════════════════════════════════════════════════════  
        \# GATE 5: PII Detection  
        \# ═══════════════════════════════════════════════════════  
        g5\_result \= self.gate\_pii.run(record)  
        \# Scan payload for PII patterns (SSN, email, phone, etc.)  
        \# No PII detected in this record  
        \# Result: PASS  
          
        evidence\_builder.add\_gate\_result(  
            gate="G5\_PII",  
            result="PASS",  
            details={"pii\_detected": False}  
        )  
          
        \# ═══════════════════════════════════════════════════════  
        \# BUILD FINAL EVIDENCE  
        \# ═══════════════════════════════════════════════════════  
        return evidence\_builder.build(  
            overall\_result="FAIL",  \# Any gate failure \= overall FAIL  
            failed\_gates=\["G4\_CONTRACT"\],  
            source={  
                "topic": record.topic,  
                "partition": record.partition,  
                "offset": record.offset  
            },  
            otel={  
                "trace\_id": record.headers.get("x-obs-trace-id")  
            }  
        )

**Evidence Event Emitted to `signal_factory.evidence`**:

{  
  "evidence\_id": "evd-01HQXY8MNP4QR7ST9VW2XYZ456",  
  "timestamp": "2024-01-15T09:58:02.312Z",  
  "dataset\_urn": "urn:dp:orders:created",  
  "producer": {  
    "id": "orders-svc",  
    "confidence": "HIGH",  
    "version": "v3.17"  
  },  
  "validation": {  
    "result": "FAIL",  
    "gates": \[  
      {  
        "gate": "G1\_RESOLUTION",  
        "result": "PASS",  
        "details": { "dataset\_urn": "urn:dp:orders:created" }  
      },  
      {  
        "gate": "G2\_IDENTITY",  
        "result": "PASS",  
        "details": { "producer": "orders-svc", "confidence": "HIGH", "version": "v3.17" }  
      },  
      {  
        "gate": "G3\_SCHEMA",  
        "result": "PASS",  
        "details": { "schema\_id": "glue:orders.created:17" }  
      },  
      {  
        "gate": "G4\_CONTRACT",  
        "result": "FAIL",  
        "reason\_code": "MISSING\_FIELD:customer\_id",  
        "details": {  
          "contract\_id": "dc:orders.created:3",  
          "violated\_rule": {  
            "field": "customer\_id",  
            "constraint": "required",  
            "actual": "null"  
          }  
        }  
      },  
      {  
        "gate": "G5\_PII",  
        "result": "PASS",  
        "details": { "pii\_detected": false }  
      }  
    \],  
    "failed\_gates": \["G4\_CONTRACT"\],  
    "reason\_codes": \["MISSING\_FIELD:customer\_id"\]  
  },  
  "source": {  
    "topic": "raw.orders.events",  
    "partition": 4,  
    "offset": 9918273,  
    "timestamp\_type": "CREATE\_TIME"  
  },  
  "otel": {  
    "trace\_id": "ab91f3c2d4e5f6a7b8c9d0e1f2a3b4c5"  
  }  
}

---

### **Step 3: Signal Engine Aggregates Evidence**

**What Happens**: The Contract Compliance Signal Engine consumes from the Evidence Bus and computes aggregate metrics over a 5-minute tumbling window.

Timeline: 10:00:00.000 AM (Window closes: 09:55 \- 10:00)

**Signal Engine Processing**:

\# signal\_engines/contract\_compliance.py

class ContractComplianceEngine:  
    def \_\_init\_\_(self):  
        self.window\_duration \= timedelta(minutes=5)  
        self.state\_store \= DynamoDBStateStore()  
        self.graph\_client \= NeptuneClient()  
      
    def process\_window(self, dataset\_urn: str, window\_start: datetime, window\_end: datetime):  
        \# Query evidence from window  
        evidence\_batch \= self.evidence\_consumer.get\_window(  
            dataset\_urn=dataset\_urn,  
            start=window\_start,  
            end=window\_end  
        )  
          
        \# Aggregate  
        total\_count \= len(evidence\_batch)  
        pass\_count \= sum(1 for e in evidence\_batch if e.validation.result \== "PASS")  
        fail\_count \= total\_count \- pass\_count  
        compliance\_rate \= pass\_count / total\_count if total\_count \> 0 else 1.0  
          
        \# For this window (09:55 \- 10:00):  
        \# total\_count: 1,247  
        \# pass\_count: 127    
        \# fail\_count: 1,120  
        \# compliance\_rate: 0.102 (10.2%)  
          
        \# Get SLO threshold from Control Plane  
        slo \= self.control\_plane.get\_slo(dataset\_urn, "contract\_compliance")  
        \# slo.threshold \= 0.95 (95%)  
          
        \# Determine state  
        if compliance\_rate \>= slo.threshold:  
            state \= "OK"  
        elif compliance\_rate \>= slo.warning\_threshold:  \# 0.80  
            state \= "WARNING"  
        else:  
            state \= "CRITICAL"  
          
        \# state \= "CRITICAL" (10.2% \< 95%)  
          
        \# Group failures by signature  
        failure\_signatures \= self.group\_by\_signature(evidence\_batch)  
        \# Result:  
        \# \[  
        \#   {"signature": "MISSING\_FIELD:customer\_id", "count": 1120, "first\_seen": "09:58:02Z"}  
        \# \]  
          
        \# Build signal  
        signal \= Signal(  
            signal\_id=f"sig-{generate\_ulid()}",  
            signal\_type="CONTRACT\_BREACH",  
            dataset\_urn=dataset\_urn,  
            state=state,  
            window={  
                "start": window\_start.isoformat(),  
                "end": window\_end.isoformat(),  
                "type": "TUMBLING\_5MIN"  
            },  
            metrics={  
                "evidence\_count": total\_count,  
                "pass\_count": pass\_count,  
                "fail\_count": fail\_count,  
                "compliance\_rate": compliance\_rate,  
                "slo\_threshold": slo.threshold  
            },  
            top\_failures=failure\_signatures\[:5\],  
            evidence\_refs=\[e.evidence\_id for e in evidence\_batch\[:10\]\]  
        )  
          
        return signal

**Signal Emitted**:

{  
  "signal\_id": "sig-01HQXZ2NPQ5RS8TU0VW3XYZ789",  
  "signal\_type": "CONTRACT\_BREACH",  
  "dataset\_urn": "urn:dp:orders:created",  
  "state": "CRITICAL",  
  "window": {  
    "start": "2024-01-15T09:55:00.000Z",  
    "end": "2024-01-15T10:00:00.000Z",  
    "type": "TUMBLING\_5MIN"  
  },  
  "metrics": {  
    "evidence\_count": 1247,  
    "pass\_count": 127,  
    "fail\_count": 1120,  
    "compliance\_rate": 0.102,  
    "slo\_threshold": 0.95  
  },  
  "top\_failures": \[  
    {  
      "signature": "MISSING\_FIELD:customer\_id",  
      "count": 1120,  
      "first\_seen": "2024-01-15T09:58:02.312Z",  
      "producer": "orders-svc",  
      "producer\_version": "v3.17"  
    }  
  \],  
  "evidence\_refs": \[  
    "evd-01HQXY8MNP4QR7ST9VW2XYZ456",  
    "evd-01HQXY8MNP4QR7ST9VW2XYZ457",  
    "evd-01HQXY8MNP4QR7ST9VW2XYZ458"  
  \]  
}

---

### **Step 4: State Written to DynamoDB & Graph Updated**

**What Happens**: The Signal Engine persists state for dashboards and updates Neptune for RCA.

Timeline: 10:00:00.500 AM

**DynamoDB Write**:

// Table: SignalState  
{  
  "PK": "urn:dp:orders:created",  
  "SK": "contract\_compliance",  
  "state": "CRITICAL",  
  "score": 0.102,  
  "breach\_start": "2024-01-15T09:58:02.312Z",  
  "last\_updated": "2024-01-15T10:00:00.500Z",  
  "window\_end": "2024-01-15T10:00:00.000Z",  
  "failure\_signature": "MISSING\_FIELD:customer\_id",  
  "top\_producer": "orders-svc",  
  "top\_producer\_version": "v3.17",  
  "evidence\_sample": \["evd-01HQXY8MNP4QR7ST9VW2XYZ456"\]  
}

**Neptune Graph Updates**:

// Create or update FailureSignature node  
MERGE (fs:FailureSignature {id: "MISSING\_FIELD:customer\_id:urn:dp:orders:created"})  
SET fs.reason\_code \= "MISSING\_FIELD:customer\_id",  
    fs.dataset\_urn \= "urn:dp:orders:created",  
    fs.first\_seen \= datetime("2024-01-15T09:58:02.312Z"),  
    fs.occurrence\_count \= 1120

// Link deployment to failure signature  
MATCH (d:Deployment {service: "orders-svc", version: "v3.17"})  
MERGE (d)-\[:INTRODUCED {  
  first\_evidence: "evd-01HQXY8MNP4QR7ST9VW2XYZ456",  
  timestamp: datetime("2024-01-15T09:58:02.312Z")  
}\]-\>(fs)

// Create Signal node  
CREATE (s:Signal {  
  id: "sig-01HQXZ2NPQ5RS8TU0VW3XYZ789",  
  type: "CONTRACT\_BREACH",  
  state: "CRITICAL",  
  timestamp: datetime("2024-01-15T10:00:00.000Z")  
})

// Link failure signature to signal  
MATCH (fs:FailureSignature {id: "MISSING\_FIELD:customer\_id:urn:dp:orders:created"})  
MERGE (fs)-\[:CAUSED\]-\>(s)

// Link signal to dataset  
MATCH (ds:Dataset {urn: "urn:dp:orders:created"})  
MERGE (s)-\[:AFFECTS\]-\>(ds)

**Graph State After Step 4**:

(Deployment:orders-svc:v3.17)  
         │  
         │ \[INTRODUCED\]  
         │ first\_evidence: evd-01HQXY8MNP...  
         │ timestamp: 09:58:02Z  
         ▼  
(FailureSignature:MISSING\_FIELD:customer\_id)  
         │  
         │ \[CAUSED\]  
         ▼  
(Signal:CONTRACT\_BREACH:CRITICAL)  
         │  
         │ \[AFFECTS\]  
         ▼  
(Dataset:urn:dp:orders:created)  
         │  
         │ \[OWNED\_BY\]  
         ▼  
(Service:orders-svc)

---

### **Step 5: Incident Created and Alert Fired**

**What Happens**: The Alerting Engine detects the CRITICAL state on a Tier-1 asset and creates an incident.

Timeline: 10:00:01.200 AM

**Alerting Engine Logic**:

\# alerting/engine.py

class AlertingEngine:  
    def evaluate\_signal(self, signal: Signal):  
        \# Get dataset tier  
        dataset\_meta \= self.registry.get\_dataset(signal.dataset\_urn)  
        \# urn:dp:orders:created → Tier 1 (revenue-critical)  
          
        \# Determine severity based on state \+ tier  
        severity \= self.calculate\_severity(signal.state, dataset\_meta.tier)  
        \# CRITICAL state \+ Tier 1 \= SEV-1  
          
        if severity in \["SEV-1", "SEV-2"\]:  
            incident \= self.create\_incident(signal, severity, dataset\_meta)  
            self.notify(incident)

**Incident Created**:

{  
  "incident\_id": "INC-7721",  
  "severity": "SEV-1",  
  "title": "Contract Violation \- orders:created \- MISSING\_FIELD:customer\_id",  
  "status": "OPEN",  
  "created\_at": "2024-01-15T10:00:01.200Z",  
  "dataset\_urn": "urn:dp:orders:created",  
  "signal\_id": "sig-01HQXZ2NPQ5RS8TU0VW3XYZ789",  
  "failure\_signature": "MISSING\_FIELD:customer\_id",  
  "suspected\_producer": {  
    "service": "orders-svc",  
    "version": "v3.17",  
    "confidence": "HIGH"  
  },  
  "impact": {  
    "tier": 1,  
    "classification": "revenue-critical",  
    "downstream\_consumers": \["finance-pipeline", "analytics-dashboard", "crm-sync"\]  
  },  
  "evidence\_summary": {  
    "total\_events": 1247,  
    "failed\_events": 1120,  
    "failure\_rate": "89.8%",  
    "first\_failure": "2024-01-15T09:58:02.312Z"  
  },  
  "primary\_evidence\_id": "evd-01HQXY8MNP4QR7ST9VW2XYZ456",  
  "primary\_trace\_id": "ab91f3c2d4e5f6a7b8c9d0e1f2a3b4c5"  
}

**Neptune Graph Update \- Link Incident**:

// Create incident node  
CREATE (i:Incident {  
  id: "INC-7721",  
  severity: "SEV-1",  
  status: "OPEN",  
  created\_at: datetime("2024-01-15T10:00:01.200Z")  
})

// Link signal to incident  
MATCH (s:Signal {id: "sig-01HQXZ2NPQ5RS8TU0VW3XYZ789"})  
MERGE (s)-\[:TRIGGERED\]-\>(i)

**PagerDuty Alert Sent**:

{  
  "routing\_key": "data-platform-oncall",  
  "event\_action": "trigger",  
  "dedup\_key": "INC-7721",  
  "payload": {  
    "summary": "\[SEV-1\] Contract Violation \- orders:created \- 89.8% failure rate",  
    "severity": "critical",  
    "source": "signal-factory",  
    "custom\_details": {  
      "incident\_id": "INC-7721",  
      "dataset": "urn:dp:orders:created",  
      "failure\_signature": "MISSING\_FIELD:customer\_id",  
      "suspected\_cause": "orders-svc v3.17 deployment at 09:58 AM",  
      "rca\_link": "https://observability.internal/rca/INC-7721"  
    }  
  }  
}

---

### **Step 6: RCA Copilot Explains the Incident**

**What Happens**: On-call engineer clicks the RCA link. The Copilot queries Neptune and generates an explanation.

Timeline: 10:02:15.000 AM (engineer clicks link)

**RCA Copilot Query Flow**:

\# rca\_copilot/analyzer.py

class RCACopilot:  
    def analyze\_incident(self, incident\_id: str) \-\> RCAReport:  
        \# Step 1: Get incident context from DynamoDB  
        incident \= self.dynamodb.get\_incident(incident\_id)  
        \# incident\_id: INC-7721  
        \# primary\_evidence\_id: evd-01HQXY8MNP4QR7ST9VW2XYZ456  
          
        \# Step 2: Direct lookup \- get failure signature from evidence  
        evidence\_sample \= self.dynamodb.get\_evidence(incident.primary\_evidence\_id)  
        failure\_signature \= evidence\_sample.validation.reason\_codes\[0\]  
        \# failure\_signature: MISSING\_FIELD:customer\_id  
          
        \# Step 3: Graph traversal \- find upstream cause  
        upstream\_query \= """  
        MATCH (i:Incident {id: $incident\_id})  
        \<-\[:TRIGGERED\]-(s:Signal)  
        \<-\[:CAUSED\]-(fs:FailureSignature)  
        \<-\[:INTRODUCED\]-(d:Deployment)  
        RETURN d.service AS service,   
               d.version AS version,   
               d.deployed\_at AS deployed\_at,  
               fs.reason\_code AS reason  
        """  
        upstream\_result \= self.neptune.query(upstream\_query, {"incident\_id": incident\_id})  
        \# Result:  
        \# service: orders-svc  
        \# version: v3.17  
        \# deployed\_at: 2024-01-15T09:57:45Z  
        \# reason: MISSING\_FIELD:customer\_id  
          
        \# Step 4: Graph traversal \- find blast radius (downstream impact)  
        blast\_radius\_query \= """  
        MATCH (ds:Dataset {urn: $dataset\_urn})  
        \-\[:FEEDS\*1..3\]-\>(downstream)  
        RETURN downstream.urn AS urn,   
               downstream.tier AS tier,  
               downstream.type AS type  
        """  
        downstream\_result \= self.neptune.query(blast\_radius\_query, {"dataset\_urn": incident.dataset\_urn})  
        \# Result:  
        \# \[  
        \#   {urn: "urn:delta:prod:sales:orders\_silver", tier: 1, type: "Delta Table"},  
        \#   {urn: "urn:delta:prod:sales:orders\_gold\_daily", tier: 1, type: "Delta Table"},  
        \#   {urn: "urn:dashboard:exec:daily\_orders", tier: 1, type: "Dashboard"},  
        \#   {urn: "urn:pipeline:finance:daily\_snapshot", tier: 1, type: "Airflow DAG"}  
        \# \]  
          
        \# Step 5: Calculate temporal correlation  
        time\_delta \= evidence\_sample.timestamp \- upstream\_result.deployed\_at  
        \# time\_delta: 17 seconds (high correlation)  
          
        \# Step 6: Generate hypothesis with confidence score  
        confidence \= self.calculate\_confidence(  
            time\_delta=time\_delta,  
            producer\_match=True,  \# evidence.producer \== deployment.service  
            signature\_match=True,  \# failure signature is deterministic  
            sample\_size=incident.evidence\_summary.failed\_events  
        )  
        \# confidence: 0.94 (HIGH)  
          
        \# Step 7: Generate natural language explanation (via Bedrock)  
        explanation \= self.llm.generate\_explanation(  
            template="incident\_rca",  
            context={  
                "incident": incident,  
                "upstream\_cause": upstream\_result,  
                "blast\_radius": downstream\_result,  
                "confidence": confidence,  
                "evidence\_sample": evidence\_sample  
            }  
        )  
          
        return RCAReport(  
            incident\_id=incident\_id,  
            root\_cause=upstream\_result,  
            blast\_radius=downstream\_result,  
            confidence=confidence,  
            explanation=explanation,  
            evidence\_refs=\[incident.primary\_evidence\_id\],  
            recommended\_action="Rollback orders-svc to v3.16"  
        )

**RCA Copilot Output**:

┌─────────────────────────────────────────────────────────────────────────────┐  
│  RCA COPILOT ANALYSIS                                                       │  
│  Incident: INC-7721 | Severity: SEV-1 | Status: OPEN                       │  
├─────────────────────────────────────────────────────────────────────────────┤  
│                                                                             │  
│  ROOT CAUSE (Confidence: 94% \- HIGH)                                       │  
│  ─────────────────────────────────────                                     │  
│  Deployment orders-svc v3.17 at 09:57:45 AM introduced a bug that stopped  │  
│  populating the required \`customer\_id\` field in order events.              │  
│                                                                             │  
│  EVIDENCE CHAIN                                                            │  
│  ─────────────────                                                         │  
│  • Deployment: orders-svc v3.17 deployed at 09:57:45 AM                    │  
│  • First failure: 09:58:02 AM (17 seconds after deployment)                │  
│  • Failure pattern: 1,120 of 1,247 events (89.8%) missing customer\_id      │  
│  • All failures have identical signature: MISSING\_FIELD:customer\_id        │  
│  • Producer attribution: HIGH confidence (explicit header match)           │  
│                                                                             │  
│  BLAST RADIUS                                                              │  
│  ────────────                                                              │  
│  The following Tier-1 assets are impacted:                                 │  
│                                                                             │  
│  • orders\_silver (Delta Table) \- STALE                                     │  
│  • orders\_gold\_daily (Delta Table) \- BLOCKED                               │  
│  • Executive Orders Dashboard \- SHOWING INCOMPLETE DATA                    │  
│  • finance\_daily\_snapshot (Airflow DAG) \- FAILED                          │  
│                                                                             │  
│  RECOMMENDED ACTION                                                        │  
│  ──────────────────                                                        │  
│  1\. Rollback orders-svc to v3.16 immediately                               │  
│  2\. After rollback, verify evidence shows PASS for new events              │  
│  3\. Investigate v3.17 changes to identify removed customer\_id assignment   │  
│                                                                             │  
│  EVIDENCE REFERENCES                                                       │  
│  ────────────────────                                                      │  
│  Primary: evd-01HQXY8MNP4QR7ST9VW2XYZ456                                   │  
│  Trace:   ab91f3c2d4e5f6a7b8c9d0e1f2a3b4c5                                │  
│  Sample:  \[+1,119 more evidence records\]                                   │  
│                                                                             │  
│  ───────────────────────────────────────────────────────────────────────── │  
│  Analysis completed in 47 seconds | Graph traversal: 23ms | LLM: 1.2s     │  
└─────────────────────────────────────────────────────────────────────────────┘

---

### **Scenario 1 Summary: End-to-End Timeline**

| Time | Component | Action | Output |
| ----- | ----- | ----- | ----- |
| 09:57:45 | orders-svc | Deployment v3.17 | Deployment event to Neptune |
| 09:58:02.127 | orders-svc | Publish order event | Kafka record (missing customer\_id) |
| 09:58:02.312 | Policy Enforcer | Validate record | Evidence event (FAIL: CONTRACT) |
| 10:00:00.000 | Contract Engine | Aggregate 5-min window | Signal (CRITICAL: 10.2% compliance) |
| 10:00:00.500 | Signal Engine | Write state | DynamoDB \+ Neptune updates |
| 10:00:01.200 | Alerting Engine | Create incident | INC-7721 \+ PagerDuty alert |
| 10:02:15.000 | RCA Copilot | Analyze incident | Root cause explanation |

**Total time from bug deployment to actionable RCA: 4 minutes 30 seconds**

---

## **Scenario 2: Batch Job Fails Due to Upstream Schema Drift**

**Context**: The nightly `orders_daily_agg` Airflow DAG reads from the `orders_bronze` table (populated by a Kafka consumer). An upstream team added a new field `discount_type` with an unexpected ENUM value, causing the Spark job to fail validation.

---

### **Step 1: Upstream Change Introduces Schema Drift**

**What Happens**: The Promotions team deploys a change to the orders-svc that adds a new `discount_type` field with a value not in the consumer's expected ENUM.

Timeline: Previous day, 14:30:00 PM

**New Event from orders-svc**:

{  
  "event\_id": "01HQW9ABCD1234567890XYZNEW",  
  "event\_type": "orders.created.v1",  
  "timestamp": "2024-01-14T14:30:00.000Z",  
  "payload": {  
    "order\_id": "ORD-2024-0114-55555",  
    "customer\_id": "cust-12345",  
    "total\_amount": 99.99,  
    "currency": "USD",  
    "discount\_type": "FLASH\_SALE"  // NEW VALUE \- not in consumer's ENUM  
  }  
}

**Policy Enforcer Evidence** (from real-time processing):

{  
  "evidence\_id": "evd-01HQW9EFGH5678901234ABCDEF",  
  "timestamp": "2024-01-14T14:30:00.215Z",  
  "dataset\_urn": "urn:dp:orders:created",  
  "validation": {  
    "result": "WARN",  
    "gates": \[  
      { "gate": "G3\_SCHEMA", "result": "PASS" },  
      { "gate": "G4\_CONTRACT", "result": "WARN", "reason\_code": "UNKNOWN\_ENUM:discount\_type:FLASH\_SALE" }  
    \]  
  }  
}

**Note**: The real-time Enforcer emits a `WARN` (not FAIL) because the contract allows unknown enum values to pass with a warning. The data flows to bronze.

---

### **Step 2: Kafka Consumer Writes to Bronze (S3/Delta)**

**What Happens**: The Kafka-to-Bronze consumer job writes the event to the bronze layer.

Timeline: 2024-01-14T14:30:01.000Z

**OpenLineage Event from Consumer Job**:

{  
  "eventType": "COMPLETE",  
  "eventTime": "2024-01-14T14:30:01.000Z",  
  "run": {  
    "runId": "kafka-consumer-run-20240114-143001",  
    "facets": {  
      "parent": {  
        "job": { "namespace": "streaming", "name": "orders-kafka-to-bronze" },  
        "run": { "runId": "persistent-consumer-001" }  
      }  
    }  
  },  
  "job": {  
    "namespace": "streaming",  
    "name": "orders-kafka-to-bronze"  
  },  
  "inputs": \[  
    {  
      "namespace": "kafka://msk-prod",  
      "name": "raw.orders.events"  
    }  
  \],  
  "outputs": \[  
    {  
      "namespace": "s3://data-lake-prod",  
      "name": "bronze/orders/2024-01-14/",  
      "facets": {  
        "outputStatistics": { "rowCount": 45230 }  
      }  
    }  
  \]  
}

---

### **Step 3: Nightly Airflow DAG Triggers Spark Job**

**What Happens**: At 02:00 AM, the `orders_daily_agg` DAG starts. The Spark job reads from bronze and attempts to transform to silver.

Timeline: 2024-01-15T02:00:00.000Z

**Airflow DAG Definition**:

\# dags/orders\_daily\_agg.py

from airflow import DAG  
from airflow.providers.apache.spark.operators.spark\_submit import SparkSubmitOperator  
from airflow.utils.dates import days\_ago

with DAG(  
    dag\_id="orders\_daily\_agg",  
    schedule\_interval="0 2 \* \* \*",  \# 2 AM daily  
    start\_date=days\_ago(1),  
    catchup=False,  
    tags=\["orders", "tier-1"\]  
) as dag:  
      
    transform\_to\_silver \= SparkSubmitOperator(  
        task\_id="transform\_orders\_silver",  
        application="/opt/spark-jobs/orders\_silver\_transform.py",  
        conf={  
            "spark.openlineage.namespace": "airflow",  
            "spark.openlineage.parentJobName": "orders\_daily\_agg",  
            "spark.openlineage.parentRunId": "{{ run\_id }}"  
        },  
        application\_args=\[  
            "--date", "{{ ds }}",  
            "--input", "s3://data-lake-prod/bronze/orders/{{ ds }}/",  
            "--output", "delta://unity-catalog/sales/orders\_silver"  
        \]  
    )

**OpenLineage START Event**:

{  
  "eventType": "START",  
  "eventTime": "2024-01-15T02:00:05.000Z",  
  "run": {  
    "runId": "spark-orders-silver-20240115-020005",  
    "facets": {  
      "parent": {  
        "job": { "namespace": "airflow", "name": "orders\_daily\_agg" },  
        "run": { "runId": "scheduled\_\_2024-01-15T02:00:00+00:00" }  
      },  
      "airflow": {  
        "dag\_id": "orders\_daily\_agg",  
        "task\_id": "transform\_orders\_silver",  
        "execution\_date": "2024-01-15T02:00:00+00:00"  
      }  
    }  
  },  
  "job": {  
    "namespace": "spark",  
    "name": "orders\_silver\_transform"  
  },  
  "inputs": \[  
    {  
      "namespace": "s3://data-lake-prod",  
      "name": "bronze/orders/2024-01-14/"  
    }  
  \],  
  "outputs": \[  
    {  
      "namespace": "delta://unity-catalog",  
      "name": "sales.orders\_silver"  
    }  
  \]  
}

---

### **Step 4: Spark Job Validates and Emits Evidence**

**What Happens**: The Spark job reads bronze data and runs validation. It encounters the `FLASH_SALE` enum value and fails validation for those records.

Timeline: 2024-01-15T02:05:30.000Z

**Spark Job Code with Inline Validation**:

\# spark-jobs/orders\_silver\_transform.py

from pyspark.sql import SparkSession  
from pyspark.sql.functions import col, when, struct, to\_json, lit, current\_timestamp  
from pyspark.sql.types import StringType  
import uuid

spark \= SparkSession.builder.appName("orders\_silver\_transform").getOrCreate()

\# Read bronze data  
bronze\_df \= spark.read.parquet("s3://data-lake-prod/bronze/orders/2024-01-14/")

\# Define expected ENUM values for discount\_type  
VALID\_DISCOUNT\_TYPES \= \["NONE", "PERCENTAGE", "FIXED\_AMOUNT", "LOYALTY", "COUPON"\]

\# Validate and create evidence  
validated\_df \= bronze\_df.withColumn(  
    "validation\_result",  
    when(  
        col("discount\_type").isNull() | col("discount\_type").isin(VALID\_DISCOUNT\_TYPES),  
        "PASS"  
    ).otherwise("FAIL")  
).withColumn(  
    "validation\_reason",  
    when(  
        \~col("discount\_type").isin(VALID\_DISCOUNT\_TYPES) & col("discount\_type").isNotNull(),  
        concat(lit("UNKNOWN\_ENUM:discount\_type:"), col("discount\_type"))  
    ).otherwise(None)  
)

\# Count validation results  
validation\_summary \= validated\_df.groupBy("validation\_result", "validation\_reason").count().collect()  
\# Result:  
\# \[  
\#   Row(validation\_result='PASS', validation\_reason=None, count=44850),  
\#   Row(validation\_result='FAIL', validation\_reason='UNKNOWN\_ENUM:discount\_type:FLASH\_SALE', count=380)  
\# \]

total\_records \= bronze\_df.count()  \# 45,230  
pass\_count \= 44850  
fail\_count \= 380  
compliance\_rate \= pass\_count / total\_records  \# 0.9916 (99.16%)

\# Generate evidence events for failed records  
evidence\_df \= validated\_df.filter(col("validation\_result") \== "FAIL").select(  
    lit("evd-").alias("prefix"),  
    col("order\_id").alias("source\_id"),  
    lit("urn:dp:orders:silver").alias("dataset\_urn"),  
    lit("FAIL").alias("result"),  
    col("validation\_reason").alias("reason\_code"),  
    current\_timestamp().alias("timestamp"),  
    lit("spark:orders\_silver\_transform").alias("producer"),  
    lit("spark-orders-silver-20240115-020005").alias("run\_id")  
)

\# Write evidence to Kafka  
evidence\_df.selectExpr(  
    "to\_json(struct(\*)) as value"  
).write \\  
    .format("kafka") \\  
    .option("kafka.bootstrap.servers", "msk-prod.internal:9092") \\  
    .option("topic", "signal\_factory.evidence") \\  
    .save()

\# Write only valid records to silver (strict mode)  
valid\_records \= validated\_df.filter(col("validation\_result") \== "PASS").drop("validation\_result", "validation\_reason")

valid\_records.write \\  
    .format("delta") \\  
    .mode("append") \\  
    .option("mergeSchema", "true") \\  
    .saveAsTable("sales.orders\_silver")

\# Report metrics  
print(f"Total records: {total\_records}")  
print(f"Valid records written: {pass\_count}")  
print(f"Invalid records (evidence emitted): {fail\_count}")

**Evidence Events Emitted** (380 records to `signal_factory.evidence`):

{  
  "evidence\_id": "evd-01HQZA1234567890ABCDEFGH",  
  "timestamp": "2024-01-15T02:05:30.000Z",  
  "dataset\_urn": "urn:dp:orders:silver",  
  "producer": {  
    "id": "spark:orders\_silver\_transform",  
    "confidence": "HIGH",  
    "run\_id": "spark-orders-silver-20240115-020005"  
  },  
  "validation": {  
    "result": "FAIL",  
    "failed\_gates": \["CONTRACT"\],  
    "reason\_codes": \["UNKNOWN\_ENUM:discount\_type:FLASH\_SALE"\]  
  },  
  "source": {  
    "input\_dataset": "s3://data-lake-prod/bronze/orders/2024-01-14/",  
    "source\_record\_id": "ORD-2024-0114-55555"  
  },  
  "lineage": {  
    "dag\_run\_id": "scheduled\_\_2024-01-15T02:00:00+00:00",  
    "spark\_run\_id": "spark-orders-silver-20240115-020005",  
    "upstream\_dataset": "urn:dp:orders:bronze"  
  }  
}

---

### **Step 5: OpenLineage COMPLETE Event with Observability Facet**

**What Happens**: The Spark job completes and emits an OpenLineage COMPLETE event with an embedded observability summary.

Timeline: 2024-01-15T02:08:45.000Z

**OpenLineage COMPLETE Event**:

{  
  "eventType": "COMPLETE",  
  "eventTime": "2024-01-15T02:08:45.000Z",  
  "run": {  
    "runId": "spark-orders-silver-20240115-020005",  
    "facets": {  
      "parent": {  
        "job": { "namespace": "airflow", "name": "orders\_daily\_agg" },  
        "run": { "runId": "scheduled\_\_2024-01-15T02:00:00+00:00" }  
      },  
      "outputStatistics": {  
        "rowCount": 44850,  
        "bytesWritten": 15234567  
      },  
      "observability\_evidence": {  
        "\_producer": "https://github.com/your-org/signal-factory",  
        "\_schemaURL": "urn:schema:ol-obs-facet:1",  
        "summary": {  
          "records\_processed": 45230,  
          "records\_passed": 44850,  
          "records\_failed": 380,  
          "compliance\_rate": 0.9916,  
          "failure\_signatures": \[  
            {  
              "reason\_code": "UNKNOWN\_ENUM:discount\_type:FLASH\_SALE",  
              "count": 380,  
              "first\_seen": "2024-01-14T14:30:00.000Z"  
            }  
          \]  
        },  
        "evidence\_topic": "signal\_factory.evidence",  
        "evidence\_count": 380  
      }  
    }  
  },  
  "job": {  
    "namespace": "spark",  
    "name": "orders\_silver\_transform",  
    "facets": {  
      "jobType": { "processingType": "BATCH", "integration": "SPARK", "jobType": "TASK" }  
    }  
  },  
  "inputs": \[  
    {  
      "namespace": "s3://data-lake-prod",  
      "name": "bronze/orders/2024-01-14/",  
      "inputFacets": {  
        "dataQualityMetrics": {  
          "rowCount": 45230,  
          "columnMetrics": {  
            "discount\_type": {  
              "nullCount": 0,  
              "distinctCount": 6  
            }  
          }  
        }  
      }  
    }  
  \],  
  "outputs": \[  
    {  
      "namespace": "delta://unity-catalog",  
      "name": "sales.orders\_silver",  
      "outputFacets": {  
        "outputStatistics": {  
          "rowCount": 44850,  
          "size": 15234567  
        },  
        "columnLineage": {  
          "fields": \[  
            {  
              "name": "discount\_type",  
              "inputFields": \[  
                { "namespace": "s3://data-lake-prod", "name": "bronze/orders/2024-01-14/", "field": "discount\_type" }  
              \],  
              "transformationDescription": "Direct passthrough with enum validation"  
            }  
          \]  
        }  
      }  
    }  
  \]  
}

---

### **Step 6: Signal Engine Processes Batch Evidence**

**What Happens**: The DQ Signal Engine processes the batch evidence and detects a drift pattern.

Timeline: 2024-01-15T02:10:00.000Z

**DQ Signal Engine Processing**:

\# signal\_engines/dq\_engine.py

class DQSignalEngine:  
    def process\_batch\_evidence(self, job\_run\_id: str):  
        \# Query all evidence for this batch run  
        evidence\_batch \= self.evidence\_store.query\_by\_run\_id(job\_run\_id)  
        \# Found 380 evidence records  
          
        \# Get dataset metadata  
        dataset\_urn \= "urn:dp:orders:silver"  
        dataset\_meta \= self.registry.get\_dataset(dataset\_urn)  
        \# tier: 1, slo\_threshold: 0.99  
          
        \# Calculate compliance  
        \# Note: For batch, we look at the OpenLineage facet for totals  
        ol\_event \= self.openlineage\_store.get\_event(job\_run\_id)  
        total \= ol\_event.facets.observability\_evidence.summary.records\_processed  
        passed \= ol\_event.facets.observability\_evidence.summary.records\_passed  
        failed \= ol\_event.facets.observability\_evidence.summary.records\_failed  
        compliance\_rate \= passed / total  \# 0.9916  
          
        \# Check against SLO  
        slo\_threshold \= dataset\_meta.slo\_threshold  \# 0.99  
          
        if compliance\_rate \< slo\_threshold:  
            state \= "WARNING"  \# 99.16% \< 99% threshold \= WARNING  
        else:  
            state \= "OK"  
          
        \# Detect if this is a NEW failure signature (drift detection)  
        failure\_signature \= "UNKNOWN\_ENUM:discount\_type:FLASH\_SALE"  
        historical \= self.get\_historical\_signatures(dataset\_urn, days=30)  
          
        is\_new\_signature \= failure\_signature not in \[h.signature for h in historical\]  
        \# is\_new\_signature \= True (first time seeing FLASH\_SALE)  
          
        if is\_new\_signature:  
            \# Emit drift signal  
            drift\_signal \= Signal(  
                signal\_type="DRIFT\_DETECTED",  
                dataset\_urn=dataset\_urn,  
                state="WARNING",  
                details={  
                    "drift\_type": "ENUM\_VALUE\_DRIFT",  
                    "field": "discount\_type",  
                    "new\_value": "FLASH\_SALE",  
                    "expected\_values": \["NONE", "PERCENTAGE", "FIXED\_AMOUNT", "LOYALTY", "COUPON"\]  
                }  
            )  
            self.emit\_signal(drift\_signal)  
          
        \# Emit DQ signal  
        dq\_signal \= Signal(  
            signal\_id=f"sig-{generate\_ulid()}",  
            signal\_type="DQ\_BREACH",  
            dataset\_urn=dataset\_urn,  
            state=state,  
            window={  
                "start": ol\_event.eventTime,  
                "end": ol\_event.eventTime,  
                "type": "BATCH\_RUN"  
            },  
            metrics={  
                "records\_processed": total,  
                "records\_passed": passed,  
                "records\_failed": failed,  
                "compliance\_rate": compliance\_rate,  
                "slo\_threshold": slo\_threshold  
            },  
            batch\_context={  
                "dag\_id": "orders\_daily\_agg",  
                "dag\_run\_id": "scheduled\_\_2024-01-15T02:00:00+00:00",  
                "spark\_run\_id": job\_run\_id  
            },  
            top\_failures=\[  
                {  
                    "signature": failure\_signature,  
                    "count": failed,  
                    "is\_new": is\_new\_signature  
                }  
            \]  
        )  
          
        return dq\_signal

**Signals Emitted**:

// Signal 1: Drift Detection  
{  
  "signal\_id": "sig-01HQZB1111111111111111111",  
  "signal\_type": "DRIFT\_DETECTED",  
  "dataset\_urn": "urn:dp:orders:silver",  
  "state": "WARNING",  
  "timestamp": "2024-01-15T02:10:00.000Z",  
  "details": {  
    "drift\_type": "ENUM\_VALUE\_DRIFT",  
    "field": "discount\_type",  
    "new\_value": "FLASH\_SALE",  
    "expected\_values": \["NONE", "PERCENTAGE", "FIXED\_AMOUNT", "LOYALTY", "COUPON"\],  
    "first\_seen\_in\_source": "2024-01-14T14:30:00.000Z",  
    "upstream\_dataset": "urn:dp:orders:bronze"  
  }  
}

// Signal 2: DQ Breach  
{  
  "signal\_id": "sig-01HQZB2222222222222222222",  
  "signal\_type": "DQ\_BREACH",  
  "dataset\_urn": "urn:dp:orders:silver",  
  "state": "WARNING",  
  "window": {  
    "start": "2024-01-15T02:00:05.000Z",  
    "end": "2024-01-15T02:08:45.000Z",  
    "type": "BATCH\_RUN"  
  },  
  "metrics": {  
    "records\_processed": 45230,  
    "records\_passed": 44850,  
    "records\_failed": 380,  
    "compliance\_rate": 0.9916,  
    "slo\_threshold": 0.99  
  },  
  "batch\_context": {  
    "dag\_id": "orders\_daily\_agg",  
    "dag\_run\_id": "scheduled\_\_2024-01-15T02:00:00+00:00",  
    "spark\_run\_id": "spark-orders-silver-20240115-020005"  
  },  
  "top\_failures": \[  
    {  
      "signature": "UNKNOWN\_ENUM:discount\_type:FLASH\_SALE",  
      "count": 380,  
      "is\_new": true  
    }  
  \]  
}

---

### **Step 7: Neptune Graph Updated with Batch Lineage**

**What Happens**: The graph is updated to reflect the batch job run and its relationship to the upstream data.

Timeline: 2024-01-15T02:10:05.000Z

**Neptune Graph Updates**:

// Create DAG Run node  
MERGE (dr:DAGRun {id: "scheduled\_\_2024-01-15T02:00:00+00:00"})  
SET dr.dag\_id \= "orders\_daily\_agg",  
    dr.execution\_date \= datetime("2024-01-15T02:00:00Z"),  
    dr.status \= "SUCCESS"

// Create Spark Job Run node  
MERGE (sr:SparkRun {id: "spark-orders-silver-20240115-020005"})  
SET sr.job\_name \= "orders\_silver\_transform",  
    sr.start\_time \= datetime("2024-01-15T02:00:05Z"),  
    sr.end\_time \= datetime("2024-01-15T02:08:45Z"),  
    sr.records\_processed \= 45230,  
    sr.records\_failed \= 380

// Link DAG to Spark Run  
MATCH (dr:DAGRun {id: "scheduled\_\_2024-01-15T02:00:00+00:00"})  
MATCH (sr:SparkRun {id: "spark-orders-silver-20240115-020005"})  
MERGE (dr)-\[:EXECUTED\]-\>(sr)

// Link Spark Run to input dataset  
MATCH (sr:SparkRun {id: "spark-orders-silver-20240115-020005"})  
MATCH (bronze:Dataset {urn: "urn:dp:orders:bronze"})  
MERGE (sr)-\[:READ\_FROM\]-\>(bronze)

// Link Spark Run to output dataset  
MATCH (sr:SparkRun {id: "spark-orders-silver-20240115-020005"})  
MATCH (silver:Dataset {urn: "urn:dp:orders:silver"})  
MERGE (sr)-\[:WROTE\_TO\]-\>(silver)

// Create FailureSignature for drift  
MERGE (fs:FailureSignature {id: "UNKNOWN\_ENUM:discount\_type:FLASH\_SALE"})  
SET fs.reason\_code \= "UNKNOWN\_ENUM:discount\_type:FLASH\_SALE",  
    fs.field \= "discount\_type",  
    fs.new\_value \= "FLASH\_SALE",  
    fs.first\_seen \= datetime("2024-01-14T14:30:00Z"),  
    fs.occurrence\_count \= 380

// Link upstream dataset change to failure signature  
MATCH (bronze:Dataset {urn: "urn:dp:orders:bronze"})  
MATCH (fs:FailureSignature {id: "UNKNOWN\_ENUM:discount\_type:FLASH\_SALE"})  
MERGE (bronze)-\[:INTRODUCED\_DRIFT\]-\>(fs)

// Link Spark Run to failure signature  
MATCH (sr:SparkRun {id: "spark-orders-silver-20240115-020005"})  
MATCH (fs:FailureSignature {id: "UNKNOWN\_ENUM:discount\_type:FLASH\_SALE"})  
MERGE (sr)-\[:ENCOUNTERED\]-\>(fs)

// Link failure signature to drift signal  
MATCH (fs:FailureSignature {id: "UNKNOWN\_ENUM:discount\_type:FLASH\_SALE"})  
MATCH (ds:Signal {id: "sig-01HQZB1111111111111111111"})  
MERGE (fs)-\[:CAUSED\]-\>(ds)

// Trace back to original producer (orders-svc)  
// This uses the evidence trail from real-time processing  
MATCH (p:Producer {id: "orders-svc"})  
MATCH (fs:FailureSignature {id: "UNKNOWN\_ENUM:discount\_type:FLASH\_SALE"})  
MERGE (p)-\[:PRODUCED\_DRIFT {  
  first\_evidence: "evd-01HQW9EFGH5678901234ABCDEF",  
  timestamp: datetime("2024-01-14T14:30:00.215Z")  
}\]-\>(fs)

**Graph State After Step 7**:

(Producer:orders-svc)  
         │  
         │ \[PRODUCED\_DRIFT\]  
         │ first\_evidence: evd-01HQW9E...  
         │ timestamp: 2024-01-14T14:30:00Z  
         ▼  
(FailureSignature:UNKNOWN\_ENUM:discount\_type:FLASH\_SALE)  
         │  
    ┌────┴────┐  
    │         │  
    ▼         ▼  
\[CAUSED\]   \[ENCOUNTERED\]  
    │         │  
    ▼         ▼  
(Signal:  (SparkRun:spark-orders-silver-20240115-020005)  
 DRIFT)           │  
                  │ \[READ\_FROM\]  
                  ▼  
           (Dataset:orders:bronze)  
                  │  
                  │ \[INTRODUCED\_DRIFT\]  
                  ▼  
           (FailureSignature:...)  \<- circular reference resolved

           (SparkRun)  
                  │  
                  │ \[WROTE\_TO\]  
                  ▼  
           (Dataset:orders:silver)

---

### **Step 8: RCA Copilot Traces Batch Lineage to Root Cause**

**What Happens**: A data analyst notices incomplete data in the gold layer dashboard and triggers an RCA query.

Timeline: 2024-01-15T08:30:00.000Z

**RCA Query**:

\# RCA Copilot query for batch drift

def trace\_batch\_drift(failure\_signature\_id: str) \-\> RCAReport:  
    \# Step 1: Find the failure signature  
    fs\_query \= """  
    MATCH (fs:FailureSignature {id: $signature\_id})  
    RETURN fs  
    """  
    failure\_sig \= neptune.query(fs\_query, {"signature\_id": failure\_signature\_id})  
      
    \# Step 2: Trace back to original producer (upstream root cause)  
    upstream\_query \= """  
    MATCH (p:Producer)-\[r:PRODUCED\_DRIFT\]-\>(fs:FailureSignature {id: $signature\_id})  
    RETURN p.id AS producer,  
           r.first\_evidence AS evidence\_id,  
           r.timestamp AS first\_occurrence  
    """  
    upstream \= neptune.query(upstream\_query, {"signature\_id": failure\_signature\_id})  
    \# Result: producer=orders-svc, first\_occurrence=2024-01-14T14:30:00Z  
      
    \# Step 3: Find all affected batch jobs  
    affected\_jobs\_query \= """  
    MATCH (sr:SparkRun)-\[:ENCOUNTERED\]-\>(fs:FailureSignature {id: $signature\_id})  
    RETURN sr.id AS job\_run\_id,  
           sr.job\_name AS job\_name,  
           sr.records\_failed AS records\_affected  
    ORDER BY sr.start\_time DESC  
    """  
    affected\_jobs \= neptune.query(affected\_jobs\_query, {"signature\_id": failure\_signature\_id})  
    \# Result: \[spark-orders-silver-20240115-020005: 380 records\]  
      
    \# Step 4: Find downstream impact (blast radius)  
    blast\_radius\_query \= """  
    MATCH (sr:SparkRun {id: $job\_run\_id})  
    \-\[:WROTE\_TO\]-\>(output:Dataset)  
    \-\[:FEEDS\*1..3\]-\>(downstream)  
    RETURN downstream.urn AS urn,  
           downstream.tier AS tier,  
           downstream.type AS type  
    """  
    downstream \= neptune.query(blast\_radius\_query, {"job\_run\_id": "spark-orders-silver-20240115-020005"})  
    \# Result:  
    \# \[  
    \#   {urn: "urn:delta:sales:orders\_gold\_daily", tier: 1, type: "Delta Table"},  
    \#   {urn: "urn:dashboard:exec:orders\_summary", tier: 1, type: "Dashboard"}  
    \# \]  
      
    \# Step 5: Find the original real-time evidence (linking batch to streaming)  
    original\_evidence \= evidence\_store.get(upstream.evidence\_id)  
    \# This shows the WARN from real-time processing on 2024-01-14  
      
    return RCAReport(...)

**RCA Copilot Output**:

┌─────────────────────────────────────────────────────────────────────────────┐  
│  RCA COPILOT ANALYSIS \- BATCH DRIFT                                        │  
│  Query: Why is orders\_gold\_daily missing 380 records?                      │  
├─────────────────────────────────────────────────────────────────────────────┤  
│                                                                             │  
│  ROOT CAUSE (Confidence: 87% \- HIGH)                                       │  
│  ─────────────────────────────────────                                     │  
│  Schema drift in upstream producer orders-svc introduced a new             │  
│  discount\_type value "FLASH\_SALE" that is not recognized by the            │  
│  orders\_silver\_transform Spark job.                                        │  
│                                                                             │  
│  TIMELINE OF EVENTS                                                        │  
│  ──────────────────                                                        │  
│  • 2024-01-14 14:30:00 \- orders-svc first emitted FLASH\_SALE value         │  
│  • 2024-01-14 14:30:00 \- Real-time Enforcer emitted WARN evidence          │  
│  • 2024-01-14 14:30:01 \- Event written to bronze layer (380 total events)  │  
│  • 2024-01-15 02:00:05 \- Batch job started                                 │  
│  • 2024-01-15 02:05:30 \- Batch job failed validation for 380 records       │  
│  • 2024-01-15 02:08:45 \- Job completed, 380 records excluded from silver   │  
│                                                                             │  
│  DATA FLOW TRACE                                                           │  
│  ────────────────                                                          │  
│                                                                             │  
│  orders-svc ──► Kafka ──► Bronze ──► Spark Job ──► Silver ──► Gold         │  
│       │                     │            │                                  │  
│       │                     │            ▼                                  │  
│  \[FLASH\_SALE          \[All 380      \[380 records                           │  
│   introduced\]          records       filtered out\]                          │  
│                        present\]                                             │  
│                                                                             │  
│  BLAST RADIUS                                                              │  
│  ────────────                                                              │  
│  The following assets have incomplete data:                                 │  
│                                                                             │  
│  • orders\_silver (Delta) \- Missing 380 records for 2024-01-14              │  
│  • orders\_gold\_daily (Delta) \- Aggregations exclude these orders           │  
│  • Executive Orders Dashboard \- Revenue underreported by \~$37,962          │  
│                                                                             │  
│  RECOMMENDED ACTIONS                                                       │  
│  ───────────────────                                                       │  
│  1\. Add "FLASH\_SALE" to valid enum list in orders\_silver\_transform.py      │  
│  2\. Reprocess bronze partition for 2024-01-14                              │  
│  3\. Coordinate with Promotions team to document new discount types         │  
│  4\. Consider adding contract test in CI for enum values                    │  
│                                                                             │  
│  EVIDENCE CHAIN                                                            │  
│  ──────────────                                                            │  
│  Real-time WARN: evd-01HQW9EFGH5678901234ABCDEF (2024-01-14 14:30:00)      │  
│  Batch FAILs:    evd-01HQZA1234567890ABCDEFGH... (+379 more)               │  
│  OpenLineage:    spark-orders-silver-20240115-020005                       │  
│  DAG Run:        scheduled\_\_2024-01-15T02:00:00+00:00                      │  
│                                                                             │  
│  ───────────────────────────────────────────────────────────────────────── │  
│  Analysis completed in 1.8 seconds | Graph hops: 5 | Evidence refs: 381   │  
└─────────────────────────────────────────────────────────────────────────────┘

---

### **Scenario 2 Summary: End-to-End Timeline**

| Time | Component | Action | Output |
| ----- | ----- | ----- | ----- |
| Jan 14, 14:30:00 | orders-svc | Emit new FLASH\_SALE value | Kafka record |
| Jan 14, 14:30:00.215 | Policy Enforcer | Validate (WARN) | Evidence (WARN: UNKNOWN\_ENUM) |
| Jan 14, 14:30:01 | Kafka Consumer | Write to bronze | S3 parquet \+ OpenLineage |
| Jan 15, 02:00:05 | Airflow | Trigger DAG | OpenLineage START |
| Jan 15, 02:05:30 | Spark Job | Validate batch | 380 Evidence events to Kafka |
| Jan 15, 02:08:45 | Spark Job | Complete | OpenLineage COMPLETE \+ Obs facet |
| Jan 15, 02:10:00 | DQ Engine | Process evidence | DRIFT \+ DQ\_BREACH signals |
| Jan 15, 02:10:05 | Signal Engine | Update graph | Neptune edges |
| Jan 15, 08:30:00 | RCA Copilot | Trace lineage | Root cause explanation |

**Key Insight**: The real-time WARN evidence from Day 1 linked to the batch FAIL evidence on Day 2, enabling the Copilot to trace the drift back to its source—even though the batch job had no direct connection to the original producer.

---

## **Comparison: Service vs Batch Emit Patterns**

| Aspect | Service (Scenario 1\) | Batch (Scenario 2\) |
| ----- | ----- | ----- |
| **Evidence Emitter** | Policy Enforcer (sidecar) | Spark Job (inline) |
| **Correlation ID** | OTel trace\_id | OpenLineage run\_id \+ dag\_run\_id |
| **Latency to Evidence** | \< 200ms | Minutes (job duration) |
| **Graph Linkage** | Deployment → FailureSignature | SparkRun → FailureSignature |
| **Root Cause Anchor** | Deployment version | Upstream dataset change |
| **Typical Failure Pattern** | Code bug (missing field) | Schema drift (new enum) |
| **Detection Speed** | 5-minute signal window | End of batch job |
| **Blast Radius Trace** | Downstream consumers | Downstream tables/dashboards |

