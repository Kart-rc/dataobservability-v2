  
**DATA OBSERVABILITY PLATFORM v2.0**

4-Team Organization Implementation Plan

Phased Vertical Integration with Flywheel Metrics

January 2026 \- December 2026

Version 1.0 | January 2026

# **Table of Contents**

# **1\. Executive Summary**

## **1.1 Strategic Context**

This implementation plan addresses a fundamental challenge in building observability platforms: the bootstrap problem. Without existing signals, the RCA Copilot cannot demonstrate value; without demonstrated value, teams resist investing in instrumentation. The recommended organizational structure breaks this circular dependency through phased vertical integration.

## **1.2 Recommended Approach: Phased Vertical Integration**

The hybrid approach combines two organizational models:

* Phased Vertical Integration (Approach 2): Teams temporarily reconfigure based on where the critical path lies, forming cross-functional tiger teams during proof-of-value phases.  
* Flywheel Metrics (Approach 5): All teams share accountability for loop velocity metrics (time-to-baseline, MTTR, PR merge rate) rather than siloed component metrics.

## **1.3 Year-End Success Criteria**

| Metric | Target | Measurement |
| :---- | :---- | :---- |
| Self-Sustaining Flywheel | Operational | Zero manual intervention for new services |
| Time-to-Baseline (new services) | \<8 weeks | Deploy to evidence flowing |
| PR Merge Rate | \>80% | Merged / Created within 2 weeks |
| MTTR for Pilot Domains | \<2 hours | Incident to resolution |
| Event Throughput | 50-500K/sec | Evidence Bus capacity |
| RCA Copilot Accuracy | \>70% | Correct root cause on pilot incidents |

# **2\. Team Structure Evolution**

## **2.1 Three-Phase Organizational Model**

The organization evolves through three distinct phases, each optimizing for different objectives:

| Phase | Duration | Objective | Team Configuration |
| :---- | :---- | :---- | :---- |
| **Phase 1: Prove Value** | M1-M3 | First incident resolved by Copilot | Tiger Team \+ Foundation \+ Autopilot Seed |
| **Phase 2: Scale Coverage** | M4-M8 | Tier-1 fully covered, Tier-2 started | Graduated swim lanes |
| **Phase 3: Self-Sustaining** | M9-M12 | Flywheel operational | Flywheel-aligned pods |

## **2.2 Phase 1: Prove Value (M1-M3)**

Critical insight: In Phase 1, traditional swim-lane teams would create integration bottlenecks at precisely the moment when tight coordination is essential. Instead, we form mission-oriented teams.

### **2.2.1 Tiger Team: Orders Domain E2E**

*Mission: Deliver the complete observability loop for the Orders domain, from evidence generation through Copilot-assisted incident resolution.*

| Role | Source Team | Responsibilities | Skills Required |
| :---- | :---- | :---- | :---- |
| **Tech Lead / EM** | Team 1 or 2 | Architecture decisions, cross-team coordination | Distributed systems, Kafka, leadership |
| Enforcer Engineer | Team 1 | Policy Enforcer G1-G2 gates, Evidence Bus | Kafka, EKS, schema validation |
| Signal Engineer | Team 2 | Freshness \+ Contract Signal Engines | Stream processing, DynamoDB |
| Graph Engineer | Team 2 | Neptune model, incident correlation | Neptune, Gremlin, graph modeling |
| Copilot Engineer | Team 4 | LLM integration, prompt engineering | LLM APIs, prompt engineering, Python |

**Team Size: 5 engineers \+ 1 EM**

Success Gate: RCA Copilot achieves \>70% accuracy on Orders domain pilot incidents by end of M3.

### **2.2.2 Foundation Team: Infrastructure at Scale**

*Mission: Build the infrastructure foundation that will support 50-500K events/sec at scale, ensuring the Tiger Team can focus on domain-specific work.*

