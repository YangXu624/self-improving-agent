# Architectural and research decisions

Reviewed 31 October 2026. This records adopted baseline choices and proposed sequencing;
it does not approve implementation of future phases. See [open questions](open-decisions.md).

| Decision | Status and rationale | Consequence / trade-off |
| --- | --- | --- |
| Keep the frozen TechJam 50k catalogue | Adopted; data-only reuse authorised, avoiding a changing comparison corpus | Mostly clothing/shoes/jewellery; broader domain transfer remains untested |
| Import product records and image URLs only | Adopted; original implementation/configuration/sessions remain outside this project | No legacy history, embeddings or model assets are silently reused |
| Direct bounded orchestration | Implemented; the baseline does not require a framework | Explicit policy/context/tool/storage contracts must remain maintainable |
| JSONL authority and JSON snapshots | Implemented for trusted local CLI use; history and corrections are inspectable | Single-writer POSIX design, not authenticated hosting or a transactional database |
| DeepSeek as first adapter | User-selected; live UI connected and a five-request smoke passed | Broad quality and dollar cost remain unmeasured; later adapters use the policy interface |
| FTS5/BM25 first | Implemented; deterministic lexical retrieval provides a measurable starting point | Limited semantic recall; explicit attributes are sparse and category matching is literal |
| Enforce stored hard needs outside the LLM | Implemented; generated proposals do not define product truth | Incorrect/missing requirement extraction is still possible and needs evaluation |
| Keep session, user and experience memory distinct | Session layer implemented; remaining layers deferred | Personalization and transferable procedural improvement must be measured separately |
| Evaluate before retrieval tuning and persistent memory | Recommended roadmap sequence | Requires independently defined truth, validated simulation and preserved baseline versions |
| Require evidence before promoting experience | Future design principle | A plausible summary or successful source episode alone does not establish a transferable lesson |
| Prefer permitted strategy/configuration choices before code edits | Future roadmap direction | Trusted execution/gates remain even when policy choice expands; code experiments require isolation |
| Complete Milestone 1 with mocked provider tests | Historical validation boundary; user later authorised live integration | Live use is explicit; no runtime script or fallback remains |

Milestone implementation was merged in [PR 1](https://github.com/YangXu624/self-improving-agent/pull/1);
user-supplied coding guidance was merged in [PR 2](https://github.com/YangXu624/self-improving-agent/pull/2).
On 31 October 2026 the user authorised Phase 3 with a mock policy and deferred the two
reviewed Phase 2 defects and live validation. Streamlit is the optional UI dependency: it
reuses the Python application and supports headless UI testing without a separate frontend
stack. Core CLI dependencies remain separate; UI dependency versions have their own lock file.
This does not authorise live provider calls, memory layers, evaluation or merging the UI PR.
No embedding model, user-memory schema, simulator model or code sandbox has been selected.

## Fresh DeepSeek configuration (31 October 2026)

The user supplied a local key and authorised replacing the scripted UI policy. Configuration
parsing is shared between CLI and provider composition. `DeepSeekPolicy.from_env_file` reads
only the explicit project file, with process settings taking precedence, without copying file
secrets into the process environment. This allows a later UI rerun to pick up a changed file
key. The CLI's `load_env` interface remains compatible. Explicit blank credentials fail closed.
The next checkpoint connects the UI and removes the scripted application policy; its results
are recorded below. Test fixtures remain offline and never require the local key.


## Live UI policy (31 October 2026)

The UI now requires the configured DeepSeek policy; the application mock module is deleted.
Historical mock sessions are retained but not reused in the new default live directory.
Fixtures remain exclusively in tests and simulate HTTP, including auth failures and token
usage. There is no fallback policy after API failure. The request shape follows
[DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/) and
[JSON Output](https://api-docs.deepseek.com/guides/json_mode/); the prompt version advances to
v2 for its explicit JSON-shape example. The live smoke used five requests, within a cap of six,
and confirmed budget correction and checked recommendations. This is not a quality study.
