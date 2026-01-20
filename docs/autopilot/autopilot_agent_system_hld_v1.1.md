# Autopilot Agent System: LLM-Powered Observability Instrumentation

**High-Level Design Document**

Version 1.1 | January 2026

---

## Document Change Log

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | Jan 2026 | Initial draft |
| 1.1 | Jan 2026 | Added Evidence Plane Appendix, scalability model, reliability patterns, latency budgets, cost tiering per architecture review |

---

## Executive Summary

The Autopilot Agent System is an LLM-based agentic automation platform that solves the **bootstrap problem** in data observability: you cannot have intelligent RCA without signals, and teams won't invest in signals without demonstrated value.

This HLD defines:
1. A **multi-agent architecture** that proactively instruments services, streams, and batch workloads
2. The **Push Model Evidence Plane** that sustains high-velocity signal ingestion from instrumented sources

### Strategic Position

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        THE OBSERVABILITY VALUE CHAIN                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   AUTOPILOT                    SIGNAL FACTORY                  RCA COPILOT  │
│   (Agent System)               (Evidence Plane)                             │
│                                                                             │
│   ┌─────────────┐            ┌─────────────────┐            ┌─────────────┐ │
│   │ Instruments │ ────────▶  │ Policy Enforcer │ ────────▶  │ AI-Powered  │ │
│   │ Source Code │   Signals  │ Evidence Bus    │  Evidence  │ Root Cause  │ │
│   │ at Repos    │            │ Signal Engines  │            │ Analysis    │ │
│   └─────────────┘            └─────────────────┘            └─────────────┘ │
│         ▲                                                         │         │
│         │                                                         │         │
│         └─────────────── Feedback Loop ───────────────────────────┘         │
│                    (Evidence failures → targeted fixes)                     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### North Star Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Tier-1 OTel Coverage | >90% | Services with trace propagation |
| Contract Definition Rate | >95% | Topics with ODCS-compliant contracts |
| Push PR Merge Rate | >80% | PRs merged within 2 weeks |
| Time to Baseline | <8 weeks | Start of push to pull-ready state |
| **Evidence Latency (P99)** | <2 seconds | Raw event → Evidence event |
| **Signal Freshness** | <5 minutes | Evidence → computed signal |
| RCA Query Latency | <2 minutes | Incident → root cause |

---

## 1. Systems Thinking Analysis

### 1.1 The Bootstrap Problem

The flywheel assumes pull dynamics ("Copilot delivers value → Teams want better signals"), but this creates a chicken-and-egg problem:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          THE BOOTSTRAP PROBLEM                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   If applications have NO instrumentation...                                │
│        ↓                                                                    │
│   Evidence Bus has NO signals to process...                                 │
│        ↓                                                                    │
│   Copilot has NOTHING to reason about...                                    │
│        ↓                                                                    │
│   Teams see NO value...                                                     │
│        ↓                                                                    │
│   Pull never materializes.                                                  │
│                                                                             │
│   THE FLYWHEEL CANNOT START FROM ZERO.                                     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Push exists to establish the minimum viable signal layer that enables Pull to take over.**

### 1.2 Hidden Assumptions

| Assumption | Risk if Wrong | Mitigation |
|------------|---------------|------------|
| Repos are accessible via Git | Can't analyze private/air-gapped repos | Verify access in Week 1 |
| Code follows detectable patterns | AST analysis fails on exotic code | Manual fallback + human review |
| Teams will merge push PRs | PRs sit unreviewed | Executive mandate for push phase |
| Contracts can be inferred from samples | Wrong inferences bake in bad assumptions | Human review of all contract drafts |
| One-time push is sufficient | Baseline decays as code changes | CI integration for ongoing enforcement |
| **Evidence Bus handles peak load** | Signal loss during incidents | Capacity planning + overload modes |
| **Agents don't create PR storms** | Team overwhelm, ignore PRs | Rate limiting + batching |

### 1.3 Cost of Action vs. Inaction

| Choice | Cost of Action | Cost of Inaction |
|--------|----------------|------------------|
| **Implement Autopilot** | Engineering investment, PR review burden | Observability remains manual, MTTR stays high |
| **Skip OTel instrumentation** | None | RCA Copilot cannot trace causality across services |
| **Skip Contracts** | None | Contract Engine has no "correctness" definition |
| **Skip Temporal Signals** | None | Freshness/Volume engines are blind |
| **Under-provision Evidence Bus** | Lower initial cost | Signal loss under load, false RCA |

---

## 2. Multi-Agent Architecture

### 2.1 Agent Topology