| Role | Source Team | Responsibilities | Skills Required |
| :---- | :---- | :---- | :---- |
| **Platform Lead** | Team 1 | EKS, networking, security | Kubernetes, AWS, IaC |
| Kafka Engineer | Team 1 | Evidence Bus, partitioning, retention | MSK/Kafka, consumer groups |
| Data Engineer | Team 1 | DynamoDB tables, S3 archival | DynamoDB, S3, data modeling |
| Observability Engineer | Team 2 | Platform monitoring, SLO dashboards | CloudWatch, Grafana, alerting |
| Storage Engineer | Team 2 | Neptune provisioning, backup | Neptune, graph databases |

**Team Size: 5 engineers**

Success Gate: Infrastructure supports 10K events/sec with \<2s p99 latency, autoscaling tested.

### **2.2.3 Autopilot Seed Team: Prove LLM Instrumentation**

*Mission: Validate that LLM-based automated instrumentation is viable by successfully instrumenting 3 representative repositories.*

| Role | Source Team | Responsibilities | Skills Required |
| :---- | :---- | :---- | :---- |
| **Autopilot Lead** | Team 3 | Agent architecture, GitHub App | GitHub APIs, LLM integration |
| AST Engineer | Team 3 | Code analysis, pattern detection | tree-sitter, Python/Java AST |
| Code Gen Engineer | Team 3 | PR generation, code templates | Polyglot, OTel SDKs |
| LLM Engineer | Team 4 | Prompt engineering for code gen | Claude API, structured outputs |

**Team Size: 4 engineers**

Success Gate: 3 repos instrumented, PRs merged, evidence flowing within 2 weeks per repo.

## **2.3 Phase 2: Scale Coverage (M4-M8)**

After Phase 1 success gates are met, teams graduate from tiger team configuration back to functional swim lanes, but with evolved responsibilities based on learnings.

### **2.3.1 Team Reconfiguration**

| Team | Phase 1 Contributors | Phase 2 Focus | Headcount |
| :---- | :---- | :---- | :---- |
| **Platform Core** | Foundation Team (full) \+ Tiger Team (1) | G3-G4 gates, multi-tenancy, DR | 6 engineers \+ 1 EM |
| **Signal Processing** | Foundation (2) \+ Tiger Team (2) | All 5 engines, anomaly detection | 5 engineers \+ 1 EM |
| **Autopilot** | Seed Team (full) | Push phase execution, Tier-1 coverage | 5 engineers \+ 1 EM |
| **AI & Intelligence** | Tiger Team (1) \+ Seed Team (1) | Blast radius, SCA lineage, similar incidents | 4 engineers \+ 1 EM |

### **2.3.2 Cross-Team Dependencies**

During Phase 2, teams operate with defined contracts but maintain weekly integration syncs:

* Evidence Schema v2: Platform Core owns definition, all teams implement by M5  
* Contract Inference API: Autopilot produces drafts, Platform Core validates, Signal Processing consumes  
* Incident Correlation: Signal Processing creates incidents, AI & Intelligence enriches with RCA

## **2.4 Phase 3: Self-Sustaining Flywheel (M9-M12)**

In the final phase, all teams align around flywheel metrics. Success is measured by loop velocity, not component delivery.

### **2.4.1 Shared Flywheel Metrics**

| Metric | Target | All Teams Accountable |
| :---- | :---- | :---- |
| Time-to-Baseline | \<8 weeks | New service → evidence flowing → signals active → Copilot ready |
| PR Merge Rate | \>80% | Autopilot PRs merged within 2 weeks (requires DX quality) |
| MTTR | \<2 hours | Incident → root cause identified → resolution |
| Evidence Gap Rate | \<5% | Incidents without sufficient evidence for RCA |

### **2.4.2 Pod Structure (M9+)**

Teams maintain functional ownership but operate as pods in the flywheel:

1. Evidence Pod (Platform Core): Ensures evidence flows for all instrumented services  
2. Signal Pod (Signal Processing): Computes health signals, creates incidents  
3. Copilot Pod (AI & Intelligence): Delivers RCA, identifies instrumentation gaps  
4. Autopilot Pod (Autopilot): Closes gaps identified by Copilot, maintains coverage

# **3\. Detailed Staffing Profiles**

## **3.1 Total Headcount by Phase**

