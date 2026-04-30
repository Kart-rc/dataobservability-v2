Executive assessment

The data observability dashboard should not be positioned as “another monitoring dashboard.” It should be the trust operating system for published data: a leadership-facing view of whether critical data is trustworthy, an application-facing view of what gaps prevent trust, and an engineering-facing view of what to fix next.

The project vision is directionally strong because it already has the right primitives: out-of-band evidence, signal engines, knowledge graph, RCA Copilot, Autopilot remediation, and business-value attribution. The architecture explicitly separates the data path from the observability path, preserves zero producer changes as the default, and uses Evidence as the immutable basis for trust decisions. The HLD defines the strategic shift as pre-consumption safety: bad data may still flow, but the platform creates evidence so consumers and SREs can make trust-based decisions.  ￼

My recommendation: build the dashboard around four nested scorecards:

1. Executive Trust Scorecard — Are Tier-1 data products becoming more trustworthy?
2. Domain / Portfolio Scorecard — Which domains are improving or lagging?
3. Application / Producer Scorecard — What exact gaps does each app need to close?
4. Signal Factory Health Scorecard — Can the observability platform itself be trusted?

The most important design principle: measure business pain removed, not instrumentation installed. The agentic onboarding document explicitly warns against measuring adoption by dashboard count, SDK presence, or PR count, and recommends tying adoption to reduced issues, prevention, and MTTD / MTTR improvement.  ￼

⸻

1. What the dashboard must prove

The dashboard must answer five leadership questions:

Leadership question	Dashboard answer
Can we trust Tier-1 data being published?	Trust score by dataset/domain, backed by Evidence, freshness, contract, DQ, drift, and lineage coverage
Are we getting better from baseline?	Current vs target trend for RCA latency, MTTD, MTTR, false positives, lineage coverage, developer toil
Which applications are creating trust risk?	Producer/app readiness score, weak signal areas, recurring failure signatures, ownership confidence
What should teams do next?	Prioritized remediation backlog with Autopilot PR suggestions and expected impact
Is this creating business value?	Incidents avoided, MTTR hours saved, stale-data exposure reduced, dashboards protected, toil reduced

This matters because the current documented pain is severe: RCA latency is 30–60 minutes, MTTD is 4–6 hours for Tier-1, MTTR is 12+ hours, false positives are 60–80%, element-level lineage is effectively 0%, and developer toil is around 20% sprint velocity. The target state is RCA under 2 minutes, MTTD under 15 minutes, MTTR under 2 hours, false positives under 20%, 100% Tier-1 lineage coverage, and developer toil under 5%.  ￼

⸻

2. Recommended dashboard structure

flowchart TB
    A[Executive Trust Dashboard] --> B[Domain / Portfolio Scorecard]
    B --> C[Dataset Trust Scorecard]
    C --> D[Application / Producer Gap View]
    D --> E[Autopilot Remediation Backlog]
    F[Evidence Bus] --> C
    G[Signal Engines] --> C
    H[Gateway Control Plane] --> C
    I[Neptune / Lineage Graph] --> C
    J[CI/CD Deploy Events] --> D
    K[Incident / Ticketing] --> A
    L[OTel / OpenLineage / Delta / Airflow] --> C
    C --> M[Value Attribution Engine]
    M --> A

The dashboard should follow the platform’s core separation of concerns:

Layer	Meaning	Dashboard role
Record Truth	Per-record PASS / FAIL from Policy Enforcer	Shows whether data is valid at publication / observation time
System Health	Windowed health from Signal Engines	Shows freshness, volume, contract, DQ, drift, anomaly state
Causal Analysis	Graph traversal from RCA Copilot	Shows why it happened, who owns it, and who is impacted
Business Value	Impact avoided or reduced	Shows whether observability is paying off

This aligns with the component decomposition: Policy Enforcer owns record truth, Signal Engines own system health, and RCA Copilot owns causal analysis.  ￼

⸻

3. North Star metrics: baseline to target

These are the executive-level metrics that should be front and center.

