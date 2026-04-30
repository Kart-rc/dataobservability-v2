Below is the metric source model I would use for the dashboard. The key is to avoid “dashboard-only” metrics. Every metric should come from a system of record, have a calculation, have an owner, and have a progress interpretation.

The project already defines the core measurement architecture: Policy Enforcer = record truth, Signal Engines = system health, and RCA Copilot / Neptune = causal explanation. The Evidence Bus is the non-negotiable downstream source for Signal Engines, while Gateway Control Plane owns dataset policies, SLOs, ownership, schema bindings, and resolution rules.  ￼

⸻

1. Source systems for the dashboard

Source system	What it contributes	Used for
Gateway Control Plane	Dataset registry, tier, owner, schema binding, contract, SLOs, producer identity map, resolution rules	Coverage, readiness, ownership, policy completeness
Policy Enforcer	Per-record gate result: resolution, identity, schema, contract, PII, schema fingerprint	Record-level trust, contract failures, drift, reason codes
Evidence Bus	Immutable Evidence events with dataset, producer, validation result, failed gates, reason codes, schema fingerprint, trace_id, topic/partition/offset	Trust score, compliance, RCA boundaries
Signal Engines	Freshness, volume, contract, schema drift, DQ, anomaly, cost signals	System health, incident creation, SLO compliance
DynamoDB State Store	SignalState, IncidentIndex, DatasetRegistry, EvidenceCache	Current health, dashboards, fast RCA lookups
Neptune Graph	Producer, deployment, failure signature, signal, incident, lineage, ownership edges	RCA, blast radius, impact analysis
CI/CD / Deploy Events	Deployment version, commit, repo, timestamp	Deploy correlation, first-bad/last-good RCA
OTel / OpenLineage / SCA LineageSpec	Trace context, job/run lineage, dataset/column lineage, confidence	Trace anchoring, lineage coverage, blast radius
Incident system	Incident open/close timestamps, severity, owner, outcome, false positive labels	MTTD, MTTR, false positive rate, toil
Autopilot / GitHub	PRs opened, merged, reverted, repo scan results, readiness gaps	Adoption progress, remediation progress

The HLD explicitly names these inputs and outputs: raw platform events, Schema Registry events, CI/CD events, Airflow metadata, Spark/Delta commits flow into Evidence, signals, correlation graphs, lineage maps, incidents, RCA explanations, and gate decisions.  ￼

⸻

2. Core trust metrics and sources

Metric	Source of truth	Calculation	Progress assessment
Evidence coverage	Raw Kafka offsets + Evidence Bus	evidence_events_observed / raw_records_observed by topic/window	Improving when Tier-1 topics move toward >95% coverage
Evidence latency	Kafka timestamp + Evidence timestamp	evidence_created_ts - raw_event_ts P50/P95/P99	Target: <2 sec P99
PASS rate	Evidence Bus	PASS evidence / total evidence	Should trend up, but must be interpreted with gate strictness
Failed gate rate	Evidence Bus	failed_gate_count / total evidence by gate	Progress means failures move from UNKNOWN/RESOLUTION to specific actionable reasons
Contract compliance	Evidence Bus + Contract Signal Engine	contract_pass_count / contract_evaluated_count per dataset/window	Target set by dataset contract, often 95%+ for Tier-1
Schema drift rate	Policy Enforcer schema fingerprint + Schema Drift Engine	Count of new schema fingerprints or incompatible fingerprint changes	Good progress means drift is detected earlier and linked to deploys
PII violation rate	PII Gate Evidence	PII_FAIL / total evidence	Should trend toward zero for datasets with strict policies
Freshness compliance	Freshness Engine + Dataset SLOs	% windows where last valid evidence is within freshness SLO	Tier-1 should meet 15-min freshness SLO
Volume stability	Volume Engine	Deviation from baseline; drops/spikes per dataset/window	Progress means fewer unexplained drops/spikes and better baselines
DQ compliance	DQ Evidence / Deequ results + DQ Engine	DQ rules passed / DQ rules evaluated	Progress means more Tier-1 datasets have DQ rules and pass rates improve

The Enforcer produces the record-level truth through gates for resolution, identity, schema, contract, and PII; the Signal Engines then compute freshness, volume, contract, drift, DQ, anomaly, and cost signals from Evidence.  ￼

⸻

3. RCA and incident metrics

Metric	Source of truth	Calculation	Progress assessment
MTTD	Evidence first-bad timestamp + Incident created timestamp	incident_created_ts - first_bad_evidence_ts	Target: <15 minutes for Tier-1
MTTR	Incident system	incident_resolved_ts - incident_created_ts	Target: <2 hours
RCA query latency	RCA Copilot logs + Neptune/DynamoDB telemetry	rca_answer_ts - rca_query_ts	Target: <2 minutes
Evidence-backed RCA rate	RCA output + Evidence references	% incidents with evidence_ids and first-bad/last-good boundary	Should trend toward >90% for Tier-1
Deploy correlation coverage	CI/CD deploy events + Evidence/IncidentIndex	% incidents with correlated deployment/ref	Should trend upward; missing deploy_ref becomes app backlog
Trace anchor coverage	Evidence otel.trace_id + OTel spans	% evidence or incidents with trace_id/span_id	Tier-1 should trend toward >90%
Blast-radius availability	Neptune + lineage graph	% incidents with impacted downstream assets listed	Improves as lineage coverage improves
RCA confidence distribution	RCA Copilot output	HIGH/MEDIUM/LOW/INCONCLUSIVE split	Progress means HIGH increases, INCONCLUSIVE decreases
False positive alert rate	Incident closure labels + alert system	false_positive_alerts / total_alerts	Target: <20%
Recurring failure signature rate	Neptune FailureSignature + IncidentIndex	Repeated incidents with same failure signature	Should decrease after remediation