| Role Type | Phase 1 | Phase 2 | Phase 3 |
| :---- | :---- | :---- | :---- |
| Engineers | 14 | 20 | 20 |
| Engineering Managers | 2 (shared) | 4 | 4 |
| Staff+ Architect | 1 | 1 | 1 |
| **Total** | **17** | **25** | **25** |

## **3.2 Critical Hiring Priorities**

The following roles are critical path and should be prioritized:

| Priority | Role | Why Critical | Hire By |
| :---- | :---- | :---- | :---- |
| **P0** | Staff Architect | Cross-team technical decisions | Before M1 (ideally in place) |
| **P0** | Kafka/Streaming Lead | Evidence Bus is critical path | M1 Week 1 |
| **P0** | LLM/Prompt Engineer | RCA Copilot and Autopilot both need | M1 Week 2 |
| **P1** | Neptune/Graph Engineer | Knowledge Plane for RCA | M2 |
| **P1** | AST/Code Analysis Engineer | Autopilot pattern detection | M2 |
| **P2** | Additional Signal Engineers (2) | Scale for Phase 2 | M4 |

## **3.3 Skill Matrix**

Required skills across the organization with minimum headcount per skill:

| Skill Domain | Min HC | Primary Team | Notes |
| :---- | :---- | :---- | :---- |
| Kafka / MSK / Streaming | 3 | Platform Core | Critical for Evidence Bus |
| Kubernetes / EKS | 2 | Platform Core | All services run on EKS |
| DynamoDB / Data Modeling | 2 | Platform Core \+ Signal | State stores, registry |
| Neptune / Gremlin | 2 | Signal Processing | Knowledge Plane |
| Stream Processing (Flink/Spark) | 2 | Signal Processing | Signal Engines |
| LLM Integration / Prompt Eng | 2 | AI & Intelligence | Copilot \+ Autopilot code gen |
| AST / Static Analysis | 2 | Autopilot | Pattern detection, code gen |
| Python (Advanced) | 6 | All teams | Primary language |
| Java/Scala | 2 | Autopilot | For instrumenting JVM repos |

# **4\. Milestone Ownership Matrix**

## **4.1 Phase 1 Milestones (M1-M3)**

| Mo | Milestone | Owner | Contributors | Success Criteria |
| :---- | :---- | :---- | :---- | :---- |
| **M1** | Infrastructure Foundation | Foundation Team | \- | EKS, Kafka 64 partitions live |
| **M1** | Policy Enforcer G1 | Tiger Team | Foundation | Resolution gate operational |
| **M1** | RCA Copilot Foundation | Tiger Team | \- | LLM integration, basic prompts |
| **M1** | Autopilot Infrastructure | Autopilot Seed | \- | GitHub App, AST libs installed |
| **M2** | Policy Enforcer G2 (Identity) | Tiger Team | \- | Producer attribution working |
| **M2** | Freshness \+ Contract Engines | Tiger Team | \- | 5-min windows, breach detection |
| **M2** | Neptune Graph Model | Tiger Team | Foundation | Incident correlation queries |
| **M2** | Baseline Scanner v1 | Autopilot Seed | \- | Python/Java pattern detection |
| **M3** | Policy Enforcer G4 (Contract) | Tiger Team | \- | Contract validation operational |
| **M3** | RCA for Orders Domain | Tiger Team | All | \>70% accuracy on pilot incidents |
| **M3** | First 3 Repos Instrumented | Autopilot Seed | Tiger Team | PRs merged, evidence flowing |

## **4.2 Phase 2 Milestones (M4-M8)**

