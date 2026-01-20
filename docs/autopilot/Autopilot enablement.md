## **Team A — Autopilot & Producer Enablement (what they’re accountable for)**

**Mission:** Make producers “minimum-observable” with *opt-in*, *low-risk*, *standardized* instrumentation—at enterprise scale—without slowing teams down.

### **What Team A must deliver (expectations)**

1. **Producer SDKs / Golden Paths (Spring, Go, Node)**  
* A tiny, safe instrumentation pack that teams can adopt with:  
  * “add dependency”  
  * “enable one flag”  
  * “deploy”  
* Must be **non-blocking** and **default-off** until explicitly enabled.

**Example (Java Spring)**

* Provide a Spring Boot starter that can emit:  
  * `DeploymentEvent` from CI/CD (preferred) or app startup (fallback)  
  * a `producer_identity_hint` (service/env/domain)  
  * optional `trace_id` propagation/creation at the edge

**What “good” looks like**

* A service team adds the starter and flips `autopilot.enabled=true`.  
* No measurable latency on the business path.  
* If the observability backend is down, the service **still runs normally** (signals drop or buffer locally).  
2. **Autopilot PR Generator (PR-bot)**  
* Autogenerates PRs per repo archetype:  
  * adds SDK dependency  
  * wires minimal config  
  * adds tests \+ rollback steps  
  * includes a “what changed / why safe” section  
* Supports staged rollout via config flags (“Ring-0 → Ring-1 → Ring-2”).

**Example (Go producer repo)**

* PR adds:  
  * `autopilot-go` module import  
  * a small wrapper around the Kafka producer client to attach identity hints  
  * CI step to emit `DeploymentEvent` on successful deploy  
* PR includes a dry-run check: “emit a synthetic signal in staging”.  
3. **Rollout & Adoption Mechanics**  
* PR fleet management: throttling, batching, owner routing, avoiding PR spam.  
* Enablement playbooks and “minimum-observable readiness” check.  
* Adoption dashboards: onboarding rate, merge time, revert rate, error rate.

**Example**

* Onboard 20 Spring services in a domain:  
  * Week 1: generate PRs but keep flags OFF.  
  * Week 2: enable in staging, validate signals.  
  * Week 3: enable in prod for 5 services (Ring-1).  
  * Week 4: expand to remaining 15 (Ring-2).  
4. **Developer Experience & Safety Bar**  
* The SDK must be:  
  * easy to remove (no lock-in)  
  * versioned safely  
  * security-reviewed  
  * minimal surface area  
* “No harm” guarantee:  
  * async emission  
  * bounded buffering  
  * kill switch per service/domain  
  * circuit breaker on signal submission

**Example**

* If the gateway is slow:  
  * SDK drops signals after N ms / N retries  
  * increments a local metric “signals\_dropped”  
  * never delays business transactions

### **Team A success metrics**

* % producers onboarded by language (Spring/Go/Node/Spark pack later)  
* median PR time-to-merge  
* rollback/revert rate \< agreed threshold  
* zero P0 incidents caused by Autopilot instrumentation

---

## **Team B — Evidence, Control Plane & RCA Loop (what they’re accountable for)**

**Mission:** Turn raw producer signals into **deterministic, trustworthy RCA** and scalable operations through a strong control plane.

### **What Team B must deliver (expectations)**

1. **Evidence Envelope \+ Storage (the “source of truth”)**  
* Define what must exist per event/flow so RCA can be evidence-based:  
  * `dataset_urn`  
  * `producer_urn`  
  * `schema_fingerprint` (or schema ID)  
  * `offset/sequence`  
  * `event_time` and `ingest_time`  
  * `deploy_ref` (link to commit/build/version)  
  * `reason_code` if a gate fails

**Example**

* A message is rejected by a contract-lite gate because `customer_id` is missing.  
* Team B ensures an Evidence record exists:  
  * “dataset:orders\_v1”  
  * “producer:checkout-service”  
  * “schema\_fp:abc123”  
  * “reason\_code:REQUIRED\_FIELD\_MISSING”  
  * “first seen at 10:21:04, last good at 10:20:58”  
  * “most correlated deploy: checkout-service v2.8.1 @ 10:20”  
2. **Dataset Resolution & Drift Handling**  
* Resolve “what dataset is this event for?” reliably:  
  * map `(topic, schema_id, headers)` → `dataset_urn`  
* Provide human approval workflow for rules.  
* Detect drift when schema/topic patterns change.

**Example**

* A producer starts emitting a new schema version on the same topic.  
* Resolution confidence drops:  
  * Team B flags: “mapping ambiguity increased”  
  * opens a change request to update the mapping rule  
  * prevents silent mis-attribution of incidents  
3. **Policy Skeletons \+ Readiness Scoring**  
* Autogenerate baseline policies per dataset:  
  * owners, tier, SLO defaults (freshness/volume), contract-lite settings  