The Autopilot system employs a **specialized multi-agent architecture** where each agent has a distinct responsibility, communicating through structured protocols:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        AUTOPILOT AGENT SYSTEM                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                     ORCHESTRATOR AGENT (Claude)                      │    │
│  │  • Workflow coordination                                            │    │
│  │  • Priority scoring and sequencing                                  │    │
│  │  • Human escalation decisions                                       │    │
│  │  • Progress tracking and reporting                                  │    │
│  └───────────────────────────┬─────────────────────────────────────────┘    │
│                              │                                              │
│            ┌─────────────────┼─────────────────┐                            │
│            ▼                 ▼                 ▼                            │
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐               │
│  │  SCOUT AGENT    │ │  AUTHOR AGENT   │ │  REVIEW AGENT   │               │
│  │                 │ │                 │ │                 │               │
│  │ • Repo analysis │ │ • Code gen      │ │ • PR validation │               │
│  │ • Gap detection │ │ • Diff creation │ │ • Test exec     │               │
│  │ • Confidence    │ │ • Contract      │ │ • Human liaison │               │
│  │   scoring       │ │   drafting      │ │                 │               │
│  └────────┬────────┘ └────────┬────────┘ └────────┬────────┘               │
│           │                   │                   │                        │
│           ▼                   ▼                   ▼                        │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                      TOOL LAYER                                     │    │
│  │  Git Operations | AST Parsers | Schema Registry | Neptune Client   │    │
│  │  CI/CD APIs     | Kafka Admin | Contract Validator | Evidence Bus  │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Agentic Integration Contract

**Critical boundary definition: what agents CAN and CANNOT do.**

| Agent Action | Allowed | Guardrails |
|--------------|---------|------------|
| Create instrumentation PRs | ✓ | Max 2 PRs/repo/week |
| Auto-merge high-confidence PRs | ✓ | Confidence ≥0.8, tests pass, no breaking changes |
| Modify contracts | ✓ | Always requires human review |
| Rollback producer deployments | ✗ | Never automated; propose only |
| Auto-mute alerts | ✗ | Never automated; propose only |
| Query Evidence Bus | ✓ | Read-only, rate-limited |
| Create incidents | ✗ | Signal Engines only |

### 2.3 Agent Rate Limiting (Incident Storm Protection)

Under incident storms (e.g., schema drift triggers massive failures), agents must not amplify the problem:

```python
class AgentRateLimiter:
    """
    Prevents agent actions from overwhelming teams during incidents.
    """
    
    # Per-repo limits
    MAX_PRS_PER_REPO_PER_WEEK = 2
    MAX_PRS_PER_REPO_PER_DAY = 1
    
    # Fleet-wide limits
    MAX_TOTAL_PRS_PER_HOUR = 50          # Across all repos
    MAX_TOTAL_PRS_DURING_INCIDENT = 10   # When active SEV-1/2
    
    # LLM cost controls
    MAX_LLM_CALLS_PER_REPO = 20          # Per analysis session
    MAX_LLM_COST_PER_DAY_USD = 500       # Hard budget cap
    
    # Evidence query limits
    MAX_EVIDENCE_QUERIES_PER_MINUTE = 100
    
    async def check_limits(self, action: AgentAction) -> bool:
        """
        Check if action is within rate limits.
        Returns False if action should be blocked.
        """
        if self._is_active_incident():
            return self._check_incident_limits(action)
        return self._check_normal_limits(action)
    
    def _is_active_incident(self) -> bool:
        """Check for active SEV-1 or SEV-2 incidents."""
        return self.incident_store.has_active_sev1_or_sev2()
```

### 2.4 Agent Specifications

#### 2.4.1 Orchestrator Agent

**Role**: Workflow coordinator and decision maker

```python
class OrchestratorAgent:
    """
    Central coordination agent that manages the instrumentation workflow.
    Uses LLM reasoning for priority decisions and escalation.
    """
    
    def __init__(self, llm_client: AnthropicClient):
        self.llm = llm_client
        self.scout = ScoutAgent()
        self.author = AuthorAgent()
        self.reviewer = ReviewAgent()
        self.rate_limiter = AgentRateLimiter()
    
    async def run_push_phase(self, org_repos: List[str]) -> PushPhaseReport:
        """
        Execute proactive instrumentation across all repositories.
        
        Phase 1 (Week 1-2): Baseline scan all repos
        Phase 2 (Week 3-8): Priority-based PR generation
        Phase 3 (Week 9+):  Transition to pull model
        """
        # Phase 1: Scan and score
        gap_reports = []
        for repo in org_repos:
            report = await self.scout.analyze(repo)
            gap_reports.append(report)
        
        # LLM decides priority ordering
        prioritized = await self._llm_prioritize(gap_reports)
        
        # Phase 2: Generate PRs (with rate limiting)
        for gap_report in prioritized:
            if not await self.rate_limiter.check_limits(
                AgentAction(type="CREATE_PR", repo=gap_report.repo)
            ):
                await self._queue_for_later(gap_report)
                continue
            
            if gap_report.confidence >= 0.8:
                # High confidence: auto-generate
                pr = await self.author.generate_pr(gap_report)
                await self.reviewer.auto_validate(pr)
            elif gap_report.confidence >= 0.6:
                # Medium confidence: generate with warnings
                pr = await self.author.generate_pr(gap_report, warn=True)
                await self._request_human_review(pr)
            else:
                # Low confidence: queue for human
                await self._queue_for_manual_review(gap_report)
        
        return self._compile_report()
```

#### 2.4.2 Scout Agent

**Role**: Repository analysis and gap detection