| Mo | Milestone | Owner | Contributors | Success Criteria |
| :---- | :---- | :---- | :---- | :---- |
| **M4** | Volume \+ DQ Engines | Signal Processing | \- | All 5 engines operational |
| **M4** | Alerting Integration | Signal Processing | AI & Intelligence | PagerDuty/Slack alerts |
| **M5** | Contract Inference Engine | Autopilot | Platform Core | Auto-generate YAML drafts |
| **M5** | Policy Enforcer G3 (Schema) | Platform Core | \- | Schema validation active |
| **M6** | Push Phase Tier-1 Complete | Autopilot | All | \>80% Tier-1 coverage |
| **M6** | Blast Radius Analysis | AI & Intelligence | Signal Processing | Downstream impact shown |
| **M7** | SCA Lineage Integration | AI & Intelligence | Platform Core | Column-level lineage for RCA |
| **M7** | Pull Model Activation | Autopilot | AI & Intelligence | Evidence failures → PRs |
| **M8** | Anomaly Detection Engine | Signal Processing | \- | ML-based thresholds |
| **M8** | Similar Incident Retrieval | AI & Intelligence | Signal Processing | Historical pattern matching |

## **4.3 Phase 3 Milestones (M9-M12)**

| Mo | Milestone | Owner | Contributors | Success Criteria |
| :---- | :---- | :---- | :---- | :---- |
| **M9** | CI/CD Migration Gate | Platform Core | Autopilot | Contract checks in CI |
| **M9** | Remediation Suggestions | AI & Intelligence | Autopilot | Copilot suggests fixes |
| **M10** | Multi-Region DR | Platform Core | Signal Processing | RPO \<1h, RTO \<15min |
| **M10** | Contract Versioning | Platform Core | \- | Grace periods, rollback |
| **M11** | Self-Service Portal | AI & Intelligence | All | Teams onboard without tickets |
| **M11** | Tier-2 Coverage Complete | Autopilot | \- | \>80% Tier-2 instrumented |
| **M12** | Production Hardening | Platform Core | All | Chaos tested, SLOs published |
| **M12** | Self-Sustaining Flywheel | **All Teams** | \- | \<8 weeks baseline, \>80% merge |

# **5\. Risk Mitigation Strategy**

## **5.1 Risk Register**

| Risk | Likelihood | Impact | Mitigation | Owner |
| :---- | :---- | :---- | :---- | :---- |
| Key hire delays | High | High | Start recruiting M-2; contractor backfill | Engineering Manager |
| Schema drift mid-flight | Medium | High | Version contracts; grace periods | Platform Core |
| LLM accuracy insufficient | Medium | High | Human-in-loop fallback; prompt iteration | AI & Intelligence |
| PR merge rate too low | High | Medium | Executive mandate; merge SLAs | Staff Architect \+ Leadership |
| Evidence Bus bottleneck | Low | High | Autoscaling from M1; capacity testing | Platform Core |
| Integration delays at Phase 2 | Medium | Medium | Weekly integration syncs; contract tests | Staff Architect |
| Domain team resistance | High | Medium | Champions program; demonstrate value early | Product/Leadership |

## **5.2 Hidden Assumptions (5 Whys Analysis)**

### **Assumption 1: Teams can reconfigure smoothly between phases**

* Why might this fail? Engineers may resist temporary reassignment.  
* Why resistance? Career growth tied to team identity, not mission.  
* Mitigation: Communicate that Phase 1 is time-boxed (12 weeks). Recognition tied to mission success, not team membership.

### **Assumption 2: Executive mandate for PR merge SLA will be enforced**

* Why might this fail? Domain teams have competing priorities.  
* Why competing priorities? Observability is seen as optional.  
* Mitigation: Tie observability compliance to production deployment approval (CI gate in M9).

### **Assumption 3: Orders domain is representative**

* Why might this fail? Other domains may have unique patterns.  
* Why unique patterns? Different tech stacks, batch vs. streaming.  
* Mitigation: Phase 2 onboards Finance domain (different patterns) to validate generalization.

## **5.3 Contingency Plans**

| If This Happens... | Then We... | Decision Point |
| :---- | :---- | :---- |
| M3 success gate not met | Extend Phase 1 by 4 weeks; add 2 engineers to Tiger Team | M3 Week 3 checkpoint |
| Autopilot PR quality too low | Switch to human-assisted mode; LLM generates drafts, humans finalize | If merge rate \<50% at M6 |
| LLM costs exceed budget | Implement caching layer; use smaller models for simple cases | Monthly cost review |
| Key person leaves | Bus factor mitigation: pair programming, documentation, cross-training | Ongoing |
| Scope creep from stakeholders | Defer to Phase 2/3; protect critical path ruthlessly | Weekly prioritization |

