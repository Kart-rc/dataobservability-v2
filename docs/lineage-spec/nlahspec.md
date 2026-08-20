A lineage-focused NLAH harness should be structured as an **executable natural-language orchestration layer** around deterministic lineage tools, not as an LLM-only extractor. The NLAH paper’s key idea is that harness behavior is externalized as portable natural-language control logic, while the runtime executes it through contracts, artifacts, roles, adapters, state semantics, and failure taxonomy. The paper is explicit that natural language should carry orchestration logic, while deterministic adapters/scripts still perform tests, parsing, verification, and other low-level hooks. ([arXiv][1])

## 1. Recommended structure

```text
lineage-nlah-harness/
  README.md

  runtime/
    RUNTIME_CHARTER.md
    PERMISSIONS.md
    TOOL_BUDGETS.md
    FAILURE_POLICY.md

  harnesses/
    lineage_extraction.nlah.md
    lineage_extraction_fast_path.nlah.md
    lineage_extraction_deep_path.nlah.md
    lineage_review.nlah.md
    lineage_publish.nlah.md

  roles/
    orchestrator.md
    repo_scout.md
    extraction_strategist.md
    service_edge_extractor.md
    element_flow_extractor.md
    lineage_combiner.md
    schema_validator.md
    adversarial_reviewer.md
    publisher.md

  contracts/
    input_contract.md
    artifact_contract.md
    lineage_spec_contract.md
    openlineage_contract.md
    validation_contract.md
    publish_contract.md

  adapters/
    repo_scanner_adapter.py
    service_registry_adapter.py
    tree_sitter_adapter.py
    joern_adapter.py
    callsite_normalizer_adapter.py
    lineage_combiner_adapter.py
    openlineage_emitter_adapter.py
    lineage_spec_emitter_adapter.py
    graph_dry_run_adapter.py
    rca_rehearsal_adapter.py

  schemas/
    assessment.schema.json
    service_edges.schema.json
    element_flows.schema.json
    combined_lineage.schema.json
    lineage_spec.schema.json
    openlineage_event.schema.json
    run_manifest.schema.json

  verifiers/
    verify_assessment.py
    verify_callsite_join.py
    verify_lineage_spec.py
    verify_openlineage.py
    verify_graph_cardinality.py
    verify_no_unbounded_edges.py

  examples/
    java_spring_kafka/
    python_fastapi_requests/
    go_gin_http/
    spark_job/
    graphql_resolver/

  runs/
    <run_id>/
      task_state.json
      manifest.json
      ledgers/
      artifacts/
      evidence/
      reports/
```

The most important design choice is the split between **runtime charter** and **task-family harness logic**. The NLAH paper frames IHR as an in-loop runtime that reads the harness, current state, environment, and runtime charter before selecting the next action; it also separates generic runtime semantics from task-specific harness logic. ([arXiv][1])

## 2. Runtime charter

The runtime charter should define what the harness is allowed to do, independent of lineage-specific logic.

```markdown
# Runtime Charter: Lineage Extraction IHR

## Mission
Execute lineage extraction workflows safely, reproducibly, and audibly.

## Non-negotiable rules
1. Never fabricate lineage.
2. Every emitted edge must be backed by a deterministic artifact.
3. Low-confidence lineage must be marked LOW, never silently omitted.
4. Lineage is RCA enrichment, not a runtime gate.
5. Do not publish if validation gates fail.
6. Preserve all intermediate artifacts in a path-addressable workspace.
7. Prefer deterministic tools over model inference.
8. Use LLM reasoning only for orchestration, gap analysis, repair planning, and review.

## Permissions
- Read repositories.
- Run approved adapters.
- Write artifacts under runs/<run_id>/.
- Publish only through approved publisher adapter.
- No production graph writes unless publish gate passes.

## Stop conditions
- Valid LineageSpec produced and verified.
- Or detector gap report produced with confidence reasons.
- Or unrecoverable failure recorded with evidence.
```

This matches the paper’s emphasis on contract-bounded agent calls: required outputs, budgets, permission scope, completion conditions, and designated output paths. ([arXiv][1])

## 3. Harness-level workflow

The lineage harness should be staged like this:

```text
INTAKE
  ↓
REPO DISCOVERY
  ↓
ASSESSMENT
  ↓
ROUTE
  ├── FAIL: produce detector gap report
  ├── FAST PATH: service-level lineage only
  └── DEEP PATH: service + element-level lineage
        ↓
STATIC EXTRACTION
        ↓
ELEMENT FLOW EXTRACTION
        ↓
CALLSITE NORMALIZATION
        ↓
COMBINE
        ↓
VALIDATE
        ↓
EMIT LINEAGESPEC + OPENLINEAGE
        ↓
GRAPH DRY RUN
        ↓
PUBLISH OR QUARANTINE
```

This should wrap your current extractor design. The existing plan already targets Tree-sitter for service topology, Joern for element-level data flow, and OpenLineage NDJSON emission across Java, Python, and Go repositories.  The NLAH harness adds **orchestration, state, validation gates, recovery behavior, and auditability** around those deterministic components.

## 4. Core NLAH file

A simplified `harnesses/lineage_extraction.nlah.md` would look like this:

```markdown
# NLAH: Element-Level Lineage Extraction

## Task family
Extract service-level and element-level lineage from application repositories and emit verified lineage artifacts.

## Inputs
- repo_path or repo_url
- commit_sha
- service registry reference
- dataset registry reference
- target languages: java, python, go
- output modes:
  - LineageSpec
  - OpenLineage
  - detector gap report

## Required outputs
- runs/<run_id>/manifest.json
- runs/<run_id>/artifacts/assessment.json
- runs/<run_id>/artifacts/service_edges.json
- runs/<run_id>/artifacts/element_flows.json
- runs/<run_id>/artifacts/combined_lineage.json
- runs/<run_id>/artifacts/lineage_spec.json
- runs/<run_id>/reports/validation_report.md
- runs/<run_id>/reports/detector_gap_report.md if extraction fails or confidence is low

## Roles
1. Orchestrator
   - Owns stage sequencing and stop conditions.
2. Repo Scout
   - Detects language, framework, service identity, and repo shape.
3. Extraction Strategist
   - Chooses fast path or deep path.
4. Service Edge Extractor
   - Runs Tree-sitter service boundary extraction.
5. Element Flow Extractor
   - Runs Joern/static flow extraction.
6. Lineage Combiner
   - Joins service edges and element flows.
7. Validator
   - Runs schema, join, confidence, and graph-cardinality checks.
8. Adversarial Reviewer
   - Challenges false precision, missing sinks, dynamic URLs, weak joins, and stale identity.
9. Publisher
   - Emits verified artifacts to approved destinations.

## Stages

### Stage 1: Intake
Read task input, create run workspace, initialize manifest, and record commit SHA.

Gate:
- repo exists
- commit SHA or content hash exists
- run_id created
- output directory is empty or atomic temp directory is used

### Stage 2: Discovery
Use repo_scanner_adapter and service_registry_adapter.

Gate:
- language detected or marked unknown
- service identity resolved with source and confidence
- dataset registry reachable or mapping fallback recorded

### Stage 3: Assessment
Use tree_sitter_adapter in assessment mode.

Gate:
- sources > 0
- sinks > 0
- confidence >= configured threshold
- framework recognition recorded
- if gate fails, produce detector gap report and stop

### Stage 4: Service edge extraction
Extract inbound routes, outbound calls, topics, database calls, and service callsites.

Gate:
- service_edges.json conforms to schema
- dynamic URLs are marked unresolved, not dropped

### Stage 5: Element flow extraction
Run joern_adapter or language-specific static flow adapter.

Gate:
- element_flows.json exists
- parser errors are captured
- timeout is reported as partial failure, not success

### Stage 6: Normalize and combine
Use callsite_normalizer_adapter and lineage_combiner_adapter.

Gate:
- absolute/relative path differences normalized
- multiline calls handled
- orphaned Joern flows reported
- unmatched service calls reported

### Stage 7: Emit lineage artifacts
Emit:
- LineageSpec for Signal Factory
- OpenLineage event for catalog consumption

Gate:
- LineageSpec schema passes
- OpenLineage schema passes
- confidence and coverage are present

### Stage 8: Graph dry run
Simulate Neptune/DynamoDB writes.

Gate:
- dataset-level READS/WRITES bounded
- column-level READS_COL/WRITES_COL bounded
- no per-record lineage
- no full AST stored in graph

### Stage 9: Publish
Publish only if all mandatory gates pass.

Stop:
- SUCCESS: artifacts published
- PARTIAL: gap report published
- FAIL: unrecoverable error recorded with evidence

## Failure taxonomy
- repo_unreadable
- unknown_language
- no_sources
- no_sinks
- joern_timeout
- joern_parse_failure
- callsite_join_failure
- low_confidence
- invalid_lineage_spec
- invalid_openlineage
- graph_cardinality_violation
- publish_failure

## Recovery rules
- Retry transient tool failures once.
- Do not retry deterministic schema failures.
- If Joern fails, produce service-level lineage and mark element lineage FAILED unless --allow-partial is enabled.
- If confidence is LOW, do not promote to primary RCA ranking.
```

