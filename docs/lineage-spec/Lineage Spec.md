Here’s how I’d interface a **parallel column-level lineage effort (SCA)** with the current **Enforcer \+ Engines \+ Neptune/Dynamo** design, without polluting the “RCA-first / Contract-lite” MVP or creating tight coupling.

## **1\) Design stance**

* **Signal Factory** remains the system of record for **runtime truth** (what happened, when, impact, first-bad/last-good).  
* **SCA lineage** becomes a system of record for **design-time intent** (what code *should* read/write at column granularity).  
* The interface is **loosely coupled, append-only, and keyed by stable IDs**.

The key is to integrate lineage as **enriching context**, not as a dependency that blocks ingestion or alerting.

---

## **2\) Canonical interface contract: URNs \+ versioned “LineageSpec”**

### **Stable IDs (must align across teams)**

Use these as the join keys everywhere:

* **Dataset URN** (already in your design):  
  `urn:dp:<domain>:<dataset>:<majorVersion>`  
* **Column URN** (new):  
  `urn:col:<dataset_urn>:<columnName>`  
  (optionally include logical type or a stable column id if you have renames)

### **LineageSpec (produced by SCA team)**

A versioned artifact per pipeline/job/service, e.g.:

* `producer`: service/job identifier (repo \+ module or job name)  
* `inputs`: dataset URNs \+ column URNs  
* `outputs`: dataset URNs \+ column URNs  
* `transforms`: optional transform summaries (not full AST)  
* `confidence`: HIGH/MED/LOW \+ reasons (dynamic SQL, reflection, etc.)  
* `code_ref`: commit SHA, file paths  
* `generated_at`: timestamp

**Critical requirement:** LineageSpec is **immutable and versioned** (keyed by commit SHA or build artifact hash). Don’t overwrite.

---

## **3\) Where the interface plugs into your current planes**

### **A) Development/CI plane (design-time ingestion)**

**SCA team emits LineageSpec** to a registry \+ event stream (e.g., S3 \+ Kafka topic like `signal_factory.lineage_specs`).

Signal Factory consumes it asynchronously via a **Lineage Ingestor**:

* validate schema  
* upsert metadata indexes  
* create/refresh graph edges

No dependency on runtime.

### **B) Knowledge plane (Neptune)**

You **do not** write per-record lineage. You write **topology edges** at dataset/column granularity.

Recommended Neptune additions:

**Nodes**

* `Dataset(ds:...)` (existing)  
* `Column(col:...)` (new)  
* `Job/Service(job:..., svc:...)` (existing-ish)  
* `LineageSpec(ls:<job>:<commit>)` (optional but useful)

**Edges**

* `(Job)-[:READS]->(Dataset)`  
* `(Job)-[:WRITES]->(Dataset)`  
* `(Job)-[:READS_COL]->(Column)`  
* `(Job)-[:WRITES_COL]->(Column)`  
* `(LineageSpec)-[:DESCRIBES]->(Job)`  
* `(LineageSpec)-[:AT_COMMIT]->(Commit)` *(or store commit as property)*

**Bound cardinality rule:**  
Store only **declared edges from specs**, not expanded runtime edges per execution.

### **C) Runtime plane (Enforcer \+ Engines)**

Enforcer/Engines remain unchanged. They only need to reference lineage when forming RCA context.

**How it’s used:**

* When an incident occurs on `Dataset X`, Copilot queries Neptune:  
  * “Who writes X?” and “What jobs/services read X?”  
  * If needed, “Which columns of X are written/read?” to narrow blast radius.

This is where column lineage adds huge value: identifying **impacted downstream consumers** and **which fields** are likely responsible.

---

## **4\) The “bridge” component: Lineage Ingestor (thin service)**

Create a small, well-bounded component owned by Signal Factory (or jointly) that:

* subscribes to `lineage_specs` (or polls S3)  
* normalizes to URNs  
* writes to Neptune \+ a small DynamoDB index for fast lookup

### **DynamoDB indexes (optional but very useful)**

To avoid expensive graph traversals for common queries:

* `DatasetToWritersIndex (dataset_urn -> [job/service])`  
* `DatasetToReadersIndex (dataset_urn -> [job/service])`  
* `ColumnToWritersIndex (column_urn -> [job/service])`  
* include `spec_version` / `commit` / `confidence`

This keeps RCA fast even if Neptune query performance varies.

---

## **5\) How RCA uses it (concrete example)**

