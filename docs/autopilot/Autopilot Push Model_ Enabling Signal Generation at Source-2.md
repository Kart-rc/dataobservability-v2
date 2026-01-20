# **Autopilot Push Model: Enabling Signal Generation at Source**

## **Reframing the Problem**

Let me step back and examine the fundamental dynamics at play.

### **The Push-Pull Paradox**

The flywheel assumes pull dynamics: *"Copilot delivers value → Teams want better signals."* But there's a bootstrap problem:

┌─────────────────────────────────────────────────────────────────┐  
│                    THE BOOTSTRAP PROBLEM                        │  
├─────────────────────────────────────────────────────────────────┤  
│                                                                 │  
│   If applications have NO instrumentation...                    │  
│        ↓                                                        │  
│   Evidence Bus has NO signals to process...                     │  
│        ↓                                                        │  
│   Copilot has NOTHING to reason about...                        │  
│        ↓                                                        │  
│   Teams see NO value...                                         │  
│        ↓                                                        │  
│   Pull never materializes.                                      │  
│                                                                 │  
│   THE FLYWHEEL CANNOT START FROM ZERO.                         │  
│                                                                 │  
└─────────────────────────────────────────────────────────────────┘

**This is why Push exists.** Push establishes the *minimum viable signal layer* that enables Pull to take over.

### **The Two Phases of Autopilot**

| Phase | Model | Goal | Trigger |
| ----- | ----- | ----- | ----- |
| **Phase 1** | Push | Establish baseline observability | Proactive scanning of all repos |
| **Phase 2** | Pull | Improve signal quality | Reactive to Evidence failures |

The user is asking me to focus on **Phase 1: The Push Model**.

---

## **Systems Thinking: What Are We Really Pushing?**

### **The Signal Generation Stack**

For the Signal Factory to work, applications must emit data that can be transformed into Evidence. Let me decompose what "signal-ready" means:

┌─────────────────────────────────────────────────────────────────┐  
│                 SIGNAL-READY APPLICATION                        │  
├─────────────────────────────────────────────────────────────────┤  
│                                                                 │  
│  Layer 5: BUSINESS CONTEXT                                      │  
│           ├── Domain entity IDs (order\_id, customer\_id)         │  
│           ├── Business event semantics                          │  
│           └── SLO expectations                                  │  
│                        ↑                                        │  
│  Layer 4: DATA CONTRACTS                                        │  
│           ├── Required fields specification                     │  
│           ├── Field type constraints                            │  
│           └── Business rule validations                         │  
│                        ↑                                        │  
│  Layer 3: DATA QUALITY                                          │  
│           ├── Completeness checks                               │  
│           ├── Validity checks                                   │  
│           └── Consistency checks                                │  
│                        ↑                                        │  
│  Layer 2: TEMPORAL SIGNALS                                      │  
│           ├── Freshness (event\_time, processing\_time)           │  
│           └── Volume (throughput, partition distribution)       │  
│                        ↑                                        │  
│  Layer 1: OBSERVABILITY FOUNDATION (OpenTelemetry)              │  
│           ├── Trace context propagation                         │  
│           ├── Span creation                                     │  
│           └── Correlation across boundaries                     │  
│                                                                 │  
└─────────────────────────────────────────────────────────────────┘

**Each layer enables specific Signal Engine capabilities:**

| Layer | Enables | Without It |
| ----- | ----- | ----- |
| OpenTelemetry | RCA Copilot can trace causality | "We know it broke, but not where" |
| Temporal Signals | Freshness & Volume engines | "We don't know if data is stale" |
| Data Quality | DQ Engine breach detection | "We don't know if data is valid" |
| Data Contracts | Contract Engine compliance | "We don't know what 'correct' means" |
| Business Context | Blast radius analysis | "We don't know what's impacted" |

---

## **Push Model Requirements Specification**

### **Requirement Structure**

For each capability domain, I'll define:

1. **What** — The instrumentation capability being pushed  
2. **Why** — The signal gap this closes  
3. **Where** — Code locations requiring instrumentation  
4. **How** — Detection and generation patterns  
5. **Output** — The signal/evidence this enables

---

## **Domain 1: OpenTelemetry Foundation**

### **REQ-OT-001: Trace Context Propagation**

**What:** Ensure trace context (trace\_id, span\_id) flows through all service boundaries.

**Why:** Without trace propagation, the RCA Copilot cannot correlate failures across services. The Neptune graph has no edges to traverse.

**Where:**

Instrumentation Points:  
├── HTTP clients (outbound requests)  
├── HTTP servers (inbound request handlers)  
├── Kafka producers (message headers)  
├── Kafka consumers (extract from headers)  
├── gRPC clients/servers  
├── Database clients (query spans)  
└── Async task queues (Celery, SQS, etc.)

**Detection Pattern:**

class OTelGapDetector:  
    def detect\_missing\_propagation(self, repo: RepoContext) \-\> List\[Gap\]:  
        gaps \= \[\]  
          
        \# Find all HTTP client calls without context injection  
        for http\_call in repo.find\_http\_clients():  
            if not self.has\_trace\_injection(http\_call):  
                gaps.append(Gap(  
                    type=GapType.MISSING\_TRACE\_PROPAGATION,  
                    location=http\_call.location,  
                    boundary="http\_client",  
                    severity="HIGH"  
                ))  
          
        \# Find all Kafka producers without header propagation  
        for producer in repo.find\_kafka\_producers():  
            if not self.has\_header\_injection(producer):  
                gaps.append(Gap(  
                    type=GapType.MISSING\_TRACE\_PROPAGATION,  
                    location=producer.location,  
                    boundary="kafka\_producer",  
                    severity="HIGH"  
                ))  
          
        return gaps

