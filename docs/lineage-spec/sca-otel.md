Below is an improved proposal that keeps the strengths of your current design, fixes the critical gaps, and explains both the current state and the future state with concrete examples so engineers can see exactly how the system should work.

Your existing architecture already has the right base principles: out-of-band enforcement, evidence as runtime truth, bounded graph writes, immutable LineageSpec, deployment linkage, and lineage as RCA enrichment rather than a gate. That should remain unchanged.  ￼  ￼

⸻

Improved OTel + SCA Proposal for Element-Level Lineage

1. Executive summary

Recommendation

Adopt an improved federated, confidence-scored, deploy-aware element-level lineage architecture that combines:
	•	SCA for design-time read/write intent
	•	OTel for runtime causality and executed path correlation
	•	OpenLineage / plan lineage for Spark and declarative execution substrates
	•	a Lineage Ingestor + Knowledge Plane for normalized topology and blast-radius traversal
	•	a new Fusion Layer that joins runtime facts to the correct static lineage version
	•	a new Verification Loop for high-value paths so the platform does not overclaim certainty

What changes from the current proposal

The current proposal is already good at saying:
	•	what likely changed
	•	which consumers are likely impacted
	•	which deployment is likely related

But it is still too implicit about:
	•	how SCA and OTel are joined
	•	how time/version mismatches are handled
	•	how confidence should be computed and decayed
	•	how the system detects stale or wrong lineage
	•	how service and column identities are normalized

The improved design adds those missing layers without violating the core out-of-band model.  ￼  ￼

⸻

2. What remains true from the current architecture

The existing architecture should stay intact.

Runtime truth remains out-of-band

The Enforcer still determines:
	•	dataset identity
	•	schema drift
	•	contract-lite violations
	•	pass/fail evidence
	•	first-bad / last-good boundaries

Lineage still does not participate in gate decisions. That separation is correct and should remain non-negotiable.  ￼  ￼

The current strength

Today’s proposal already supports this flow:
	1.	producer emits raw event
	2.	Enforcer validates and emits Evidence
	3.	Signal Engines create incident
	4.	RCA queries topology + lineage for impact
	5.	Copilot explains likely blast radius

That is already a strong RCA-enrichment model.  ￼  ￼

⸻

3. Current state: how the approach works today

3.1 Conceptual model today

SCA provides
	•	input/output datasets
	•	input/output columns
	•	transform hints
	•	commit-linked lineage spec
	•	confidence and coverage metadata  ￼  ￼

OTel provides
	•	service.name
	•	spans and operations that actually executed
	•	runtime causal path across boundaries
	•	propagation across services when present  ￼  ￼

Knowledge plane provides
	•	bounded Neptune topology
	•	lookup indexes in DynamoDB
	•	deployed version linkage
	•	RCA traversal entry points  ￼  ￼

3.2 Current-state example

Scenario

order-service deploys a breaking change and stops emitting payment_method.

What happens today

Step 1: runtime detection
Enforcer sees an event missing payment_method.

It computes:
	•	schema_fingerprint_prev = A1B2
	•	schema_fingerprint_curr = C9D8
	•	reason_code = FIELD_REMOVED:payment_method

This happens entirely in the Enforcer, independent of lineage.  ￼

Step 2: incident creation
Signal Engines detect the drift / contract breach and create an incident against urn:dp:orders:order_created:v1.  ￼

Step 3: lineage-assisted RCA
RCA queries the graph and finds:
	•	orders-delta-landing reads payment_method
	•	payment_method_norm downstream depends on it
	•	revenue-kpi-dashboard depends on curated output

So the incident page can say:
	•	what changed: payment_method removed
	•	where: upstream producer path
	•	what is impacted: landing job, curated dataset, dashboard
	•	mitigation: rollback or hotfix consumer handling  ￼  ￼

3.3 Why the current state is still incomplete

Today the graph can answer “who likely depends on this field,” but the join between:
	•	the exact runtime path that executed,
	•	the exact deployment version,
	•	and the exact static lineage spec

is still too loose.

That creates the false-precision risk already identified in your own assessment.  ￼

⸻

4. Future state: the improved architecture

4.1 Design goals

The future-state system should answer five questions reliably:
	1.	What actually happened at runtime?
	2.	Which deployed code version executed?
	3.	Which static lineage spec matches that deployed code?
	4.	How confident are we in the element-level mapping?
	5.	Has runtime behavior drifted away from design-time lineage?

