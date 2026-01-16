# SCA Lineage Integration - Quick Reference Card

## 🎯 The Big Picture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                                                                         │
│   SCA answers: "What SHOULD this code read/write?"  (Design-time)       │
│                                                                         │
│   Enforcer answers: "What ACTUALLY happened?"       (Runtime)           │
│                                                                         │
│   Lineage + Incident → "Who is IMPACTED?"          (RCA)               │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 📝 What SCA Team Must Deliver

### Minimum Viable (MUST)

| Requirement | Description |
|-------------|-------------|
| **LineageSpec v1** | Emit to `signal_factory.lineage_specs` Kafka topic |
| **Dataset-level lineage** | inputs[] and outputs[] with dataset URNs |
| **Column-level lineage** | column_urns[] for ≥70% of Tier-1 producers |
| **Confidence scoring** | HIGH/MEDIUM/LOW with coverage percentages |
| **Immutability** | Never overwrite specs; new commit = new spec |
| **Commit linkage** | `ref.ref_value` must match deployment commit SHA |

### Strongly Recommended (SHOULD)

| Requirement | Description |
|-------------|-------------|
| **Transform hints** | `output_column` ← `input_columns[]` mappings |
| **Dynamic SQL flagging** | Mark LOW confidence when SQL is dynamic |
| **Backfill support** | On-demand generation for existing producers |

---

## 📦 LineageSpec Format (Minimum)

```json
{
  "spec_version": "1.0",
  "lineage_spec_id": "lspec:<producer>:git:<commit_sha>",
  "emitted_at": "ISO8601 timestamp",
  
  "producer": {
    "type": "JOB|SERVICE",
    "name": "orders-delta-landing",
    "platform": "SPARK|AIRFLOW|DBT|FLINK|CUSTOM",
    "runtime": "EMR|EKS|GLUE|DATABRICKS|SNOWFLAKE|OTHER",
    "owner_team": "checkout-platform",
    "repo": "github:org/repo",
    "ref": {
      "ref_type": "GIT_SHA",
      "ref_value": "9f31c2d"  ← CRITICAL: Must match deployment
    }
  },
  
  "lineage": {
    "inputs": [{
      "dataset_urn": "urn:dp:orders:order_created:v1",
      "column_urns": ["urn:col:urn:dp:orders:order_created:v1:payment_method"]
    }],
    "outputs": [{
      "dataset_urn": "urn:dp:orders:order_created_curated:v1",
      "column_urns": ["urn:col:urn:dp:orders:order_created_curated:v1:payment_method_norm"]
    }]
  },
  
  "confidence": {
    "overall": "HIGH",
    "reasons": ["STATIC_SQL", "SPARK_DF_ANALYSIS"],
    "coverage": {
      "input_columns_pct": 0.92,
      "output_columns_pct": 0.88
    }
  }
}
```

---

## 🔗 URN Formats

| Type | Format | Example |
|------|--------|---------|
| **Dataset** | `urn:dp:<domain>:<dataset>:v<major>` | `urn:dp:orders:order_created:v1` |
| **Column** | `urn:col:<dataset_urn>:<column>` | `urn:col:urn:dp:orders:order_created:v1:payment_method` |
| **LineageSpec** | `lspec:<producer>:git:<sha>` | `lspec:orders-delta-landing:git:9f31c2d` |

---

## 📊 Confidence Levels

| Level | When to Use | Example |
|-------|-------------|---------|
| **HIGH** | Static SQL, resolved DataFrame plan | `SELECT customer_id, order_id FROM orders` |
| **MEDIUM** | Star expansion resolved, some config | `SELECT * FROM ${config.table}` (table resolved) |
| **LOW** | Dynamic SQL, reflection, UDFs | `spark.sql(buildQuery(params))` |

**Golden Rule:** Never pretend certainty. Mark LOW and explain why.

---

## 🚀 Delivery

### Kafka (Recommended)
```
Topic: signal_factory.lineage_specs
Key: lineage_spec_id
Value: LineageSpec JSON
```

### S3 (Alternative)
```
s3://<bucket>/lineage/specs/<org>/<repo>/<commit_sha>/lineage_spec.json
```

### SLOs

| Tier | Emission Cadence | Latency |
|------|------------------|---------|
| Tier-1 | Every merge to main | < 1 hour |
| Tier-2 | Every merge to main | < 4 hours |
| Other | Daily minimum | < 24 hours |

---

## ❌ What SCA Should NOT Do

| Anti-Pattern | Why |
|--------------|-----|
| Emit per-run lineage | Cardinality explosion |
| Block deployments on lineage | Creates brittleness |
| Resolve dataset URNs independently | Signal Factory owns URN mapping |
| Omit LOW confidence silently | Misleads RCA |
| Overwrite specs in place | Loses history |

---

## ✅ Definition of Done

- [ ] LineageSpec v1 emitting to Kafka/S3
- [ ] 90% dataset-level coverage for Tier-1
- [ ] 70% column-level coverage for Tier-1
- [ ] LOW confidence properly marked
- [ ] Backfill support working
- [ ] Commit SHA linkage verified

### Steel Thread Test

Pass when RCA can show:
1. Which column was removed
2. Which jobs read that column
3. What version each job was running

---

## 📞 Contacts

| Team | Responsibility | Contact |
|------|----------------|---------|
| SCA | LineageSpec generation | [SCA Team] |
| Signal Factory | Ingestion, storage, RCA | [Signal Factory Team] |