**Generation Pattern:**

\# Before (gap detected)  
response \= requests.post(url, json=payload)

\# After (Autopilot instrumentation)  
from opentelemetry.propagate import inject

headers \= {}  
inject(headers)  \# Injects trace context  
response \= requests.post(url, json=payload, headers=headers)

**Output Signal:**

{  
  "evidence\_id": "evd-...",  
  "otel": {  
    "trace\_id": "abc123...",  
    "span\_id": "def456...",  
    "parent\_span\_id": "ghi789..."  
  }  
}

---

### **REQ-OT-002: Span Creation for Key Operations**

**What:** Wrap critical business operations in OTel spans with semantic attributes.

**Why:** Spans provide the granularity needed for precise RCA. Without spans, we only know a service was involved, not *which operation* failed.

**Where:**

Span-Worthy Operations:  
├── API endpoint handlers  
├── Database queries (especially writes)  
├── External service calls  
├── Message publish operations  
├── Message consume/process operations  
├── Batch job steps  
└── Business-critical functions (flagged by annotation)

**Detection Pattern:**

def detect\_missing\_spans(self, repo: RepoContext) \-\> List\[Gap\]:  
    gaps \= \[\]  
      
    \# API handlers without spans  
    for handler in repo.find\_api\_handlers():  
        if not self.is\_auto\_instrumented(handler) and not self.has\_manual\_span(handler):  
            gaps.append(Gap(  
                type=GapType.MISSING\_SPAN,  
                location=handler.location,  
                operation\_type="api\_handler",  
                suggested\_span\_name=f"{repo.service\_name}.{handler.name}"  
            ))  
      
    \# Kafka consumers without processing spans  
    for consumer in repo.find\_kafka\_consumers():  
        if not self.has\_processing\_span(consumer):  
            gaps.append(Gap(  
                type=GapType.MISSING\_SPAN,  
                location=consumer.location,  
                operation\_type="kafka\_consumer"  
            ))  
      
    return gaps

**Generation Pattern:**

\# Before  
def process\_order(order\_data: dict):  
    validate\_order(order\_data)  
    save\_to\_database(order\_data)  
    publish\_event(order\_data)

\# After (Autopilot instrumentation)  
from opentelemetry import trace

tracer \= trace.get\_tracer(\_\_name\_\_)

def process\_order(order\_data: dict):  
    with tracer.start\_as\_current\_span(  
        "orders-svc.process\_order",  
        attributes={  
            "order.id": order\_data.get("order\_id"),  
            "order.customer\_id": order\_data.get("customer\_id")  
        }  
    ) as span:  
        validate\_order(order\_data)  
        save\_to\_database(order\_data)  
        publish\_event(order\_data)

---

### **REQ-OT-003: Producer Identity Header**

**What:** Inject `x-obs-producer-service` header into all Kafka messages.

**Why:** The Policy Enforcer's Gate 2 (Identity) requires this to attribute failures to specific services. Without it, attribution falls back to topic mapping (lower confidence).

**Where:**

All Kafka producer configurations and produce() calls

**Detection Pattern:**

def detect\_missing\_producer\_header(self, repo: RepoContext) \-\> List\[Gap\]:  
    for producer in repo.find\_kafka\_producers():  
        if not self.injects\_producer\_header(producer):  
            return Gap(  
                type=GapType.MISSING\_PRODUCER\_HEADER,  
                location=producer.location,  
                service\_name=repo.service\_name  
            )

**Generation Pattern:**

\# Before  
producer.send("raw.orders.events", value=event)

\# After  
producer.send(  
    "raw.orders.events",  
    value=event,  
    headers=\[  
        ("x-obs-producer-service", b"orders-svc"),  
        ("x-obs-producer-version", b"v3.17")  
    \]  
)

---

## **Domain 2: Data Contracts**

### **REQ-DC-001: Contract Definition Files**

**What:** Every dataset must have an ODCS-compliant contract definition.

**Why:** The Policy Enforcer's Gate 4 (Contract) validates against these definitions. Without contracts, we cannot distinguish "missing field" from "optional field."

**Where:**

contracts/  
├── orders/  
│   ├── orders.created.yaml      \# Contract for orders:created dataset  
│   └── orders.updated.yaml  
├── payments/  
│   └── payments.processed.yaml  
└── \_templates/  
    └── contract.template.yaml

**Contract Schema (ODCS-aligned):**

\# contracts/orders/orders.created.yaml  
apiVersion: odcs/v1  
kind: DataContract  
metadata:  
  name: orders.created  
  version: "3"  
  owner: orders-team  
  tier: 1

spec:  
  dataset:  
    urn: "urn:dp:orders:created"  
    topic: "raw.orders.events"  
    
  schema:  
    registry: glue  
    subject: orders-created  
    compatibility: BACKWARD  
    
  fields:  
    required:  
      \- name: order\_id  
        type: string  
        description: Unique order identifier  
        pii: false  
        
      \- name: customer\_id  
        type: string  
        description: Customer who placed the order  
        pii: true  
          
      \- name: event\_time  
        type: timestamp  
        description: When the order was created  
      
    optional:  
      \- name: promo\_code  
        type: string  
        nullable: true  
    
  quality:  
    rules:  
      \- name: order\_id\_not\_empty  
        expression: "LENGTH(order\_id) \> 0"  
      \- name: total\_amount\_positive  
        expression: "total\_amount \> 0"  
    
  slos:  
    freshness:  
      maxDelaySeconds: 900  \# 15 minutes for Tier-1  
    volume:  
      minEventsPerHour: 100  
      maxEventsPerHour: 100000  
    compliance:  
      minRate: 0.95  \# 95% of events must pass contract

