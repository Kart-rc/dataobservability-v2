hi Below is an improved proposal that keeps the strengths of your current design, fixes the critical gaps, and explains both the current state and the future state with concrete examples so engineers can see exactly how the system should work.

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
	•	and one steel-thread sequence diagram end to end


It should happen in both places, but not for the same purpose.

Design time is where you create the candidate lineage map.
Runtime is where you decide which candidate actually applies to this execution/incident.

That separation matches your current architecture: SCA emits immutable LineageSpec artifacts during build/deploy, while runtime remains Enforcer → Evidence → Signal Engines, with lineage consulted later for RCA enrichment, not gate evaluation.  ￼  ￼  ￼

The clean answer

1. Design-time fusion does not happen

At design time, there is no true “fusion” yet.

What happens at design time is:
	•	SCA analyzes code
	•	emits LineageSpec
	•	records dataset/column read-write intent
	•	attaches commit/build metadata
	•	publishes it to the knowledge plane asynchronously  ￼  ￼

So design time gives you:
	•	“this code version should read these fields”
	•	“this code version should write these fields”

That is intent, not runtime proof.  ￼

2. Runtime fusion does happen

The actual fusion decision should happen at runtime / incident analysis time.

That is when you have:
	•	the record-level Evidence
	•	the trace/span context from OTel
	•	the deployed version
	•	the matching LineageSpec
	•	the failure signature

Then the system can say:
	•	this record failed at runtime
	•	this service/span/operation executed
	•	this deployed version was active
	•	the matching SCA spec for that deployed version says output field Y depends on input field X

That is the real fusion.  ￼  ￼

⸻

How OTel works if it happens for each record

This is the subtle part:

OTel is not extracting element-level lineage for each record.
It is extracting runtime execution context per request/message/operation.

That context is then used to select or strengthen the right static lineage spec.

OTel context propagation is meant to correlate work across services and processes by carrying trace and span identifiers across boundaries.  ￼

What OTel contributes per record/message

For a given message or request, OTel can give you:
	•	trace_id
	•	span_id
	•	service.name
	•	operation/span name
	•	parent-child or linked causal relationship
	•	deployment/version attributes if you attach them
	•	message metadata if instrumented

OTel context propagation lets the downstream service correlate that work with upstream work across boundaries.  ￼

What OTel does not give you per record

It does not directly say:
	•	field payment_method_norm came from field payment_method
	•	output column A derives from input column B

That is why SCA is still needed for services. Your own docs already say OTel alone gives runtime causality, not field-level transformation mapping.  ￼

⸻

The right mental model

Think of it like this:

SCA says

“Here are the possible field mappings this code version can perform.”

OTel says

“This exact path of code actually ran for this request/message.”

Fusion says

“For this incident, use the lineage spec for the deployed version and executed operation.”

⸻

End-to-end example

Scenario

order-service publishes an order event.

Event 9918273 is missing payment_method.

Downstream orders-enricher processes it.

Step 1: design time

SCA analyzes orders-enricher build 9f31c2d and emits:
	•	input dataset: urn:dp:orders:order_created:v1
	•	input field: payment_method
	•	output dataset: urn:dp:orders:order_enriched:v1
	•	output field: payment_method_norm
	•	operation: orders.process_order

That spec is stored asynchronously in Neptune/Dynamo as design-time intent.  ￼  ￼

Step 2: deployment time

CI/CD emits:
	•	deployment: orders-enricher@2026.01.16.1
	•	commit: 9f31c2d

This gives the join from deployed code to lineage spec.  ￼  ￼

Step 3: runtime record processing

For record 9918273, OTel instrumentation on orders-enricher emits:
	•	trace_id = abc123
	•	service.name = orders-enricher
	•	operation = orders.process_order
	•	deployment version attribute
	•	maybe message metadata like topic/partition/offset if attached

That is per record/message execution context.

Step 4: Enforcer detects the actual issue

The Enforcer independently determines:
	•	field missing: payment_method
	•	schema fingerprint changed
	•	contract-lite failed

This still happens without lineage.  ￼

Step 5: fusion at RCA time

Now RCA has:
	•	runtime evidence: FIELD_REMOVED:payment_method
	•	runtime execution context: orders-enricher, orders.process_order, trace abc123
	•	deployed version: 2026.01.16.1
	•	matching SCA spec: commit 9f31c2d

So the system can say:
	•	the failing record flowed through orders.process_order
	•	that deployed version’s lineage spec says payment_method_norm depends on payment_method
	•	therefore orders-enricher is a likely impacted consumer

That is the fusion.