Incident: `SCHEMA_DRIFT` on `urn:dp:orders:order_created:v1`

RCA flow:

1. Enforcer evidence gives: dataset\_urn, schema\_fingerprint delta, first-bad/last-good, producer service, deploy correlation.  
2. Copilot queries lineage:  
   * Writers of `order_created` (should match producer; if mismatch → valuable anomaly)  
   * Readers of `order_created` (blast radius)  
   * If drift shows `payment_method` removed:  
     * Find consumers that `READS_COL urn:col:...:payment_method`  
     * Rank those as likely broken

Outcome:

* Incident page includes “Most likely impacted consumers” and “columns implicated”.

This is the cleanest way column lineage improves MTTR without altering runtime systems.

---

## **6\) Governance and separation of concerns (avoid team collisions)**

### **Ownership**

* SCA team owns: generating LineageSpec \+ confidence scoring \+ repo integration  
* Signal Factory owns: ingestion contract, URN normalization, storage model, RCA usage

### **SLAs**

Lineage is **best-effort** for RCA enrichment:

* stale lineage should never block alerting or incident creation  
* Copilot should degrade gracefully (show “lineage unavailable / low confidence”)

### **Versioning**

* Always keep multiple specs (per commit)  
* Copilot should default to:  
  * “spec nearest to incident time” OR  
  * “spec deployed version” if you can map job deploys to commit SHAs

---

## **7\) Anti-patterns to avoid**

* **Don’t** push column lineage into Enforcer gates (too heavy, too brittle)  
* **Don’t** write per-run column lineage into Neptune (cardinality explosion)  
* **Don’t** require SCA lineage to resolve dataset identity (keep dataset URN mapping owned by Signal Factory)  
* **Don’t** treat low-confidence SCA output as truth; annotate confidence and show it in RCA

---

## **8\) Recommended interface pattern (what I’d choose)**

**Asynchronous “LineageSpec event stream” \+ thin Lineage Ingestor \+ Neptune topology edges \+ DynamoDB lookup indexes.**

It’s:

* decoupled  
* scalable  
* doesn’t change producer/runtime paths  
* immediately improves RCA and blast radius

---

If you want, I can produce a **one-page “Interface Spec”** you can hand to the SCA team:

* LineageSpec JSON schema  
* URN conventions  
* required fields  
* confidence model  
* ingestion topic/S3 layout  
* Neptune edge mapping and TTL/version rules

Below is a **ready-to-share Interface Spec** between **Signal Factory (Enforcer/Engines/RCA)** and the **SCA Element/Column Lineage** team, plus a clear list of **requirements expected from SCA**.

---

# **Interface Spec: SCA Element-Level Lineage → Signal Factory Knowledge Plane**

## **1\) Purpose**

Enable Signal Factory RCA to answer, for any dataset incident:

* **Who writes this dataset/column?**  
* **Who reads this dataset/column?**  
* **Which downstream jobs/dashboards are impacted?**  
* **Which columns are implicated by the failure signature (missing/renamed/type change)?**

This is achieved via **design-time** lineage extracted by SCA and published as immutable **LineageSpec** artifacts/events.

---

## **2\) Non-Goals**

* Per-record lineage or runtime lineage at event scale  
* Blocking ingestion/processing based on lineage availability  
* Full semantic transformation logic reconstruction  
* Real-time lineage for every query/execution

Lineage is **RCA enrichment**, not a gate.

---

## **3\) Systems of Record**

* **Signal Factory**: dataset identity (Dataset URN), runtime evidence, incidents, signals  
* **SCA**: design-time lineage intent (job/service code → inputs/outputs at column granularity)

---

# **4\) Canonical Identifiers and Naming**

## **4.1 Dataset URN (required)**

Must match Signal Factory dataset identity:

urn:dp:\<domain\>:\<dataset\>:v\<major\>

Examples:

* `urn:dp:orders:order_created:v1`  
* `urn:dp:billing:invoice_line:v2`

## **4.2 Column URN (required for element-level lineage)**

Stable column identity within a dataset:

urn:col:\<dataset\_urn\>:\<column\_name\>

Examples:

* `urn:col:urn:dp:orders:order_created:v1:payment_method`  
* `urn:col:urn:dp:orders:order_created:v1:customer_id`

**Rename support (recommended):**  
If your org supports column renames, add optional `column_id` (stable UUID) and `aliases[]`.

---