**Detection Pattern:**

def detect\_missing\_contracts(self, repo: RepoContext) \-\> List\[Gap\]:  
    gaps \= \[\]  
      
    \# Find all Kafka topics this service produces to  
    produced\_topics \= set()  
    for producer in repo.find\_kafka\_producers():  
        produced\_topics.add(producer.topic)  
      
    \# Check if contracts exist for each topic  
    existing\_contracts \= repo.find\_contract\_files()  
    contracted\_topics \= {c.spec.dataset.topic for c in existing\_contracts}  
      
    for topic in produced\_topics:  
        if topic not in contracted\_topics:  
            gaps.append(Gap(  
                type=GapType.MISSING\_CONTRACT,  
                topic=topic,  
                suggested\_urn=self.infer\_urn(topic),  
                severity="HIGH" if self.is\_tier1(topic) else "MEDIUM"  
            ))  
      
    return gaps

**Generation Pattern:**

Autopilot analyzes the actual payload structure to generate a draft contract:

class ContractGenerator:  
    def generate\_contract(self, topic: str, sample\_events: List\[dict\]) \-\> str:  
        \# Analyze sample events to infer schema  
        field\_stats \= self.analyze\_fields(sample\_events)  
          
        contract \= {  
            "apiVersion": "odcs/v1",  
            "kind": "DataContract",  
            "metadata": {  
                "name": self.topic\_to\_name(topic),  
                "version": "1",  
                "owner": "FIXME: assign owner",  
                "tier": 2  \# Default to Tier-2, human upgrades to Tier-1  
            },  
            "spec": {  
                "dataset": {  
                    "urn": self.infer\_urn(topic),  
                    "topic": topic  
                },  
                "fields": {  
                    "required": \[  
                        {  
                            "name": field.name,  
                            "type": field.inferred\_type,  
                            "pii": self.detect\_pii\_field(field.name)  
                        }  
                        for field in field\_stats  
                        if field.presence\_rate \> 0.99  \# Present in \>99% of events  
                    \],  
                    "optional": \[  
                        {  
                            "name": field.name,  
                            "type": field.inferred\_type,  
                            "nullable": True  
                        }  
                        for field in field\_stats  
                        if 0.5 \< field.presence\_rate \<= 0.99  
                    \]  
                }  
            }  
        }  
          
        return yaml.dump(contract)

---

### **REQ-DC-002: Contract Validation at Produce Time**

**What:** Validate events against contract before publishing to Kafka.

**Why:** While the Policy Enforcer validates out-of-band, producer-side validation enables *fail-fast* behavior and better error messages for developers.

**Where:**

Kafka producer wrapper/decorator

**Generation Pattern:**

\# Autopilot generates a contract-aware producer wrapper

from dataclasses import dataclass  
from typing import Any  
import jsonschema

@dataclass  
class ContractValidationResult:  
    valid: bool  
    errors: list\[str\]

class ContractAwareProducer:  
    def \_\_init\_\_(self, producer, contract\_registry):  
        self.producer \= producer  
        self.contract\_registry \= contract\_registry  
      
    def send(self, topic: str, value: dict, \*\*kwargs):  
        \# Load contract for this topic  
        contract \= self.contract\_registry.get\_contract(topic)  
          
        if contract:  
            result \= self.validate(value, contract)  
            if not result.valid:  
                \# Log validation failure (don't block in push phase)  
                logger.warning(  
                    "Contract validation failed",  
                    extra={  
                        "topic": topic,  
                        "errors": result.errors,  
                        "contract\_version": contract.version  
                    }  
                )  
                \# Emit metric for dashboarding  
                metrics.increment(  
                    "contract.validation.failures",  
                    tags={"topic": topic, "error\_type": result.errors\[0\]}  
                )  
          
        \# Still send the message (out-of-band philosophy)  
        return self.producer.send(topic, value=value, \*\*kwargs)

---

## **Domain 3: Data Quality**

### **REQ-DQ-001: Field-Level Quality Checks**

**What:** Embed quality assertions at data production points.

**Why:** The DQ Signal Engine aggregates quality metrics over time, but it needs per-record quality signals to work with.

**Quality Dimensions:**

| Dimension | Check Type | Example |
| ----- | ----- | ----- |
| **Completeness** | Null/empty check | `customer_id IS NOT NULL` |
| **Validity** | Format/range check | `email MATCHES regex` |
| **Consistency** | Cross-field check | `end_time > start_time` |
| **Uniqueness** | Duplicate detection | `order_id not seen before` |
| **Timeliness** | Freshness check | `event_time within 5 min of now` |

**Detection Pattern:**

def detect\_missing\_dq\_checks(self, repo: RepoContext) \-\> List\[Gap\]:  
    gaps \= \[\]  
      
    for producer in repo.find\_kafka\_producers():  
        contract \= self.contract\_registry.get(producer.topic)  
        if not contract:  
            continue  
          
        payload\_builder \= producer.find\_payload\_construction()  
          
        \# Check if required fields have validation  
        for required\_field in contract.spec.fields.required:  
            if not self.has\_validation\_for\_field(payload\_builder, required\_field.name):  
                gaps.append(Gap(  
                    type=GapType.MISSING\_DQ\_CHECK,  
                    field=required\_field.name,  
                    check\_type="completeness",  
                    location=payload\_builder.location  
                ))  
          
        \# Check if quality rules from contract are implemented  
        for rule in contract.spec.quality.rules:  
            if not self.has\_rule\_implementation(payload\_builder, rule):  
                gaps.append(Gap(  
                    type=GapType.MISSING\_DQ\_CHECK,  
                    rule=rule.name,  
                    check\_type="validity",  
                    expression=rule.expression  
                ))  
      
    return gaps

