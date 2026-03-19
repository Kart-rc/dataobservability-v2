# Recommendation Memo: Move Toward an Independent Application for Team 2

## Purpose

This document consolidates the recommendation for moving from a shared monolithic UI toward an **independent application** for Team 2. It is intended for application teams, architects, and engineering leaders evaluating the long-term target architecture.

The recommendation is grounded in the scenarios discussed:

- the current UI is a monolith
- two teams support distinct functional areas
- release coordination and PR approval friction are high
- the initiatives are increasingly separate
- product direction, users, and operational concerns are diverging
- the current implementation is an Angular monorepo
- the decision is strategic and long-term, not just tactical

---

## Executive Summary

### Recommendation

**Adopt an Independent Application for Team 2 as the long-term target architecture** when the divergence across product, users, and operations is real and durable.

### Why

A separate application is the better choice when:

- the two areas are evolving into **different product surfaces**
- the two areas increasingly serve **different user groups**
- the two areas need to be **released, supported, monitored, and operated differently**
- the cost of preserving a shared runtime and shell is becoming higher than the value of a unified experience

### Core reasoning

A Vertical MFE is strongest when the organization wants to **split implementation while keeping the product together**.

A Separate Application is strongest when the business is already moving toward **two distinct experiences**, and the architecture should reflect that reality.

---

## Current Problem Statement

Today, the UI exists as a shared monolith in an Angular monorepo. Two teams support different capabilities inside the same application.

### Current pain points

- shared release cadence
- cross-team PR approvals
- ownership friction
- difficulty moving at different speeds
- growing mismatch between the needs of the two functional areas

### Visual picture of the current state

```text
+------------------------------------------------------------------+
|                         MONOLITH UI APP                          |
|                                                                  |
|   +--------------------------+   +-----------------------------+  |
|   | Team 1 functionality     |   | Team 2 functionality       |  |
|   | same repo                |   | same repo                  |  |
|   | same release             |   | same release               |  |
|   | shared approvals         |   | shared approvals           |  |
|   +--------------------------+   +-----------------------------+  |
|                                                                  |
|   Friction: release coordination, PR bottlenecks, ownership blur |
+------------------------------------------------------------------+
```

---

## Why the Decision Has Shifted Toward Separate Application

At first, a Vertical MFE can appear attractive because it promises team autonomy while preserving one application experience. However, the recommendation changes materially when the following three dimensions diverge together:

1. **Product divergence**
2. **User divergence**
3. **Operational divergence**

When all three are present, the problem is no longer just modularization. It becomes a product and operating-model separation problem.

---

## 1. Product Divergence

### What it means

The two functional areas are no longer simply features inside one cohesive product. They are evolving toward different goals, priorities, and UX styles.

### Typical signals

- different roadmaps
- different stakeholder priorities
- different success metrics
- different UX patterns
- different change velocity

### Example

Suppose the monolith contains:

- **Team 1:** customer onboarding / guided plan setup
- **Team 2:** internal case review / exception handling

Over time:

- Team 1 optimizes for guided flow, clarity, completion, and lower cognitive load
- Team 2 optimizes for queue handling, throughput, analyst productivity, and operational speed

These are not simply different screens. They are different product experiences with different design goals.

### Why this matters architecturally

If two areas need very different UX models, a shared host shell starts to become a constraint instead of a benefit.

---

## 2. User Divergence

### What it means

The two areas increasingly serve different users or user personas, with less overlap in daily workflow.

### Typical signals

- different personas
- different permissions
- low cross-navigation between areas
- different usage patterns and frequency
- different entry points

### Example

Continuing the example:

- Team 1 supports customer-facing or advisor-facing users
- Team 2 supports internal operations or compliance analysts

If the same user is no longer naturally moving between both experiences, the value of preserving one shared app shell drops significantly.

### Why this matters architecturally

A unified application has strong value when there is a coherent end-to-end user journey. That value declines when the user bases are separate.

---

## 3. Operations Divergence

### What it means

The two areas no longer want to be **run the same way in production**, even if they still live in the same codebase.

Operations divergence is about how software is:

- released
- deployed
- monitored
- supported
- secured
- rolled back
- audited

### Typical signals

- different release cadence
- different incident urgency
- different support ownership
- different observability requirements
- different availability expectations
- different security and audit needs
- different rollback needs

### Why it matters

This is often the strongest reason to choose separate applications. Two systems may both be UIs, but if they require different operating models, shared runtime structure becomes friction.

### Example 1: release cadence

Team 1:
- slower, controlled releases
- more regression validation
- customer-facing stability