# **5\) Transport and Delivery Contract**

## **5.1 Delivery mechanism (choose one; both supported)**

**A) Kafka (recommended)**

* Topic: `signal_factory.lineage_specs`  
* Key: `lineage_spec_id`  
* Value: LineageSpec JSON (below)

**B) S3 \+ manifest**

* S3 prefix: `s3://<bucket>/lineage/specs/<org>/<repo>/<commit_sha>/lineage_spec.json`  
* Optional manifest events to Kafka: `signal_factory.lineage_spec_manifests`

## **5.2 Delivery guarantees**

* At-least-once delivery is fine (Signal Factory will dedupe by `lineage_spec_id`)  
* Specs are **immutable** (no updates; new spec \= new version)

---

# **6\) LineageSpec Schema (v1)**

## **6.1 Required fields (MUST)**

{

  "spec\_version": "1.0",

  "lineage\_spec\_id": "lspec:orders-delta-landing:git:9f31c2d",

  "emitted\_at": "2026-01-16T12:30:00Z",

  "producer": {

    "type": "JOB|SERVICE",

    "name": "orders-delta-landing",

    "platform": "SPARK|AIRFLOW|DBT|FLINK|CUSTOM",

    "runtime": "EMR|EKS|GLUE|DATABRICKS|SNOWFLAKE|OTHER",

    "owner\_team": "checkout-platform",

    "repo": "github:org/orders-analytics",

    "ref": {

      "ref\_type": "GIT\_SHA",

      "ref\_value": "9f31c2d"

    }

  },

  "lineage": {

    "inputs": \[

      {

        "dataset\_urn": "urn:dp:orders:order\_created:v1",

        "columns": \["customer\_id", "order\_id", "payment\_method"\],

        "column\_urns": \[

          "urn:col:urn:dp:orders:order\_created:v1:customer\_id",

          "urn:col:urn:dp:orders:order\_created:v1:order\_id",

          "urn:col:urn:dp:orders:order\_created:v1:payment\_method"

        \]

      }

    \],

    "outputs": \[

      {

        "dataset\_urn": "urn:dp:orders:order\_created\_curated:v1",

        "columns": \["customer\_id", "order\_id", "payment\_method\_norm"\],

        "column\_urns": \[

          "urn:col:urn:dp:orders:order\_created\_curated:v1:customer\_id",

          "urn:col:urn:dp:orders:order\_created\_curated:v1:order\_id",

          "urn:col:urn:dp:orders:order\_created\_curated:v1:payment\_method\_norm"

        \]

      }

    \]

  },

  "confidence": {

    "overall": "HIGH|MEDIUM|LOW",

    "reasons": \["STATIC\_SQL", "SPARK\_DF\_ANALYSIS", "DYNAMIC\_SQL\_DETECTED"\],

    "coverage": {

      "input\_columns\_pct": 0.92,

      "output\_columns\_pct": 0.88

    }

  }

}

## **6.2 Optional fields (SHOULD if available)**

{

  "transforms": \[

    {

      "output\_column": "payment\_method\_norm",

      "input\_columns": \["payment\_method"\],

      "operation": "CASE\_NORMALIZE",

      "details\_ref": "s3://.../transform\_details.json"

    }

  \],

  "data\_access": {

    "queries": \["SELECT ..."\], 

    "tables": \["db.schema.table"\]

  },

  "tags": \["PII\_TOUCHING", "TIER1"\]

}

### **Notes**

* `columns[]` is optional if `column_urns[]` are provided; but at least one must exist.  
* If SCA cannot enumerate columns (e.g., `select *`), it MUST still emit dataset-level edges and set confidence accordingly.

---

# **7\) Signal Factory Consumption Contract**

## **7.1 Dedupe \+ idempotency**

Signal Factory dedupes by:

* `lineage_spec_id`

Specs are treated as append-only; later specs supersede earlier ones **by ref time** (or by deployed version mapping if available).

## **7.2 Storage mapping**

* **Neptune**: topology edges (bounded)  
* **DynamoDB**: lookup indexes for fast “who reads/writes dataset/column”

### **Required Neptune node/edge mapping**

**Nodes**

* `Job/Service` (from `producer`)  
* `Dataset` (from `dataset_urn`)  
* `Column` (from `column_urn`)

**Edges**