```python
class ScoutAgent:
    """
    Analyzes repositories to detect technology stack, identify observability gaps,
    and calculate confidence scores for automated instrumentation.
    """
    
    async def analyze(self, repo_url: str) -> GapReport:
        """
        Execute full repository analysis workflow.
        """
        repo = await self._clone_repo(repo_url)
        
        # Step 1: Tech stack detection
        tech_stack = await self._detect_tech_stack(repo)
        
        # Step 2: Archetype matching
        archetype = await self._match_archetype(repo, tech_stack)
        
        # Step 3: Current observability assessment
        current_state = await self._assess_observability(repo)
        
        # Step 4: Gap identification
        gaps = await self._identify_gaps(archetype, current_state)
        
        # Step 5: Confidence scoring
        confidence = self._calculate_confidence(repo, archetype, gaps)
        
        return GapReport(
            repo=repo_url,
            archetype=archetype,
            tech_stack=tech_stack,
            current_state=current_state,
            gaps=gaps,
            confidence=confidence
        )
    
    def _calculate_confidence(
        self, 
        repo: RepoContext, 
        archetype: Archetype, 
        gaps: List[Gap]
    ) -> float:
        """
        Calculate confidence score for automated instrumentation.
        
        Factors:
        - Signal clarity (+0.2): Unambiguous archetype markers
        - Dependency versions (+0.2): Modern, well-supported versions
        - Code patterns (+0.2): Standard framework usage
        - Test coverage (+0.2): Existing tests for instrumented paths
        - Configuration access (+0.2): Environment config discoverable
        """
        score = 0.0
        
        if archetype.confidence >= 0.9:
            score += 0.2
        if self._has_modern_deps(repo):
            score += 0.2
        if self._follows_standard_patterns(repo, archetype):
            score += 0.2
        if repo.test_coverage >= 0.6:
            score += 0.2
        if self._config_discoverable(repo):
            score += 0.2
        
        return score
```

#### 2.4.3 Author Agent

**Role**: Code generation and PR creation

```python
class AuthorAgent:
    """
    Generates instrumentation code and creates pull requests.
    Uses LLM for context-aware code generation with structured outputs.
    """
    
    def __init__(self, llm_client: AnthropicClient):
        self.llm = llm_client
        self.templates = InstrumentationTemplates()
    
    async def generate_pr(
        self, 
        gap_report: GapReport, 
        warn: bool = False
    ) -> PullRequest:
        """
        Generate a pull request that addresses identified gaps.
        """
        # Generate code for each gap using structured LLM output
        changes = []
        for gap in gap_report.gaps:
            change = await self._generate_instrumentation(gap, gap_report)
            changes.append(change)
        
        # Validate generated code before PR creation
        validation = await self._validate_changes(changes)
        if not validation.passed:
            raise CodeGenerationError(validation.errors)
        
        # Create branch and PR
        branch = await self._create_branch(gap_report.repo)
        await self._apply_changes(branch, changes)
        
        pr = await self._create_pr(
            repo=gap_report.repo,
            branch=branch,
            title=f"[Autopilot] Add data observability instrumentation",
            body=self._generate_pr_body(gap_report, changes, warn),
            labels=["autopilot", "observability"]
        )
        
        # Audit trail
        await self._audit_log(pr, gap_report, changes)
        
        return pr
```

---

## 3. Instrumentation Domains

### 3.1 Signal-Ready Application Stack

For the Signal Factory to work, applications must emit data that can be transformed into Evidence:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      SIGNAL-READY APPLICATION                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Layer 5: BUSINESS CONTEXT                                                  │
│           ├── Domain entity IDs (order_id, customer_id)                     │
│           ├── Business event semantics                                      │
│           └── SLO expectations                                              │
│                        ↑                                                    │
│  Layer 4: DATA CONTRACTS                                                    │
│           ├── Required fields specification                                 │
│           ├── Field type constraints                                        │
│           └── Business rule validations                                     │
│                        ↑                                                    │
│  Layer 3: DATA QUALITY                                                      │
│           ├── Completeness checks                                           │
│           ├── Validity checks                                               │
│           └── Consistency checks                                            │
│                        ↑                                                    │
│  Layer 2: TEMPORAL SIGNALS                                                  │
│           ├── Freshness (event_time, processing_time)                       │
│           └── Volume (throughput, partition distribution)                   │
│                        ↑                                                    │
│  Layer 1: OBSERVABILITY FOUNDATION (OpenTelemetry)                          │
│           ├── Trace context propagation                                     │
│           ├── Span creation                                                 │
│           └── Correlation across boundaries                                 │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Requirements Matrix

| Req ID | Domain | Requirement | Priority | Enables |
|--------|--------|-------------|----------|---------|
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

## 4. Closed-Loop Feedback System

### 4.1 Push-Pull Transition

```
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
│  instrumentation      │    ──────►    │  targeted fixes       │
│         │             │   TRANSITION  │         │             │
│         ▼             │               │         ▼             │
│  Generates baseline   │               │  Copilot improves     │
│  PRs for all services │               │  with richer signals  │
│                       │               │                       │
└───────────────────────┘               └───────────────────────┘

Trigger: Existence of repo          Trigger: Evidence failures
Goal: Minimum viable signals        Goal: Continuous improvement
Timeline: Weeks 1-8                 Timeline: Week 9+
```