Team 2:
- faster changes
- urgent fixes
- operational responsiveness

In one shared app, these two models fight each other.

### Example 2: incident model

Team 1 incidents:
- UX or conversion issues
- less operational urgency

Team 2 incidents:
- queues blocked
- analysts impacted
- urgent workflow repair needed

These two systems want different incident response patterns.

### Example 3: observability model

Team 1 cares about:
- page load
- funnel completion
- user drop-off
- interaction quality

Team 2 cares about:
- queue latency
- case transition failures
- action completion time
- audit event correctness

These are different observability needs and often imply different dashboards, alerting, and ownership models.

### Example 4: access and audit controls

Team 2 may need:
- stricter role-based entitlements
- deeper audit logging
- more sensitive workflows
- action-level security tracking

This can be materially different from Team 1’s access model.

---

## Why Vertical MFE Becomes Weaker in This Scenario

Vertical MFE is a good architecture when the company still wants one product experience, but needs cleaner domain ownership.

It becomes weaker when product, users, and operations are diverging in durable ways.

### Visual intuition

```text
MFE = split the code, keep the product together
Separate App = split the product because the business already has
```

### Common MFE failure mode: distributed monolith

A Vertical MFE can look independent on paper but still remain coupled through:

- shell ownership
- routing assumptions
- auth/session patterns
- global navigation
- permissions contracts
- shared runtime and dependency constraints

### Example scenario

Team 2 wants to launch a new workflow.

To do that, they still need:

- host shell updates
- navigation updates
- route registration updates
- shared permission changes
- shared context changes
- cross-team coordination

This means the team has code separation, but not true operational autonomy.

### Practical downside

Instead of one monolith, you can end up with a **distributed monolith**: multiple UI pieces that still need coordinated change.

---

## Detailed Case for Separate Application

A separate application gives Team 2 a cleaner boundary across architecture, ownership, and operations.

### What Team 2 gains

- independent release cadence
- independent deployment lifecycle
- independent production support model
- independent UX model
- independent observability dashboards and alerts
- independent access-control evolution
- smaller blast radius for changes
- clearer ownership and accountability

### Visual picture

```text
                  +----------------------------------+
                  | Shared Enterprise Capabilities   |
                  | SSO | Design System | Branding   |
                  +----------------------------------+

                        /                        \
                       /                          \

     +--------------------------------+    +--------------------------------+
     | Team 1 Application             |    | Team 2 Application             |
     | Own UX model                   |    | Own UX model                   |
     | Own release                    |    | Own release                    |
     | Own deployment                 |    | Own deployment                 |
     | Own observability              |    | Own observability              |
     +--------------------------------+    +--------------------------------+
```

### Important nuance

Separate application does **not** mean everything must be duplicated.

The applications can still share enterprise-level capabilities such as:

- SSO/authentication platform
- shared design system
- branding and visual standards
- common analytics conventions
- common UI component library where sensible
- shared API standards
- shared engineering guardrails

The separation should happen at the **application runtime and operating model**, not necessarily at every library.

---

## Scenarios Where Separate Application Is the Right Choice

### Scenario A: Different product journeys

**Example**

- Team 1 app: customer onboarding
- Team 2 app: internal case operations

These journeys are no longer part of one coherent experience.

**Why separate app fits**
- different UX principles
- different business outcomes
- different release urgency

---

### Scenario B: Different user populations

**Example**

- Team 1: customer success / advisor users
- Team 2: operations and compliance analysts

These users have different goals, behaviors, and access needs.

**Why separate app fits**
- no strong value in one shared shell
- different navigation models are acceptable
- product optimization can be tailored per user group

---

### Scenario C: Different operational urgency

**Example**

- Team 1 changes are planned and reviewed carefully
- Team 2 needs rapid hotfixes because operations workflows break under live conditions

**Why separate app fits**
- independent release pipeline
- lower blast radius
- faster rollback for Team 2

---

### Scenario D: Different observability and support models

**Example**

Team 1 monitors:
- funnel conversion
- UX quality
- performance by page

Team 2 monitors:
- queue latency
- stuck actions
- operational workflow failures
- audit correctness

**Why separate app fits**
- each team can define fit-for-purpose dashboards, alerts, and runbooks
- support ownership becomes clearer

---

### Scenario E: Different access and compliance needs

**Example**

Team 2 needs:
- privileged action approval paths
- more auditing
- tighter entitlements
- stricter user session handling

**Why separate app fits**
- security and audit controls can evolve without being constrained by the consumer experience model

---

## Example: End-to-End Narrative

### Current monolith