## 5. Artifact model

The paper emphasizes file-backed state as an explicit module: state should be externalized into artifacts, path-addressable, and stable across truncation, restart, and delegation. ([arXiv][1]) For lineage extraction, that means the harness should never rely on chat memory for important decisions.

A run should create this:

```text
runs/2026-04-29-orders-service-9f31c2d/
  task_state.json
  manifest.json

  ledgers/
    decisions.md
    tool_calls.jsonl
    confidence_ledger.md
    failure_ledger.md

  artifacts/
    repo_profile.json
    assessment.json
    service_edges.json
    element_flows.json
    normalized_callsites.json
    combined_lineage.json
    lineage_spec.json
    openlineage_events.ndjson

  evidence/
    tree_sitter_raw/
    joern_raw/
    schema_validation/
    graph_dry_run/

  reports/
    extraction_summary.md
    detector_gap_report.md
    validation_report.md
    publish_report.md
```

This is critical because lineage extraction is long-horizon and multi-step. You want every stage to reopen the exact artifacts by path rather than depend on prior conversation state.

## 6. Output contract

For Signal Factory, the primary output should be **LineageSpec**, with OpenLineage as a secondary catalog-facing output. Your existing Signal Factory lineage specification already defines SCA lineage as design-time intent, while Signal Factory remains the source for runtime truth; it also states the key boundary that lineage enriches RCA and never blocks ingestion or alerting. 

Minimum `lineage_spec.json`:

```json
{
  "spec_version": "1.0",
  "lineage_spec_id": "lspec:orders-service:git:9f31c2d",
  "emitted_at": "2026-04-29T12:30:00Z",
  "producer": {
    "type": "SERVICE",
    "name": "orders-service",
    "platform": "SPRING_BOOT",
    "runtime": "EKS",
    "owner_team": "orders-platform",
    "repo": "github:org/orders-service",
    "ref": {
      "ref_type": "GIT_SHA",
      "ref_value": "9f31c2d"
    }
  },
  "lineage": {
    "inputs": [
      {
        "dataset_urn": "urn:dp:customers:customer_profile:v1",
        "column_urns": [
          "urn:col:urn:dp:customers:customer_profile:v1:customer_id"
        ]
      }
    ],
    "outputs": [
      {
        "dataset_urn": "urn:dp:orders:order_created:v1",
        "column_urns": [
          "urn:col:urn:dp:orders:order_created:v1:customer_id"
        ]
      }
    ],
    "transforms": [
      {
        "output_column": "customer_id",
        "input_columns": ["customer_id"],
        "operation": "COPY",
        "evidence_ref": "runs/.../evidence/joern_raw/flow-001.json"
      }
    ]
  },
  "confidence": {
    "overall": "MEDIUM",
    "reasons": ["TREE_SITTER_ROUTE_MATCH", "JOERN_FLOW_MATCH", "DYNAMIC_URL_PARTIAL"],
    "coverage": {
      "input_columns_pct": 0.75,
      "output_columns_pct": 0.68
    }
  }
}
```

The harness should enforce the same deployment correlation model as the project lineage flow: the deployment event and LineageSpec should share the same commit SHA, enabling a reliable join between what was deployed and what lineage describes. 

## 7. Deterministic adapters

The NLAH harness should call adapters like tools. Each adapter should have a strict input/output contract.

| Adapter                        | Responsibility                                             | Output                      |
| ------------------------------ | ---------------------------------------------------------- | --------------------------- |
| `repo_scanner_adapter`         | Language, framework, service identity, repo metadata       | `repo_profile.json`         |
| `tree_sitter_adapter`          | Sources, sinks, service edges, callsites                   | `service_edges.json`        |
| `joern_adapter`                | Element-level data flows                                   | `element_flows.json`        |
| `callsite_normalizer_adapter`  | Normalize absolute/relative paths, line ranges, symbol IDs | `normalized_callsites.json` |
| `lineage_combiner_adapter`     | Join service edges and element flows                       | `combined_lineage.json`     |
| `lineage_spec_emitter_adapter` | Emit Signal Factory LineageSpec                            | `lineage_spec.json`         |
| `openlineage_emitter_adapter`  | Emit OpenLineage events                                    | `openlineage_events.ndjson` |
| `graph_dry_run_adapter`        | Validate Neptune/DynamoDB write shape                      | `graph_write_plan.json`     |
| `rca_rehearsal_adapter`        | Simulate blast-radius query                                | `rca_rehearsal_report.md`   |