Metric	Current baseline	Target state	Source of truth	Why it matters
RCA query latency	30–60 min	< 2 min	RCA Copilot logs, Neptune query telemetry, EvidenceCache	Proves incidents can be explained quickly
MTTD for Tier-1 data issues	4–6 hrs	< 15 min	IncidentIndex, SignalState, alert timestamps	Measures early detection
MTTR	12+ hrs	< 2 hrs	PagerDuty/Jira/ServiceNow incident lifecycle	Measures operational impact
False positive alert rate	60–80%	< 20%	Alert outcomes, muted alerts, closed-no-action incidents	Measures signal trust
Tier-1 lineage coverage	0% element-level	100% Tier-1	Neptune, LineageSpec registry, OpenLineage/SCA feeds	Enables blast radius and impact analysis
Developer toil	20% sprint velocity	< 5%	Incident time logs, Jira labels, on-call review	Measures productivity recovered
Evidence latency	New metric	< 2 sec P99	Policy Enforcer metrics, Evidence Bus timestamps	Ensures trust signals arrive quickly
Signal freshness	New metric	< 5 min	Signal Engine state timestamps	Ensures dashboard is not stale
Evidence coverage for Tier-1 topics	New metric	> 95% initially, > 99% mature	Raw topic offsets vs Evidence Bus offsets	Ensures observability coverage is real

The HLD and LLD already define the latency pattern: producer-to-Kafka data path adds 0 ms, Kafka-to-Evidence target is under 2 seconds, signal evaluation uses 5-minute windows, and RCA query path targets under 2 minutes.  ￼

⸻

4. Data trust score: the main dataset-level metric

A dashboard that only shows individual metrics will be noisy. Leadership needs one composite trust score, while engineers need the decomposition.

Recommended formula

Dataset Trust Score =
  20% Evidence Coverage
+ 15% Freshness Compliance
+ 15% Contract / Schema Compliance
+ 10% Volume Stability
+ 10% DQ Compliance
+ 10% Producer Attribution Confidence
+ 10% Lineage / Blast Radius Coverage
+ 5% RCA Readiness
+ 5% Platform Observability Health

Example interpretation

Score	Meaning	Action
90–100	Trusted	Safe for executive / Tier-1 consumption
75–89	Mostly trusted	Monitor, close remaining gaps
60–74	Conditional trust	Consumers should be warned; remediation backlog required
40–59	Low trust	Not suitable for critical consumption without review
< 40	Untrusted	Escalate to domain owner and platform governance

This score should never hide the underlying reasons. Every score must drill down into: failed gates, top reason codes, stale signals, lineage gaps, missing owner, missing contract, missing trace anchors, or platform health degradation.

⸻

5. Metrics and source systems

A. Trust and correctness metrics

Metric	Definition	Source	App-facing diagnosis
Evidence coverage	Evidence events / observed raw events	Raw Kafka offsets, Evidence Bus offsets	“Your topic is not fully observable”
PASS rate	PASS evidence / total evidence	Evidence Bus	“Data is being observed and mostly valid”
Contract compliance rate	Contract PASS / total evaluated	Contract Signal Engine	“Required fields or business constraints are failing”
Schema drift count	Number of schema fingerprint changes	Policy Enforcer, Schema Registry	“Your payload shape changed from baseline”
Top failed gates	CONTRACT, SCHEMA, PII, RESOLUTION, IDENTITY	Evidence validation result	“Your main problem is missing field / schema mismatch / identity ambiguity”
Top reason codes	MISSING_FIELD, TYPE_CHANGE, PII_DETECTED, REGISTRY_UNAVAILABLE	Evidence reason codes	“Here is the exact fix target”
DQ rule pass rate	Passed DQ checks / total DQ checks	Deequ/DQ Evidence, DQ Engine	“Field-level quality is deteriorating”
PII policy violations	Unauthorized PII detected per dataset	PII gate, policy metadata	“Sensitive data is appearing where policy disallows it”

The Policy Enforcer gate pipeline already supports this model: dataset resolution, producer identity, schema validation, contract validation, PII detection, and Evidence emission.  ￼

⸻

B. Freshness, volume, and availability metrics

Metric	Definition	Source	App-facing diagnosis
Freshness SLO compliance	% windows where last valid evidence is within SLA	Freshness Engine, DatasetRegistry SLOs	“Data is stale or timestamps are missing”
Event-time lag	ingest_time - event_time	Evidence source metadata	“Producer emits old events or lacks event_time”
Processing lag	now - last Evidence event time	Evidence Bus, SignalState	“Observability or ingestion path is delayed”
Volume anomaly score	Deviation from learned / declared baseline	Volume Engine	“Data dropped, spiked, or partially published”
Zero evidence during traffic window	No evidence where traffic expected	Signal Engine, policy calendar	“Possible producer stoppage or enforcer gap”
Landing freshness	Delta commit time vs SLA	Delta history, Airflow, OpenLineage	“Kafka may be fine, but table landing is stale”