### 4.2 Transition Criteria

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      PUSH → PULL TRANSITION                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Push Phase Complete When:                                                  │
│  ✓ >80% of Tier-1 repos have OTel propagation                              │
│  ✓ >80% of Tier-1 datasets have contract definitions                       │
│  ✓ Evidence Bus is receiving signals from all Tier-1 topics                │
│  ✓ Signal Engines can compute freshness/volume/contract state              │
│                                                                             │
│  Pull Phase Begins:                                                         │
│  → Evidence failures trigger reactive Autopilot PRs                         │
│  → Copilot can now reason over actual data                                  │
│  → Flywheel starts spinning                                                 │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Execution Strategy

### 5.1 Phase Timeline

| Phase | Duration | Deliverables |
|-------|----------|--------------|
| **1** | Weeks 1-2 | Baseline scan all repos, gap backlog |
| **2** | Weeks 3-4 | Tier-1: OTel, headers, timestamps, contracts |
| **3** | Weeks 5-6 | Tier-1+2: Spans, DQ, producer validation |
| **4** | Weeks 7-8 | Full coverage: Volume metrics, SLOs |
| **5** | Week 9+ | Pull model activation |

### 5.2 Success Criteria

| Metric | Target | Measurement |
|--------|--------|-------------|
| Tier-1 OTel Coverage | >90% | Services with trace propagation / Total Tier-1 |
| Contract Definition Rate | >95% | Topics with contracts / Total Tier-1 topics |
| Evidence Flow Rate | >99% | Topics emitting evidence / Total instrumented |
| Push PR Merge Rate | >80% | Merged PRs / Created PRs (within 2 weeks) |
| Time to Baseline | <8 weeks | Start of push to pull-ready state |

---

## 6. Security & Risk Mitigation

### 6.1 Security Model

| Concern | Approach |
|---------|----------|
| Repository Access | Read-only Git tokens with org scope |
| PR Creation | Bot account with limited write scope |
| Secret Management | AWS Secrets Manager, no env vars |
| LLM Prompts | No secrets in prompts, sanitize context |
| Audit Trail | All operations logged to DynamoDB + S3 |

### 6.2 Guardrails

| Risk | Mitigation |
|------|------------|
| Bad code generation | Auto-validation + test execution before PR |
| Contract inference errors | Human review for all contract drafts |
| Overwhelming teams with PRs | Rate limiting: max 2 PRs per repo per week |
| LLM hallucination | Template-guided generation, structured outputs |
| Breaking existing functionality | Run existing tests, require green CI |
| Incident storm amplification | Reduced PR rate during active SEV-1/2 |

### 6.3 Human-in-the-Loop Gates

| Action | Always Requires Human |
|--------|----------------------|
| Contract creation | ✓ |
| Breaking changes | ✓ |
| Low confidence (<0.6) PRs | ✓ |
| Rollback recommendations | ✓ |
| Alert muting | ✓ |

---

# APPENDIX A: Push Model Evidence Plane Architecture

**This appendix defines the ingestion substrate that the Autopilot agent system depends on.**

## A.1 Scalability & Throughput Model

### A.1.1 Capacity Planning

| Metric | Baseline | Peak (Incident) | Burst |
|--------|----------|-----------------|-------|
| **Raw Events/sec** | 50,000 | 200,000 | 500,000 |
| **Evidence Events/sec** | 50,000 | 200,000 | 500,000 |
| **Producers (services)** | 200 | 200 | 200 |
| **Topics monitored** | 500 | 500 | 500 |
| **Partitions (Evidence Bus)** | 64 | 64 | 64 |
| **Enforcer instances** | 8 | 32 (HPA) | 64 (burst) |

### A.1.2 Partitioning Strategy

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

### A.1.3 Autoscaling Signals

| Component | Scale-Up Trigger | Scale-Down Trigger | Min | Max |
|-----------|------------------|-------------------|-----|-----|
| Policy Enforcer | Kafka lag >30s OR CPU >70% | Lag <5s AND CPU <30% | 4 | 64 |
| Signal Engines | Lag >60s OR CPU >70% | Lag <10s AND CPU <30% | 4 | 32 |
| Evidence Bus | Partition fill >80% | N/A (manual) | 64 | 256 |

### A.1.4 Backpressure & Overload Behavior

```python
class OverloadManager:
    """
    Manages system behavior under overload conditions.
    """
    
    # Overload detection thresholds
    OVERLOAD_LAG_SECONDS = 120        # 2 minutes lag = overload
    CRITICAL_LAG_SECONDS = 300        # 5 minutes = critical
    
    # Degradation modes
    class Mode(Enum):
        NORMAL = "normal"              # Full processing
        DEGRADED = "degraded"          # Skip P2 validations
        SHED = "shed"                  # Sample + DLQ overflow
        EMERGENCY = "emergency"        # Core signals only
    
    def determine_mode(self, lag_seconds: float) -> Mode:
        if lag_seconds < 30:
            return Mode.NORMAL
        elif lag_seconds < self.OVERLOAD_LAG_SECONDS:
            return Mode.DEGRADED
        elif lag_seconds < self.CRITICAL_LAG_SECONDS:
            return Mode.SHED
        else:
            return Mode.EMERGENCY
    
    def apply_mode(self, mode: Mode, event: RawEvent) -> ProcessingDecision:
        """
        Apply processing rules based on current mode.
        """
        if mode == Mode.NORMAL:
            return ProcessingDecision(
                process=True,
                gates=["G1", "G2", "G3", "G4", "G5"],
                sample_rate=1.0
            )
        
        elif mode == Mode.DEGRADED:
            # Skip PII scanning (G5), process everything else
            return ProcessingDecision(
                process=True,
                gates=["G1", "G2", "G3", "G4"],
                sample_rate=1.0
            )
        
        elif mode == Mode.SHED:
            # Sample non-Tier-1, full process Tier-1
            tier = self.get_tier(event.dataset_urn)
            if tier == 1:
                return ProcessingDecision(process=True, gates=["G1", "G2", "G3", "G4"], sample_rate=1.0)
            else:
                return ProcessingDecision(process=True, gates=["G1", "G2"], sample_rate=0.1)
        
        else:  # EMERGENCY
            # Tier-1 only, minimal gates
            tier = self.get_tier(event.dataset_urn)
            if tier == 1:
                return ProcessingDecision(process=True, gates=["G1", "G2"], sample_rate=1.0)
            else:
                return ProcessingDecision(process=False, dlq=True)
```