The Lineage Ingestor side should remain asynchronous: consume LineageSpec, validate schema and URNs, write bounded Neptune topology edges, and update DynamoDB lookup indexes. The project flow explicitly warns not to write per-run execution edges, per-record lineage, or full transform AST. 

## 8. Validation gates

The harness should be validation-heavy. These gates are more important than the LLM.

| Gate               | Pass condition                                  | Failure action                |
| ------------------ | ----------------------------------------------- | ----------------------------- |
| Repo gate          | repo readable, commit pinned                    | stop with `repo_unreadable`   |
| Language gate      | language supported or explicitly unknown        | produce gap report            |
| Source/sink gate   | sources > 0 and sinks > 0                       | fail assessment               |
| Confidence gate    | score above threshold                           | otherwise detector gap report |
| Joern gate         | CPG generated and parsed                        | mark element lineage failed   |
| Join gate          | callsites normalized and match rate acceptable  | produce join gap report       |
| Schema gate        | artifacts validate against JSON schemas         | block publish                 |
| OpenLineage gate   | emitted events validate against pinned schema   | block OpenLineage publish     |
| LineageSpec gate   | URNs, producer, commit, confidence present      | block Signal Factory publish  |
| Graph gate         | no per-record/per-run graph writes              | block graph publish           |
| RCA rehearsal gate | sample incident can identify impacted consumers | warn if unavailable           |

Runtime enforcement should remain independent of lineage. Your project flow states that the Enforcer, Evidence emission, Signal Engines, and incident creation do not use lineage because lineage describes intent, can be stale/incomplete, and must not become a deterministic runtime dependency. 

## 9. Role design

```text
Orchestrator
  Owns control flow, stop rules, and recovery.

Repo Scout
  Finds language, framework, service identity, build files, repo topology.

Extraction Strategist
  Chooses fast path vs deep path.
  Example: Java Spring + clear sinks → deep path.
  Unknown language → gap report.

Service Edge Extractor
  Uses Tree-sitter to find routes, Kafka producers/consumers, HTTP clients, DB calls.

Element Flow Extractor
  Uses Joern or static analysis to infer field-level flows.

Lineage Combiner
  Normalizes callsites and builds combined lineage.

Validator
  Runs schema, confidence, graph, OpenLineage, and LineageSpec checks.

Adversarial Reviewer
  Challenges false precision:
  - Did dynamic SQL get marked LOW?
  - Are unmatched flows reported?
  - Are paths normalized?
  - Are dataset URNs authoritative?
  - Is deployed version aligned to commit?

Publisher
  Publishes only verified artifacts.
```

## 10. How it fits Signal Factory RCA

The harness output should feed this path:

```text
Repo / Commit
  ↓
NLAH Lineage Harness
  ↓
LineageSpec + OpenLineage artifacts
  ↓
Lineage Ingestor
  ↓
Neptune topology edges + DynamoDB indexes
  ↓
RCA Copilot blast-radius query
```

During an incident, RCA starts from evidence and failure signature, then uses the lineage graph to find downstream readers of the implicated column. The flow document describes this pattern: incident → failure signature such as `FIELD_REMOVED:payment_method` → query lineage graph → calculate blast radius → produce impacted consumers. 

## 11. Recommendation

Build the NLAH harness as a **control and verification harness**, not as the extraction engine itself.

The right split is:

```text
LLM / NLAH:
  orchestration
  branch decisions
  ambiguity handling
  gap explanation
  adversarial review
  recovery planning
  human-readable reports

Deterministic adapters:
  parsing
  static analysis
  Joern execution
  callsite joining
  schema validation
  OpenLineage validation
  graph write simulation
```

This gives you the benefit of NLAH—portable, inspectable, composable harness logic—without trusting an LLM to invent lineage. The first steel thread should be one Java Spring service or one Spark job, one deployed commit, one LineageSpec, one graph dry run, and one RCA rehearsal showing impacted consumers for a removed field.