4.2 New components added

The improved design adds four explicit capabilities:

A. Fusion Contract

A formal join model between runtime evidence and static lineage.

B. Canonical Identity Layer

A single normalization layer for service, dataset, deployment, and column identities.

C. Confidence Engine

A multi-factor score, not just HIGH/MEDIUM/LOW from SCA.

D. Verification Loop

A lightweight runtime verification mechanism for Tier-1 and ambiguous paths.

⸻

5. Improved target architecture

5.1 High-level flow

Current state

SCA -> LineageSpec -> Graph
and
OTel -> Trace -> RCA

Future state

SCA -> LineageSpec -> Fusion Layer <- OTel/Deployment/Evidence
then
Fusion Layer -> Verified/Ranked lineage context -> RCA

The key change is that SCA and OTel are no longer “both present”; they are explicitly reconciled.

⸻

6. Detailed future-state architecture

6.1 Step 0: canonical identity foundation

Before fusion works reliably, all IDs must normalize into canonical forms.

Required canonical IDs

Producer identity
producer_urn = urn:producer:<domain>:<service_or_job>

Dataset identity
dataset_urn = urn:dp:<domain>:<dataset>:v<major>

Column identity
Use two forms:
	•	human-readable column_urn = urn:col:<dataset_urn>:<column_path>
	•	stable column_id = uuid for rename-safe Tier-1 lineage

Deployment identity
deployment_urn = urn:deploy:<producer_urn>:<artifact_version_or_sha>

Why this is required

OTel service.name can default to unknown_service if not set explicitly, and resources need consistent naming for reliable correlation.  ￼

Example

Without normalization:
	•	orders-svc
	•	order-service
	•	svc:orders
	•	orders-prod-v3

With normalization:
all aliases map to:
urn:producer:orders:order-service

Engineering action

Build a Producer Identity Registry:
	•	canonical producer URN
	•	aliases
	•	service.name mappings
	•	repo mapping
	•	deployment mapping
	•	team ownership

This should sit in the Control Plane, not in ad hoc code.

⸻

6.2 Step 1: SCA emits a richer LineageSpec

The current LineageSpec is a good start. It now needs stronger required fields.

New required fields
	•	lineage_spec_id
	•	producer_urn
	•	deployment_ref.commit_sha
	•	build_artifact_id
	•	operation_ids[] or function/method identifiers
	•	dataset_urns
	•	column_ids for Tier-1
	•	confidence.extraction
	•	coverage
	•	opaque_regions[]
	•	dynamic_behavior_flags[]

Example

{
  "spec_version": "2.0",
  "lineage_spec_id": "lspec:urn:producer:orders:orders-enricher:git:9f31c2d",
  "producer_urn": "urn:producer:orders:orders-enricher",
  "deployment_ref": {
    "commit_sha": "9f31c2d",
    "artifact_id": "orders-enricher:2026.04.08.1"
  },
  "operations": [
    {
      "operation_id": "orders.process_order",
      "code_ref": "src/service/orders.py#process_order"
    }
  ],
  "lineage": {
    "inputs": [
      {
        "dataset_urn": "urn:dp:orders:order_created:v1",
        "columns": [
          {
            "column_id": "col-001",
            "column_urn": "urn:col:urn:dp:orders:order_created:v1:payment_method"
          }
        ]
      }
    ],
    "outputs": [
      {
        "dataset_urn": "urn:dp:orders:order_enriched:v1",
        "columns": [
          {
            "column_id": "col-987",
            "column_urn": "urn:col:urn:dp:orders:order_enriched:v1:payment_method_norm"
          }
        ]
      }
    ]
  },
  "confidence": {
    "extraction": "MEDIUM",
    "reasons": ["STATIC_AST", "REFLECTION_DETECTED"]
  },
  "coverage": {
    "input_columns_pct": 0.91,
    "output_columns_pct": 0.74
  },
  "opaque_regions": ["serializer.payment_transform"]
}

Why this helps

It makes the static side explicit enough to join to runtime operations, not just repo or commit.

⸻

6.3 Step 2: OTel emits runtime execution facts that are lineage-relevant

OTel should not be overloaded with lineage truth, but it should emit enough runtime context to support fusion.