⸻

Why not fuse fully at design time

Because design time cannot know:
	•	which branch actually executed
	•	which feature flags were active
	•	which async path ran
	•	whether retries or fan-out changed the path
	•	which deployment version was active at incident time

That is why design-time only gives candidate mappings.

⸻

Why not do full per-record lineage at runtime

Because that would be too heavy and violates your current architecture goals.

Your own specs explicitly say:
	•	no per-record lineage at event scale
	•	no per-run lineage in Neptune
	•	lineage is RCA enrichment, not a runtime gate

So the right model is:
	•	per record: OTel gives runtime causal context
	•	per deploy: SCA gives static element-level intent
	•	per incident / RCA query: fusion combines them

⸻

Practical implementation guidance

Recommended answer for engineers

Fusion stages
	1.	Build time
	•	generate LineageSpec
	•	store candidate field mappings
	2.	Deploy time
	•	emit DeploymentEvent
	•	bind spec to deployed artifact
	3.	Runtime
	•	OTel emits execution context per message/request
	•	Enforcer emits record truth per message
	4.	RCA time
	•	join Evidence + OTel + Deployment + LineageSpec
	•	rank impacted consumers with confidence

What to store per record from OTel

Keep it light:
	•	trace_id
	•	span_id
	•	service.name
	•	operation name
	•	deployment version
	•	message/topic/offset if available

Do not try to store full field-level lineage per record.

When to use span links

For async fan-out, retries, queued work, and batch joins, span links are the right OTel mechanism for causal association when strict parent-child timing is not valid.  ￼

⸻

Final answer

OTel fusion should be finalized at runtime / RCA time, not at design time.
	•	Design time: SCA creates versioned candidate lineage
	•	Runtime: OTel gives per-record execution context
	•	Fusion: joins runtime context to the correct deployed SCA spec
	•	Result: deploy-aware, execution-aware lineage enrichment for RCA

So when you say “OTel extraction happens for each record,” the correct interpretation is:

OTel captures execution context for each record or message-processing operation; it does not itself compute field lineage for each record.
That execution context is what lets the platform choose the right static lineage map later.


Yes, as a discovery and augmentation mechanism, this is feasible.
No, as a primary source of new element-level lineage truth, it is not sufficient.

That is the key distinction.

Your own project direction already supports the right framing: SCA is the design-time source for field mappings, OTel is the runtime source for executed path and causal correlation, and lineage should remain asynchronous RCA enrichment rather than a runtime gate.  ￼  ￼

What this approach is good for

Using OTel to identify new flows not captured by SCA is valuable because OTel context propagation can correlate work across service boundaries using trace and span IDs, and span links are specifically meant to associate asynchronous or causally related work across traces.  ￼

So OTel can help you find:
	•	a new producer → consumer path
	•	a new async branch or retry path
	•	a new service or operation participating in a flow
	•	a missing runtime edge that SCA did not model
	•	a changed execution path after a deploy

That makes it a strong coverage discovery signal.

What it is not good for

OTel does not natively tell you that output field Y derives from input field X. It gives execution context, not field-derivation semantics. Your own assessment already states this explicitly: SCA alone lacks runtime proof, and OTel alone provides runtime causality but not field-level transformation mapping.  ￼

So if you use OTel to “augment lineage,” the safe interpretation is:
	•	augment topology
	•	augment runtime participation
	•	augment confidence and freshness of lineage
	•	sometimes trigger candidate lineage discovery
	•	but do not promote OTel-only observations into trusted field lineage without another corroborating source

Pros

The main benefits are strong.

First, it helps catch flows SCA misses. Your own docs already call out service-SCA variability, weak code patterns, reflection, dynamic payloads, and custom integrations as real sources of missed coverage.

Second, it improves runtime truth about what actually executed. If SCA says a code path exists but OTel never sees it execute, that matters. If OTel starts showing a path no SCA spec describes, that also matters.  ￼

Third, it is aligned with your existing out-of-band architecture. You already have OTel traces, deploy events, Evidence, and a knowledge graph in the target design, so this is an incremental extension, not a separate platform.

Fourth, it is especially useful for continuous drift detection after onboarding. Your Autopilot model already assumes a push-to-pull transition where runtime evidence reveals what targeted fixes are needed next. This fits that model well.

Cons

The downsides are equally important.

The biggest one is false precision. If OTel discovers that orders-enricher participated in a failing flow, that does not prove which field mapping inside orders-enricher changed. Your project docs already list false precision as a major risk.  ￼