**Invariants under overload:**
1. Tier-1 datasets ALWAYS get full processing (never sampled)
2. Evidence for Tier-1 is NEVER dropped (DLQ if necessary)
3. Lag metrics are always emitted (observability of observability)
4. Mode transitions are logged and alerted

---

## A.2 Reliability & Fault Tolerance

### A.2.1 Delivery Semantics

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

### A.2.2 Idempotency Implementation

```python
class EvidenceIdGenerator:
    """
    Generates deterministic evidence IDs for idempotency.
    """
    
    @staticmethod
    def generate(raw_topic: str, partition: int, offset: int) -> str:
        """
        Deterministic evidence_id from source coordinates.
        Same raw event always produces same evidence_id.
        """
        source_key = f"{raw_topic}:{partition}:{offset}"
        hash_bytes = hashlib.sha256(source_key.encode()).digest()
        # ULID-like format for sortability
        return f"evd-{base32_encode(hash_bytes[:16])}"


class SignalEngine:
    """
    Signal Engines are idempotent by design.
    """
    
    async def process_evidence(self, evidence: Evidence):
        """
        Idempotent processing - same evidence always produces same result.
        """
        # Check if already processed in this window
        window = self._get_current_window()
        cache_key = f"{evidence.evidence_id}:{window.id}"
        
        if await self.cache.exists(cache_key):
            self.metrics.increment("evidence.duplicate_skipped")
            return
        
        # Process and mark as seen
        await self._update_signal_state(evidence)
        await self.cache.set(cache_key, ttl=window.duration * 2)
```

### A.2.3 DLQ Policy & Replay

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     DLQ ARCHITECTURE                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  DLQ Topics:                                                                │
│  • signal_factory.dlq.parse_failures     (malformed JSON)                  │
│  • signal_factory.dlq.validation_errors  (gate exceptions)                 │
│  • signal_factory.dlq.overload_shed      (shed during overload)            │
│                                                                             │
│  DLQ Record Schema:                                                         │
│  {                                                                          │
│    "dlq_id": "dlq-01HQX...",                                               │
│    "original_topic": "raw.orders.events",                                  │
│    "original_partition": 7,                                                │
│    "original_offset": 1882341,                                             │
│    "failure_reason": "PARSE_ERROR",                                        │
│    "error_message": "Invalid JSON at position 42",                         │
│    "raw_payload_b64": "eyJvcmRlcl9pZCI6...",                               │
│    "timestamp": "2026-01-15T10:30:00Z",                                    │
│    "enforcer_instance": "enforcer-7b4f9",                                  │
│    "retry_count": 0                                                        │
│  }                                                                          │
│                                                                             │
│  Retention:                                                                 │
│  • parse_failures: 7 days (likely permanent issues)                        │
│  • validation_errors: 14 days (may be fixed by schema updates)             │
│  • overload_shed: 3 days (replay after capacity restored)                  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### A.2.4 Replay Tooling

```python
class DLQReplayTool:
    """
    CLI tool for replaying DLQ messages after fixes.
    """
    
    async def replay(
        self,
        dlq_topic: str,
        start_time: datetime,
        end_time: datetime,
        dry_run: bool = True
    ) -> ReplayReport:
        """
        Replay DLQ messages to main processing pipeline.
        
        Safety features:
        - Dry run by default
        - Rate limited to prevent re-overload
        - Idempotency ensures no duplicate signals
        """
        messages = await self._fetch_dlq_range(dlq_topic, start_time, end_time)
        
        if dry_run:
            return ReplayReport(
                total=len(messages),
                would_replay=len(messages),
                dry_run=True
            )
        
        replayed = 0
        for batch in self._batch(messages, size=100):
            # Rate limit: 1000 messages/sec
            await self._replay_batch(batch)
            replayed += len(batch)
            await asyncio.sleep(0.1)
        
        return ReplayReport(total=len(messages), replayed=replayed, dry_run=False)
```

### A.2.5 Retry Tiers

| Retry Tier | Condition | Max Retries | Backoff | Final Action |
|------------|-----------|-------------|---------|--------------|
| **Immediate** | Transient network | 3 | 100ms, 500ms, 2s | DLQ |
| **Short** | Registry timeout | 5 | 1s, 5s, 15s, 30s, 60s | DLQ + alert |
| **Long** | Schema not found | 3 | 5min, 15min, 1hr | DLQ + incident |