**Generation Pattern:**

\# Autopilot generates a DQ validator from contract

from pydantic import BaseModel, validator, Field  
from typing import Optional  
from datetime import datetime

class OrderCreatedEvent(BaseModel):  
    """  
    Auto-generated from contract: dc:orders.created:3  
    """  
    order\_id: str \= Field(..., min\_length=1)  
    customer\_id: str \= Field(..., min\_length=1)  
    total\_amount: float \= Field(..., gt=0)  
    currency: str \= Field(..., regex="^\[A-Z\]{3}$")  
    event\_time: datetime  
    promo\_code: Optional\[str\] \= None  
      
    @validator('event\_time')  
    def event\_time\_not\_future(cls, v):  
        if v \> datetime.utcnow():  
            raise ValueError('event\_time cannot be in the future')  
        return v  
      
    class Config:  
        extra \= 'forbid'  \# Reject unknown fields

\# Usage in producer  
def publish\_order\_created(self, order: Order):  
    event\_data \= {  
        "order\_id": order.id,  
        "customer\_id": order.customer\_id,  
        "total\_amount": order.total,  
        "currency": order.currency,  
        "event\_time": datetime.utcnow().isoformat()  
    }  
      
    \# Validate before sending  
    validated \= OrderCreatedEvent(\*\*event\_data)  
      
    self.producer.send("raw.orders.events", value=validated.dict())

---

## **Domain 4: Data Freshness**

### **REQ-FR-001: Event Time vs Processing Time**

**What:** Every event must include both `event_time` (when it happened) and `processing_time` (when it was processed).

**Why:** The Freshness Signal Engine computes staleness as `processing_time - event_time`. Without both timestamps, freshness SLOs cannot be evaluated.

**Detection Pattern:**

def detect\_missing\_timestamps(self, repo: RepoContext) \-\> List\[Gap\]:  
    gaps \= \[\]  
      
    for producer in repo.find\_kafka\_producers():  
        payload\_fields \= producer.get\_payload\_fields()  
          
        has\_event\_time \= any(  
            f.name in \["event\_time", "eventTime", "created\_at", "timestamp"\]  
            for f in payload\_fields  
        )  
          
        if not has\_event\_time:  
            gaps.append(Gap(  
                type=GapType.MISSING\_EVENT\_TIME,  
                location=producer.location,  
                topic=producer.topic  
            ))  
      
    return gaps

**Generation Pattern:**

\# Before  
event \= {  
    "order\_id": order.id,  
    "customer\_id": order.customer\_id  
}

\# After (Autopilot adds temporal fields)  
from datetime import datetime, timezone

event \= {  
    "order\_id": order.id,  
    "customer\_id": order.customer\_id,  
    "event\_time": order.created\_at.isoformat(),  \# Business event time  
    "processing\_time": datetime.now(timezone.utc).isoformat()  \# When processed  
}

---

### **REQ-FR-002: Freshness SLO Declaration**

**What:** Every Tier-1 dataset must declare a freshness SLO in its contract.

**Why:** The Freshness Signal Engine needs thresholds to evaluate. Without declared SLOs, we can measure latency but not detect *breaches*.

**Contract Extension:**

\# In contract file  
slos:  
  freshness:  
    maxDelaySeconds: 900      \# Alert if event\_time to evidence\_time \> 15 min  
    warningDelaySeconds: 600  \# Warn at 10 min  
      
  \# Freshness can also be defined per consumer  
  consumerSlos:  
    \- consumer: exec-dashboard  
      maxDelaySeconds: 300    \# Dashboard needs fresher data  
    \- consumer: monthly-reports  
      maxDelaySeconds: 86400  \# Daily is fine for reports

---

## **Domain 5: Data Volume**

### **REQ-VOL-001: Throughput Metrics Emission**

**What:** Every producer must emit throughput metrics that the Volume Signal Engine can consume.

**Why:** Volume anomalies (sudden drops, unexpected spikes) are leading indicators of upstream failures. Without metrics, we're blind to volume changes until consumers complain.

**Detection Pattern:**

def detect\_missing\_volume\_metrics(self, repo: RepoContext) \-\> List\[Gap\]:  
    gaps \= \[\]  
      
    for producer in repo.find\_kafka\_producers():  
        if not self.has\_throughput\_metric(producer):  
            gaps.append(Gap(  
                type=GapType.MISSING\_VOLUME\_METRIC,  
                location=producer.location,  
                topic=producer.topic,  
                suggested\_metric=f"kafka.producer.messages.sent.{producer.topic}"  
            ))  
      
    return gaps

**Generation Pattern:**

\# Autopilot adds metrics instrumentation

from prometheus\_client import Counter, Histogram

\# Metrics definitions  
messages\_sent \= Counter(  
    'kafka\_producer\_messages\_sent\_total',  
    'Total messages sent to Kafka',  
    \['topic', 'service'\]  
)

message\_size \= Histogram(  
    'kafka\_producer\_message\_size\_bytes',  
    'Size of messages sent to Kafka',  
    \['topic'\],  
    buckets=\[100, 500, 1000, 5000, 10000, 50000\]  
)