The second issue is coverage bias. OTel only sees what is instrumented and propagated. Your docs already note that many legacy services will not propagate correlation cleanly, and Spark does not propagate OTel across shuffles, which is why you already prefer OpenLineage for batch correlation.

The third issue is identity quality. OpenTelemetry recommends explicitly setting service.name; otherwise SDKs may default to unknown_service. If identity is weak, discovered “new flows” become noisy or fragmented.  ￼

The fourth issue is async ambiguity. OTel span links let you associate asynchronous work, which is very useful, but they express causal association, not necessarily deterministic data lineage.  ￼

The fifth issue is cardinality and noise. If every newly observed runtime edge is written directly into the graph as truth, you risk graph pollution and unstable blast-radius output. Your own program already correctly treats bounded graph cardinality as a non-negotiable guardrail.  ￼

Concrete example

Suppose SCA for orders-enricher-svc captured:
	•	payment_method -> payment_method_norm

But after a deploy, OTel starts showing a new runtime path:
	•	order-service -> orders-router -> orders-enricher-v2 -> fallback-transform

SCA did not capture fallback-transform because it was config-driven or reflection-based.

In that case, OTel is extremely useful to say:
	•	there is a new runtime flow
	•	this service and operation are now part of the path
	•	this path correlates strongly with the incident after the deploy

But OTel alone still cannot safely conclude:
	•	payment_method_norm is now derived from payment_instrument.type

That still needs SCA refresh, runtime verification, payload-diff evidence, or another lineage-capable substrate.

Recommendation

Use OTel for discovery and suspicion, not for direct promotion to trusted element-level lineage.

The right path forward is a three-tier model:

Tier 1: trusted lineage

Produced by:
	•	SCA for service/custom code
	•	OpenLineage / plan lineage for Spark and supported batch
	•	declarative SQL lineage where available

This remains your authoritative element-level lineage layer.

Tier 2: runtime-discovered candidate edges

Produced by:
	•	OTel traces
	•	span links
	•	deployment correlation
	•	evidence co-occurrence

These should be marked as:
	•	candidate_flow
	•	runtime_discovered
	•	unverified

Not as trusted field lineage.

Tier 3: promotion workflow

A candidate edge gets promoted only after one of these:
	•	refreshed SCA spec confirms it
	•	runtime verification loop supports it
	•	human review approves it
	•	another strong lineage source confirms it

Recommended implementation

I would implement it this way:
	1.	Keep SCA as the primary element-level lineage source for services.
	2.	Use OTel to emit runtime flow observations keyed by producer, consumer, operation, deploy, and dataset.
	3.	Store OTel-discovered paths separately from trusted lineage edges.
	4.	Add a candidate-edge scorer using:
	•	recurrence
	•	deploy-time alignment
	•	evidence correlation
	•	operation stability
	•	identity quality
	5.	Trigger one of two follow-ups:
	•	automatic SCA re-run / parser refresh
	•	human review for high-value Tier-1 gaps
	6.	Promote only after corroboration.

Final call

Feasible? Yes.
Good idea? Yes, with the right guardrails.
Should OTel be allowed to directly create trusted element-level lineage edges? No.

The best path is:

OTel discovers missing runtime flows; SCA or another corroborating source confirms the field-level lineage; the graph carries both trusted and candidate states separately.

That gives you the value of runtime discovery without poisoning the lineage plane with precise-looking but weakly grounded edges.

Using OTel flows to carry full schemas so you can fill missing element-level lineage is possible, but I would not recommend it as the default design.

My recommendation is:

Do not put full schemas into normal OTel spans or baggage for broad production use.
Instead, use OTel to carry lightweight runtime flow context and schema fingerprints, and publish any richer schema payloads through a separate, bounded side channel or custom event stream that can be joined later with Evidence and LineageSpec. This keeps the architecture scalable, safer, and more trustworthy.

Why this idea is attractive

The idea solves a real problem. If SCA misses a flow or misses some field-level detail, a runtime observation that includes the actual request/event schema could help the platform discover:
	•	newly active fields,
	•	nested fields SCA missed,
	•	previously unseen producer → consumer paths,
	•	partial evidence for missing element-level lineage.

That is especially useful in the exact cases your docs already worry about:
	•	reflection,
	•	dynamic payload builders,
	•	config-driven code paths,
	•	legacy services,
	•	weak SCA coverage.

The biggest issue

The problem is not whether this can work technically. It can.

The problem is that OTel is fundamentally an observability transport for traces, metrics, and logs, not a primary substrate for moving large, high-cardinality, potentially sensitive schema payloads at scale. OTel’s own guidance emphasizes semantic attributes for metadata, baggage as propagated key-value pairs, and performance-safe client design; it does not position spans or baggage as a general-purpose bulk schema transport.  ￼

