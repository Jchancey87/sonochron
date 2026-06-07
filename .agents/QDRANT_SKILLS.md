# Qdrant Skills — Sonochron Integration Guide

> This document maps official Qdrant agent skills to Sonochron's specific
> architecture and flags actionable improvements for future work sessions.
> 
> Skills live in: `.agents/skills/qdrant/`  
> Upstream source: https://github.com/qdrant/skills

---

## How to Use These Skills

When working on any Qdrant-related code in Sonochron, read the relevant skill
file first. Skills answer **"when?" and "why?"** — they tell you what to do
given a problem, not just how the API works.

```
Sonochron code           →  Relevant skill
─────────────────────────────────────────────────────
backend/app/search.py    →  search-quality, performance-optimization
backend/app/ml.py        →  model-migration
backend/app/pipeline.py  →  clients-sdk, performance-optimization
Any deployment change    →  deployment-options, scaling, version-upgrade
```

---

## Current Qdrant Setup

| Setting         | Value                                         |
|-----------------|-----------------------------------------------|
| Mode            | **Local filesystem** (no server process)      |
| Client version  | `qdrant-client 1.18`                          |
| Storage path    | `backend/qdrant_storage/`                     |
| Collections     | `sonochron_text` (384-dim cosine), `sonochron_audio` (512-dim cosine) |
| Vector IDs      | `entry_id.int` (UUID → Python int)            |
| Distance metric | Cosine (both collections)                     |

> **Important:** Local mode (`QdrantClient(path=...)`) is appropriate for 
> Sonochron's single-node LXC deployment. Per the deployment-options skill:
> *"Do not use local mode for production benchmarking — not optimized."*
> For Sonochron's personal diary scale this is fine. If the collection grows
> beyond ~1M entries, evaluate migrating to a Qdrant Docker server process.

---

## Skill Index & Sonochron Relevance

### 🔍 [Search Quality](skills/qdrant/qdrant-search-quality/SKILL.md)
**Relevance: HIGH** — applies to `GET /api/search` and `GET /api/entries/{id}/similar`

Key sub-skills:
- [Diagnosis](skills/qdrant/qdrant-search-quality/diagnosis/SKILL.md) — use when users report bad search results
- [Search Strategies → Hybrid Search](skills/qdrant/qdrant-search-quality/search-strategies/hybrid-search/SKILL.md) — **priority future work** (see below)
- [Relevance Feedback](skills/qdrant/qdrant-search-quality/search-strategies/relevance-feedback/SKILL.md) — relevant for "similar audio" feature

**Actionable for Sonochron:**
- Currently using **single-vector dense search** (text only for `/api/search`)
- **Hybrid search** (dense + sparse/BM25) would improve keyword-heavy queries like searching by proper nouns, locations, or specific words spoken in recordings
- When enabling hybrid search: collections need to be recreated with **named vectors** (currently using default unnamed vectors) — consult the model-migration skill

---

### ⚡ [Performance Optimization](skills/qdrant/qdrant-performance-optimization/SKILL.md)
**Relevance: MEDIUM** — applies when scaling up or if search latency becomes noticeable

Key sub-skills:
- [Search Speed](skills/qdrant/qdrant-performance-optimization/search-speed-optimization/SKILL.md)
- [Indexing Performance](skills/qdrant/qdrant-performance-optimization/indexing-performance-optimization/SKILL.md)
- [Memory Usage](skills/qdrant/qdrant-performance-optimization/memory-usage-optimization/SKILL.md)

**Actionable for Sonochron:**
- At current scale (personal diary, <10k entries), no optimization needed
- When collections grow: consider **scalar quantization** to reduce memory footprint without significant quality loss
- Upserts in `pipeline.py` happen one-at-a-time per entry — for bulk reindex (`cli.py reindex`), consider batching via `client.upload_points()` with `parallel=4`

---

### 🤖 [Model Migration](skills/qdrant/qdrant-model-migration/SKILL.md)
**Relevance: HIGH** — applies when switching audio embedding model (CLAP/PANNs)

**Critical for the planned CLAP/PANNs swap:**

The current `sonochron_audio` collection uses **unnamed default vectors**. Per the model-migration skill:
> *"You cannot add sparse vectors to an existing collection that uses a default (unnamed) dense vector. Must recreate."*

When switching from librosa → CLAP/PANNs:
1. CLAP typically outputs 512-dim (compatible dimension) but the model space is completely different
2. **Must recreate** `sonochron_audio` with a new collection
3. Use collection aliases to enable zero-downtime swap
4. Re-embed all audio via `python -m app.cli reindex` with new model
5. Per the skill: *"Delete old collection only after verifying new one"*