class InstrumentedProducer:  
    def send(self, topic: str, value: dict, \*\*kwargs):  
        \# Emit metrics  
        messages\_sent.labels(topic=topic, service=self.service\_name).inc()  
        message\_size.labels(topic=topic).observe(len(json.dumps(value)))  
          
        return self.\_producer.send(topic, value=value, \*\*kwargs)

---

### **REQ-VOL-002: Volume SLO Declaration**

**What:** Tier-1 datasets must declare expected volume ranges.

**Why:** The Volume Signal Engine needs baselines. A 50% drop is only an anomaly if we know what "normal" looks like.

**Contract Extension:**

slos:  
  volume:  
    \# Static thresholds  
    minEventsPerHour: 1000  
    maxEventsPerHour: 100000  
      
    \# Or dynamic (ML-based)  
    anomalyDetection:  
      enabled: true  
      sensitivity: "medium"  \# low, medium, high  
      seasonality: "daily"   \# Account for daily patterns

---

## **Consolidated Push Requirements Matrix**

| Req ID | Domain | Requirement | Priority | Enables |
| ----- | ----- | ----- | ----- | ----- |
| REQ-OT-001 | OpenTelemetry | Trace context propagation | P0 | RCA causality |
| REQ-OT-002 | OpenTelemetry | Span creation for key ops | P1 | Precise RCA |
| REQ-OT-003 | OpenTelemetry | Producer identity header | P0 | Attribution |
| REQ-DC-001 | Contracts | Contract definition files | P0 | Contract Engine |
| REQ-DC-002 | Contracts | Producer-side validation | P1 | Fail-fast DX |
| REQ-DQ-001 | Data Quality | Field-level quality checks | P1 | DQ Engine |
| REQ-FR-001 | Freshness | Event/processing timestamps | P0 | Freshness Engine |
| REQ-FR-002 | Freshness | Freshness SLO declaration | P1 | Breach detection |
| REQ-VOL-001 | Volume | Throughput metrics | P1 | Volume Engine |
| REQ-VOL-002 | Volume | Volume SLO declaration | P2 | Anomaly detection |

---

## **Push Model Execution Strategy**

### **Phase 1: Baseline Scan (Week 1-2)**

┌─────────────────────────────────────────────────────────────────┐  
│                    BASELINE GAP ANALYSIS                        │  
├─────────────────────────────────────────────────────────────────┤  
│                                                                 │  
│  For each repository in the organization:                       │  
│                                                                 │  
│  1\. Clone and analyze                                           │  
│     ├── Detect language/framework                               │  
│     ├── Find all Kafka producers                                │  
│     ├── Find all HTTP clients/servers                           │  
│     └── Map to dataset URNs                                     │  
│                                                                 │  
│  2\. Score observability readiness (0-100)                       │  
│     ├── OTel coverage: X%                                       │  
│     ├── Contract coverage: X%                                   │  
│     ├── DQ checks: X%                                           │  
│     ├── Timestamp presence: X%                                  │  
│     └── Volume metrics: X%                                      │  
│                                                                 │  
│  3\. Generate gap report per repository                          │  
│                                                                 │  
│  Output: Prioritized backlog of push PRs                        │  
│                                                                 │  
└─────────────────────────────────────────────────────────────────┘

### **Phase 2: Priority-Based Push (Week 3-8)**

**Prioritization Formula:**

Priority Score \= (Tier Weight × 3\) \+ (Gap Severity × 2\) \+ (Downstream Impact × 1\)

Where:  
\- Tier Weight: Tier-1 \= 10, Tier-2 \= 5, Tier-3 \= 1  
\- Gap Severity: P0 \= 10, P1 \= 5, P2 \= 2  
\- Downstream Impact: Number of consuming services/dashboards

**Push Sequence:**

Week 3-4: All Tier-1 services  
├── REQ-OT-001: Trace propagation  
├── REQ-OT-003: Producer headers  
├── REQ-FR-001: Timestamps  
└── REQ-DC-001: Contract files (drafts)

Week 5-6: All Tier-1 \+ Tier-2 services  
├── REQ-OT-002: Span creation  
├── REQ-DQ-001: DQ checks  
└── REQ-DC-002: Producer validation

Week 7-8: Full coverage  
├── REQ-VOL-001: Volume metrics  
├── REQ-FR-002: Freshness SLOs  
└── REQ-VOL-002: Volume SLOs

### **Phase 3: Handoff to Pull (Week 9+)**

Once baseline instrumentation is in place:

┌─────────────────────────────────────────────────────────────────┐  
│                    PUSH → PULL TRANSITION                       │  
├─────────────────────────────────────────────────────────────────┤  
│                                                                 │  
│  Push Phase Complete When:                                      │  
│  ✓ \>80% of Tier-1 repos have OTel propagation                  │  
│  ✓ \>80% of Tier-1 datasets have contract definitions           │  
│  ✓ Evidence Bus is receiving signals from all Tier-1 topics    │  
│  ✓ Signal Engines can compute freshness/volume/contract state  │  
│                                                                 │  
│  Pull Phase Begins:                                             │  
│  → Evidence failures trigger reactive Autopilot PRs             │  
│  → Copilot can now reason over actual data                      │  
│  → Flywheel starts spinning                                     │  
│                                                                 │  
└─────────────────────────────────────────────────────────────────┘

---

## **Hidden Assumptions in Push Model**