The HLD defines Freshness, Volume, Contract, DQ, Drift, Anomaly, and Cost engines as the evolved Signal Engine set, all consuming from the Evidence Bus rather than raw topics.  ￼

⸻

C. RCA readiness metrics

Metric	Definition	Source	Why it matters
Incidents with evidence-backed boundary	% incidents with first-bad / last-good evidence	Evidence Bus, IncidentIndex	Shows whether RCA can be deterministic
Incidents with deploy correlation	% incidents linked to recent deploy_ref	CI/CD events, DeploymentEvent, RCA graph	Identifies likely change source
Incidents with trace anchor	% incidents with trace_id / span_id references	OTel, Evidence otel fields	Enables causal path across services
Incidents with lineage blast radius	% incidents with downstream impact list	Neptune, LineageSpec, OpenLineage	Shows who is affected
RCA confidence	HIGH / MED / LOW / INCONCLUSIVE	RCA Copilot output metadata	Prevents overclaiming
Inconclusive RCA rate	Inconclusive RCAs / total RCAs	RCA Copilot logs	Shows where signal gaps remain
Mean RCA time	Incident creation → RCA explanation available	Incident system, RCA logs	Proves RCA speed improvement

The Autopilot enablement document calls out the minimal RCA UX: failure reason codes, first-bad/last-good boundaries, correlated deploys, impacted downstream assets, and evidence samples for auditability.  ￼

⸻

D. Lineage and impact metrics

Metric	Definition	Source	Target
Dataset-level lineage coverage	Tier-1 datasets with upstream/downstream lineage	Neptune, OpenLineage, SCA LineageSpec	100% Tier-1
Column-level lineage coverage	Tier-1 columns with READS_COL / WRITES_COL edges	SCA, OpenLineage column facets, Neptune	70–100% by maturity
Lineage confidence mix	% HIGH / MED / LOW lineage edges	LineageSpec confidence	HIGH dominates Tier-1
Blast radius availability	% incidents where impacted consumers are listed	Neptune + RCA Copilot	> 90% Tier-1
Stale lineage rate	Deployed commit lacks matching LineageSpec	CI/CD + LineageSpec registry	< 5% Tier-1
Consumer impact ranking accuracy	RCA-predicted impacted assets later confirmed	RCA postmortems	Improve over time

Lineage should remain RCA enrichment, not a runtime gate. The lineage spec states that Signal Factory is runtime truth, SCA is design-time intent, and lineage should be loosely coupled, append-only, and keyed by stable IDs.  ￼

⸻

E. Application readiness metrics

This is the most important application-facing view.

Readiness area	Metric	Source	Typical fix
Identity	Producer attribution confidence	Kafka principal, topic map, headers, payload hints	Add producer identity header/field or improve topic ownership map
Dataset resolution	Resolution confidence	DatasetResolutionMap, Gateway Control Plane	Register topic → dataset URN rule
Schema	Schema binding coverage	Glue Schema Registry, Control Plane	Register schema and compatibility policy
Contracts	Contract coverage	ODCS contract registry	Add required-field and SLO contract
Freshness	event_time / processing_time coverage	Evidence source metadata	Emit event_time or processing timestamp
Tracing	trace_id coverage	OTel spans, Evidence otel fields	Add trace propagation / key spans
Lineage	dataset/column lineage coverage	OpenLineage, SCA, Neptune	Emit LineageSpec or OpenLineage facets
Runbook	runbook_ref availability	Control Plane, Service catalog	Attach dataset-specific runbook
Operational safety	rollback rate / instrumentation incident count	CI/CD, incident system	Improve Autopilot PR validation

The recommended onboarding model uses zero-change discovery as the baseline and selective light-touch instrumentation for Tier-1 assets or confidence gaps. It explicitly recommends trust tiers and targeted changes such as tracing, attribution, event_time, contracts, DQ markers, and dataset URNs.  ￼

⸻

6. Application problem-area diagnosis

Every application should get a “Why my score is low” panel.

Example: Orders Service scorecard