**Recommended pre-emptive change (before GPU passthrough):**
Switch both collections to use **named vectors** now, while the dataset is small:
```python
# In search.py, change collections to use named vectors:
# VectorParams → {name: "text"} and {name: "audio"}
# This enables zero-downtime model migration later via v1.18+ UpdateVectors API
```
Consult [Update vector schema](https://skills.qdrant.tech/md/documentation/manage-data/collections/?s=update-vector-schema) when implementing.

---

### 📦 [Deployment Options](skills/qdrant/qdrant-deployment-options/SKILL.md)
**Relevance: MEDIUM** — current local mode is correct for now

Current: local mode (`QdrantClient(path="backend/qdrant_storage/")`)

Per the skill: local mode is acceptable for prototyping and small deployments.
If moving to a Docker-based Qdrant server:
- Data format is NOT compatible — must migrate via snapshot or re-index
- Enables clustering, monitoring, and managed backups

---

### 📈 [Scaling](skills/qdrant/qdrant-scaling/SKILL.md)
**Relevance: LOW** — not applicable at personal diary scale

Sub-skills available for future reference:
- [Minimize Latency](skills/qdrant/qdrant-scaling/minimize-latency/SKILL.md)
- [Scaling Data Volume](skills/qdrant/qdrant-scaling/scaling-data-volume/SKILL.md)
- [Scaling Query Volume](skills/qdrant/qdrant-scaling/scaling-qps/SKILL.md)

---

### 📡 [Monitoring](skills/qdrant/qdrant-monitoring/SKILL.md)
**Relevance: LOW-MEDIUM** — useful for debugging search issues

Sub-skills:
- [Debugging](skills/qdrant/qdrant-monitoring/debugging/SKILL.md)
- [Setup](skills/qdrant/qdrant-monitoring/setup/SKILL.md)

**Actionable for Sonochron:**
- Local mode exposes fewer metrics than server mode
- For debugging collection state: use `client.get_collection(name)` to inspect point counts and vector configs
- The `python -m app.cli check-entry <uuid>` command already helps debug per-entry Qdrant state

---

### 🔄 [Version Upgrade](skills/qdrant/qdrant-version-upgrade/SKILL.md)
**Relevance: LOW** — track when upgrading `qdrant-client` pip package

---

### 🛠️ [Clients SDK](skills/qdrant/qdrant-clients-sdk/SKILL.md)
**Relevance: HIGH** — we use the Python SDK in `backend/app/search.py`

Key feature: **code snippet search API**
```bash
# Look up Python SDK examples for any Qdrant operation:
curl "https://skills.qdrant.tech/snippets/search?language=python&query=hybrid+search"
curl "https://skills.qdrant.tech/snippets/search?language=python&query=named+vectors"
curl "https://skills.qdrant.tech/snippets/search?language=python&query=scalar+quantization"
```
Use this before writing any new Qdrant code to get canonical examples.

---

## Priority Future Work (Qdrant-Informed)

### 1. Switch to Named Vectors (Do Soon)
**Why:** Enables zero-downtime model migration for the planned CLAP/PANNs audio upgrade.  
**Skill:** [Model Migration](skills/qdrant/qdrant-model-migration/SKILL.md)  
**Files:** `backend/app/search.py` — change `VectorParams` to named vector config  
**Impact:** Requires collection recreation + `reindex` on the live server (downtime acceptable for personal use)

### 2. Hybrid Search for Text (Future)
**Why:** Improves recall for specific words/names/locations spoken in recordings.  
**Skill:** [Hybrid Search](skills/qdrant/qdrant-search-quality/search-strategies/hybrid-search/SKILL.md)  
**Files:** `backend/app/search.py` `search_text()`, `backend/app/pipeline.py` text_embed stage  
**Requires:** Named vectors (see #1), sparse vector model (BM25/SPLADE)

### 3. Batch Upserts in Reindex (Easy Win)
**Why:** Current `reindex_all()` in `search.py` calls `upsert_entry()` one-at-a-time.  
**Skill:** [Clients SDK — upload_points](skills/qdrant/qdrant-clients-sdk/SKILL.md)  
**Files:** `backend/app/search.py` `reindex_all()`  
**Change:** Use `client.upload_points(collection, points=batch, parallel=4)`

---

## Skills API Reference

The Qdrant skills system has a live code snippet search endpoint:
```
https://skills.qdrant.tech/snippets/search?language=python&query=<your query>
```

Documentation links within skills use the format:
```
https://skills.qdrant.tech/md/documentation/<path>/
```

---

*Integrated: 2026-06-06 | Source: https://github.com/qdrant/skills*