### A.2.6 Circuit Breakers

```python
class RegistryCircuitBreaker:
    """
    Protects Enforcer from cascading Registry failures.
    """
    
    FAILURE_THRESHOLD = 5          # Failures before open
    RECOVERY_TIMEOUT = 30          # Seconds before half-open
    SUCCESS_THRESHOLD = 3          # Successes to close
    
    async def call_registry(self, dataset_urn: str) -> RegistryResponse:
        if self.state == CircuitState.OPEN:
            if self._should_attempt_recovery():
                self.state = CircuitState.HALF_OPEN
            else:
                # Fallback: emit evidence with REGISTRY_UNAVAILABLE
                return self._fallback_response(dataset_urn)
        
        try:
            response = await self.registry.get_dataset(dataset_urn)
            self._record_success()
            return response
        except RegistryException as e:
            self._record_failure()
            if self.failure_count >= self.FAILURE_THRESHOLD:
                self.state = CircuitState.OPEN
            raise
```

---

## A.3 Data Freshness & Latency Model

### A.3.1 Latency Budgets

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     END-TO-END LATENCY BUDGET                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Raw Event Published                                                        │
│       │                                                                     │
│       ├── Kafka produce latency ──────────────────── 50ms (P99)            │
│       │                                                                     │
│       ▼                                                                     │
│  Enforcer Consumes                                                          │
│       │                                                                     │
│       ├── Consumer poll + deserialize ────────────── 20ms (P99)            │
│       ├── G1: Resolution (DynamoDB lookup) ───────── 15ms (P99)            │
│       ├── G2: Identity (header parse) ────────────── 5ms (P99)             │
│       ├── G3: Schema (Glue Registry) ─────────────── 50ms (P99)            │
│       ├── G4: Contract (in-memory) ───────────────── 10ms (P99)            │
│       ├── G5: PII (regex scan) ───────────────────── 30ms (P99)            │
│       ├── Evidence serialize + produce ───────────── 50ms (P99)            │
│       │                                                                     │
│       ▼                                                                     │
│  Evidence on Bus ──────────────────────────────────── 230ms (P99) TOTAL    │
│       │                                                                     │
│       ├── Signal Engine consume ──────────────────── 20ms (P99)            │
│       ├── Window aggregation ─────────────────────── 5 minutes (tumbling)  │
│       ├── Signal emit ────────────────────────────── 50ms (P99)            │
│       │                                                                     │
│       ▼                                                                     │
│  Signal Available ────────────────────────────────── 5min + 300ms (P99)    │
│                                                                             │
│  SLO TARGETS:                                                               │
│  • Evidence Latency (raw → evidence): < 2 seconds P99                      │
│  • Signal Freshness (evidence → signal): < 5 minutes                       │
│  • RCA Query (incident → root cause): < 2 minutes                          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### A.3.2 Freshness Computation & Watermarking

```python
class FreshnessEngine:
    """
    Computes freshness signals with proper late-event handling.
    """
    
    # Watermark configuration
    MAX_OUT_OF_ORDER_SECONDS = 60      # Accept events up to 1 min late
    WATERMARK_IDLE_TIMEOUT = 300       # Advance watermark if no events for 5 min
    
    def compute_freshness(
        self,
        dataset_urn: str,
        window: TimeWindow
    ) -> FreshnessSignal:
        """
        Compute freshness with watermark-based late event handling.
        """
        # Get all evidence in window
        evidence_batch = self.evidence_store.query(
            dataset_urn=dataset_urn,
            window_start=window.start,
            window_end=window.end
        )
        
        if not evidence_batch:
            # No evidence - check if this is a gap or expected silence
            return self._handle_no_evidence(dataset_urn, window)
        
        # Compute freshness metrics
        latest_event_time = max(e.event_time for e in evidence_batch)
        latest_evidence_time = max(e.evidence_time for e in evidence_batch)
        
        # Freshness = now - latest_event_time
        freshness_seconds = (datetime.utcnow() - latest_event_time).total_seconds()
        
        # Check against SLO
        slo = self.registry.get_freshness_slo(dataset_urn)
        
        if freshness_seconds > slo.max_delay_seconds:
            state = SignalState.CRITICAL
        elif freshness_seconds > slo.warning_delay_seconds:
            state = SignalState.WARNING
        else:
            state = SignalState.OK
        
        return FreshnessSignal(
            dataset_urn=dataset_urn,
            state=state,
            freshness_seconds=freshness_seconds,
            latest_event_time=latest_event_time,
            window=window,
            # Include late event stats for debugging
            late_events_count=self._count_late_events(evidence_batch),
            watermark_position=self._get_watermark(dataset_urn)
        )
    
    def _handle_late_event(self, evidence: Evidence) -> bool:
        """
        Decide whether to include a late-arriving event.
        """
        current_watermark = self._get_watermark(evidence.dataset_urn)
        event_time = evidence.event_time
        
        if event_time < current_watermark - timedelta(seconds=self.MAX_OUT_OF_ORDER_SECONDS):
            # Too late - record but don't update signal
            self.metrics.increment("freshness.late_events_dropped")
            return False
        
        return True
```