Required runtime facts
	•	service.name
	•	deployment.version
	•	operation.id or standardized span name
	•	trace_id
	•	span_id
	•	span.links[] for fan-in/fan-out and retries
	•	messaging.message.id or equivalent event key
	•	environment / region
	•	config bundle or feature flag snapshot hash for Tier-1

Important guardrail

Use OTel for runtime correlation, not for raw lineage semantics. Context propagation is what lets signals correlate across boundaries, but it does not itself prove column lineage.  ￼

Example

{
  "service.name": "orders-enricher",
  "deployment.version": "2026.04.08.1",
  "operation.id": "orders.process_order",
  "trace_id": "abc123...",
  "span_id": "def456...",
  "message.id": "kafka:raw.orders.events:4:9918273",
  "feature_config_hash": "cfg-2281"
}

Guardrail on baggage and headers

Do not put sensitive or rich lineage semantics into baggage. Baggage is propagated context and can carry arbitrary data, so it should be tightly restricted.  ￼

⸻

6.4 Step 3: Deployment system emits richer DeploymentEvent

The deployment event must become a first-class join artifact.

Required fields
	•	producer_urn
	•	deployment_urn
	•	commit_sha
	•	artifact_id
	•	deploy_time
	•	environment
	•	feature_flag_set_hash
	•	config_bundle_hash

Example

{
  "producer_urn": "urn:producer:orders:orders-enricher",
  "deployment_urn": "urn:deploy:urn:producer:orders:orders-enricher:2026.04.08.1",
  "commit_sha": "9f31c2d",
  "artifact_id": "orders-enricher:2026.04.08.1",
  "deploy_time": "2026-04-08T10:00:00Z",
  "environment": "prod",
  "feature_flag_set_hash": "ff-18A",
  "config_bundle_hash": "cfg-2281"
}

Why this matters

Commit SHA alone is not enough. The effective runtime state also depends on config and feature flags.

⸻

6.5 Step 4: introduce the Fusion Layer

This is the biggest improvement.

Purpose

The Fusion Layer decides:
“Which lineage spec should be trusted for this runtime incident?”

Fusion inputs
	•	Evidence event
	•	DeploymentEvent
	•	OTel span data
	•	LineageSpec
	•	Control Plane identities

Fusion join keys

Ranked in this order:
	1.	producer_urn
	2.	deployment_urn or artifact ID
	3.	commit_sha
	4.	operation.id
	5.	dataset_urn
	6.	time_validity
	7.	config / feature flag match

Fusion output

A FusedLineageContext object:

{
  "incident_id": "INC-2026-04-08-001",
  "producer_urn": "urn:producer:orders:orders-enricher",
  "matched_lineage_spec_id": "lspec:...:9f31c2d",
  "join_confidence": "HIGH",
  "runtime_match": {
    "deploy_match": true,
    "operation_match": true,
    "config_match": true
  },
  "effective_lineage_confidence": 0.89
}

Example

Current state
RCA sees:
	•	producer deploy near incident time
	•	SCA spec from same commit
	•	likely mapping from payment_method -> payment_method_norm

Future state
Fusion Layer confirms:
	•	same producer URN
	•	exact deployment artifact
	•	exact operation orders.process_order
	•	same config bundle hash

Only then does RCA present the field dependency as strong evidence.

⸻

6.6 Step 5: improve confidence scoring

The current confidence model is useful but too coarse.  ￼

New confidence dimensions

Extraction confidence
How well SCA or plan lineage resolved the mapping.

Join confidence
How well runtime facts match the static spec.

Runtime corroboration confidence
Whether lightweight runtime verification supports the static mapping.

Recency confidence
Whether the matching spec is current relative to the incident time.

Example formula

overall_confidence =
  0.35 * extraction_confidence +
  0.30 * join_confidence +
  0.25 * runtime_corroboration +
  0.10 * recency_confidence

Example

A service path with reflection:
	•	extraction = 0.55
	•	join = 0.95
	•	runtime corroboration = 0.70
	•	recency = 1.0

overall = 0.74

That should be shown as “medium-high confidence,” not blindly “HIGH.”

⸻

6.7 Step 6: add verification loop for Tier-1 paths

This is the most important new operational addition.

Purpose

Detect when design-time lineage and runtime behavior drift apart.

What to verify

Not full per-record lineage.
Only lightweight verification signals such as:
	•	field presence sketches
	•	schema fingerprint deltas
	•	sampled field-set signatures
	•	sampled input/output dependency hints for approved paths
	•	contradiction signals