The deck’s steel-thread example shows the intended RCA chain: failed Evidence events aggregate into a contract breach, Neptune captures Deployment → FailureSignature → Signal → Incident, and RCA identifies root cause, blast radius, confidence, and recommended action.  ￼

⸻

4. Lineage and impact metrics

Metric	Source of truth	Calculation	Progress assessment
Dataset-level lineage coverage	Neptune + OpenLineage + SCA LineageSpec	Tier-1 datasets with upstream/downstream edges / total Tier-1 datasets	Target: 100% Tier-1
Column-level lineage coverage	SCA LineageSpec + OpenLineage column facets + Neptune	Tier-1 columns with READS_COL/WRITES_COL edges / total Tier-1 columns	Progress means blast radius becomes field-specific
Lineage freshness	Deployed commit + LineageSpec commit	% deployed producers with matching recent LineageSpec	Stale lineage should become visible risk
Lineage confidence	LineageSpec confidence fields	HIGH/MED/LOW distribution	Progress means LOW-confidence lineage decreases
Blast-radius precision	RCA output + postmortem confirmation	% predicted impacted assets confirmed	Measures usefulness, not just coverage
Consumer impact visibility	Neptune + catalog/dashboard metadata	Count of downstream DAGs, tables, dashboards per incident	Progress means each incident has clear impacted consumers

Lineage should be treated as RCA enrichment, not as a runtime gate. Runtime Evidence answers what happened; lineage answers who is impacted. The component decomposition includes a dedicated Lineage Ingestor and Neptune/DynamoDB stores for this knowledge-plane role.  ￼

⸻

5. Application readiness metrics

This is what each application team should see.

Readiness dimension	Source	Metric	Progress signal
Dataset resolution readiness	Gateway Control Plane	% produced topics mapped to dataset_urn	Moves from unknown → mapped → approved
Producer identity confidence	Enforcer + Producer Identity Map	HIGH/MED/LOW identity confidence	Move from topic fallback to trusted producer identity
Contract readiness	Contract registry / ODCS files	% datasets with active contract	Tier-1 should reach >95%
Schema readiness	Glue Schema Registry + Control Plane	% topics with registered schema binding	Reduces schema UNKNOWN/WARN cases
Timestamp readiness	Evidence payload metadata	% events with event_time and processing_time	Enables reliable freshness
Trace readiness	OTel + Evidence trace_id	% records/incidents with trace anchors	Enables deterministic causality
DQ readiness	DQ rule registry / Deequ	% Tier-1 datasets with minimum DQ checks	Moves from freshness-only to correctness coverage
Deploy correlation readiness	CI/CD events	% deploys emitting DeploymentEvent	Enables first-bad to deploy correlation
Runbook readiness	Service catalog / Control Plane	% Tier-1 datasets with runbook_ref	Improves response quality
Autopilot remediation progress	GitHub + Autopilot	PR open/merged/reverted + gap closure	Measures whether gaps are being fixed safely

The Autopilot enablement document defines readiness scoring around trace anchor coverage, identity confidence, deploy correlation coverage, and policy completeness, and uses that score to drive targeted backlog items.  ￼

⸻

6. Platform health metrics

These are required so teams do not mistake an observability outage for a data outage.

Metric	Source	Calculation	Progress / target
Enforcer lag	Kafka consumer lag / Enforcer metrics	Lag seconds by raw topic	Alert if >30 sec
Evidence rate	Evidence Bus	Evidence events/sec by dataset/topic	Alert if drops >50% unexpectedly
Signal freshness	Signal Engine state	now - last_signal_computed_ts	Target: <5 minutes; alert if >10 minutes
Neptune query latency	Neptune telemetry	P95/P99 query latency	Alert if P99 >5 sec
Evidence DLQ rate	Evidence Bus DLQ	malformed evidence / total evidence	Should trend near zero
Registry / Control Plane availability	Service metrics	availability, error rate, cache hit rate	Should support >99.5% platform availability
Platform availability	Component SLO rollup	uptime of Enforcer, Evidence Bus, Engines, stores	Target: >99.5%

The HLD calls out observability-of-observability signals such as Enforcer lag, Evidence rate, Signal freshness, and Neptune query latency, and defines failure modes for Enforcer, Registry, lag spikes, Neptune, and LLM failures.  ￼

⸻

7. Business-value metrics