* `(Producer)-[:READS]->(Dataset)`  
* `(Producer)-[:WRITES]->(Dataset)`  
* `(Producer)-[:READS_COL]->(Column)` *(if provided)*  
* `(Producer)-[:WRITES_COL]->(Column)` *(if provided)*

**No per-run edges**. No evidence events in Neptune.

---

# **8\) Operational Requirements**

## **8.1 Freshness expectations (SLOs)**

* Specs for Tier-1 producers: emitted on every merge to main OR at least daily  
* Specs must be available within:  
  * **1 hour** of merge for Tier-1 (target)  
  * **24 hours** max for non-Tier-1

## **8.2 Backfill expectations**

SCA team should support backfill by repo \+ commit range for onboarding.

## **8.3 Contract validation rules (Signal Factory will enforce)**

LineageSpec will be rejected (dead-letter) if:

* Missing `lineage_spec_id`, `producer`, or `lineage.inputs/outputs`  
* Invalid URN formats  
* Dataset URNs unknown *and* no mapping hints provided (see below)

---

# **9\) Dataset/Column Resolution Responsibility Split**

## **9.1 Who owns dataset identity?**

Signal Factory owns the authoritative Dataset URN mapping.

## **9.2 How SCA aligns to URNs (two options)**

**Option A (preferred): SCA emits canonical URNs**

* SCA uses shared registry lookup (read-only) to map sources/sinks → URNs.

**Option B: SCA emits “raw refs” \+ mapping hints**  
If SCA can’t resolve URNs, it MUST include:

{

  "raw\_refs": {

    "inputs": \[{"type":"KAFKA\_TOPIC","value":"orders.created"}\],

    "outputs": \[{"type":"DELTA\_TABLE","value":"s3://.../orders\_created\_curated"}\]

  }

}

Signal Factory maps raw refs to URNs using its resolution maps.

---

# **10\) What Signal Factory Expects from SCA (Requirements)**

## **10.1 MUST (minimum acceptable for integration)**

1. **Publish LineageSpec** via Kafka or S3 on a reliable cadence  
2. Include **producer identity** (name, type, repo, commit)  
3. Emit **dataset-level lineage** at minimum:  
   * inputs dataset(s)  
   * outputs dataset(s)  
4. Provide **column-level lineage** where feasible:  
   * input columns used  
   * output columns produced  
5. Include **confidence** and **coverage metrics**  
6. Be **immutable \+ versioned** (no in-place updates)

## **10.2 SHOULD (strongly recommended)**

1. Emit **transform hints** for column derivations (input→output column mapping)  
2. Identify **select \*** and dynamic SQL and downgrade confidence accordingly  
3. Provide **owner\_team** (or a stable pointer to service catalog)  
4. Provide **deployment linkage** if available (job version → commit SHA actually deployed)  
5. Provide **aliases/column\_id** support for renames

## **10.3 MAY (nice-to-have)**

* PII touch tags per column  
* Join keys / filter predicates summary  
* Data sensitivity classification pointers

---

# **11\) Confidence Model (Required Semantics)**

SCA must never “pretend certainty.”

* **HIGH**: static SQL / resolvable DF plan / strongly inferred  
* **MEDIUM**: partial resolution, some dynamic behavior, star-expansion resolved  
* **LOW**: heavy dynamic SQL, reflection, runtime constructed columns

**Coverage**

* `input_columns_pct`  
* `output_columns_pct`

This is critical because RCA will prioritize high-confidence edges.

---

# **12\) Example: How this helps an Option 2 incident**

Incident: `SCHEMA_DRIFT` on `urn:dp:orders:order_created:v1`, column removed `payment_method`

RCA Copilot queries:

* “Consumers reading dataset” → list jobs/dashboards  
* “Consumers reading column payment\_method” → prioritize impacted assets

This is why **column URNs \+ READS\_COL edges** are the critical output.

---

# **13\) Definition of Done for SCA Deliverable (Acceptance Checklist)**

SCA is “interface-complete” when:

*  Emits LineageSpec v1 to agreed transport  
*  At least dataset-level inputs/outputs for 90% of Tier-1 producers  
*  Column-level lineage for ≥70% Tier-1 producers (with confidence+coverage)  
*  Dynamic/unknown cases correctly marked LOW confidence (not omitted silently)  
*  Backfill supported for onboarding  
*  Spec IDs are immutable and dedupable

---

## **Next step (recommended)**

If you tell me what your “SCA” stands for in your org (Static Code Analysis vs something else) and the main compute patterns (Spark SQL, DataFrames, dbt, etc.), I can tailor:

* an exact **field list for transforms\[\]**  
* and a **mapping table** from your common frameworks → how to extract columns \+ confidence rules.

Below is a **step-by-step integration** of **SCA element-level lineage generated per deployment** into the **Out-of-Band (OOB) flow**, with a **clear, concrete example** showing how it improves **Option 2 (Contract-Lite) RCA** without changing producers.

---

# **1\) What changes when SCA runs per deployment**

### **Current OOB truth sources**

* **Runtime truth** (what actually happened): Enforcer Evidence → Engines → Incident (DynamoDB) \+ Causal edges (Neptune)  
* **Knowledge truth** (topology/causality): Dataset/Service/Owner \+ limited causal edges (Neptune)

### **New addition**

* **Design-time intent** (what this deploy *should* read/write at column level): SCA produces a **LineageSpec** artifact *at deploy time*, and Signal Factory ingests it into Neptune (and optional DynamoDB indexes).

**Important boundary:**  
SCA lineage does **not** block ingestion. It enriches OOB RCA and blast radius.

---

# **2\) Step-by-step OOB flow with SCA lineage (Deployment → Runtime → RCA)**

## **Step 0 — Preconditions (one-time setup)**

1. Signal Factory owns **Dataset URNs** and topic/table → dataset mappings.  
2. SCA team adopts the **LineageSpec** interface and can emit:  
   * dataset URNs (preferred), or raw refs \+ mapping hints  
3. Signal Factory runs a **Lineage Ingestor** service (EKS) that:  
   * validates specs  
   * writes Neptune topology edges  
   * writes fast lookup indexes (optional DynamoDB)

---

## **Step 1 — Build phase (SCA runs)**

**Trigger:** PR merged / build started for `orders-delta-landing` (Spark job)  
SCA runs static analysis to compute element-level lineage.

### **SCA output (example)**

Job: `orders-delta-landing`  
Commit: `9f31c2d`

It emits LineageSpec:

* **Inputs**  
  * `urn:dp:orders:order_created:v1` columns: `order_id, customer_id, payment_method`  
* **Outputs**  
  * `urn:dp:orders:order_created_curated:v1` columns: `order_id, customer_id, payment_method_norm`

Confidence: `HIGH` (Spark plan resolvable)

---

## **Step 2 — Deployment phase (LineageSpec is published *with* deployment)**

**Key requirement you stated:** “SCA planned to build element level lineage as part of each deployment.”

So the deployment pipeline must publish **two things**:

1. The actual deploy event (or deployment metadata)  
2. The LineageSpec

### **Recommended wiring**

* CI/CD publishes:  
  * `DeploymentEvent(job=orders-delta-landing, version=2026.01.16.1, commit=9f31c2d, ts=...)`  
  * `LineageSpec(lineage_spec_id=..., commit=9f31c2d, ...)`

This is the critical “join”: **deployment → lineage spec** via commit SHA/version.

---

## **Step 3 — Lineage Ingestor updates Knowledge Plane (Neptune)**

Signal Factory consumes the LineageSpec asynchronously and writes **bounded topology edges**.

### **What gets written to Neptune (example)**

**Nodes**

* `Job:orders-delta-landing`  
* `Dataset:urn:dp:orders:order_created:v1`  
* `Dataset:urn:dp:orders:order_created_curated:v1`  
* Column nodes:  
  * `urn:col:urn:dp:orders:order_created:v1:payment_method`  
  * `urn:col:urn:dp:orders:order_created_curated:v1:payment_method_norm`  
* `LineageSpec:lspec:orders-delta-landing:9f31c2d` (optional but useful)  
* `Deployment:orders-delta-landing@2026.01.16.1` (or equivalent)

**Edges**

* `Deployment -> (DEPLOYS) -> Job`  
* `LineageSpec -> (DESCRIBES) -> Job`  
* `LineageSpec -> (AT_COMMIT) -> Commit(9f31c2d)` *(or store commit as property)*  
* `Job -> READS -> Dataset(order_created)`  
* `Job -> WRITES -> Dataset(order_created_curated)`  
* `Job -> READS_COL -> Column(order_created.payment_method)`  
* `Job -> WRITES_COL -> Column(order_created_curated.payment_method_norm)`

Still **no per-run** edges, no evidence events, no time-series stored in Neptune.

---

## **Step 4 — Runtime: out-of-band enforcement detects an issue**