So the architectural question is really:
Should the schema travel inside OTel, or alongside OTel?

My answer is: alongside, except in narrow, controlled cases.

⸻

Pros

1. Better coverage for missing lineage paths

If a flow exists at runtime but SCA missed it, observing the actual payload shape at ingress and egress can help you infer:
	•	a new dataset edge,
	•	a newly active field,
	•	a previously unknown nested structure,
	•	possible candidate field dependencies.

Example

orders-enricher has a dynamic fallback path not captured by SCA.
At runtime, OTel-correlated observations show that records entering orders.process_order now contain:
	•	payment_instrument.type
and no longer contain:
	•	payment_method

That can tell you:
	•	the runtime schema changed,
	•	the flow is real,
	•	the field set is different,
	•	SCA is stale or incomplete.

That is useful augmentation.

⸻

2. Better freshness than pure SCA

SCA is tied to code analysis and deployment cadence. Runtime flow observation is naturally fresher because it reflects what actually executed now, not only what code appears capable of doing. Your docs already treat runtime truth and design-time intent as different truths; this idea strengthens the runtime side.

Example

A deploy lands with no new SCA spec yet, but production traffic immediately starts exercising a new path. Runtime schema snapshots can reveal that change before SCA catches up.

⸻

3. Stronger contradiction detection

Full or partial runtime schema observations can help detect when the static lineage is stale.

Example

Static spec says:
payment_method_norm <- payment_method

Runtime observations show:
	•	output field payment_method_norm still exists
	•	input field payment_method is absent
	•	alternative field payment_instrument.type is present

That is a strong contradiction signal even if it is not yet a complete new lineage proof.

⸻

4. Useful for candidate generation

Even if you do not trust runtime schema observations as final lineage, they are very useful for creating:
	•	candidate missing edges,
	•	candidate missing columns,
	•	candidate SCA refresh requests,
	•	candidate blast-radius hints.

⸻

Cons

1. Payload size and performance risk

This is the biggest downside.

Full schemas, especially nested event or API schemas, can become large. OTel client and pipeline design is explicitly performance-sensitive, and the project guidance stresses safe, non-blocking telemetry behavior. Large schemas in every span or propagated context will increase:
	•	span size,
	•	collector load,
	•	serialization cost,
	•	network overhead,
	•	storage cost,
	•	backpressure risk.  ￼

Example

A nested commerce event with 120 fields, arrays, and embedded objects gets attached to every processing span across 6 services.
Now your observability system is shipping copies of a quasi-schema document repeatedly with the hottest traffic.

That is exactly the kind of design that starts fine in pilot and becomes painful in production.

⸻

2. Baggage/header misuse risk

If “full schemas in OTel flows” means putting them into baggage or propagated headers, I would strongly advise against it.

OTel baggage is propagated automatically and is just key-value string data associated with the request context. It is not a safe place for rich schema payloads, and it increases leakage, propagation overhead, and governance risk.  ￼

Example

A producer adds an encoded schema JSON blob to baggage.
That blob now propagates to downstream services, maybe across trust boundaries, and could accidentally expose internal or sensitive structural information far beyond the original service path.

⸻

3. High cardinality and poor deduplication

Schemas are not stable at the same granularity as traces.

If you store full schemas per record/span, you will create many near-duplicate payloads differing only by:
	•	field ordering,
	•	optional fields,
	•	nullability patterns,
	•	experimental fields,
	•	environment-specific decorations.

OTel systems are optimized around semantic attributes and correlation, not around heavy schema deduplication. By contrast, OpenLineage already has a Schema Dataset Facet for dataset schema metadata and a Column Lineage Facet for input/output column dependency semantics, which is a much better fit for durable lineage representation.  ￼

⸻

4. Privacy and compliance concerns

A “full schema” often reveals more than structure:
	•	PII field names,
	•	sensitive business semantics,
	•	nested personal attributes,
	•	partner payload shapes.

Your platform already has explicit PII and contract enforcement concerns; broad schema propagation through telemetry increases the surface area unnecessarily.

Example

A span attribute contains nested field names like:
	•	ssn
	•	dob
	•	bank_account_number

Even without values, those names may themselves be sensitive metadata in some environments.

⸻

5. Sampling makes it incomplete anyway

Even if you do capture full schemas in OTel, traces may be sampled, dropped, or partially retained depending on your telemetry pipeline and cost controls. That means you still do not get a guaranteed, complete runtime schema corpus from tracing alone. OTel is not a guaranteed per-record lineage store.  ￼