Metric	Source	Calculation	How to assess progress
MTTR hours saved	Incident system	(baseline MTTR - current MTTR) × incident count	Convert reliability improvement into engineering hours saved
MTTD hours saved	Evidence + incident timestamps	(baseline MTTD - current MTTD) × incident count	Shows earlier detection value
False-positive toil avoided	Alert outcomes + incident labels	false positives reduced × average triage time	Shows alert quality improvement
Incidents prevented	Evidence warnings, soft-fail/hard-fail gates, downstream impact	Count cases where issue detected before consumer impact	Strongest leadership ROI metric
Dashboards protected	Catalog + lineage + freshness/contract status	Count of Tier-1 dashboards with trusted upstreams	Connects platform work to business consumers
Developer toil reduction	Jira/on-call time/sprint allocation	Baseline incident toil - current incident toil	Target: reduce from 20% sprint velocity to <5%
Adoption-to-impact linkage	Autopilot PRs + readiness score + incident trend	Score improvement after specific app fixes	Proves remediation is changing outcomes

The pitch deck frames the leadership outcomes as ROI visibility, faster incident resolution, higher trust, and team efficiency; it also sets the current pain at 12+ hour MTTR, 60–80% false positives, 20% sprint velocity lost, and 0% element-level lineage.  ￼

⸻

8. How to assess progress

Use four levels of progress, not a single green/red score.

Level 1 — Coverage progress

Measures whether the platform can see the estate.

Question	Example metric
Are Tier-1 datasets registered?	% Tier-1 datasets in DatasetRegistry
Are raw events producing Evidence?	Evidence coverage
Are owners mapped?	% datasets with owner/team
Are SLOs defined?	% Tier-1 datasets with freshness/volume/contract SLOs

This is the first 30-day proof point.

⸻

Level 2 — Quality progress

Measures whether the signals are useful.

Question	Example metric
Are failed gates specific?	Top reason codes populated
Are contract/schema failures detected?	Contract and drift signal rates
Are freshness/volume baselines stable?	False positive rate decreasing
Is signal freshness good?	Signal computed within 5 minutes

This is the 30–60 day proof point.

⸻

Level 3 — RCA progress

Measures whether incidents become explainable.

Question	Example metric
Can we find first-bad/last-good?	Evidence-backed boundary rate
Can we correlate to deploys?	Deploy correlation coverage
Can we identify impacted assets?	Blast-radius availability
Is RCA fast enough?	RCA query latency <2 min
Is RCA trusted?	Inconclusive RCA rate decreasing

This is the 60–90 day proof point.

⸻

Level 4 — Business progress

Measures whether the program is worth the investment.

Question	Example metric
Are incidents detected earlier?	MTTD trend
Are incidents resolved faster?	MTTR trend
Are teams wasting less time?	Toil trend
Are bad/stale dashboards reduced?	Consumer-impacting incident trend
Are teams adopting because they see value?	Pull requests from app teams / voluntary adoption

This is the leadership-level success measure.

⸻

9. Recommended baseline and target cadence

Time window	What to measure	Expected outcome
Weeks 1–4: G0 Visibility	Dataset registry, Evidence coverage, basic freshness/volume, raw gap scan	Establish current baseline
Weeks 5–8: G1 Warn	Missing contracts, URNs, owner gaps, schema drift, readiness score	Create app-specific backlog
Weeks 9–12: G2 Soft-Fail for Tier-1	RCA coverage, deploy correlation, blast radius, false positives	Prove Tier-1 operational value
Week 13+: G3 Hard-Fail for Tier-1	Prevention, policy conformance, incidents prevented	Move from detection to prevention

The HLD’s progressive gate strategy follows this exact path: G0 visibility in weeks 1–4, G1 warn in weeks 5–8, G2 soft-fail in weeks 9–12 for Tier-1, and G3 hard-fail after week 13 for Tier-1.  ￼

⸻

10. The practical dashboard model

For each metric, store this metadata:

metric_name
metric_owner
source_system
source_table_or_topic
calculation
baseline_value
current_value
target_value
trend_7d
trend_30d
confidence
freshness_age
business_owner
remediation_action

Example

Metric: Tier-1 Evidence Coverage
Source: Kafka raw topic offsets + signal_factory.evidence
Calculation: evidence_events / raw_events by dataset_urn per 5-min window
Baseline: 42%
Current: 81%
Target: >95%
Trend: +12% over 30 days
Confidence: HIGH
Freshness: 4 minutes
Owner: Platform Core + Domain Data Owner
Next action: Add missing resolution rules for 7 topics

⸻

11. Final recommendation

Use this hierarchy:

1. Source metrics from systems of record, not manually maintained dashboards.
2. Calculate progress as baseline → current → target, with 7-day and 30-day trends.
3. Show confidence for each metric, especially inferred identity, inferred lineage, and RCA.
4. Separate adoption from value: onboarding, PRs, and SDKs are not success unless MTTD, MTTR, false positives, RCA confidence, and incidents prevented improve.
5. Force every red metric to create a backlog item: missing contract, missing event_time, weak identity, stale lineage, no deploy_ref, no runbook, or high false positives.

The best leadership view is not “how many teams onboarded.” It is: how much more of our critical data estate is trusted, explainable, and protected than it was last month.