Now assume a runtime incident occurs.

### **Concrete incident example**

On **Jan 16**, producer `order-service` deploys and removes `payment_method` from `orders.created` events:

* Schema fingerprint changes: `A1B2 → C9D8`  
* Contract-lite gate flags `FIELD_REMOVED:payment_method`

**Enforcer emits Evidence FAIL** with:

* dataset\_urn \= `urn:dp:orders:order_created:v1`  
* schema\_fingerprint delta  
* reason\_code \= `FIELD_REMOVED:payment_method`  
* first\_bad\_ts / last\_good\_ts

Signal Engines compute:

* `SCHEMA_DRIFT` incident on dataset `order_created`

Signal Factory writes causal nodes/edges for the incident:

* `Incident(INC-2026-01-16-001)`  
* `FailureSignature(FIELD_REMOVED:payment_method)`  
* Link incident → dataset, failure signature, possibly producer deploy

---

## **Step 5 — RCA traversal uses SCA lineage to find *blast radius at column level***

This is the payoff.

### **Without SCA lineage**

RCA can say:

* “Producer changed schema; dataset impacted; some consumers might break”  
  But it struggles to rank “who is actually broken”.

### **With SCA lineage (per deployment)**

RCA Copilot performs this traversal:

1. Start from the incident:  
* `INC-2026-01-16-001 -> ABOUT -> Dataset(order_created)`  
* Identify the implicated element:  
* `FailureSignature` contains `payment_method`  
2. Traverse to consumers of the dataset:  
* `Dataset(order_created) <- READS - Job(*)`  
3. Narrow to consumers that read the specific column:  
* `Column(order_created.payment_method) <- READS_COL - Job(*)`  
4. Rank by “deployed version closest to incident time”:  
* For each job found, pick the **latest Deployment node prior to incident time**  
* Because SCA runs every deploy, you can confidently select the right lineage spec/version for that job.

### **Result (human-friendly output)**

Impacted assets ranked:

1. `orders-delta-landing@2026.01.16.1` reads `payment_method` (HIGH confidence) → likely failing/parsing nulls  
2. `revenue-kpi-dashboard` depends on curated dataset column `payment_method_norm` → downstream KPI degradation likely

Mitigation suggestion:

* rollback producer deploy OR  
* hotfix landing job to handle missing field OR  
* quarantine route for the dataset

---

# **3\) How “same job, different days” works with per-deploy lineage**

Because SCA emits a LineageSpec **per deployment**, the graph has:

* **multiple LineageSpecs** (per commit)  
* **multiple Deployment nodes**  
* lineage edges are attached to Job and optionally to LineageSpec nodes; Copilot chooses **the spec matching the deployed version** closest to the incident time.

So the Copilot can answer:

“This incident affects the currently deployed landing job version, which explicitly reads the removed column.”

This avoids stale lineage.

---

# **4\) Minimal requirements to make this integration reliable**

## **Must-have**

1. CI/CD emits **DeploymentEvent with commit SHA**  
2. SCA emits **LineageSpec with same commit SHA**  
3. Signal Factory writes **Deployment → Job → LineageSpec** linkage  
4. Column URNs exist and are stable enough (handle renames via aliases or stable IDs)

## **Strongly recommended**

5. Confidence \+ coverage are mandatory and used in ranking (LOW confidence edges shouldn’t dominate RCA)  
6. Store only bounded samples/pointers; no massive graph writes

---

# **5\) The simplest “steel thread” you should implement first**

To de-risk this end-to-end:

1. One Spark job (landing) with SCA lineage per deploy  
2. One schema drift incident on upstream dataset  
3. RCA output must show:  
   * implicated column  
   * top 3 impacted consumers reading that column  
   * deployed version of each consumer at incident time

That proves the integration is real.

---

If you want, I can convert the above into:

* a **sequence diagram** (Deploy pipeline → SCA → Lineage Ingestor → Neptune → Runtime Incident → RCA traversal),  
* and a **tiny set of Gremlin query patterns** the Copilot will execute (incident → dataset → column → consumer jobs with latest deployment at time T).

Short answer: **No — this determination does *not* use the lineage graph.**  
It is made **entirely in the Enforcer \+ Contract-Lite gate**, *before* lineage is ever consulted.

Below is the precise breakdown so the separation of concerns is crystal clear.

---

## **1\. Where the determination actually happens**