| Assumption | Risk if Wrong | Validation Approach |
| ----- | ----- | ----- |
| Repos are accessible via Git | Can't analyze private/air-gapped repos | Verify access in Week 1 |
| Code follows detectable patterns | AST analysis fails on exotic code | Manual fallback for edge cases |
| Teams will merge push PRs | PRs sit unreviewed, no baseline established | Executive mandate for push phase |
| Contracts can be inferred from samples | Wrong inferences bake in bad assumptions | Human review of all contract drafts |
| One-time push is sufficient | Baseline decays as code changes | CI integration for ongoing enforcement |

---

## **Success Criteria for Push Phase**

| Metric | Target | Measurement |
| ----- | ----- | ----- |
| **Tier-1 OTel Coverage** | \>90% | Services with trace propagation / Total Tier-1 services |
| **Contract Definition Rate** | \>95% | Topics with contracts / Total Tier-1 topics |
| **Evidence Flow Rate** | \>99% | Topics emitting evidence / Total instrumented topics |
| **Push PR Merge Rate** | \>80% | Merged PRs / Created PRs (within 2 weeks) |
| **Time to Baseline** | \<8 weeks | Start of push to pull-ready state |

---

## **The Push-Pull Continuum**

       PUSH PHASE                              PULL PHASE  
        (Proactive)                             (Reactive)  
            │                                       │  
            ▼                                       ▼  
┌───────────────────────┐               ┌───────────────────────┐  
│                       │               │                       │  
│  Autopilot scans      │               │  Evidence Bus shows   │  
│  all repos            │               │  failures             │  
│         │             │               │         │             │  
│         ▼             │               │         ▼             │  
│  Detects gaps in      │               │  Autopilot generates  │  
│  instrumentation      │    ──────▶    │  targeted fixes       │  
│         │             │   TRANSITION  │         │             │  
│         ▼             │               │         ▼             │  
│  Generates baseline   │               │  Copilot improves     │  
│  PRs for all services │               │  with richer signals  │  
│                       │               │                       │  
└───────────────────────┘               └───────────────────────┘

Trigger: Existence of repo          Trigger: Evidence failures  
Goal: Minimum viable signals        Goal: Continuous improvement  
Timeline: Weeks 1-8                 Timeline: Week 9+

The push model establishes the foundation. The pull model builds the castle. You can't have pull without push—but push alone is just infrastructure. The magic happens when the flywheel starts spinning.

What aspect would you like to explore further—the AST detection patterns for specific frameworks, the contract inference algorithms, or the CI integration strategy for ongoing enforcement?

# **Signal-Ready Application: Minimum Viable Instrumentation**

## **Executive Summary**

As a senior AWS architect, I'll cut through the comprehensive documentation and give you the **absolute minimum**required to make an application "signal-ready" for the Data Observability Platform.

**The North Star**: Enable the Policy Enforcer to create Evidence events that at least ONE Signal Engine can consume. Everything else is optimization.

---

## **The Critical Path: 3 Non-Negotiable Requirements**

### **1\. Producer Attribution (Gate 2: Identity)**

**Why This Matters**: Without knowing WHO produced the data, the RCA Copilot cannot trace incidents back to deployments. This is the foundational edge in the Neptune graph.

**Minimum Implementation**:

\# Kafka Producer Configuration  
producer\_config \= {  
    'bootstrap.servers': 'kafka:9092',  
    'client.id': 'orders-svc',  \# Application identifier  
}

\# Every message MUST include these headers  
headers \= \[  
    ('x-obs-producer-service', b'orders-svc'),      \# CRITICAL  
    ('x-obs-producer-version', b'v3.17'),           \# CRITICAL  
\]

producer.send(  
    topic='raw.orders.events',  
    value=event\_payload,  
    headers=headers  \# This is the minimum  
)

**Cost of Skipping**: Policy Enforcer falls back to topic-based mapping (MEDIUM confidence). RCA accuracy drops from 92% to \~60%.

---

### **2\. Temporal Signals (Freshness Enablement)**

**Why This Matters**: Freshness is the **easiest signal to compute** and provides immediate value. It answers: "Is data flowing or stale?"

**Minimum Implementation**:

\# Every event payload MUST include  
event \= {  
    'event\_id': generate\_ulid(),  
    'event\_time': order.created\_at.isoformat(),  \# CRITICAL: When it happened  
    'payload': {  
        'order\_id': order.id,  
        'customer\_id': order.customer\_id,  
        \# ... business data  
    }  
}

**Alternative Pattern** (if event\_time is unavailable):

\# Use Kafka message timestamp as fallback  
\# But this is LESS accurate for batch/async scenarios

**Cost of Skipping**: Freshness Signal Engine cannot operate. You lose the first line of defense against pipeline staleness.

---

### **3\. Contract Definition (Gate 4: Contract)**

**Why This Matters**: Without a contract, the Policy Enforcer can validate schema (G3) but cannot distinguish "missing required field" from "missing optional field". Contract validation is the **highest signal-to-noise ratio**.

**Minimum Implementation**:

\# contracts/orders/orders.created.yaml  
apiVersion: odcs/v1  
kind: DataContract  
metadata:  
  name: orders.created  
  version: "1"  
  owner: orders-team  \# CRITICAL: For attribution  
  tier: 1             \# CRITICAL: Determines enforcement level

spec:  
  dataset:  
    urn: "urn:dp:orders:created"  \# CRITICAL: Links to Neptune  
    topic: "raw.orders.events"  
      
  fields:  
    required:  \# MINIMUM: Just the critical fields  
      \- name: order\_id  
        type: string  
      \- name: customer\_id  
        type: string  
      \- name: event\_time  
        type: timestamp  
      
  slos:  \# MINIMUM: Just freshness  
    freshness:  
      maxDelaySeconds: 900  \# 15 minutes