* Compute readiness score:  
  * trace anchor coverage  
  * identity confidence  
  * deploy correlation coverage  
  * policy completeness

**Example**

* Dataset “payments\_settlements” readiness is 62% because:  
  * deploy correlation exists (✅)  
  * dataset resolution is confident (✅)  
  * trace anchors missing (❌)  
  * no runbook link (❌)  
* This drives targeted backlog: “add trace anchor for 3 producers \+ attach runbook”.  
4. **Incident \+ RCA UX and Copilot Guardrails**  
* Provide the minimal UI/API that shows:  
  * failure reason codes  
  * first-bad/last-good boundaries  
  * correlated deploy(s)  
  * impacted downstream assets (where lineage exists)  
  * evidence samples (IDs) for auditability  
* Copilot must be **evidence-grounded** with confidence scoring.

**Example (RCA output)**

* “Most likely cause: checkout-service deployment v2.8.1 introduced missing `customer_id` on OrdersCreated.”  
* Backed by:  
  * evidence IDs showing first-bad right after deploy  
  * gate failure reason codes  
  * distribution shift of missing field rate from 0% → 18%  
* If evidence is insufficient, Copilot says “inconclusive” and lists the next best checks.  
5. **Operational SLOs for the Observability Backbone**  
* Evidence ingestion health  
* rule resolution latency  
* drift detection time  
* incident creation latency  
* correctness/false-positive controls

**Example**

* If evidence ingestion lags \> 2 minutes:  
  * Team B triggers an alert  
  * incident creation is paused or tagged “stale evidence”  
  * prevents misleading RCA conclusions

### **Team B success metrics**

* % incidents with evidence-backed boundaries  
* % incidents with deploy correlation  
* mapping resolution confidence \+ drift remediation time  
* false-positive and “inconclusive RCA” rates (should fall over time)

---

## **How Team A and Team B work together (one concrete end-to-end example)**

**Scenario: Java Spring producer breaks a field**

1. Team A’s Spring starter is enabled for `checkout-service`.  
2. The service deploys v2.8.1; CI emits `DeploymentEvent`.  
3. A new code path omits `customer_id` in `OrdersCreated`.

**What happens**

* Team B’s gate detects missing required field → rejects or flags event (depending on enforcement mode).  
* Team B writes Evidence with reason code \+ offsets \+ timestamps.  
* Team B correlates “first-bad” to the deploy event at 10:20.

**Outcome**

* On-call sees:  
  * “Orders dataset failing contract-lite: REQUIRED\_FIELD\_MISSING(customer\_id)”  
  * “First bad immediately after checkout-service v2.8.1”  
  * “Suggested fix: rollback v2.8.1 or patch field mapping”  
* Team A’s instrumentation made attribution possible; Team B’s evidence/control plane made RCA deterministic.

---

If you want the same style examples for:

* **Go producer with partial tracing**  
* **Node producer with schema drift**  
* **Spark batch job writing a Delta table late (freshness incident)**

…I can add those as “canonical incident playbooks” for both teams to use during rollout.

---

## **Use case**

A nightly Spark job **`orders_enriched_batch`** writes to **Delta table** `s3://lake/curated/orders_enriched_delta` (dataset\_urn: `ds://curated/orders_enriched`).

**SLO:** Table must be updated by **02:00 ET** daily.  
**Incident:** At **02:15 ET**, downstream dashboards show stale data.

---

## **What “minimum-observable” means for Spark freshness**

To do deterministic RCA, the system must know:

1. **Expected cadence/window** (policy)  
2. **Last successful write** time and **partition watermark** (evidence)  
3. Whether the delay is from:  
   * job didn’t start  
   * job ran slow  
   * job failed/retried  
   * data was late upstream  
   * write committed but partitions missing  
4. Who owns it \+ what changed recently (deploy/version/config)

---

## **Team A expectations (Spark batch “minimum pack”) — with concrete emissions**

### **A1) Spark Job Run Events (from Spark listener / job wrapper)**

Team A provides a **Spark autopilot pack** (library or wrapper) that emits these events asynchronously:

* `JobRunStarted`  
  * `producer_urn`: `job://orders_enriched_batch`  
  * `run_id`: `2026-01-19T01:00Z_abc`  
  * `code_ref`: git SHA / artifact version  
  * `env`, `cluster_id`, `spark_app_id`  
  * `input_datasets` (optional if known)  
  * `scheduled_time`, `actual_start_time`  
* `JobRunCompleted` / `JobRunFailed`  
  * duration, failure reason, retry count, exit code  
  * resource summary (executors, memory), key stage timings (optional)

**Why this matters:** It separates **“job never ran”** from **“job ran but slow/failed.”**

### **A2) Delta Commit Evidence Hook (write-side)**

Team A’s pack attaches a lightweight hook at write time to emit:

* `DatasetWriteCommitted`  
  * `dataset_urn`: `ds://curated/orders_enriched`  
  * `run_id`  
  * `commit_version` (Delta table version)  
  * `commit_timestamp`  
  * `output_partitions_written` (e.g., `dt=2026-01-19`)  
  * `rows_written`, `files_added` (optional)

**Why this matters:** It turns “freshness” into a concrete **watermark**: *what partition/version is available now*.

### **A3) Deployment correlation for batch**

Even batch needs “deploy correlation”:

* When the job code/config changes, Team A ensures `deploy_ref` is emitted via CI/CD (preferred) or included in job run events.

**Outcome:** When freshness breaks, you can immediately ask: “Did we ship something?”

---

## **Team B expectations (freshness engine \+ evidence \+ policy) — with concrete logic**

### **B1) Freshness policy definition (per dataset)**

Team B defines `FreshnessPolicy` for `ds://curated/orders_enriched`, e.g.:

* `expected_update_by`: 02:00 ET daily  
* `grace_period`: 10 minutes  
* `watermark_dimension`: `dt` partition must reach “today”  
* `owner_team`: “Orders Analytics”  
* `tier`: 1  
* `runbook_url`: link

### **B2) Freshness signal computation (the “detector”)**

Team B’s engine computes:

* **Last Commit Time** from `DatasetWriteCommitted`  
* **Last Watermark** from `output_partitions_written` (or derived from Delta log)  
* **Expected vs actual**  
* **Reason classification** using join logic across Evidence:

**Classifier example:**

* If no `JobRunStarted` after schedule → `REASON: JOB_NOT_TRIGGERED`  
* If `JobRunStarted` exists but no `DatasetWriteCommitted`:  
  * If `JobRunFailed` exists → `REASON: JOB_FAILED`  
  * Else → `REASON: JOB_RUNNING_SLOW`  
* If `DatasetWriteCommitted` exists but watermark partition missing → `REASON: PARTIAL_WRITE / WRONG_PARTITION`  
* If job succeeded but inputs were late (if input evidence exists) → `REASON: UPSTREAM_DATA_LATE`

### **B3) Incident assembly \+ evidence drilldown**

Team B generates an incident with:

* **first\_bad\_time**: 02:10 (grace period exceeded)  
* **last\_good\_time**: yesterday 01:47  
* **current\_watermark**: `dt=2026-01-18` (expected `2026-01-19`)  
* **correlated run**: `run_id=...`  
* **correlated deploy\_ref**: `sha=...` (if changed recently)  
* **evidence IDs**: links to the specific job-run and commit events

### **B4) Copilot output guardrails**

Copilot must only claim root cause if evidence supports it:

* If `JobRunStarted` is missing: “Scheduler did not trigger”  
* If `JobRunFailed` with OOM: “Likely resource regression”  
* If `JobRunRunningSlow` with stage skew: “Performance regression or input volume spike”  
* If watermark stuck: “Write committed but wrong partition/date logic”

---

## **What the on-call sees (example incident narrative)**

**Incident:** `Freshness SLO breach: ds://curated/orders_enriched`  
**Detected:** 02:10 ET (grace exceeded)  
**Current watermark:** `dt=2026-01-18` (expected `2026-01-19`)  
**Most likely cause (evidence-backed):** `JOB_RUNNING_SLOW`

**Evidence:**

* `JobRunStarted` at 01:00 ET, run\_id `…abc`  
* No `DatasetWriteCommitted` yet  
* Job still running at 02:15 ET, duration 75 mins (baseline 35 mins)  
* No new deploy since yesterday (deploy\_ref unchanged)

**Suggested next action:**

* Check Spark stage 3 skew; compare input size to baseline  
* Scale executors for this run (temporary), then open perf ticket  
* If dashboards are Tier-1, trigger fallback dataset or partial refresh

---

## **Two concrete “late” variants and how the system distinguishes them**

### **Variant 1: Job never started (scheduler issue)**

* Evidence: no `JobRunStarted` after schedule  
* Incident reason: `JOB_NOT_TRIGGERED`  
* Action: check Airflow/StepFunctions trigger, permissions, missed schedule

### **Variant 2: Job succeeded but wrote wrong partition date (logic bug)**

* Evidence: `DatasetWriteCommitted` exists, but watermark dimension doesn’t advance (still `dt=2026-01-18`)  
* Incident reason: `WRONG_PARTITION / PARTIAL_WRITE`  
* Action: validate `dt` derivation logic, time zone boundary, source event-time vs processing-time mismatch

---

## **Why this is the right “minimum” for Spark freshness**

You don’t need full lineage or deep metrics to get strong RCA. The minimum set is:

* **Job run start/stop/fail**  
* **Delta commit/watermark evidence**  
* **Freshness policy with expected update window**  
* **Deploy correlation**

That combo makes “late data” incidents explainable in minutes, not hours.

If you want, I can also lay this out as a **sequence diagram** (scheduler → Spark → evidence → freshness engine → incident → copilot) and a **minimal event schema** for the four events above so Team A and Team B can implement consistently.

