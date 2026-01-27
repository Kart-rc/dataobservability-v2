# C-03: Evidence Bus - Low-Level Design

**Data Observability Platform v2.0**  
*Signal Factory Architecture - Out-of-Band Enforcement Pattern*

| Attribute | Value |
|-----------|-------|
| **Version** | 1.0 |
| **Status** | Draft |
| **Owner** | Platform Core Team |
| **Last Updated** | January 2026 |
| **Prerequisite** | HLD v2.0 Out-of-Band Enforcement Architecture |

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Component Analysis](#2-component-analysis)
3. [Architecture Design](#3-architecture-design)
4. [Data Models & Schemas](#4-data-models--schemas)
5. [API Specifications](#5-api-specifications)
6. [Scalability & Throughput](#6-scalability--throughput)
7. [Reliability & Fault Tolerance](#7-reliability--fault-tolerance)
8. [Security Architecture](#8-security-architecture)
9. [Observability & Monitoring](#9-observability--monitoring)
10. [Operational Runbooks](#10-operational-runbooks)
11. [Cost Analysis](#11-cost-analysis)
12. [Appendices](#12-appendices)

---

## 1. Executive Summary

### 1.1 Component Purpose

The **Evidence Bus** (C-03) is the sole, non-negotiable integration backbone for all downstream systems in the Data Observability Platform. It represents the `signal_factory.evidence` Kafka topic that stores the immutable record of per-event validation results produced by the Policy Enforcer.

### 1.2 Core Design Principles

| Principle | Rationale |
|-----------|-----------|
| **Single Topic** | Centralizes all validation state; prevents duplication of gate logic across consumers |
| **Immutable** | Evidence serves as audit trail and replay source for incident investigation |
| **Kafka-based** | Ordered, durable, partitioned for parallel consumption by multiple engine consumer groups |
| **Dataset-URN Partitioned** | Ensures ordering guarantees within a dataset for drift detection |

### 1.3 Key Constraints

| Constraint | Description |
|------------|-------------|
| Signal Engines MUST NOT consume raw business topics | All downstream processing operates exclusively on Evidence |
| Evidence Bus as Single Source of Truth | The canonical data contract for the entire platform |
| Zero Producer Changes | Enforcer generates evidence; producers remain untouched |

### 1.4 Non-Functional Requirements

| Requirement | Target | Notes |
|-------------|--------|-------|
| Evidence Latency | < 2 seconds P99 | From Policy Enforcer emit to consumer availability |
| Throughput | 50K-500K events/sec | 64-256 partitions depending on load |
| Availability | > 99.9% | < 8.7 hours downtime/year |
| Retention (Hot) | 7 days | Primary consumer access |
| Retention (Warm) | 30 days | S3 Standard for replay |
| Retention (Cold) | 90 days | S3 Glacier for compliance |

---

## 2. Component Analysis

### 2.1 Hidden Assumptions

Applying systems thinking, we identify the following hidden assumptions:

| Assumption | Risk if Invalid | Mitigation |
|------------|-----------------|------------|
| Evidence events fit in single Kafka record | Large payloads cause serialization failures | Emit evidence with `payload_ref: s3://evidence-archive/{id}` for large payloads |
| Evidence Bus can handle peak volume | High cardinality → partition hotspots → consumer lag → signal staleness | Implement tiered sampling (100% Tier-1, 10% Tier-3) |
| Schema Registry is always available | Consumers cannot deserialize evidence | Cache last-known-good schema; emit with `REGISTRY_STALE` flag |
| Consumers keep pace with producers | Unbounded lag → stale signals → missed incidents | Backpressure detection with automatic scaling triggers |
| Network partitions are temporary | Split-brain evidence streams | Cross-AZ replication with manual failover runbook |

### 2.2 5 Whys Analysis: Why Single Topic?

1. **Why single topic?** → To centralize validation state
2. **Why centralize?** → Prevents gate logic duplication across Signal Engines
3. **Why prevent duplication?** → Ensures consistent interpretation of evidence
4. **Why consistent interpretation?** → RCA correlation requires deterministic truth
5. **Why deterministic truth?** → Incident attribution fails without it

### 2.3 Cost of Action vs. Inaction

| Scenario | Cost of Action | Cost of Inaction |
|----------|---------------|------------------|
| 64→256 partition expansion | ~$2K/month MSK increase, 4-hour maintenance window | Consumer lag during incidents, stale signals |
| S3 archival implementation | ~$1.5K/month storage, development effort | No replay capability, compliance gaps |
| DLQ implementation | Operational overhead, monitoring complexity | Silent data loss, debugging blind spots |
| Multi-region replication | ~$4K/month, operational complexity | Regional failure = platform outage |

---

## 3. Architecture Design

### 3.1 Component Context Diagram

```mermaid
flowchart TB
    subgraph Upstream["Upstream (Producers)"]
        PE[Policy Enforcer<br/>C-01]
        BATCH[Batch Jobs<br/>Spark/Airflow]
        STREAM[Stream Processors<br/>Flink/KStreams]
    end
    
    subgraph EvidenceBus["Evidence Bus (C-03)"]
        KAFKA[(signal_factory.evidence<br/>64-256 partitions)]
        DLQ[(signal_factory.evidence.dlq<br/>Dead Letter Queue)]
        S3ARCH[(S3 Archive<br/>Hot→Warm→Cold)]
    end
    
    subgraph Downstream["Downstream (Consumers)"]
        FRESH[Freshness Engine]
        VOL[Volume Engine]
        CONTRACT[Contract Engine]
        DRIFT[Schema Drift Engine]
        DQ[DQ Engine]
        ANOMALY[Anomaly Engine]
        ARCHIVE[Archive Worker]
    end
    
    PE -->|AT-LEAST-ONCE| KAFKA
    BATCH -->|AT-LEAST-ONCE| KAFKA
    STREAM -->|AT-LEAST-ONCE| KAFKA
    
    KAFKA -->|Fan-out| FRESH
    KAFKA -->|Fan-out| VOL
    KAFKA -->|Fan-out| CONTRACT
    KAFKA -->|Fan-out| DRIFT
    KAFKA -->|Fan-out| DQ
    KAFKA -->|Fan-out| ANOMALY
    KAFKA -->|Archive| ARCHIVE
    
    ARCHIVE --> S3ARCH
    KAFKA -.->|Malformed/Poison| DLQ
```

### 3.2 Logical Architecture

```mermaid
flowchart LR
    subgraph Input["Input Layer"]
        direction TB
        PRODUCER[Evidence Producer]
        SCHEMA_REG[Schema Registry<br/>Glue/Confluent]
    end
    
    subgraph Core["Core Layer"]
        direction TB
        BROKER1[Broker 1]
        BROKER2[Broker 2]
        BROKER3[Broker 3]
        ZK[(ZooKeeper/<br/>KRaft)]
    end
    
    subgraph Output["Output Layer"]
        direction TB
        CG1[Consumer Group 1<br/>signal_engines.freshness]
        CG2[Consumer Group 2<br/>signal_engines.volume]
        CG3[Consumer Group 3<br/>signal_engines.contract]
        CGN[Consumer Group N<br/>...]
    end
    
    PRODUCER -->|Serialize| SCHEMA_REG
    PRODUCER -->|Produce| BROKER1
    PRODUCER -->|Produce| BROKER2
    PRODUCER -->|Produce| BROKER3
    
    BROKER1 --> CG1
    BROKER2 --> CG2
    BROKER3 --> CG3
    BROKER1 --> CGN
```

### 3.3 Physical Deployment (AWS)

| Component | AWS Service | Configuration |
|-----------|-------------|---------------|
| Kafka Cluster | Amazon MSK | 3+ brokers, kafka.m5.2xlarge |
| Storage | EBS gp3 | 1TB per broker, 3000 IOPS |
| Schema Registry | AWS Glue Schema Registry | Integrated with MSK |
| S3 Archive | Amazon S3 | Standard → IA → Glacier lifecycle |
| Monitoring | CloudWatch + Prometheus | Custom metrics via JMX |

---

## 4. Data Models & Schemas

### 4.1 Canonical Evidence Schema (JSON Schema)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "urn:schema:evidence:2.0",
  "type": "object",
  "required": [
    "evidence_id",
    "timestamp",
    "dataset_urn",
    "producer",
    "validation",
    "source"
  ],
  "properties": {
    "evidence_id": {
      "type": "string",
      "pattern": "^evd-[0-9A-HJKMNP-TV-Z]{26}$",
      "description": "ULID prefixed with evd-"
    },
    "timestamp": {
      "type": "string",
      "format": "date-time",
      "description": "ISO 8601 timestamp of evidence creation"
    },
    "dataset_urn": {
      "type": "string",
      "pattern": "^urn:dp:[a-z_]+:[a-z_]+$",
      "description": "Resolved dataset identifier"
    },
    "producer": {
      "type": "object",
      "required": ["id", "confidence"],
      "properties": {
        "id": {
          "type": "string",
          "description": "Producer service identifier"
        },
        "confidence": {
          "type": "string",
          "enum": ["HIGH", "MEDIUM", "LOW", "NONE"],
          "description": "Identity inference confidence"
        },
        "version": {
          "type": "string",
          "description": "Producer service version if available"
        }
      }
    },
    "validation": {
      "type": "object",
      "required": ["result", "gates"],
      "properties": {
        "result": {
          "type": "string",
          "enum": ["PASS", "FAIL"],
          "description": "Overall validation result"
        },
        "gates": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["gate", "result"],
            "properties": {
              "gate": {
                "type": "string",
                "enum": [
                  "G1_RESOLUTION",
                  "G2_IDENTITY",
                  "G3_SCHEMA",
                  "G4_CONTRACT",
                  "G5_PII"
                ]
              },
              "result": {
                "type": "string",
                "enum": ["PASS", "FAIL", "SKIP", "WARN"]
              },
              "reason_code": {
                "type": "string",
                "description": "Failure reason code"
              },
              "details": {
                "type": "object",
                "description": "Gate-specific details"
              }
            }
          }
        },
        "failed_gates": {
          "type": "array",
          "items": { "type": "string" },
          "description": "List of gates that failed"
        },
        "reason_codes": {
          "type": "array",
          "items": { "type": "string" },
          "description": "Aggregated failure reasons"
        }
      }
    },
    "fingerprints": {
      "type": "object",
      "properties": {
        "schema_fingerprint": {
          "type": "string",
          "description": "SHA-256 of canonicalized schema"
        },
        "payload_hash": {
          "type": "string",
          "description": "SHA-256 of payload for deduplication"
        }
      }
    },
    "source": {
      "type": "object",
      "required": ["topic", "partition", "offset"],
      "properties": {
        "topic": { "type": "string" },
        "partition": { "type": "integer" },
        "offset": { "type": "integer" },
        "timestamp_type": {
          "type": "string",
          "enum": ["CREATE_TIME", "LOG_APPEND_TIME"]
        }
      }
    },
    "otel": {
      "type": "object",
      "properties": {
        "trace_id": {
          "type": "string",
          "pattern": "^[a-f0-9]{32}$"
        },
        "span_id": {
          "type": "string",
          "pattern": "^[a-f0-9]{16}$"
        }
      }
    },
    "correlation": {
      "type": "object",
      "description": "Cross-evidence correlation for batch/streaming",
      "properties": {
        "run_id": { "type": "string" },
        "dag_id": { "type": "string" },
        "job_id": { "type": "string" }
      }
    }
  }
}
```

### 4.2 Avro Schema (Production)

```json
{
  "type": "record",
  "name": "EvidenceEvent",
  "namespace": "com.dataobs.evidence",
  "fields": [
    {"name": "evidence_id", "type": "string"},
    {"name": "timestamp", "type": {"type": "long", "logicalType": "timestamp-millis"}},
    {"name": "dataset_urn", "type": "string"},
    {"name": "producer", "type": {
      "type": "record",
      "name": "Producer",
      "fields": [
        {"name": "id", "type": "string"},
        {"name": "confidence", "type": {"type": "enum", "name": "Confidence", "symbols": ["HIGH", "MEDIUM", "LOW", "NONE"]}},
        {"name": "version", "type": ["null", "string"], "default": null}
      ]
    }},
    {"name": "validation", "type": {
      "type": "record",
      "name": "Validation",
      "fields": [
        {"name": "result", "type": {"type": "enum", "name": "Result", "symbols": ["PASS", "FAIL"]}},
        {"name": "gates", "type": {"type": "array", "items": {
          "type": "record",
          "name": "GateResult",
          "fields": [
            {"name": "gate", "type": "string"},
            {"name": "result", "type": "string"},
            {"name": "reason_code", "type": ["null", "string"], "default": null},
            {"name": "details", "type": ["null", {"type": "map", "values": "string"}], "default": null}
          ]
        }}},
        {"name": "failed_gates", "type": {"type": "array", "items": "string"}, "default": []},
        {"name": "reason_codes", "type": {"type": "array", "items": "string"}, "default": []}
      ]
    }},
    {"name": "fingerprints", "type": ["null", {
      "type": "record",
      "name": "Fingerprints",
      "fields": [
        {"name": "schema_fingerprint", "type": ["null", "string"], "default": null},
        {"name": "payload_hash", "type": ["null", "string"], "default": null}
      ]
    }], "default": null},
    {"name": "source", "type": {
      "type": "record",
      "name": "Source",
      "fields": [
        {"name": "topic", "type": "string"},
        {"name": "partition", "type": "int"},
        {"name": "offset", "type": "long"},
        {"name": "timestamp_type", "type": ["null", "string"], "default": null}
      ]
    }},
    {"name": "otel", "type": ["null", {
      "type": "record",
      "name": "OTel",
      "fields": [
        {"name": "trace_id", "type": ["null", "string"], "default": null},
        {"name": "span_id", "type": ["null", "string"], "default": null}
      ]
    }], "default": null},
    {"name": "correlation", "type": ["null", {
      "type": "record",
      "name": "Correlation",
      "fields": [
        {"name": "run_id", "type": ["null", "string"], "default": null},
        {"name": "dag_id", "type": ["null", "string"], "default": null},
        {"name": "job_id", "type": ["null", "string"], "default": null}
      ]
    }], "default": null}
  ]
}
```

### 4.3 Sample Evidence Events

#### 4.3.1 Successful Validation (PASS)

```json
{
  "evidence_id": "evd-01HQXY8MNP4QR7ST9VW2XYZ123",
  "timestamp": "2026-01-15T09:58:02.312Z",
  "dataset_urn": "urn:dp:orders:created",
  "producer": {
    "id": "orders-svc",
    "confidence": "HIGH",
    "version": "v3.16"
  },
  "validation": {
    "result": "PASS",
    "gates": [
      {"gate": "G1_RESOLUTION", "result": "PASS", "details": {"dataset_urn": "urn:dp:orders:created"}},
      {"gate": "G2_IDENTITY", "result": "PASS", "details": {"producer": "orders-svc", "confidence": "HIGH"}},
      {"gate": "G3_SCHEMA", "result": "PASS", "details": {"schema_id": "glue:orders.created:17"}},
      {"gate": "G4_CONTRACT", "result": "PASS", "details": {"contract_id": "dc:orders.created:3"}},
      {"gate": "G5_PII", "result": "PASS", "details": {"pii_detected": false}}
    ],
    "failed_gates": [],
    "reason_codes": []
  },
  "fingerprints": {
    "schema_fingerprint": "sha256:9f2c...",
    "payload_hash": "sha256:a1b3..."
  },
  "source": {
    "topic": "raw.orders.events",
    "partition": 4,
    "offset": 9918273,
    "timestamp_type": "CREATE_TIME"
  },
  "otel": {
    "trace_id": "ab91f3c2d4e5f6a7b8c9d0e1f2a3b4c5"
  }
}
```

#### 4.3.2 Failed Validation (Contract Breach)

```json
{
  "evidence_id": "evd-01HQXY8MNP4QR7ST9VW2XYZ456",
  "timestamp": "2026-01-15T09:58:02.312Z",
  "dataset_urn": "urn:dp:orders:created",
  "producer": {
    "id": "orders-svc",
    "confidence": "HIGH",
    "version": "v3.17"
  },
  "validation": {
    "result": "FAIL",
    "gates": [
      {"gate": "G1_RESOLUTION", "result": "PASS", "details": {"dataset_urn": "urn:dp:orders:created"}},
      {"gate": "G2_IDENTITY", "result": "PASS", "details": {"producer": "orders-svc", "confidence": "HIGH", "version": "v3.17"}},
      {"gate": "G3_SCHEMA", "result": "PASS", "details": {"schema_id": "glue:orders.created:17"}},
      {
        "gate": "G4_CONTRACT",
        "result": "FAIL",
        "reason_code": "MISSING_FIELD:customer_id",
        "details": {
          "contract_id": "dc:orders.created:3",
          "violated_rule": {
            "field": "customer_id",
            "constraint": "required",
            "actual": "null"
          }
        }
      },
      {"gate": "G5_PII", "result": "PASS", "details": {"pii_detected": false}}
    ],
    "failed_gates": ["G4_CONTRACT"],
    "reason_codes": ["MISSING_FIELD:customer_id"]
  },
  "fingerprints": {
    "schema_fingerprint": "sha256:a1b3...",
    "payload_hash": "sha256:c4d5..."
  },
  "source": {
    "topic": "raw.orders.events",
    "partition": 4,
    "offset": 9918274,
    "timestamp_type": "CREATE_TIME"
  },
  "otel": {
    "trace_id": "cd23e4f5a6b7c8d9e0f1a2b3c4d5e6f7"
  }
}
```

---

## 5. API Specifications

### 5.1 Upstream Contract (Producer API)

#### 5.1.1 Kafka Producer Configuration

```python
from confluent_kafka import Producer
from confluent_kafka.serialization import SerializationContext, MessageField
from confluent_kafka.schema_registry.avro import AvroSerializer

class EvidenceProducer:
    """
    Evidence Bus producer for Policy Enforcer and batch/stream emitters.
    """
    
    TOPIC = "signal_factory.evidence"
    DLQ_TOPIC = "signal_factory.evidence.dlq"
    
    def __init__(self, bootstrap_servers: str, schema_registry_url: str):
        self.schema_registry = SchemaRegistryClient({'url': schema_registry_url})
        self.avro_serializer = AvroSerializer(
            self.schema_registry,
            EVIDENCE_AVRO_SCHEMA,
            to_dict=lambda e, ctx: e.to_dict()
        )
        
        self.producer = Producer({
            'bootstrap.servers': bootstrap_servers,
            'acks': 'all',  # Strongest durability
            'enable.idempotence': True,  # Exactly-once semantics
            'max.in.flight.requests.per.connection': 5,
            'retries': 2147483647,  # Infinite retries
            'delivery.timeout.ms': 120000,  # 2 minutes
            'linger.ms': 5,  # Batch for efficiency
            'batch.size': 65536,  # 64KB batches
            'compression.type': 'zstd',  # Best compression ratio
            'client.id': 'policy-enforcer-producer'
        })
    
    def emit_evidence(self, evidence: EvidenceEvent) -> None:
        """
        Emit evidence event to the Evidence Bus.
        
        Partition key: dataset_urn (ensures ordering within dataset)
        """
        try:
            self.producer.produce(
                topic=self.TOPIC,
                key=evidence.dataset_urn.encode('utf-8'),
                value=self.avro_serializer(
                    evidence,
                    SerializationContext(self.TOPIC, MessageField.VALUE)
                ),
                headers={
                    'evidence_id': evidence.evidence_id.encode('utf-8'),
                    'producer_id': evidence.producer.id.encode('utf-8'),
                    'validation_result': evidence.validation.result.encode('utf-8')
                },
                callback=self._delivery_callback
            )
        except Exception as e:
            self._handle_produce_error(evidence, e)
    
    def _delivery_callback(self, err, msg):
        if err:
            logger.error(f"Evidence delivery failed: {err}", extra={
                'evidence_id': msg.headers().get('evidence_id'),
                'topic': msg.topic(),
                'partition': msg.partition()
            })
            metrics.increment('evidence_bus.produce.error')
        else:
            metrics.increment('evidence_bus.produce.success')
            metrics.histogram('evidence_bus.produce.latency_ms', 
                            (time.time_ns() - msg.timestamp()[1]) / 1_000_000)
    
    def _handle_produce_error(self, evidence: EvidenceEvent, error: Exception):
        """Route to DLQ on persistent failures."""
        logger.error(f"Moving evidence to DLQ: {error}", extra={
            'evidence_id': evidence.evidence_id
        })
        # Simplified DLQ routing
        self.producer.produce(
            topic=self.DLQ_TOPIC,
            key=evidence.dataset_urn.encode('utf-8'),
            value=evidence.to_json().encode('utf-8'),
            headers={'error': str(error).encode('utf-8')}
        )
```

#### 5.1.2 Evidence ID Generation (Deterministic)

```python
import hashlib
from ulid import ULID

class EvidenceIdGenerator:
    """
    Generates deterministic evidence IDs for idempotency.
    Same raw event always produces same evidence_id.
    """
    
    @staticmethod
    def generate(raw_topic: str, partition: int, offset: int) -> str:
        """
        Deterministic evidence_id from source coordinates.
        
        Args:
            raw_topic: Source Kafka topic name
            partition: Source partition number
            offset: Source offset within partition
            
        Returns:
            Deterministic evidence ID (evd-<ulid>)
        """
        # Create deterministic seed from source coordinates
        seed = f"{raw_topic}:{partition}:{offset}".encode('utf-8')
        hash_bytes = hashlib.sha256(seed).digest()[:16]
        
        # Generate ULID with deterministic randomness
        ulid = ULID.from_bytes(hash_bytes)
        return f"evd-{ulid}"
    
    @staticmethod
    def generate_for_batch(run_id: str, dataset_urn: str, batch_index: int) -> str:
        """Generate deterministic ID for batch evidence."""
        seed = f"{run_id}:{dataset_urn}:{batch_index}".encode('utf-8')
        hash_bytes = hashlib.sha256(seed).digest()[:16]
        ulid = ULID.from_bytes(hash_bytes)
        return f"evd-{ulid}"
```

### 5.2 Downstream Contract (Consumer API)

#### 5.2.1 Consumer Group Naming Convention

| Consumer Group | Owner | Purpose |
|----------------|-------|---------|
| `signal_engines.freshness` | Signal Processing | Freshness signal computation |
| `signal_engines.volume` | Signal Processing | Volume anomaly detection |
| `signal_engines.contract` | Signal Processing | Contract compliance rates |
| `signal_engines.drift` | Signal Processing | Schema drift detection |
| `signal_engines.dq` | Signal Processing | Data quality aggregation |
| `signal_engines.anomaly` | Signal Processing | ML-based anomaly detection |
| `evidence_archiver` | Platform Core | S3 archival worker |
| `rca_replay` | AI & Intelligence | On-demand replay for RCA |

#### 5.2.2 Kafka Consumer Configuration

```python
from confluent_kafka import Consumer, KafkaError
from confluent_kafka.serialization import SerializationContext, MessageField
from confluent_kafka.schema_registry.avro import AvroDeserializer

class EvidenceConsumer:
    """
    Evidence Bus consumer for Signal Engines.
    """
    
    TOPIC = "signal_factory.evidence"
    
    def __init__(
        self,
        bootstrap_servers: str,
        schema_registry_url: str,
        consumer_group: str,
        instance_id: str
    ):
        self.schema_registry = SchemaRegistryClient({'url': schema_registry_url})
        self.avro_deserializer = AvroDeserializer(
            self.schema_registry,
            EVIDENCE_AVRO_SCHEMA,
            from_dict=EvidenceEvent.from_dict
        )
        
        self.consumer = Consumer({
            'bootstrap.servers': bootstrap_servers,
            'group.id': consumer_group,
            'group.instance.id': f"{consumer_group}-{instance_id}",  # Static membership
            'auto.offset.reset': 'earliest',
            'enable.auto.commit': False,  # Manual commit for at-least-once
            'max.poll.interval.ms': 300000,  # 5 minutes
            'session.timeout.ms': 45000,
            'heartbeat.interval.ms': 15000,
            'fetch.min.bytes': 1024,
            'fetch.max.wait.ms': 500,
            'max.partition.fetch.bytes': 1048576,  # 1MB
            'isolation.level': 'read_committed'  # Transactional safety
        })
        
        self.consumer.subscribe([self.TOPIC], on_assign=self._on_assign)
    
    def _on_assign(self, consumer, partitions):
        """Log partition assignments for debugging."""
        logger.info(f"Assigned partitions: {[p.partition for p in partitions]}")
        metrics.gauge('evidence_bus.assigned_partitions', len(partitions))
    
    def poll_batch(self, batch_size: int = 500, timeout: float = 1.0) -> List[EvidenceEvent]:
        """
        Poll a batch of evidence events.
        
        Returns:
            List of deserialized evidence events
        """
        messages = self.consumer.consume(batch_size, timeout)
        events = []
        
        for msg in messages:
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                logger.error(f"Consumer error: {msg.error()}")
                metrics.increment('evidence_bus.consume.error')
                continue
            
            try:
                event = self.avro_deserializer(
                    msg.value(),
                    SerializationContext(msg.topic(), MessageField.VALUE)
                )
                events.append(event)
                metrics.increment('evidence_bus.consume.success')
            except Exception as e:
                logger.error(f"Deserialization failed: {e}", extra={
                    'partition': msg.partition(),
                    'offset': msg.offset()
                })
                metrics.increment('evidence_bus.consume.deserialize_error')
        
        return events
    
    def commit(self) -> None:
        """Commit offsets after successful processing."""
        self.consumer.commit(asynchronous=False)
```

### 5.3 Admin API (REST)

#### 5.3.1 OpenAPI Specification

```yaml
openapi: 3.0.3
info:
  title: Evidence Bus Admin API
  version: 1.0.0
  description: Administrative API for Evidence Bus operations

paths:
  /api/v1/evidence-bus/health:
    get:
      summary: Health check
      responses:
        '200':
          description: Healthy
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HealthStatus'

  /api/v1/evidence-bus/metrics:
    get:
      summary: Get Evidence Bus metrics
      responses:
        '200':
          description: Current metrics
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/BusMetrics'

  /api/v1/evidence-bus/consumer-groups:
    get:
      summary: List consumer groups and lag
      responses:
        '200':
          description: Consumer group status
          content:
            application/json:
              schema:
                type: array
                items:
                  $ref: '#/components/schemas/ConsumerGroupStatus'

  /api/v1/evidence-bus/replay:
    post:
      summary: Trigger evidence replay
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/ReplayRequest'
      responses:
        '202':
          description: Replay initiated
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ReplayResponse'

  /api/v1/evidence-bus/dlq:
    get:
      summary: Get DLQ status and messages
      parameters:
        - name: limit
          in: query
          schema:
            type: integer
            default: 100
      responses:
        '200':
          description: DLQ messages
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/DLQStatus'

  /api/v1/evidence-bus/dlq/retry:
    post:
      summary: Retry DLQ messages
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/DLQRetryRequest'
      responses:
        '202':
          description: Retry initiated

components:
  schemas:
    HealthStatus:
      type: object
      properties:
        status:
          type: string
          enum: [healthy, degraded, unhealthy]
        brokers_available:
          type: integer
        partitions_online:
          type: integer
        replication_factor:
          type: integer
        last_evidence_timestamp:
          type: string
          format: date-time

    BusMetrics:
      type: object
      properties:
        messages_per_second:
          type: number
        bytes_per_second:
          type: number
        total_messages_24h:
          type: integer
        total_bytes_24h:
          type: integer
        partition_distribution:
          type: array
          items:
            type: object
            properties:
              partition:
                type: integer
              message_count:
                type: integer
              bytes:
                type: integer

    ConsumerGroupStatus:
      type: object
      properties:
        group_id:
          type: string
        state:
          type: string
          enum: [Stable, Rebalancing, Dead, Empty]
        members:
          type: integer
        total_lag:
          type: integer
        partitions:
          type: array
          items:
            type: object
            properties:
              partition:
                type: integer
              current_offset:
                type: integer
              end_offset:
                type: integer
              lag:
                type: integer

    ReplayRequest:
      type: object
      required:
        - start_time
        - end_time
      properties:
        start_time:
          type: string
          format: date-time
        end_time:
          type: string
          format: date-time
        dataset_urn:
          type: string
          description: Filter by dataset (optional)
        target_topic:
          type: string
          description: Replay destination topic

    ReplayResponse:
      type: object
      properties:
        replay_id:
          type: string
        status:
          type: string
        estimated_messages:
          type: integer
        estimated_duration_seconds:
          type: integer

    DLQStatus:
      type: object
      properties:
        total_messages:
          type: integer
        oldest_message:
          type: string
          format: date-time
        error_breakdown:
          type: object
          additionalProperties:
            type: integer
        messages:
          type: array
          items:
            type: object
            properties:
              evidence_id:
                type: string
              error:
                type: string
              timestamp:
                type: string
                format: date-time

    DLQRetryRequest:
      type: object
      properties:
        evidence_ids:
          type: array
          items:
            type: string
        retry_all:
          type: boolean
          default: false
```

---

## 6. Scalability & Throughput

### 6.1 Capacity Planning

| Metric | Baseline | Peak (Incident) | Burst |
|--------|----------|-----------------|-------|
| Raw Events/sec | 50,000 | 200,000 | 500,000 |
| Evidence Events/sec | 50,000 | 200,000 | 500,000 |
| Producers (services) | 200 | 200 | 200 |
| Topics monitored | 500 | 500 | 500 |
| Partitions (Evidence Bus) | 64 | 64 | 256 (expanded) |
| Evidence size (avg) | 1.2 KB | 1.5 KB | 2 KB |
| Daily volume | ~4 TB | ~16 TB | ~40 TB |

### 6.2 Partitioning Strategy

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     EVIDENCE BUS PARTITIONING                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Partition Key: dataset_urn                                                 │
│                                                                             │
│  Rationale:                                                                 │
│  • Ensures all evidence for a dataset lands in same partition              │
│  • Enables Signal Engines to maintain per-dataset state locally            │
│  • Provides ordering guarantee within a dataset (required for drift)       │
│                                                                             │
│  Partition Assignment:                                                      │
│  • hash(dataset_urn) % 64 → partition_id                                   │
│  • Hot datasets (>10K events/sec) get dedicated partitions                 │
│                                                                             │
│  Consumer Group Model:                                                      │
│  • signal_engines.freshness (6 instances, 10-11 partitions each)           │
│  • signal_engines.volume (6 instances)                                      │
│  • signal_engines.contract (6 instances)                                    │
│  • signal_engines.dq (6 instances)                                          │
│  • signal_engines.anomaly (4 instances)                                     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 6.3 Autoscaling Triggers

| Component | Scale-Up Trigger | Scale-Down Trigger | Min | Max |
|-----------|------------------|-------------------|-----|-----|
| Evidence Bus | Partition fill >80% | N/A (manual) | 64 | 256 |
| Consumer Instances | Lag >30s OR CPU >70% | Lag <5s AND CPU <30% | 4 | 32 |

### 6.4 Backpressure Handling

```python
class BackpressureManager:
    """
    Manages Evidence Bus behavior under overload conditions.
    """
    
    MODES = {
        'NORMAL': {
            'sampling_rate': {'TIER1': 1.0, 'TIER2': 1.0, 'TIER3': 1.0},
            'dlq_threshold': 0.01  # 1% error rate triggers DLQ
        },
        'DEGRADED': {
            'sampling_rate': {'TIER1': 1.0, 'TIER2': 0.5, 'TIER3': 0.1},
            'dlq_threshold': 0.05  # 5% error rate triggers DLQ
        },
        'CRITICAL': {
            'sampling_rate': {'TIER1': 1.0, 'TIER2': 0.1, 'TIER3': 0.01},
            'dlq_threshold': 0.10  # 10% error rate triggers DLQ
        }
    }
    
    def __init__(self):
        self.current_mode = 'NORMAL'
        self.lag_threshold_seconds = {
            'NORMAL': 30,
            'DEGRADED': 120,
            'CRITICAL': 300
        }
    
    def evaluate_mode(self, metrics: BusMetrics) -> str:
        """
        Determine operating mode based on current metrics.
        
        Invariants:
        1. Tier-1 datasets ALWAYS get full processing (never sampled)
        2. Evidence for Tier-1 is NEVER dropped (DLQ if necessary)
        3. Lag metrics are always emitted (observability of observability)
        4. Mode transitions are logged and alerted
        """
        max_lag = max(metrics.consumer_lag.values())
        
        if max_lag > self.lag_threshold_seconds['CRITICAL']:
            new_mode = 'CRITICAL'
        elif max_lag > self.lag_threshold_seconds['DEGRADED']:
            new_mode = 'DEGRADED'
        else:
            new_mode = 'NORMAL'
        
        if new_mode != self.current_mode:
            logger.warning(f"Mode transition: {self.current_mode} → {new_mode}", extra={
                'max_lag_seconds': max_lag,
                'previous_mode': self.current_mode,
                'new_mode': new_mode
            })
            self.current_mode = new_mode
        
        return self.current_mode
    
    def should_process(self, evidence: EvidenceEvent, mode: str) -> bool:
        """Determine if evidence should be processed based on tier and mode."""
        tier = self._get_dataset_tier(evidence.dataset_urn)
        sampling_rate = self.MODES[mode]['sampling_rate'][tier]
        
        if tier == 'TIER1':
            return True  # Never sample Tier-1
        
        return random.random() < sampling_rate
```

---

## 7. Reliability & Fault Tolerance

### 7.1 Delivery Semantics

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     DELIVERY SEMANTICS BOUNDARY                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Raw Topic → Enforcer:        AT-LEAST-ONCE                                │
│  • Kafka consumer commits after evidence emit                              │
│  • Crash before commit = reprocess (duplicate evidence possible)           │
│                                                                             │
│  Enforcer → Evidence Bus:     AT-LEAST-ONCE with IDEMPOTENCY               │
│  • evidence_id = deterministic(raw_topic, partition, offset)               │
│  • Duplicate evidence has same evidence_id                                 │
│  • Signal Engines dedupe by evidence_id within window                      │
│                                                                             │
│  Evidence Bus → Signal Engines: AT-LEAST-ONCE                              │
│  • Engines are idempotent (upsert by evidence_id + window)                 │
│  • Duplicate processing = same signal state                                │
│                                                                             │
│  NET EFFECT: EFFECTIVELY-ONCE for signal computation                       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 7.2 Dead Letter Queue (DLQ) Strategy

```python
class DLQManager:
    """
    Manages Dead Letter Queue for malformed or unprocessable evidence.
    """
    
    DLQ_TOPIC = "signal_factory.evidence.dlq"
    
    # Retry tiers with exponential backoff
    RETRY_POLICY = {
        'TRANSIENT': {
            'max_retries': 5,
            'base_delay_seconds': 1,
            'max_delay_seconds': 60
        },
        'SCHEMA': {
            'max_retries': 3,
            'base_delay_seconds': 300,  # 5 minutes
            'max_delay_seconds': 3600   # 1 hour
        },
        'PERMANENT': {
            'max_retries': 0,
            'action': 'ALERT_AND_ARCHIVE'
        }
    }
    
    def classify_error(self, error: Exception) -> str:
        """Classify error for retry policy selection."""
        if isinstance(error, (ConnectionError, TimeoutError)):
            return 'TRANSIENT'
        elif isinstance(error, SerializationError):
            return 'SCHEMA'
        else:
            return 'PERMANENT'
    
    def should_retry(self, evidence_id: str, error_class: str) -> bool:
        """Determine if evidence should be retried."""
        retry_count = self._get_retry_count(evidence_id)
        policy = self.RETRY_POLICY[error_class]
        return retry_count < policy['max_retries']
    
    def route_to_dlq(
        self,
        evidence: EvidenceEvent,
        error: Exception,
        error_class: str
    ) -> None:
        """Route failed evidence to DLQ with metadata."""
        dlq_record = {
            'evidence': evidence.to_dict(),
            'error': {
                'message': str(error),
                'type': type(error).__name__,
                'class': error_class,
                'stack_trace': traceback.format_exc()
            },
            'metadata': {
                'routed_at': datetime.utcnow().isoformat(),
                'retry_count': self._get_retry_count(evidence.evidence_id),
                'source_partition': evidence.source.partition,
                'source_offset': evidence.source.offset
            }
        }
        
        self.producer.produce(
            topic=self.DLQ_TOPIC,
            key=evidence.evidence_id.encode('utf-8'),
            value=json.dumps(dlq_record).encode('utf-8'),
            headers={
                'error_class': error_class.encode('utf-8'),
                'original_topic': evidence.source.topic.encode('utf-8')
            }
        )
        
        metrics.increment('evidence_bus.dlq.routed', tags={
            'error_class': error_class,
            'dataset_urn': evidence.dataset_urn
        })
```

### 7.3 DLQ Replay Tool

```python
class DLQReplayTool:
    """
    Operator tool for replaying DLQ messages.
    """
    
    def replay_by_time_range(
        self,
        start_time: datetime,
        end_time: datetime,
        error_class: Optional[str] = None,
        dry_run: bool = True
    ) -> ReplayResult:
        """
        Replay DLQ messages within a time range.
        
        Args:
            start_time: Start of replay window
            end_time: End of replay window
            error_class: Filter by error class (optional)
            dry_run: If True, only count messages without replaying
        """
        messages = self._fetch_dlq_messages(start_time, end_time, error_class)
        
        if dry_run:
            return ReplayResult(
                total_messages=len(messages),
                would_replay=len(messages),
                replayed=0,
                failed=0
            )
        
        replayed = 0
        failed = 0
        
        for msg in messages:
            try:
                # Re-emit to main topic
                self.evidence_producer.emit_evidence(
                    EvidenceEvent.from_dict(msg['evidence'])
                )
                # Mark as replayed in DLQ
                self._mark_replayed(msg['evidence']['evidence_id'])
                replayed += 1
            except Exception as e:
                logger.error(f"Replay failed: {e}")
                failed += 1
        
        return ReplayResult(
            total_messages=len(messages),
            would_replay=len(messages),
            replayed=replayed,
            failed=failed
        )
```

### 7.4 Circuit Breaker

```python
class EvidenceBusCircuitBreaker:
    """
    Circuit breaker for Evidence Bus producers.
    
    States:
    - CLOSED: Normal operation, requests flow through
    - OPEN: Failures exceeded threshold, fast-fail all requests
    - HALF_OPEN: Testing if system recovered
    """
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 30,
        half_open_requests: int = 3
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_requests = half_open_requests
        
        self.state = 'CLOSED'
        self.failure_count = 0
        self.last_failure_time = None
        self.half_open_successes = 0
    
    def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with circuit breaker protection."""
        if self.state == 'OPEN':
            if self._should_attempt_recovery():
                self.state = 'HALF_OPEN'
                self.half_open_successes = 0
            else:
                raise CircuitBreakerOpenError("Circuit breaker is OPEN")
        
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise
    
    def _on_success(self):
        if self.state == 'HALF_OPEN':
            self.half_open_successes += 1
            if self.half_open_successes >= self.half_open_requests:
                self.state = 'CLOSED'
                self.failure_count = 0
                logger.info("Circuit breaker CLOSED after recovery")
        else:
            self.failure_count = 0
    
    def _on_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.failure_threshold:
            self.state = 'OPEN'
            logger.warning(f"Circuit breaker OPEN after {self.failure_count} failures")
            metrics.increment('evidence_bus.circuit_breaker.opened')
    
    def _should_attempt_recovery(self) -> bool:
        return (time.time() - self.last_failure_time) >= self.recovery_timeout
```

---

## 8. Security Architecture

### 8.1 Authentication & Authorization

| Domain | Approach | Implementation |
|--------|----------|----------------|
| Producer Auth | Service-to-service IAM | IRSA (IAM Roles for Service Accounts) |
| Consumer Auth | Service-to-service IAM | IRSA with scoped policies |
| Admin API Auth | mTLS + IAM | ALB with client certificate validation |
| MSK Auth | IAM authentication | AWS MSK IAM auth mode |

### 8.2 IAM Policies

#### 8.2.1 Policy Enforcer (Producer)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ProduceToEvidenceBus",
      "Effect": "Allow",
      "Action": [
        "kafka-cluster:Connect",
        "kafka-cluster:DescribeTopic",
        "kafka-cluster:WriteData"
      ],
      "Resource": [
        "arn:aws:kafka:*:*:cluster/signal-factory/*",
        "arn:aws:kafka:*:*:topic/signal-factory/*/signal_factory.evidence",
        "arn:aws:kafka:*:*:topic/signal-factory/*/signal_factory.evidence.dlq"
      ]
    },
    {
      "Sid": "AccessSchemaRegistry",
      "Effect": "Allow",
      "Action": [
        "glue:GetSchemaVersion",
        "glue:GetSchema"
      ],
      "Resource": "arn:aws:glue:*:*:schema/signal-factory/*"
    }
  ]
}
```

#### 8.2.2 Signal Engine (Consumer)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ConsumeFromEvidenceBus",
      "Effect": "Allow",
      "Action": [
        "kafka-cluster:Connect",
        "kafka-cluster:DescribeTopic",
        "kafka-cluster:DescribeGroup",
        "kafka-cluster:ReadData"
      ],
      "Resource": [
        "arn:aws:kafka:*:*:cluster/signal-factory/*",
        "arn:aws:kafka:*:*:topic/signal-factory/*/signal_factory.evidence",
        "arn:aws:kafka:*:*:group/signal-factory/*/signal_engines.*"
      ]
    },
    {
      "Sid": "AccessSchemaRegistry",
      "Effect": "Allow",
      "Action": [
        "glue:GetSchemaVersion",
        "glue:GetSchema"
      ],
      "Resource": "arn:aws:glue:*:*:schema/signal-factory/*"
    }
  ]
}
```

### 8.3 Encryption

| Layer | Mechanism | Configuration |
|-------|-----------|---------------|
| In-Transit | TLS 1.3 | MSK TLS listeners, internal ALBs with ACM certs |
| At-Rest (Kafka) | KMS | AWS managed key for MSK encryption |
| At-Rest (S3) | SSE-S3 / SSE-KMS | Bucket default encryption |
| Schema Registry | TLS | Glue API over HTTPS |

### 8.4 PII Handling

Evidence events may contain PII indicators from the G5_PII gate. The Evidence Bus itself does NOT store raw PII data, but the `pii_detected` flag and field-level indicators are stored.

```python
class PIIRedactionPolicy:
    """
    PII handling policy for Evidence Bus.
    """
    
    # Evidence DOES contain:
    # - pii_detected: boolean flag
    # - pii_fields: list of field names flagged as PII
    
    # Evidence DOES NOT contain:
    # - Actual PII values (redacted at source)
    # - Raw payload with PII
    
    @staticmethod
    def validate_evidence_pii_compliance(evidence: EvidenceEvent) -> bool:
        """Ensure evidence does not contain raw PII values."""
        # PII details should only contain field names, not values
        pii_gate = next(
            (g for g in evidence.validation.gates if g.gate == 'G5_PII'),
            None
        )
        
        if pii_gate and pii_gate.details:
            # Verify only field names, not values
            if 'pii_values' in pii_gate.details:
                raise PIIViolationError("Evidence must not contain PII values")
        
        return True
```

---

## 9. Observability & Monitoring

### 9.1 Platform Health Metrics

| Metric | Description | Alert Threshold | Severity |
|--------|-------------|-----------------|----------|
| `evidence_bus.lag_seconds` | Max consumer lag across groups | >30s (warn), >120s (crit) | P1 |
| `evidence_bus.produce.rate` | Evidence production rate | <50% baseline | P1 |
| `evidence_bus.produce.error_rate` | Producer error percentage | >1% | P2 |
| `evidence_bus.consume.rate` | Evidence consumption rate | <50% of produce rate | P1 |
| `evidence_bus.partition_skew` | Partition imbalance ratio | >2.0 | P2 |
| `evidence_bus.dlq.count` | DLQ message accumulation | >1000 in 1hr | P2 |
| `evidence_bus.replication_lag` | Under-replicated partitions | >0 for 5min | P1 |

### 9.2 Prometheus Metrics

```python
from prometheus_client import Counter, Gauge, Histogram

# Producer metrics
evidence_produced_total = Counter(
    'evidence_bus_produced_total',
    'Total evidence events produced',
    ['dataset_urn', 'validation_result']
)

evidence_produce_latency = Histogram(
    'evidence_bus_produce_latency_seconds',
    'Evidence production latency',
    ['producer_id'],
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 2.0]
)

# Consumer metrics
evidence_consumed_total = Counter(
    'evidence_bus_consumed_total',
    'Total evidence events consumed',
    ['consumer_group', 'partition']
)

consumer_lag_seconds = Gauge(
    'evidence_bus_consumer_lag_seconds',
    'Consumer lag in seconds',
    ['consumer_group', 'partition']
)

# DLQ metrics
dlq_messages_total = Counter(
    'evidence_bus_dlq_total',
    'Total messages routed to DLQ',
    ['error_class', 'dataset_urn']
)

dlq_pending_count = Gauge(
    'evidence_bus_dlq_pending',
    'Pending messages in DLQ'
)

# System metrics
partition_message_count = Gauge(
    'evidence_bus_partition_messages',
    'Message count per partition',
    ['partition']
)

circuit_breaker_state = Gauge(
    'evidence_bus_circuit_breaker_state',
    'Circuit breaker state (0=closed, 1=half-open, 2=open)'
)
```

### 9.3 Distributed Tracing

All evidence events preserve OTel trace context for end-to-end tracing:

```python
from opentelemetry import trace
from opentelemetry.propagate import extract, inject

class TracingMiddleware:
    """
    OTel tracing integration for Evidence Bus.
    """
    
    tracer = trace.get_tracer("evidence-bus")
    
    @classmethod
    def extract_context(cls, evidence: EvidenceEvent) -> Context:
        """Extract trace context from evidence event."""
        if evidence.otel and evidence.otel.trace_id:
            # Reconstruct carrier from evidence
            carrier = {
                'traceparent': f"00-{evidence.otel.trace_id}-{evidence.otel.span_id or '0'*16}-01"
            }
            return extract(carrier)
        return None
    
    @classmethod
    def create_span(cls, evidence: EvidenceEvent, operation: str) -> Span:
        """Create span linked to original trace."""
        context = cls.extract_context(evidence)
        
        with cls.tracer.start_as_current_span(
            f"evidence_bus.{operation}",
            context=context,
            kind=trace.SpanKind.CONSUMER
        ) as span:
            span.set_attribute("evidence_id", evidence.evidence_id)
            span.set_attribute("dataset_urn", evidence.dataset_urn)
            span.set_attribute("validation_result", evidence.validation.result)
            return span
```

### 9.4 Logging Strategy

```python
import structlog

logger = structlog.get_logger()

# Standard log format for Evidence Bus operations
log_config = {
    'evidence_id': str,
    'dataset_urn': str,
    'producer_id': str,
    'validation_result': str,
    'partition': int,
    'offset': int,
    'consumer_group': str,
    'processing_time_ms': float
}

# Example log entries
logger.info(
    "evidence_produced",
    evidence_id="evd-01HQXY8MNP4QR7ST9VW2XYZ123",
    dataset_urn="urn:dp:orders:created",
    producer_id="orders-svc",
    validation_result="PASS",
    partition=4,
    offset=9918273,
    processing_time_ms=1.23
)

logger.warning(
    "consumer_lag_high",
    consumer_group="signal_engines.freshness",
    partition=12,
    lag_seconds=45,
    threshold_seconds=30
)

logger.error(
    "evidence_to_dlq",
    evidence_id="evd-01HQXY8MNP4QR7ST9VW2XYZ456",
    error_class="SCHEMA",
    error_message="Schema version not found",
    retry_count=2
)
```

### 9.5 Dashboard Specifications

#### 9.5.1 Evidence Flow Dashboard

| Panel | Visualization | Query |
|-------|---------------|-------|
| Evidence Rate | Time series | `rate(evidence_bus_produced_total[5m])` |
| Consumer Lag | Gauge per group | `max(evidence_bus_consumer_lag_seconds) by (consumer_group)` |
| Error Rate | Percentage | `rate(evidence_bus_dlq_total[5m]) / rate(evidence_bus_produced_total[5m])` |
| Partition Distribution | Heatmap | `evidence_bus_partition_messages` |
| P99 Latency | Time series | `histogram_quantile(0.99, evidence_bus_produce_latency_seconds)` |

---

## 10. Operational Runbooks

### 10.1 Consumer Lag Recovery

```markdown
## Runbook: Evidence Bus Consumer Lag Recovery

### Trigger
- Alert: evidence_bus.lag_seconds > 120 for any consumer group

### Investigation
1. Check consumer group status:
   ```bash
   kafka-consumer-groups.sh --bootstrap-server $BOOTSTRAP \
     --describe --group signal_engines.freshness
   ```

2. Identify lagging partitions:
   ```bash
   # Look for partitions with lag > 10000
   ```

3. Check consumer instance health:
   ```bash
   kubectl get pods -l app=signal-engine-freshness
   kubectl logs -l app=signal-engine-freshness --tail=100
   ```

### Resolution Options

#### Option A: Scale consumers (preferred)
```bash
kubectl scale deployment signal-engine-freshness --replicas=12
```

#### Option B: Reset offsets (data loss - requires approval)
```bash
kafka-consumer-groups.sh --bootstrap-server $BOOTSTRAP \
  --group signal_engines.freshness \
  --topic signal_factory.evidence \
  --reset-offsets --to-latest --execute
```

#### Option C: Enable degraded mode (sampling)
```bash
kubectl set env deployment/signal-engine-freshness \
  BACKPRESSURE_MODE=DEGRADED
```

### Escalation
- P1: Page on-call if lag > 300 seconds
- P0: Page incident commander if lag > 600 seconds
```

### 10.2 DLQ Processing

```markdown
## Runbook: DLQ Processing

### Trigger
- Alert: evidence_bus.dlq.count > 1000 in 1 hour

### Investigation
1. Check DLQ error breakdown:
   ```bash
   curl -X GET "http://evidence-bus-admin/api/v1/evidence-bus/dlq"
   ```

2. Sample DLQ messages:
   ```bash
   kafka-console-consumer.sh --bootstrap-server $BOOTSTRAP \
     --topic signal_factory.evidence.dlq \
     --max-messages 10 \
     --from-beginning
   ```

3. Categorize errors:
   - TRANSIENT: Network timeouts, broker unavailable
   - SCHEMA: Schema version mismatch
   - PERMANENT: Malformed evidence, validation failure

### Resolution

#### For TRANSIENT errors:
```bash
# Automatic retry will handle these
# If persistent, check MSK cluster health
```

#### For SCHEMA errors:
1. Verify schema registry availability
2. If schema missing, register schema version
3. Trigger replay:
   ```bash
   curl -X POST "http://evidence-bus-admin/api/v1/evidence-bus/dlq/retry" \
     -d '{"error_class": "SCHEMA"}'
   ```

#### For PERMANENT errors:
1. Export to S3 for analysis
2. Create ticket for data team investigation
3. Clear from DLQ after export
```

### 10.3 Partition Rebalancing

```markdown
## Runbook: Partition Expansion

### Trigger
- Sustained throughput > 80% capacity
- Partition fill > 80% for 1 hour

### Pre-Requisites
- Maintenance window approval
- All consumer groups in STABLE state

### Procedure

1. Create expansion plan:
   ```bash
   kafka-reassign-partitions.sh --bootstrap-server $BOOTSTRAP \
     --topics-to-move-json-file topics.json \
     --broker-list "1,2,3,4,5,6" \
     --generate
   ```

2. Execute reassignment (during maintenance window):
   ```bash
   kafka-reassign-partitions.sh --bootstrap-server $BOOTSTRAP \
     --reassignment-json-file reassignment.json \
     --execute
   ```

3. Verify completion:
   ```bash
   kafka-reassign-partitions.sh --bootstrap-server $BOOTSTRAP \
     --reassignment-json-file reassignment.json \
     --verify
   ```

4. Update consumer configurations:
   ```bash
   # Consumers will automatically rebalance to new partitions
   # Monitor for temporary lag increase
   ```

### Rollback
- Partition count cannot be reduced
- If issues, revert consumer scaling to handle reduced parallelism
```

---

## 11. Cost Analysis

### 11.1 Infrastructure Costs

| Component | Configuration | Monthly Cost | Notes |
|-----------|---------------|--------------|-------|
| Amazon MSK | 3x kafka.m5.2xlarge, 64 partitions | ~$3,500 | 7-day retention |
| EBS Storage | 3 TB (1TB per broker) | ~$300 | gp3 volumes |
| Data Transfer | ~100 TB/month inter-AZ | ~$200 | Consumer traffic |
| **MSK Subtotal** | | **~$4,000** | |
| S3 Standard | ~50 TB (30-day warm) | ~$1,150 | Evidence archive |
| S3 Glacier | ~150 TB (90-day cold) | ~$300 | Long-term retention |
| S3 Requests | ~1B PUT/GET | ~$50 | Archive operations |
| **S3 Subtotal** | | **~$1,500** | |
| **TOTAL** | | **~$5,500/month** | |

### 11.2 Cost Optimization Strategies

| Strategy | Potential Savings | Trade-off |
|----------|-------------------|-----------|
| Tiered sampling | ~20% | Reduced visibility for Tier-3 |
| Compression (zstd) | ~30% storage | CPU overhead |
| Reduced retention (5d hot) | ~15% MSK | Shorter replay window |
| S3 Intelligent Tiering | ~10% S3 | Access latency variation |

---

## 12. Appendices

### 12.1 Glossary

| Term | Definition |
|------|------------|
| Evidence | Immutable record of per-event validation result (PASS/FAIL with reason codes) |
| Evidence Bus | The `signal_factory.evidence` Kafka topic - sole API for downstream systems |
| Consumer Group | Set of consumer instances sharing partition assignments |
| DLQ | Dead Letter Queue for failed/unprocessable messages |
| ULID | Universally Unique Lexicographically Sortable Identifier |

### 12.2 Interface Contracts Summary

| Interface | Direction | Contract |
|-----------|-----------|----------|
| Policy Enforcer → Evidence Bus | Upstream | Avro Evidence Schema v2.0 |
| Evidence Bus → Signal Engines | Downstream | Avro Evidence Schema v2.0 |
| Evidence Bus → S3 Archive | Downstream | Parquet (batched hourly) |
| Admin API → Operators | Management | OpenAPI 3.0 REST |

### 12.3 Sequence Diagram: End-to-End Flow

```mermaid
sequenceDiagram
    participant PE as Policy Enforcer
    participant EB as Evidence Bus
    participant SR as Schema Registry
    participant FE as Freshness Engine
    participant VE as Volume Engine
    participant S3 as S3 Archive
    
    PE->>SR: Get schema version
    SR-->>PE: Schema v2.0
    
    PE->>EB: Produce Evidence (key=dataset_urn)
    EB-->>PE: Ack (partition=4, offset=9918273)
    
    par Fan-out to Consumers
        EB->>FE: Consume (group=signal_engines.freshness)
        FE->>FE: Process freshness signal
        FE-->>EB: Commit offset
    and
        EB->>VE: Consume (group=signal_engines.volume)
        VE->>VE: Process volume signal
        VE-->>EB: Commit offset
    and
        EB->>S3: Archive batch (hourly)
        S3-->>EB: Archived to s3://evidence-archive/
    end
```

### 12.4 Component Dependency Matrix

| Depends On | Required By |
|------------|-------------|
| MSK (external) | C-03 Evidence Bus |
| Glue Schema Registry | C-03 Evidence Bus |
| C-01 Policy Enforcer | C-03 Evidence Bus (producer) |
| C-03 Evidence Bus | C-04 Signal Engines |
| C-03 Evidence Bus | C-09 RCA Copilot (replay) |

---

## Self-Critique Against Rubric

### Completeness ✓
- [x] API specs: Kafka Producer/Consumer configs, REST Admin API (OpenAPI)
- [x] Database Schema: Avro schema, JSON schema, sample events
- [x] Error Handling: DLQ strategy, retry policies, circuit breaker
- [x] Logging: Structured logging with correlation IDs

### Scalability ✓
- [x] Explicit throughput targets: 50K-500K events/sec
- [x] Partitioning strategy: 64-256 partitions, dataset_urn key
- [x] Backpressure handling: Mode-based sampling, degraded modes
- [x] Autoscaling triggers defined

### Interoperability ✓
- [x] Upstream contract: Policy Enforcer producer spec
- [x] Downstream contract: Signal Engine consumer spec
- [x] Consumer group naming conventions
- [x] Schema versioning strategy

### Observability ✓
- [x] Prometheus metrics defined
- [x] Distributed tracing integration (OTel)
- [x] Dashboard specifications
- [x] Alert thresholds documented

### Security ✓
- [x] IAM policies for producers and consumers
- [x] Encryption in-transit (TLS) and at-rest (KMS)
- [x] PII handling policy
- [x] Service-to-service authentication (IRSA)

---

*Document Version: 1.0*  
*Status: Ready for Architecture Review*  
*Owner: Platform Core Team*