# **6\. Governance Model**

## **6.1 Decision Rights**

| Decision Type | Decision Maker | Consulted |
| :---- | :---- | :---- |
| Architecture decisions (cross-team) | Staff Architect | All team leads |
| Evidence schema changes | Platform Core Lead | Signal Processing, AI & Intelligence |
| Hiring prioritization | Engineering Director | EMs |
| Phase transition (go/no-go) | Engineering Director | Staff Architect, all EMs |
| Team-internal technical decisions | Team Lead / EM | Team members |
| PR merge SLA enforcement | VP Engineering | Domain team leads |

## **6.2 Meeting Cadence**

| Meeting | Frequency | Attendees | Purpose |
| :---- | :---- | :---- | :---- |
| All-Hands Sync | Weekly (30min) | All engineers | Progress, blockers, wins |
| Architecture Guild | Weekly (1hr) | Leads \+ Architect | Cross-team technical decisions |
| Integration Checkpoint | Weekly (30min) | Team leads | Contract/dependency review |
| Leadership Review | Bi-weekly (1hr) | Director \+ EMs | Milestone tracking, risks |
| Phase Retrospective | End of phase | All | Learnings, process improvements |

## **6.3 Escalation Path**

5. Team-level blocker: Team Lead attempts resolution within 24 hours  
6. Cross-team blocker: Architecture Guild discussion at next session (or ad-hoc if urgent)  
7. Resource/priority conflict: Engineering Director makes call within 48 hours  
8. External dependency (domain teams): VP Engineering engages peer leadership

# **7\. Success Metrics Dashboard**

## **7.1 Leading Indicators (Track Weekly)**

| Metric | Phase 1 Target | Phase 2 Target | Phase 3 Target |
| :---- | :---- | :---- | :---- |
| Evidence events/day | 100K | 10M | 50M+ |
| Datasets with contracts | 10 (Orders) | 50 (Tier-1) | 100+ (Tier-1+2) |
| PRs created/week | 5-10 | 25-50 | 10-20 (steady) |
| PR merge rate | \>60% | \>75% | \>80% |
| Incidents with RCA | First 10 | 100+ | All Tier-1 |

## **7.2 Lagging Indicators (Track Monthly)**

| Metric | Baseline | M6 Target | M12 Target |
| :---- | :---- | :---- | :---- |
| MTTR (pilot domains) | \~4 hours | \<3 hours | \<2 hours |
| RCA accuracy | N/A | \>70% | \>80% |
| Time-to-baseline (new svc) | N/A | \<12 weeks | \<8 weeks |
| Platform availability | N/A | \>99% | \>99.9% |
| False positive alert rate | N/A | \<30% | \<20% |

# **8\. Appendix**

## **8.1 Glossary**

| Term | Definition |
| :---- | :---- |
| **Evidence** | Per-record validation result (PASS/FAIL) emitted by Policy Enforcer |
| **Signal** | Aggregated health metric computed over time windows by Signal Engines |
| **Tiger Team** | Cross-functional team formed temporarily to achieve a specific mission |
| **Flywheel** | Self-reinforcing loop: evidence → signals → Copilot → Autopilot → better evidence |
| **Push Model** | Proactive instrumentation of repos before failures occur |
| **Pull Model** | Reactive instrumentation triggered by evidence gaps |
| **Time-to-Baseline** | Duration from new service deploy to full observability coverage |

## **8.2 Infrastructure Cost Estimate**

| Component | Monthly Cost | Notes |
| :---- | :---- | :---- |
| EKS (Enforcer \+ Engines) | \~$3,000 | Autoscaling |
| Amazon Neptune | \~$4,000 | Knowledge Plane |
| DynamoDB | \~$2,000 | State stores |
| MSK (Evidence Bus) | \~$3,000 | 64-256 partitions |
| LLM API (Claude) | \~$2,000 | Rate-limited |
| S3, CloudWatch, Misc | \~$1,000 | \- |
| **Total Estimated Monthly** | **\~$15,000** | \- |

*— End of Document —*