⸻

6. It still does not prove field derivation by itself

This is crucial.

Even if you capture the full input schema and full output schema, you still do not automatically know:
	•	which output field derives from which input field,
	•	whether the relationship is direct or indirect,
	•	whether a field only influenced filtering or grouping,
	•	whether transformation logic changed semantics.

OpenLineage’s column lineage model explicitly distinguishes direct and indirect dependencies and transformation semantics; just having two schemas in OTel does not get you that level of truth.  ￼

Example

Input fields:
	•	price
	•	discount
	•	region

Output field:
	•	net_price

A full input/output schema snapshot still does not tell you whether:
	•	net_price = price - discount
	•	net_price came from a lookup
	•	region only influenced row filtering

So full schemas help discover possibilities, but not final element lineage truth.

⸻

Recommendation

Recommended design

Default path

Use OTel flows to carry only lightweight runtime lineage signals:
	•	trace_id
	•	span_id
	•	service.name
	•	operation.id
	•	deployment.version
	•	dataset ID / dataset URN
	•	schema fingerprint or schema hash
	•	bounded field-set signature
	•	optional top-N changed fields summary

This is lightweight, scalable, and consistent with OTel’s intended role.  ￼

Side channel for richer schema capture

If you need actual schema detail, publish it through a separate channel:
	•	custom lineage observation event,
	•	evidence-adjacent topic,
	•	bounded custom facet/event store,
	•	or a schema observation table keyed by trace/message/deploy.

Then join it later with:
	•	Evidence,
	•	DeploymentEvent,
	•	LineageSpec,
	•	and graph entities.

This keeps full schemas out of the hot tracing path while still making them available for augmentation.

Promotion policy

Use runtime schema observations only to create:
	•	candidate columns,
	•	candidate missing flows,
	•	candidate missing dependencies,
	•	contradiction signals,
	•	SCA refresh triggers.

Do not promote them directly to trusted element-level lineage without corroboration from:
	•	refreshed SCA,
	•	OpenLineage/plan lineage,
	•	deterministic transform metadata,
	•	or human approval for Tier-1.

⸻

Best-fit architecture pattern

What I would implement

Tier A — normal OTel spans

Carry:
	•	IDs,
	•	fingerprints,
	•	operation markers,
	•	maybe a compact field signature.

Tier B — schema observation stream

Emit only on:
	•	new flow detected,
	•	schema fingerprint change,
	•	Tier-1 targeted verification,
	•	sampled canary traffic,
	•	contradiction detection.

Tier C — knowledge-plane reconciliation

Fusion layer joins:
	•	OTel runtime context,
	•	schema observation event,
	•	SCA spec,
	•	deployment metadata,
	•	Evidence.

Tier D — promotion workflow

Promote candidate lineage only after corroboration.

⸻

Concrete example

Bad pattern

Every orders.process_order span includes:

{
  "full_input_schema": {...120 fields...},
  "full_output_schema": {...145 fields...}
}

This repeats on hot traffic and bloats the tracing system.

Better pattern

Each span includes:

{
  "dataset_urn": "urn:dp:orders:order_created:v1",
  "schema_fingerprint_in": "A1B2",
  "schema_fingerprint_out": "C9D8",
  "field_signature_in": "payment_method|order_id|customer_id|...",
  "field_signature_out": "payment_method_norm|order_id|customer_id|..."
}

Only when:
	•	A1B2 -> C9D8 is first observed,
or
	•	a Tier-1 verification rule fires,

emit a separate SchemaObservationEvent:

{
  "trace_id": "abc123",
  "producer_urn": "urn:producer:orders:orders-enricher",
  "deployment_urn": "urn:deploy:urn:producer:orders:orders-enricher:2026.04.08.1",
  "input_schema": {...},
  "output_schema": {...},
  "observation_reason": "NEW_FLOW_OR_SCHEMA_CHANGE"
}

That is a much better tradeoff.

⸻

Final call

Putting full schemas directly into OTel flows as a general strategy is not the right default.
It gives you discovery value, but at too much cost and risk for the tracing path.

Recommended approach:
	•	use OTel for lightweight runtime flow correlation and compact schema signatures,
	•	emit richer schema payloads only through a bounded side channel,
	•	use those observations to generate candidate lineage and contradiction signals,
	•	require corroboration before promoting to trusted element-level lineage.

That path gives you the benefits of runtime schema augmentation without turning OpenTelemetry into a bulky schema transport system.




 to end.