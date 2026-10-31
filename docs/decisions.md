# Architectural and research decisions

Reviewed 31 October 2026. This records adopted baseline choices and proposed sequencing;
it does not approve implementation of future phases. See [open questions](open-decisions.md).

| Decision | Status and rationale | Consequence / trade-off |
| --- | --- | --- |
| Keep the frozen TechJam 50k catalogue | Adopted; data-only reuse authorised, avoiding a changing comparison corpus | Mostly clothing/shoes/jewellery; broader domain transfer remains untested |
| Import product records and image URLs only | Adopted; original implementation/configuration/sessions remain outside this project | No legacy history, embeddings or model assets are silently reused |
| Direct bounded orchestration | Implemented; the baseline does not require a framework | Explicit policy/context/tool/storage contracts must remain maintainable |
| JSONL authority and JSON snapshots | Implemented for trusted local CLI use; history and corrections are inspectable | Single-writer POSIX design, not authenticated hosting or a transactional database |
| DeepSeek as first adapter | User-selected and implemented; transport tested with mocks | Live compatibility/quality and spend remain unverified; later adapters use the policy interface |
| FTS5/BM25 first | Implemented; deterministic lexical retrieval provides a measurable starting point | Limited semantic recall; explicit attributes are sparse and category matching is literal |
| Enforce stored hard needs outside the LLM | Implemented; generated proposals do not define product truth | Incorrect/missing requirement extraction is still possible and needs evaluation |
| Keep session, user and experience memory distinct | Session layer implemented; remaining layers deferred | Personalization and transferable procedural improvement must be measured separately |
| Evaluate before retrieval tuning and persistent memory | Recommended roadmap sequence | Requires independently defined truth, validated simulation and preserved baseline versions |
| Require evidence before promoting experience | Future design principle | A plausible summary or successful source episode alone does not establish a transferable lesson |
| Prefer permitted strategy/configuration choices before code edits | Future roadmap direction | Trusted execution/gates remain even when policy choice expands; code experiments require isolation |
| Complete Milestone 1 with mocked provider tests | User-selected validation boundary | No subsequent live requests are authorised merely by recording a roadmap |

Milestone implementation was merged in [PR 1](https://github.com/YangXu624/self-improving-agent/pull/1);
user-supplied coding guidance was merged in [PR 2](https://github.com/YangXu624/self-improving-agent/pull/2).
Subsequent phases and merges require separate approval. No UI stack, embedding model, user
memory schema, simulator model or code-experiment sandbox has been chosen here.