Dimension	Current	Target	Status	Diagnosis	Recommended solution
Evidence coverage	98%	99.9%	Yellow	Evidence lag during peak traffic	Increase Enforcer partitions / tune consumer lag
Producer identity confidence	62%	95%	Red	Topic mapping only, no trusted producer signal	Add producer identity header or Kafka principal mapping
Contract coverage	40%	95%	Red	Contract exists for only one event type	Autopilot draft ODCS contracts for missing topics
Freshness truth	55%	95%	Red	event_time missing in many events	Add event_time / processing_time field
Trace anchor coverage	30%	90%	Red	Missing trace propagation through Kafka	Add OTel propagation on producer and consumer
Lineage coverage	75% dataset, 20% column	100% Tier-1	Yellow	SCA covers job-level, not element-level	Emit LineageSpec with column URNs
RCA readiness	50%	90%	Red	Incidents lack deploy_ref and first-bad boundary	Add CI/CD DeploymentEvent and evidence boundary tracking

This should automatically generate a prioritized backlog:

Priority Score =
  Tier Weight
+ Gap Severity
+ Downstream Impact
+ Incident Recurrence
+ Business Criticality
- Implementation Friction

The Autopilot Push Model already uses a similar priority concept: tier weight, gap severity, and downstream impact to sequence work.  ￼

⸻

7. Business-value attribution metrics

This is where the dashboard becomes credible to leadership.

Business value metric	Formula	Source
MTTR hours saved	Baseline MTTR - current MTTR, multiplied by incident count	Incident system
MTTD hours saved	Baseline MTTD - current MTTD	SignalState, IncidentIndex
Avoided stale dashboard exposure	Time from detection to consumer warning vs prior detection time	Dashboard metadata, freshness signals
False positive toil avoided	Reduced false positives × average triage time	Alert system, incident closure reason
Consumer-impacting incidents prevented	Warnings/quarantine/soft-fails that prevented bad data consumption	Evidence, enforcement mode, consumer logs
Critical assets protected	Tier-1 dashboards/tables with trust score > threshold	Catalog, lineage graph
Engineering toil reduction	Reduction in incident-related Jira/on-call hours	Jira, PagerDuty, sprint labels
Adoption-to-outcome linkage	Score improvement after specific app fixes	Autopilot PRs, readiness score history

The business-value attribution layer should explicitly show: better evidence quality → faster detection → faster RCA → stronger prevention → fewer consumer-impacting incidents → reduced business disruption. This is directly aligned with the agentic onboarding model’s value chain.  ￼

⸻

8. Current-state to target-state progression model

Phase 0 — Unknown trust

Characteristic	Dashboard signal
No dataset inventory	Asset discovery incomplete
No Evidence	Evidence coverage unknown
No ownership confidence	Producer attribution low
Manual RCA	RCA latency high
No business value traceability	No impact measurement

Phase 1 — Visible

Characteristic	Dashboard signal
Dataset URNs registered	DatasetRegistry coverage rising
Evidence emitted	Evidence coverage visible
Freshness and volume baselines	Freshness / volume panels active
Basic owner attribution	Producer confidence visible
Incidents linked to datasets	IncidentIndex populated

Phase 2 — Explainable

Characteristic	Dashboard signal
Contract/schema failures explained	Top failed gates and reason codes
First-bad / last-good boundary	Evidence-backed RCA
Deployment correlation	Deploy_ref coverage
Trace anchors available	trace_id coverage
RCA confidence improves	Inconclusive rate falls

Phase 3 — Impact-aware

Characteristic	Dashboard signal
Dataset and column lineage available	Blast radius coverage
Downstream dashboards identified	Impacted consumers listed
Business impact quantified	Hours saved / dashboards protected
Prioritized remediation	Domain backlog generated

Phase 4 — Preventive trust

Characteristic	Dashboard signal
Mature Tier-1 controls	Progressive gates at G2/G3
Contract and freshness conformance	High trust score
Repeated issues reduced	Recurrence rate down
Pull flywheel active	Teams request better signals
Leadership sees ROI	Value scorecard trend improving

⸻

9. Recommended dashboard pages

Page 1 — Executive Trust Overview

Shows only what leadership needs:

Widget	Purpose
Enterprise Data Trust Score	Overall posture
Tier-1 Trust Coverage	% Tier-1 datasets above trust threshold
MTTD / MTTR trend	Operational improvement
False positive trend	Alert trust improvement
Critical dashboards protected	Business relevance
Top 5 risky domains	Where leadership attention is needed
Value realized	Hours saved, incidents prevented, toil reduced

Page 2 — Domain Health

For domain leaders:

Widget	Purpose
Trust score by domain	Compare Orders, Payments, Finance, Inventory
Tier-1 readiness	Coverage of critical assets
Incident heatmap	Recurring hotspots
Remediation backlog	Ranked actions
SLA/SLO conformance	Freshness, volume, contract, DQ
Adoption progress	Baseline → target progression

Page 3 — Dataset Trust Detail

For data product owners:

Widget	Purpose
Evidence trend	PASS/FAIL by time window
Freshness / volume	Health over time
Contract / schema drift	Correctness issues
DQ and PII	Governance posture
Lineage graph	Upstream/downstream impact
RCA history	Past incidents and causes

Page 4 — Application / Producer Readiness

For engineering teams:

Widget	Purpose
Readiness score	Overall app posture
Weak trust dimensions	Identity, tracing, contract, event_time, lineage
Top failed gates	Exact problem areas
Recommended fixes	Actionable backlog
Autopilot PR status	Open, merged, deferred, reverted
Business impact of fixes	Why team should care

Page 5 — Signal Factory Health

For platform/SRE:

Widget	Purpose
Enforcer lag	Platform health
Evidence latency	Trust timeliness
Evidence completeness	Coverage quality
Signal freshness	Dashboard reliability
Neptune query latency	RCA graph health
Registry / policy store status	Dependency health
Observability pipeline incidents	Avoid misleading users

The platform must monitor its own health because Enforcer down, Evidence Bus unavailable, high consumer lag, Registry unavailable, DynamoDB issues, and Neptune unavailability can all degrade or mislead RCA. The Signal Engine LLD explicitly calls out these failure modes and required behaviors.  ￼

⸻

10. What good looks like

A high-quality dashboard should produce this kind of output for an application team:

Orders Service trust readiness: 64 → target 90.
Main blockers: low trace coverage, missing event_time, incomplete contract definitions, weak column lineage.
Business risk: feeds 3 Tier-1 dashboards and 2 finance pipelines.
Last 30 days: 4 incidents, 2 with inconclusive RCA, 1 schema drift recurrence.
Recommended next actions: add event_time, accept Autopilot PR for OTel propagation, approve contract draft, publish LineageSpec.
Expected impact: reduce freshness false positives, improve RCA confidence from MEDIUM to HIGH, and reduce blast-radius analysis from manual to automated.

For leadership, the same underlying evidence should roll up as:

Orders domain trust improved from 58 to 81 in 8 weeks. MTTR dropped from 11.5 hours to 2.4 hours. False positives dropped from 68% to 27%. 6 Tier-1 dashboards now have freshness and contract coverage. Two consumer-impacting incidents were prevented by early schema drift detection.

That is the narrative that will sustain investment.

⸻

11. Key risks and mitigations

Risk	Why it matters	Mitigation
Dashboard becomes vanity adoption tracker	PR count and SDK count do not prove trust	Use value attribution: MTTD, MTTR, false positives, incidents prevented
Scores hide uncertainty	Teams may overtrust inferred signals	Use trust tiers: inferred, platform-attested, producer-attested
Lineage treated as runtime truth	Stale SCA can mislead RCA	Keep lineage as enrichment, not gate
False positives erode confidence	Teams ignore alerts	Track false positive rate, suppress stale-observability alerts
Observability platform outage misread as data outage	Could create wrong incident routing	Dedicated Signal Factory health page
Tier-1 gaps not prioritized	Effort diffuses across low-value assets	Weight by tier, downstream impact, recurrence, and business criticality
Producers resist changes	Adoption slows	Default zero-change baseline; only targeted light-touch changes for Tier-1/confidence gaps

⸻

12. Final recommendation

Build the dashboard as a trust progression and value attribution system, not as a raw telemetry board.

The right dashboard should show:

1. Current trust baseline — where each dataset/app/domain stands today.
2. Target state — what “trusted” means for Tier-1 data.
3. Evidence-backed health — freshness, volume, contract, schema, DQ, drift, PII.
4. RCA readiness — first-bad/last-good, deploy correlation, trace anchor, lineage blast radius.
5. Application problem areas — exact gaps and recommended fixes.
6. Autopilot remediation progress — targeted PRs, approvals, rollout, regression safety.
7. Business value — MTTD/MTTR reduction, false positive reduction, incidents prevented, dashboards protected, toil reduced.

The strongest operating model is the documented hybrid approach: zero-change baseline for fast coverage, selective light-touch Autopilot for Tier-1/confidence gaps, and mandatory business-value attribution for leadership visibility. That model gives you both adoption speed and trustworthy data outcomes.  ￼