### **Schema fingerprint change**

A1B2 → C9D8

**Computed by:** ✅ **Enforcer (ingestion-time)**  
**Input:** Incoming payloads \+ resolved schema  
**Not involved:** ❌ Neptune, ❌ SCA lineage

**How**

1. Enforcer resolves dataset → schema reference (from registry / baseline)  
2. Enforcer canonicalizes the incoming payload schema  
3. Enforcer computes a deterministic **schema fingerprint**  
4. Fingerprint is compared against:  
   * last-known-good fingerprint (cached or fetched)  
5. If different → schema drift candidate detected

This is **purely runtime evidence**, not design-time intent.

---

### **Contract-lite violation**

FIELD\_REMOVED: payment\_method

**Computed by:** ✅ **Enforcer Contract-Lite Gate**  
**Input:** Payload structure vs baseline contract  
**Not involved:** ❌ Neptune, ❌ SCA lineage

**How**

Contract-lite baseline says:  
required\_fields \= \["order\_id", "customer\_id", "payment\_method"\]

1.   
2. Incoming payload does not contain `payment_method`

Gate evaluates:  
missing\_required\_field("payment\_method") \== true

3. 

Gate emits:  
reason\_code \= FIELD\_REMOVED:payment\_method

4. 

This is a **hard fact about the payload**, not about who consumes it.

---

## **2\. Why lineage is *not* used here (by design)**

This is a **deliberate architectural choice**.

### **If lineage were used here, it would be wrong because:**

* Lineage describes **what code *intends* to read/write**  
* Contract-lite validates **what data *actually arrived***  
* Lineage can be stale, partial, or low-confidence  
* Contract validation must be:  
  * deterministic  
  * synchronous  
  * blocking-capable (or quarantine-capable)

So:

**Lineage never influences gate decisions.**

It would introduce false negatives and coupling.

---

## **3\. Exact responsibility split (critical)**

| Question | Answered by | Uses lineage? |
| ----- | ----- | ----- |
| Did the schema change? | Enforcer | ❌ No |
| Which field changed? | Contract-lite gate | ❌ No |
| Is the change compatible? | Contract-lite gate | ❌ No |
| Should we emit FAIL evidence? | Enforcer | ❌ No |
| Who is impacted downstream? | RCA Copilot | ✅ Yes |
| Which jobs read that column? | Lineage graph | ✅ Yes |
| Blast radius ranking | Lineage \+ confidence | ✅ Yes |

This separation is what keeps the system correct.

---

## **4\. End-to-end timeline showing the handoff**

### **T0 – Runtime ingestion**

Payload arrives **without** `payment_method`

**Enforcer**

* computes fingerprint → `C9D8`  
* compares to baseline → `A1B2`  
* detects missing field → emits:

{  
  "schema\_fingerprint\_prev": "A1B2",  
  "schema\_fingerprint\_curr": "C9D8",  
  "reason\_code": "FIELD\_REMOVED:payment\_method"  
}

➡ Evidence emitted  
➡ Signal Engines evaluate  
➡ Incident created

---

### **T1 – RCA time**

Now lineage comes into play.

**RCA Copilot**

Reads incident:  
FailureSignature \= FIELD\_REMOVED:payment\_method  
Dataset \= orders\_created

1. 

Queries Neptune:  
Which jobs READ\_COL orders\_created.payment\_method?

2.   
3. Ranks impacted consumers  
4. Produces RCA narrative

At no point does lineage affect **whether** the violation existed.

---

## **5\. Why this design scales and stays correct**

### **What would break if lineage were used earlier**

* False negatives when lineage is incomplete  
* False positives when jobs no longer deployed  
* Runtime outages because design-time data lagged

### **What works instead**

* **Runtime truth first (Enforcer)**  
* **Design-time intent second (Lineage)**  
* **Correlation only at RCA layer**

This is the same principle used in:

* Databases (constraints ≠ query plans)  
* Compilers (type checking ≠ call graphs)  
* SRE (health checks ≠ dependency graphs)

---

## **6\. One-sentence rule to remember**

**Contract-lite gates answer “Is this data valid?”**  
**Lineage answers “Who cares if it isn’t?”**

That boundary is what makes your architecture robust.

---

If you want, next I can:

* show how **schema fingerprint canonicalization** works in detail,  
* or explain **how baselines are learned safely** without producer contracts,  
* or walk through **a false-positive scenario and how it’s suppressed**.