**Cost of Skipping**: Contract Signal Engine cannot detect violations. The "missing customer\_id" incident in the pitch deck would be invisible.

---

## **What You Can DEFER (And Why)**

| Capability | Value | Can Defer? | Reason |
| ----- | ----- | ----- | ----- |
| **OTel Trace Propagation** | HIGH | ✅ **Yes** | The Policy Enforcer works without it. RCA will use graph traversal instead of trace correlation. Add this in Week 5-8. |
| **Span Creation** | MEDIUM | ✅ **Yes** | Enhances RCA granularity but not required for basic incident detection. |
| **DQ Checks (Deequ)** | MEDIUM | ✅ **Yes** | DQ Signal Engine is secondary. Start with Contract compliance. |
| **Volume Metrics** | LOW | ✅ **Yes** | Volume anomalies are nice-to-have. Freshness \+ Contract covers 80% of incidents. |
| **Schema Registry Integration** | MEDIUM | ⚠️ **Partial** | If you already use Glue/Confluent, wire it up (1 day). Otherwise, skip Gate 3 initially. |

---

## **The 48-Hour Bootcamp: Making One Service Signal-Ready**

### **Day 1: Headers \+ Timestamps (4 hours)**

\# Step 1: Wrap your Kafka producer  
class SignalReadyProducer:  
    def \_\_init\_\_(self, base\_producer, service\_name, service\_version):  
        self.producer \= base\_producer  
        self.service\_name \= service\_name  
        self.service\_version \= service\_version  
      
    def send(self, topic, value, \*\*kwargs):  
        \# Inject minimum headers  
        headers \= kwargs.get('headers', \[\])  
        headers.extend(\[  
            ('x-obs-producer-service', self.service\_name.encode()),  
            ('x-obs-producer-version', self.service\_version.encode()),  
        \])  
          
        \# Ensure event\_time exists  
        if isinstance(value, dict) and 'event\_time' not in value:  
            value\['event\_time'\] \= datetime.utcnow().isoformat()  
          
        return self.producer.send(topic, value=value, headers=headers)

\# Step 2: Replace producer initialization  
\# OLD: producer \= KafkaProducer(...)  
\# NEW:  
base\_producer \= KafkaProducer(...)  
producer \= SignalReadyProducer(  
    base\_producer=base\_producer,  
    service\_name=os.getenv('SERVICE\_NAME', 'orders-svc'),  
    service\_version=os.getenv('SERVICE\_VERSION', 'unknown')  
)

**Deployment**: Update CI/CD to inject `SERVICE_NAME` and `SERVICE_VERSION` as environment variables.

---

### **Day 2: Contract Definition (2 hours)**

\# Step 1: Sample your production topic  
aws kafka describe-cluster \--cluster-arn \<arn\>  
kafka-console-consumer \\  
  \--bootstrap-server \<broker\> \\  
  \--topic raw.orders.events \\  
  \--max-messages 1000 \\  
  \--from-beginning \> sample.jsonl

\# Step 2: Analyze field presence  
cat sample.jsonl | jq \-r 'keys\[\]' | sort | uniq \-c | sort \-nr  
\# Output:  
\# 1000 order\_id  
\# 1000 customer\_id  
\#  987 event\_time  
\#  650 promo\_code  
\#   12 referral\_source

\# Step 3: Draft contract (only 99%+ fields are "required")  
cat \> contracts/orders/orders.created.yaml \<\<EOF  
apiVersion: odcs/v1  
kind: DataContract  
metadata:  
  name: orders.created  
  version: "1"  
  owner: orders-team  
  tier: 1  
spec:  
  dataset:  
    urn: "urn:dp:orders:created"  
    topic: "raw.orders.events"  
  fields:  
    required:  
      \- name: order\_id  
        type: string  
      \- name: customer\_id  
        type: string  
      \- name: event\_time  
        type: timestamp  
    optional:  
      \- name: promo\_code  
        type: string  
        nullable: true  
  slos:  
    freshness:  
      maxDelaySeconds: 900  
EOF

\# Step 4: Register with Gateway Control Plane  
curl \-X POST https://control-plane.internal/api/v1/contracts \\  
  \-H "Content-Type: application/yaml" \\  
  \--data-binary @contracts/orders/orders.created.yaml

---

## **Verification: Is My Application Signal-Ready?**

Run this checklist:

\# 1\. Check headers are present  
kafka-console-consumer \\  
  \--bootstrap-server \<broker\> \\  
  \--topic raw.orders.events \\  
  \--property print.headers=true \\  
  \--max-messages 1 \\  
  | grep "x-obs-producer-service"  
\# Expected: x-obs-producer-service:orders-svc

\# 2\. Check event\_time exists  
kafka-console-consumer \\  
  \--bootstrap-server \<broker\> \\  
  \--topic raw.orders.events \\  
  \--max-messages 1 \\  
  | jq '.event\_time'  
\# Expected: "2026-01-14T12:34:56.789Z"

\# 3\. Verify Evidence is flowing  
kafka-console-consumer \\  
  \--bootstrap-server \<broker\> \\  
  \--topic signal\_factory.evidence \\  
  \--property print.key=true \\  
  \--from-beginning \\  
  | grep "urn:dp:orders:created"  
\# Expected: Evidence events with dataset\_urn

\# 4\. Check Signal Engine state  
aws dynamodb get-item \\  
  \--table-name SignalState \\  
  \--key '{"PK": {"S": "urn:dp:orders:created"}, "SK": {"S": "freshness"}}' \\  
  | jq '.Item.state.S'  