Example

Static lineage says:
payment_method_norm <- payment_method

Runtime verification sees:
after deployment, payment_method disappears but payment_method_norm still appears due to fallback from payment_instrument.type

That does not mean the system should derive full runtime lineage, but it does mean:
	•	static mapping is now stale
	•	confidence should decay
	•	RCA should say “static lineage contradicted by observed runtime behavior”

Output example

{
  "lineage_spec_id": "lspec:...:9f31c2d",
  "verification_status": "CONTRADICTED",
  "contradiction_reason": "Output field present while declared source field absent",
  "confidence_penalty": 0.25
}


⸻

6.8 Step 7: add lineage drift detection

Purpose

Flag stale or diverged lineage even when incidents are not yet severe.

Drift types
	•	deployment drift: runtime uses newer deploy than latest spec
	•	config drift: spec matched deploy, but config differs
	•	field drift: expected source field no longer observed
	•	shape drift: nested path move or rename
	•	confidence drift: repeated contradictions lower trust

Example

Over 24 hours:
	•	8 incidents reference payment_method
	•	6 runtime samples contradict static source mapping
	•	no refreshed SCA spec exists

Action:
	•	mark affected edges stale
	•	open lineage refresh task
	•	RCA continues, but with degraded confidence banner

⸻

6.9 Step 8: enrich graph semantics

The graph should store more than just READS and WRITES.

OpenLineage column lineage already distinguishes direct and indirect lineage and includes transformation semantics. Your graph should borrow those semantics for ranking.  ￼

New edge properties
	•	type = DIRECT | INDIRECT
	•	transformation_subtype = FILTER | JOIN | AGGREGATION | TRANSFORMATION | SORT | WINDOW
	•	masking = true|false
	•	valid_from
	•	valid_to
	•	confidence
	•	verification_status
	•	spec_id

Example

orders-delta-landing READS_COL payment_method
could be:
	•	DIRECT, if used to derive payment_method_norm
	•	INDIRECT, if only used in a filter

That difference should affect blast-radius ranking.

⸻

7. End-to-end future-state example

Scenario

A Tier-1 incident occurs in the orders domain.

Upstream order-service deploys and removes payment_method.
Downstream:
	•	orders-enricher service
	•	orders-delta-landing Spark job
	•	revenue-kpi-dashboard

Step-by-step

Step 1: build time

SCA analyzes orders-enricher and emits LineageSpec v2.0.

It declares:
	•	operation orders.process_order
	•	input column payment_method
	•	output column payment_method_norm
	•	extraction confidence 0.62
	•	opaque region in serializer

Step 2: deployment

CI/CD emits:
	•	DeploymentEvent for orders-enricher:2026.04.08.1
	•	commit SHA 9f31c2d
	•	config hash cfg-2281

Step 3: runtime execution

A request flows through the service.

OTel emits:
	•	service.name=orders-enricher
	•	deployment.version=2026.04.08.1
	•	operation.id=orders.process_order
	•	trace and message IDs

Step 4: Enforcer detects break

Incoming payload missing payment_method.

Evidence emitted:

{
  "dataset_urn": "urn:dp:orders:order_created:v1",
  "reason_code": "FIELD_REMOVED:payment_method",
  "schema_fingerprint_prev": "A1B2",
  "schema_fingerprint_curr": "C9D8",
  "trace_id": "abc123..."
}

Step 5: Signal Engine creates incident

Incident INC-2026-04-08-001 is created.

Step 6: Fusion Layer matches lineage

Fusion Layer joins:
	•	producer URN
	•	deployment version
	•	operation ID
	•	config hash
	•	trace timing

It finds the correct static spec and computes:
	•	extraction confidence = 0.62
	•	join confidence = 0.97
	•	runtime corroboration = 0.68
	•	recency = 1.0
	•	overall = 0.77

Step 7: verification loop runs

Sampled runtime check observes:
	•	output field payment_method_norm still appears
	•	source field payment_method absent
	•	fallback path using payment_instrument.type likely active

Verification flags contradiction.

Overall confidence drops to 0.58.

Step 8: RCA output

RCA Copilot says:
	•	Observed fact: upstream field payment_method removed
	•	Strongly impacted: orders-delta-landing@2026.04.08.1 reads payment_method directly
	•	Potentially impacted: orders-enricher@2026.04.08.1 previously mapped payment_method -> payment_method_norm, but runtime contradiction suggests fallback logic
	•	Downstream impact: revenue-kpi-dashboard depends on curated payment_method_norm
	•	Recommended mitigation: rollback upstream producer or patch consumers; refresh lineage for orders-enricher