### A.3.3 Clock Skew Handling

| Scenario | Detection | Handling |
|----------|-----------|----------|
| Producer clock ahead | event_time > now + 5s | Clamp to now, emit WARNING |
| Producer clock behind | event_time < now - 1hr | Accept, flag as potentially_stale |
| Evidence processing delay | evidence_time - event_time > 5min | Include delay in freshness calc |

### A.3.4 Backlog Impact on Signal Correctness

```python
class SignalCorrectnessAnnotator:
    """
    Annotates signals with data quality indicators when backlog exists.
    """
    
    def annotate(self, signal: Signal, current_lag: float) -> Signal:
        """
        Add correctness annotations based on processing lag.
        """
        annotations = {}
        
        if current_lag > 30:
            annotations["data_staleness"] = "STALE"
            annotations["staleness_seconds"] = current_lag
        
        if current_lag > 120:
            annotations["signal_confidence"] = "LOW"
            annotations["reason"] = "High processing lag may affect accuracy"
        
        if current_lag > 300:
            annotations["signal_confidence"] = "DEGRADED"
            annotations["recommended_action"] = "Wait for backlog to clear"
        
        signal.annotations.update(annotations)
        return signal
```

---

## A.4 Cost Efficiency Model

### A.4.1 Storage Tiering

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     STORAGE TIERING STRATEGY                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  HOT TIER (DynamoDB + Neptune)                                              │
│  ├── Evidence Cache: Last 24 hours                                          │
│  ├── Signal State: Current + last 7 days                                    │
│  ├── Incident Index: Active + last 30 days                                  │
│  └── Graph Edges: All (pruned by TTL)                                       │
│                                                                             │
│  WARM TIER (S3 Standard)                                                    │
│  ├── Evidence Archive: 24 hours - 90 days                                   │
│  ├── Signal History: 7 days - 1 year                                        │
│  └── Query latency: ~500ms (Athena)                                         │
│                                                                             │
│  COLD TIER (S3 Glacier)                                                     │
│  ├── Evidence Archive: 90 days - 7 years (compliance)                       │
│  ├── Signal History: 1 year - 7 years                                       │
│  └── Query latency: ~hours (Athena + restore)                               │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### A.4.2 TTL by Entity Type

| Entity | Hot TTL | Warm TTL | Cold TTL | Rationale |
|--------|---------|----------|----------|-----------|
| Evidence (PASS) | 24hr | 30d | 1yr | Volume driver; short hot |
| Evidence (FAIL) | 7d | 90d | 7yr | RCA value; longer hot |
| Signal State | 7d | 1yr | 7yr | Trend analysis |
| Incidents | 30d | 2yr | 7yr | Post-mortems |
| Neptune Edges | 90d | N/A | N/A | Graph pruning |
| FailureSignature | 180d | N/A | N/A | Pattern matching |

### A.4.3 Sampling Strategy

```python
class EvidenceSampler:
    """
    Reduces storage costs for high-volume, low-value evidence.
    """
    
    # Sampling rules by tier and state
    SAMPLING_RULES = {
        # Tier 1: Never sample FAIL, sample PASS at high volume
        (1, "FAIL"): SamplingRule(rate=1.0, min_volume=0),
        (1, "PASS"): SamplingRule(rate=1.0, min_volume=0, 
                                   reduce_to=0.1, above_volume=100_000),
        
        # Tier 2: Sample PASS more aggressively
        (2, "FAIL"): SamplingRule(rate=1.0, min_volume=0),
        (2, "PASS"): SamplingRule(rate=0.1, min_volume=1000),
        
        # Tier 3: Sample everything except first failures
        (3, "FAIL"): SamplingRule(rate=0.5, min_volume=100),
        (3, "PASS"): SamplingRule(rate=0.01, min_volume=100),
    }
    
    def should_store(self, evidence: Evidence) -> bool:
        """
        Determine if evidence should be stored (hot tier).
        """
        tier = self.registry.get_tier(evidence.dataset_urn)
        result = evidence.validation.result
        
        rule = self.SAMPLING_RULES.get((tier, result))
        if not rule:
            return True  # Unknown = store
        
        # Always store first occurrence of new failure signature
        if result == "FAIL" and self._is_new_signature(evidence):
            return True
        
        # Apply sampling
        return random.random() < rule.effective_rate(
            self._get_current_volume(evidence.dataset_urn)
        )
```

### A.4.4 Cardinality Controls

| Dimension | Limit | Enforcement |
|-----------|-------|-------------|
| Datasets | 10,000 | Registration required |
| FailureSignatures per dataset | 1,000 | LRU eviction |
| Unique reason_codes | 500 | Bucketing to OTHER |
| Graph nodes per dataset | 10,000 | Aggregation |
| Graph edges per node | 1,000 | Sampling |

### A.4.5 Cost Estimate (Updated)

| Component | Monthly Cost | Notes |
|-----------|-------------|-------|
| EKS (Enforcer + Engines) | ~$5,000 | 8-32 instances, autoscaling |
| Amazon Neptune | ~$4,000 | r5.large, HA |
| DynamoDB | ~$3,000 | On-demand, hot tier |
| MSK (Evidence Bus) | ~$4,000 | 64 partitions, 7d retention |
| S3 (Warm + Cold) | ~$1,500 | ~50TB/month |
| Bedrock (LLM for Autopilot) | ~$2,000 | Rate-limited |
| CloudWatch, X-Ray, Misc | ~$1,500 | Observability |
| **Total Estimated Monthly** | **~$21,000** | |