```text
Angular Monolith
  ├── Customer onboarding
  └── Operations case management
```

### Team 1 operating model
- customer-facing
- guided UX
- careful releases
- broader regression testing
- optimize for completion and usability

### Team 2 operating model
- internal tool
- dense workflow UX
- quick operational updates
- faster incident response
- optimize for throughput and analyst productivity

### What happens if kept in one MFE shell

- navigation ownership becomes a debate
- release cadence becomes a compromise
- shell and route dependencies persist
- customer-facing and ops-facing UX models fight each other
- shared runtime means larger blast radius during incidents

### What happens with separate applications

- Team 1 can optimize for guided customer experience
- Team 2 can optimize for operational console efficiency
- each team can release on its own schedule
- each app can have tailored observability and support models
- ownership becomes clearer

---

## Decision Framework

### Choose Vertical MFE when

- it is still meaningfully one product
- users naturally move across both domains
- operations are mostly shared
- you want gradual separation without changing the perceived product boundary

### Choose Separate Application when

- product direction is materially different
- users are materially different
- operating model is materially different
- teams need true autonomy, not just code ownership separation
- the value of one shell is lower than the coordination cost it introduces

---

## Decision Matrix

| Criterion | Vertical MFE | Separate Application |
|---|---:|---:|
| Preserves one product experience | 5 | 2 |
| Supports current tight coupling | 5 | 2 |
| Supports gradual migration | 5 | 2 |
| Supports diverged product strategy | 3 | 5 |
| Supports diverged user journeys | 3 | 5 |
| Supports separate operations model | 2 | 5 |
| Enables true team autonomy | 3 | 5 |
| Aligns to durable long-term divergence | 3 | 5 |

### Interpretation

If the organization still wants one product and one operating model, Vertical MFE is the better fit.

If the organization is moving toward different products, users, and operations, Separate Application becomes the stronger long-term architecture.

---

## Risks and Trade-offs of a Separate Application

A separate app is the recommended target in this scenario, but it is not free. Teams should understand the trade-offs.

### Costs and challenges

- higher initial split effort
- need to define and preserve shared enterprise capabilities cleanly
- possible duplication of some bootstrap/application concerns
- need for stronger cross-app standards for consistency
- migration requires careful planning around routing, auth, and user transition

### Why the trade-off is still worth it here

Because the organization is already paying a coordination tax inside the monolith, and the divergence signals suggest that tax will increase over time.

In other words: the split cost is upfront, but the current friction is recurring.

---

## Recommended Architecture Principles

If moving toward a separate application, align on these principles:

### 1. Separate runtime, shared enterprise foundations
Keep application runtime and deployment independent, but share enterprise concerns where valuable.

### 2. Avoid accidental recoupling
Do not recreate hidden coupling through broad “shared utilities” that encode domain assumptions for both teams.

### 3. Share only what is truly platform-level
Good candidates for sharing:
- authentication integration
- design tokens
- common UI components
- logging and telemetry conventions
- API client standards

Bad candidates for sharing:
- domain logic
- cross-team business models
- workflow-specific helpers
- assumptions about navigation or screen lifecycle

### 4. Align ownership to product and operations
Each application should have a clear owning team for:
- roadmap
- release
- support
- incident response
- production quality

### 5. Design for low-friction user transition if needed
If users occasionally move between both apps, support that through:
- consistent branding
- SSO/session continuity
- cross-links where appropriate
- aligned design system

---

## Practical Team-Level Guidance

### For Team 1
Preserve focus on:
- customer or primary user journey
- guided experience quality
- product consistency
- stable release process

### For Team 2
Design around:
- operational efficiency
- workflow speed
- rapid update capability
- tailored observability
- stronger operational controls

### For both teams
Agree explicitly on:
- what is shared
- what is independent
- ownership boundaries
- change approval boundaries
- cross-app user handoff patterns

---

## Leadership-Ready Conclusion

The recommendation is to move toward an **Independent Application for Team 2** because the architectural boundary is now supported by three reinforcing realities:

1. **Product divergence**  
   The two areas are evolving toward different goals, UX patterns, and roadmaps.

2. **User divergence**  
   The two areas increasingly serve different personas with different workflows.

3. **Operations divergence**  
   The two areas need different release, support, monitoring, access, and incident models.

When these three dimensions diverge together, preserving a shared runtime through Vertical MFE often keeps the coordination cost without preserving enough user or business value.

A separate application better aligns the system to the emerging business reality.

---

## One-Line Takeaway

```text
Choose Separate Application when the teams are no longer just building different features —
they are building, running, and supporting different product surfaces.
```