This is much stronger than today because the system:
	•	separates hard runtime truth from lineage intent
	•	shows where lineage is contradicted
	•	avoids false precision

⸻

8. Implementation plan

Phase 1: harden current state

Goal: make the existing proposal reliable before adding verification.

Deliverables
	•	canonical producer identity registry
	•	stable dataset and deployment URNs
	•	mandatory service.name policy
	•	LineageSpec v2.0
	•	deployment event hardening

Example outcome

The system can say:
“this incident matches this deployed producer and this lineage spec”

but not yet:
“runtime corroboration confirms the static mapping”

⸻

Phase 2: Fusion Layer

Goal: move from coexistence to actual fusion.

Deliverables
	•	FusedLineageContext schema
	•	join logic and precedence rules
	•	time-valid spec selection
	•	join confidence scoring

Example outcome

Two specs exist for same producer on different days.
RCA selects the deployed version closest to incident time, not “latest.”

That aligns with the existing per-deploy lineage principle already captured in your docs.  ￼

⸻

Phase 3: Verification loop for Tier-1

Goal: reduce false precision.

Deliverables
	•	field-set signature sampling
	•	contradiction detection
	•	confidence decay rules
	•	stale lineage alerting

Example outcome

Service path with dynamic fallback no longer looks “high confidence” just because SCA found one path.

⸻

Phase 4: graph semantics and ranking

Goal: improve RCA quality and blast-radius ranking.

Deliverables
	•	direct vs indirect edge semantics
	•	transformation subtype support
	•	verification status on edges
	•	ranking model for impacted consumers

Example outcome

A direct derivation path outranks an indirect filter dependency during RCA.

⸻

9. What engineers need to internalize

9.1 What the system can prove

Hard truth

From Enforcer / Evidence:
	•	schema changed
	•	field missing
	•	first-bad / last-good
	•	deploy timing correlation

Confidence-scored truth

From fusion:
	•	likely code path
	•	likely field mapping
	•	likely impacted consumers

Verified truth

Only for selected paths where runtime verification supports the static mapping.

9.2 What the system should never do
	•	never let lineage influence gate pass/fail
	•	never treat LOW confidence as truth
	•	never assume latest spec is the right spec
	•	never rely on raw service.name strings without normalization
	•	never write per-record lineage to Neptune
	•	never stuff rich lineage semantics into baggage

⸻

10. Definition of done for the improved proposal

The improved OTel + SCA approach is ready when:
	1.	every Tier-1 producer has canonical producer and deployment identity
	2.	LineageSpec v2.0 is emitted per deployment
	3.	Fusion Layer selects lineage spec by deploy + operation + time
	4.	RCA shows extraction confidence, join confidence, and overall confidence
	5.	Tier-1 service paths have runtime contradiction detection
	6.	graph edges support direct/indirect semantics
	7.	stale lineage decays instead of remaining silently trusted
	8.	engineers can explain, for any incident:
	•	hard runtime fact
	•	matched static lineage
	•	confidence level
	•	whether runtime verification supported or contradicted the lineage

⸻

11. Final recommendation

Keep the current architecture’s strongest principle:

runtime truth remains out-of-band and deterministic; lineage remains asynchronous and non-blocking.

But upgrade the proposal from:
	•	“SCA and OTel both exist”
to
	•	“runtime evidence, deployment facts, and static lineage are explicitly fused, confidence-scored, and selectively verified.”

That is the version of the proposal I would put in front of engineering and leadership.

It gives you:
	•	realistic element-level lineage for enterprise scale
	•	lower false precision
	•	stronger MTTR improvement
	•	clearer implementation steps
	•	and a path from RCA-grade lineage to selectively verified lineage over time

The external standards support this split: OpenTelemetry is the right mechanism for runtime correlation and context propagation, but not by itself lineage proof; OpenLineage gives a richer model for direct/indirect and transformation-aware column lineage that your graph should adopt for ranking semantics.  ￼

If you want, the next step should be to turn this into a full engineering design doc with:
	•	component interfaces,
	•	JSON schemas,
	•	sample DynamoDB and Neptune models,
	•	and one steel-thread sequence diagram end to end.