### A.4.6 Cost Control Levers

| Lever | Savings | Trade-off |
|-------|---------|-----------|
| Increase PASS sampling (Tier 2/3) | ~30% | Reduced drill-down for passing |
| Reduce hot tier TTL (24h → 12h) | ~15% | Slower RCA for older incidents |
| Compress evidence payloads | ~20% | CPU overhead |
| Reduce Neptune retention | ~10% | Limited historical graph |

---

## A.5 Multi-Region & DR Posture

### A.5.1 Deployment Model

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     MULTI-REGION ARCHITECTURE                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  PRIMARY REGION (us-east-1)                                                 │
│  ├── Enforcer Fleet (active)                                                │
│  ├── Signal Engines (active)                                                │
│  ├── Neptune (primary writer)                                               │
│  ├── DynamoDB (global table - active)                                       │
│  └── Evidence Bus (MSK - primary)                                           │
│                                                                             │
│  DR REGION (us-west-2)                                                      │
│  ├── Enforcer Fleet (standby, can activate in <15min)                       │
│  ├── Signal Engines (standby)                                               │
│  ├── Neptune (read replica, can promote)                                    │
│  ├── DynamoDB (global table - active reads)                                 │
│  └── Evidence Bus (MSK mirror - async)                                      │
│                                                                             │
│  REPLICATION:                                                               │
│  • DynamoDB: Global Tables (async, <1s typical)                            │
│  • Neptune: Cross-region read replica (async, ~minutes)                    │
│  • MSK: MirrorMaker 2.0 (async, configurable lag)                          │
│  • S3: Cross-region replication (async, ~15min)                            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### A.5.2 RPO/RTO Targets

| Scenario | RPO | RTO | Procedure |
|----------|-----|-----|-----------|
| Single AZ failure | 0 | <5min | Auto-failover (EKS, Neptune) |
| Region failure | <5min | <30min | Manual failover to DR |
| Data corruption | <1hr | <2hr | Point-in-time restore |
| Enforcer fleet failure | 0 | <5min | HPA + ASG replacement |
| Neptune failure | <1min | <15min | Promote read replica |

### A.5.3 Failover Runbook

```
REGION FAILOVER PROCEDURE

1. DETECTION (automated)
   - CloudWatch alarms: Evidence lag > 5min across all enforcers
   - Health check failures > 50% of fleet

2. DECISION (human)
   - Incident Commander confirms regional issue
   - Approves failover via Slack workflow

3. EXECUTION (automated)
   - Route53 health check marks primary unhealthy
   - Traffic shifts to DR region ALB
   - DR Enforcer fleet scales up (5min)
   - Neptune replica promoted to writer (10min)
   - DynamoDB global table continues serving

4. VALIDATION
   - Evidence flow resumes (check lag metrics)
   - Signal computation resumes
   - RCA Copilot accessible

5. RECOVERY (post-incident)
   - Root cause primary region failure
   - Restore primary region
   - Failback during maintenance window
```

---

## A.6 Observability of Observability

### A.6.1 Platform Health Metrics

| Metric | Alert Threshold | Severity |
|--------|----------------|----------|
| `enforcer.lag_seconds` | >30s (warn), >120s (crit) | P1 |
| `enforcer.evidence_rate` | <50% of baseline | P1 |
| `enforcer.error_rate` | >1% | P2 |
| `evidence_bus.partition_lag` | >100K messages | P2 |
| `signal_engine.freshness_seconds` | >10min | P1 |
| `neptune.query_latency_p99` | >5s | P2 |
| `dlq.message_count` | >1000 in 1hr | P2 |

### A.6.2 Dashboards

1. **Evidence Flow Dashboard**: Real-time evidence rate, lag, error breakdown
2. **Signal Health Dashboard**: Per-engine processing, signal states by tier
3. **Autopilot Dashboard**: PR creation rate, merge rate, queue depth
4. **Cost Dashboard**: Daily spend by component, projected monthly

---

## Summary

This HLD v1.1 addresses the architecture review feedback by adding:

1. **Scalability Model**: Explicit throughput targets (50K-500K events/sec), partitioning strategy, consumer groups, autoscaling signals
2. **Reliability Patterns**: Delivery semantics boundaries, idempotency keys, retry tiers, DLQ policy with replay tooling, circuit breakers
3. **Latency Budgets**: P99 latency breakdown, freshness computation with watermarking, late-event handling, backlog impact on correctness
4. **Cost Efficiency**: Storage tiering (hot/warm/cold), TTL by entity type, sampling strategy, cardinality controls
5. **Multi-Region DR**: RPO/RTO targets, replication strategy, failover runbook
6. **Agent Guardrails**: Rate limiting during incidents, LLM cost caps, clear automation boundaries

The Autopilot Agent System now has a complete specification for both the **agentic instrumentation layer** and the **evidence ingestion substrate** it depends on.

---

*Document Version: 1.1*
*Status: Ready for Architecture Sign-off*
*Owner: Data Platform Architecture Team*