\# Expected: "OK" or "WARNING" or "CRITICAL"

**Success Criteria**: If all 4 checks pass, your application is signal-ready.

---

## **The Hidden Cost of "Just One More Field"**

A common trap: "Since we're adding headers, let's also add trace\_id, span\_id, user\_agent, ip\_address..."

**Don't do this.** Here's why:

| Approach | Time to Signal-Ready | Coordination Required | Risk |
| ----- | ----- | ----- | ----- |
| **Minimum (3 items)** | 2 days | 1 team | LOW |
| **"Nice to have" (8 items)** | 3 weeks | 3+ teams | MEDIUM |
| **"Gold standard" (15 items)** | 3 months | Org-wide mandate | HIGH (never ships) |

**The Autopilot Push Model exists for a reason**: Get to signal-ready fast, then let the flywheel drive incremental improvement.

---

## **Systems Thinking: Hidden Assumptions**

| Assumption | Risk if Wrong | Mitigation |
| ----- | ----- | ----- |
| **Kafka is the only ingestion point** | Direct S3 writes from vendors bypass Policy Enforcer | Add S3 Event Notifications → Lambda → Evidence Bus pattern |
| **event\_time is always present** | Old/legacy services may not have it | Policy Enforcer falls back to `processing_time` (warns via Gate) |
| **Service version is in ENV** | CI/CD may not inject it | Policy Enforcer uses Git SHA from deployment event as fallback |
| **Contracts can be statically defined** | Schema evolution breaks Gate 4 | Implement contract versioning (v1, v2) with backward compatibility rules |

---

## **Cost of Action vs. Inaction**

### **Action (Implement Minimum)**

* **Time**: 2 days per service  
* **Complexity**: Low (wrapper pattern)  
* **Coordination**: 1 team  
* **Result**: Evidence flowing, one signal engine operational

### **Inaction (Wait for "Perfect")**

* **Current MTTR**: 12+ hours  
* **Developer Toil**: 20% sprint velocity  
* **Data Trust**: Eroding (consumers build their own validation)  
* **Opportunity Cost**: 6 months of continued firefighting

**The 5 Whys on Inaction**:

1. Why delay? → "We need complete instrumentation"  
2. Why complete? → "So the Copilot is accurate"  
3. Why not start with partial? → "We don't want false positives"  
4. Why would partial data cause false positives? → "We assume it would"  
5. **Root Cause**: Perfectionism is blocking incremental value

---

## **The Forcing Function: What Breaks Without This?**

Without these 3 minimum requirements:

No Producer Headers  
  ↓  
Policy Enforcer: confidence \= "NONE"  
  ↓  
RCA Copilot: "Unknown producer" (useless)

No event\_time  
  ↓  
Freshness Signal Engine: cannot compute staleness  
  ↓  
Stale data incidents invisible until consumers complain

No Contract  
  ↓  
Gate 4 skipped (always PASS)  
  ↓  
"Missing customer\_id" incident never detected  
  ↓  
Executive Dashboard shows bad data for 6 hours

**Each missing piece removes a detection layer.**

---

## **Reference Architecture: AWS-Specific Considerations**

┌─────────────────────────────────────────────────────────┐  
│ Signal-Ready Application (ECS/EKS)                      │  
├─────────────────────────────────────────────────────────┤  
│                                                         │  
│  Service Container                                      │  
│  ├── ENV: SERVICE\_NAME (from task definition)          │  
│  ├── ENV: SERVICE\_VERSION (from CI/CD)                 │  
│  └── Kafka Producer Wrapper                            │  
│      ├── Injects headers automatically                 │  
│      └── Ensures event\_time exists                     │  
│                                                         │  
│  Sidecar: OTel Collector (OPTIONAL \- defer to Week 5\)  │  
│                                                         │  
└─────────────────────────────────────────────────────────┘  
               ↓  
    Amazon MSK (Kafka)  
    ├── Topic: raw.orders.events (unchanged)  
    └── Topic: signal\_factory.evidence (new)  
               ↓  
┌─────────────────────────────────────────────────────────┐  
│ Policy Enforcer (EKS Pod)                               │  
│ ├── Consumes: raw.orders.events                        │  
│ ├── Produces: signal\_factory.evidence                  │  
│ └── Config: DynamoDB (Gateway Control Plane)           │  
└─────────────────────────────────────────────────────────┘

**Key AWS Patterns**:

* Use **ECS Task Metadata** to auto-inject `SERVICE_NAME` and `SERVICE_VERSION`  
* Use **Parameter Store** for contract storage (alternative to DynamoDB)  
* Use **EventBridge** for deployment events (triggers Neptune graph updates)

---

## **Final Recommendation**

**Start with ONE Tier-1 service.** Make it signal-ready in 48 hours using these 3 requirements:

1. Producer headers (4 hours)  
2. Event timestamps (2 hours)  
3. Contract definition (2 hours)

**Then observe**:

* Does Evidence flow? (Check signal\_factory.evidence topic)  
* Does Freshness Signal Engine emit state? (Check DynamoDB SignalState table)  
* Can RCA Copilot explain a simulated incident? (Manually create a contract breach)

**If yes**: You've validated the critical path. Scale to more services.

**If no**: Debug before scaling. The minimum is still too complex if it doesn't work.

**The forcing function**: In Week 2, introduce a REAL incident in staging (deploy a version that violates the contract). The Copilot MUST detect and explain it in \< 2 minutes. If not, the minimum isn't sufficient.

