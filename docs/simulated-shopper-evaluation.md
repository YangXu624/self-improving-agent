# Simulated-shopper evaluation framework

Status (31 October 2026): implemented and tested **offline** with scripted and mocked
components. **No real Ollama conversation, no DeepSeek-driven evaluation run and no result
exist yet**; see [what is verified and what is not](#what-is-verified-and-what-is-not).
Nothing here implements experience memory: memory OFF is the only condition.

## Components and boundaries

```text
catalogue ──generate──▶ scenarios.jsonl  (what the runner and shopper may know)
                        ground_truth.jsonl (scorer only, separate hash-checked file)

Scenario ─▶ DialogueRunner ─▶ ShoppingAgent (ASTRA)   sees only the shopper's messages
               │  ▲                 │
               │  └── ShopperSimulator (scripted | Ollama)   sees profile, ledger, window,
               │                     and ASTRA's visible words and product cards
               ▼
        SessionRecord ─▶ score_session (independent oracle over raw catalogue rows)
               ▼
        results.jsonl, transcripts ─▶ report.json / report.md
```

| Module (`src/astra_eval/`) | Responsibility |
| --- | --- |
| `models.py` | Typed `Fact`, immutable `ShopperProfile`, `Scenario` (no truth), `GroundTruth`, `ShopperReply` |
| `oracle.py` | Independent judge of raw catalogue rows with its own exact rules; unknown never passes |
| `scenarios.py` | Seeded generator, splits by product family, frozen files with hash checks |
| `memory.py` | Shopper session memory: profile, bounded window, ledger, full transcript |
| `consistency.py` | Deterministic checks that the shopper stayed faithful to its profile |
| `simulators.py` | `ScriptedShopper` (offline) and `OllamaShopper` (HTTP), config, connectivity probe |
| `dialogue.py` | Multi-turn loop, per-turn trace taken from ASTRA's own event log |
| `scoring.py` | Hit/Success@K, nDCG@K, violations, turns, resources, failure taxonomy |
| `experiment.py` | Scenarios x conditions, shared hashed config, budgets, circuit breaker |
| `report.py`, `cli.py` | Aggregation, Markdown report, transcript viewer, command line |

The shopping application (`shopping_agent`) never imports this package (a test enforces it).
Ollama is not needed to import, construct or test anything; only `OllamaShopper.respond` and
`check-simulator` make HTTP calls, through an injectable transport.

## Scenarios

Generated from the real catalogue, deterministically for a fixed seed. Product types are
leaf categories with at least 40 priced products where at least 30% of the type's products
have a title containing a stem of a type word; brand-like or demographic leaves are excluded. Hidden **hard** facts (type, budget,
department, sometimes brand or colour) and **soft** preferences (colour, material) come from
attributes the catalogue really contains. The **acceptable set** is computed by the oracle
over the whole catalogue: a product is acceptable only if every hard fact passes on explicit
fields. Missing price or attributes are unknown and never acceptable.

| Kind | Meaning |
| --- | --- |
| `feasible` | The opening states the type and budget; other hidden facts surface when asked |
| `underspecified` | The opening states only the type; budget and more are revealed on request (the ambiguous-requirements case) |
| `no_valid_product` | A verifiably empty variation of a satisfiable task (budget below the cheapest known price, or a colour/brand pair that never co-occurs). Correct behaviour is to abstain |

Splits `learning`, `development`, `held_out` are assigned by **family cluster**: product types
that share a noun ("Necklaces" and "Pendant Necklaces", "Sunglasses" and "Replacement Sunglass
Lenses") are grouped first, because their product scopes overlap, and each cluster stays in one
split. Identical tasks are not generated twice, departments are limited to men/women/boys/girls/
unisex, and no-valid budgets are never absurdly low (a pair variant is used when the cheapest
product costs under $5). Held-out feedback must not be used for learning. Graded relevance:
grade 0 if a hard fact fails or is unknown; otherwise 1-3 by the share of soft preferences
matched (3 when there are none). `ideal_grades` holds the best 20 grades for nDCG.

Files: `scenarios.jsonl` (profiles and openings only), `ground_truth.jsonl` (scorer only) and
`manifest.json` with the seed, catalogue hash and both file hashes. A set is written to a new
directory and never overwritten; loaders reject a file that does not match its manifest.

## The simulated shopper and its memory

The shopper is told its hidden profile (firm vs flexible facts), to reveal at most two facts per
message, never to invent a requirement, never to change an earlier answer, and not to name a
product. Replies are structured: `{"message", "reveals", "action": reply|accept|give_up}`.

**Session memory (consistency only, within one scenario, never across scenarios):**

1. the immutable profile in the system prompt on every call;
2. a bounded window of recent dialogue (`--window-turns`, default 8 exchanges) further trimmed
   oldest-first to a token budget (`num_ctx - max_tokens - 128`, estimated at 3 characters per
   token, which over-counts on purpose); the profile, ledger and current message must fit or
   the call fails with `simulator_context_overflow` instead of truncating them;
3. a compact **ledger built by code**, not by a model: facts already revealed (and when), the
   assistant's recent questions and which of them repeat an answered one, products recently shown.

Reveals are checked before they enter the ledger: a key the model lists but did not actually
state (a price, department or attribute value missing from the message) stays out of the ledger
and is flagged. The window is configurable (default 8 exchanges; the requested 6-10 is the
intended range, any value of at least 1 is accepted and checked when the config is built).

A complete append-only transcript (JSONL) is kept separately for replay and is never sent
whole to the model. There is no vector store, no persistent evaluator memory and no model-written
summary, so nothing generated can override the profile. The shopper cannot see ASTRA's memories,
ground truth, scores or the evaluation condition; tests inspect every payload sent to it.

**Consistency checks** (lexical, so cheap and explainable, not a proof): reveals must name real
profile keys and not exceed two; any price must be in the profile or shown on a card; colour,
material or department words that contradict the profile, or that the profile never mentioned,
are errors (a contradiction of a profile attribute is an error even if ASTRA suggested the
value); an attribute only ASTRA suggested, which the shopper then adopts, is a warning
(`adopted_assistant_suggestion`); a product on a displayed card may be echoed; product
identifiers or target titles ASTRA never displayed are leaks; a reveal whose value is absent
from the message is a warning. An error triggers one re-ask with feedback; a second error makes the
session **invalid** (a simulator fault). Malformed JSON is retried once inside the adapter. All
of this is logged and summarised under "Simulator reliability" in the report, with a warning if
more than 10% of sessions are invalid.

## Metrics and failure handling

Defaults, fixed before any run (change them before a run, never after seeing results):
`K` in {1, 3, 5}, headline `K=3`, turn budget `B` = the scenario's `max_user_turns` (6).

- **Success@K within B** (the "verified task success"): some recommendation by turn B has an
  independently verified acceptable product in its top K. **First-recommendation Hit@K** looks
  only at the first recommendation; no recommendation counts as a miss.
- **Strict success@K**: every item in the top K of some recommendation is verified, reported next
  to the lenient headline. Precision@K of the first recommendation is also kept.
- **nDCG@K** with graded relevance, for the first and the final recommendation; the
  no-recommendation-as-zero version is the headline for both.
- **Hard-violation rate**: share of distinct recommended items failing a hidden hard
  requirement; items with an unknown required attribute and invented IDs are counted separately.
  Success@K is lenient (one hit is enough), so always read it with the violation rate.
- **Turns to first success**: median over successes plus a penalised mean (a failure counts as
  B+1). Failures are never dropped.
- **Searches, clarifications**, plus *redundant* clarifications (re-asking an answered fact) and
  clarifications about nothing in the profile.
- **Resources**: ASTRA model calls and reported tokens (including cache hits), model seconds,
  wall time; cost only if you pass prices (nothing is hardcoded). Simulator tokens and latency
  are reported separately and are not charged.
- **Retrieval diagnostics** (feasible tasks): whether an acceptable product was ever returned to
  the agent, the hard-pass rate of the candidates it saw, hidden hard facts missing from ASTRA's
  stored state, and a failure category: `agent_budget_exhausted`, `agent_error`, `no_search`,
  `recommendation_failure` (acceptable products were returned but not recommended),
  `state_extraction_failure` (ASTRA's requirements never matched the shopper's) or
  `retrieval_failure` (nothing acceptable surfaced).
- **No-valid-product** scenarios are reported separately: correct abstention (nothing recommended
  and no agent error) vs false recommendation. A safe closure after an exhausted search budget
  is **not** an abstention.

**Invalid sessions** (simulator failure, provider error, run budget exhausted) are counted and
excluded from agent-quality denominators because they are not the agent's behaviour; they are
reported with their rate and reasons. Because exclusion can be non-random, the report also shows
the headline success with invalid sessions counted as failures, termination counts per cell
(accepted, gave up, max turns, errors), and for a paired comparison the number of dropped pairs
with reasons plus a worst-case difference. Compare invalid rates across conditions before
trusting a difference. **Agent failures and exhausted per-turn budgets stay in every
denominator.** The scorer never asks the shopper whether it was satisfied; it re-judges every
recommended and returned product from raw catalogue rows. Wilson intervals accompany rates;
with a few dozen sessions these are descriptive, not significance claims.

## Memory OFF vs ON (future)

Each scenario runs under its own ASTRA user ID (`eval-shopper-<scenario id>`), so nothing
user-scoped can leak between scenarios. `run.json` records the decision-policy class, model and
prompt version plus the catalogue and index hashes in the shared config.

`Condition(name, experience)` and `ExperienceSnapshot(snapshot_id, sha256, entries)` define the
seam. Every condition runs the same scenarios (condition order rotates per scenario) with the
same simulator settings, agent bounds, budgets and scoring, asserted by one hashed
`shared_config` stored in `run.json` and on every result. `default_agent_factory` runs the
unchanged ASTRA and raises `NotImplementedError` for a condition with experience; a future
factory injects the frozen snapshot through context construction without changing the harness.
With two conditions the report adds a paired comparison (exact McNemar). Nothing learns or stores
experience yet, and evaluation outcomes must never feed a snapshot.

## Mac setup and running (macOS or Ubuntu)

Requirements: Python 3.11+ (the project is tested on 3.14), Git, Ollama with `llama3.1:latest`,
your DeepSeek key, and the ignored `data/catalogue/` files.

```bash
# 1. Get the branch
git fetch origin
git switch feat/simulated-shopper-eval        # or main once merged
git pull

# 2. Environment (same on macOS and Ubuntu; no Ollama/DeepSeek SDK needed)
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python -m shopping_agent index        # builds data/index/catalogue.sqlite (about 3 s)
cp .env.example .env                            # then put DEEPSEEK_API_KEY=... in this file only

# 3. Verify Ollama and the model, with a structured-output probe (no DeepSeek involved)
ollama list                                     # should show llama3.1:latest
.venv/bin/python -m astra_eval check-simulator
#    exit 0 and "probe_ok": true means the model answered in the required JSON and stated the budget

# 4. Create a frozen scenario set (local, offline, a few seconds)
.venv/bin/python -m astra_eval generate --output data/eval/scenarios/v1

# 5. Plan a single conversation (dry run: prints the plan, contacts nothing)
.venv/bin/python -m astra_eval run --scenarios data/eval/scenarios/v1 --split development \
    --limit 1 --output data/eval/runs/one

# 6. Run it for real (uses paid DeepSeek calls; the cap is mandatory)
.venv/bin/python -m astra_eval run --scenarios data/eval/scenarios/v1 --split development \
    --limit 1 --output data/eval/runs/one --live --max-model-calls 20

# 7. A small batch (6 development sessions; worst case 108 DeepSeek calls, typically far fewer)
.venv/bin/python -m astra_eval run --scenarios data/eval/scenarios/v1 --split development \
    --limit 6 --output data/eval/runs/batch1 --live --max-model-calls 120

# 8. Reports and transcripts
.venv/bin/python -m astra_eval report data/eval/runs/batch1            # also written as report.md
.venv/bin/python -m astra_eval show data/eval/runs/batch1 <scenario-id>
.venv/bin/python -m astra_eval show data/eval/runs/batch1 <scenario-id> \
    --debug-scenarios data/eval/scenarios/v1       # adds the hidden profile and ground truth
```

Useful options: `--simulator scripted` runs the deterministic shopper instead of Ollama (to
check the DeepSeek side only); `--sim-model`, `--sim-url`, `--sim-temperature`, `--sim-seed`,
`--sim-num-ctx`, `--sim-max-tokens`, `--sim-timeout`, `--window-turns` override the
`ASTRA_SIM_MODEL`, `ASTRA_SIM_OLLAMA_URL`, `ASTRA_SIM_TEMPERATURE`, `ASTRA_SIM_SEED`,
`ASTRA_SIM_NUM_CTX`, `ASTRA_SIM_MAX_TOKENS`, `ASTRA_SIM_TIMEOUT`, `ASTRA_SIM_WINDOW_TURNS`
environment variables (defaults: `llama3.1:latest`, `http://127.0.0.1:11434`, temperature 0,
seed 7, context 4096, 220 reply tokens, window 8). `--price-input-per-million` and
`--price-output-per-million` turn on a cost estimate; check DeepSeek's current published prices
yourself. Option values are validated before anything is spent (`--limit`, `--max-model-calls` and
`--turn-budget` must be at least 1, `--headline-k` must be one of `--k`, `--window-turns` at
least 1, a timeout positive); an invalid value prints `error: ...` and exits 2. A live run with
`--simulator ollama` first runs the free `check-simulator` probe and stops before any DeepSeek
call if Ollama is unreachable or the model is missing. A run needs a **new** output directory; an interrupted run is not resumed (start a new
one). `data/` is git-ignored, so scenarios, transcripts and session logs stay local.

Cost control: nothing paid runs without `--live` and `--max-model-calls`. ASTRA allows at most
3 model calls per user turn and 6 user turns per scenario, so the worst case per session is 18
calls; the run stops cleanly when the cap is reached, and after 3 consecutive sessions that end in
a provider error. Expect roughly 3-6 calls per typical session; real token use and cost are
unmeasured until you run it.

### Troubleshooting

| Symptom | Likely cause and fix |
| --- | --- |
| `check-simulator`: "Cannot reach Ollama" | Start the Ollama app or `ollama serve`; test `curl http://127.0.0.1:11434/api/tags`; set `ASTRA_SIM_OLLAMA_URL` if it listens elsewhere |
| "Model not found" | `ollama pull llama3.1` and confirm the name in `ollama list` matches `--sim-model` |
| `simulator_unreachable` or timeouts mid-run | Ollama stopped or the first call is loading the model; raise `--sim-timeout` (e.g. 300) and warm the model with `ollama run llama3.1 "hi"` |
| `simulator_malformed_reply` | The model did not return the JSON schema twice. Use temperature 0, raise `--sim-max-tokens`, re-run `check-simulator`; persistent failures mean this model is unreliable for the task |
| `simulator_inconsistent:<code>` | The shopper contradicted or leaked. `show` the transcript: `invented_attribute`/`contradicts_profile` (it added a colour, material or department), `price_not_in_profile`, `over_reveal`, `target_leak`. A few are normal; the report warns above 10% invalid |
| Many `claimed_reveal_missing` warnings | Only a warning: the model listed a key it did not clearly state |
| `simulator_context_overflow` | `--sim-num-ctx` too small for the profile and ledger; raise it (4096 or more) |
| DeepSeek `provider_http_401/402/429` | Key invalid, balance exhausted or rate limited; the run stops after 3 consecutive provider failures and those sessions are invalid, not agent failures |
| Very high success with the scripted shopper | Expected: it is a trivial rule-based user for plumbing tests, not a quality signal |

## Target-item evaluation mode

Target-item evaluation (`--evaluation-mode target_item`) measures exact-item discovery and grounded abstention, deliberately separate from the preference-based benchmark.

- **Offline catalogue audit (`audit-targets`):** The catalogue audit classifies products using documented explicit fields:
  - 1,554 distinguishable products (unique matching profile across the catalogue)
  - 8,855 ambiguous products (multiple products satisfy the maximal profile)
  - 39,591 products with insufficient evidence (missing prices or ungrounded attributes)
- **Target task generation:** Scenarios are sampled by split using coarse USD budgets (next strictly greater $10 boundary, never an identifying exact price) and explicit category tokens/attributes. Target IDs and titles are stored strictly in `TargetGroundTruth` and never enter the shopping agent or shopper simulator contexts.
- **Early-termination stopping rule:** The dialogue runner halts immediately once ASTRA recommends the target item within primary $K$ ($K \le 5$, default $K=5$). No additional simulated-shopper or shopping-agent calls are made after a target hit.
- **Session call reservation:** `--session-max-model-calls` (default 18) guarantees an identical reservation limit across conditions and terminates safely if reserved calls cannot be made.
- **Conservative disclosure validation (`target-v1`):** Literal word verification normalises NFKC unicode, accounts for negation, canonicalizes color spelling variants (gray/grey), and flags budget operator contradictions (`contradicts_budget_operator`). More than two new facts per turn triggers an `over_reveal` retry error. Unclaimed disclosures are recorded as warnings and added to verified disclosures.
- **Metrics & Reporting:**
  - `hit_at_k_all_started` and `hit_at_k_valid_only`: primary exact-item discovery rate.
  - `first_hit_mrr_at_k`: reciprocal rank of first qualifying hit ($1/\text{rank}$ or $0.0$).
  - `mttc_successes_only` and `penalized_mttc`: mean turns to cutoff (penalized treats failure as turn budget + 1).
  - `cumulative_success_by_turn`: success rate by turn up to horizon.
  - `mean_searches_to_success` and `mean_clarifications_to_success`: agent efficiency.
  - Separate `no_target` grounded abstention reporting for verified-empty impossible tasks.
  - Invalid sessions are recorded safely in results and report tables rather than failing the batch.
  - Paired comparison with exact McNemar test when two conditions are run.

## What is verified and what is not

**Verified offline (mocks and fixtures, 316 tests including strict ResourceWarning mode):**
scenario reproducibility, split disjointness, oracle agreement with the agent gate, scoring
maths and failure taxonomy, shopper memory/ledger/window behaviour over long conversations,
consistency checks, the Ollama adapter request shape, retries and error mapping, connectivity
probe cases, multi-turn dialogues with a real `ShoppingAgent` under test-only decision policies,
budgets and circuit breakers, isolation of ground truth and conditions, the report and CLI.
On the real 50k catalogue, generation (about 5 s) and a 14-session run with the scripted shopper
and a rule-based test policy completed end to end; that run only checks plumbing.

**Not verified until you run it locally:**
- Llama 3.1 behaviour: whether it follows the JSON schema, stays consistent, reveals
  progressively and avoids drift. The checks and reliability section exist to measure this.
- Real DeepSeek behaviour in these dialogues, its token use, latency and cost.
- Whether templated openings and the scripted-shopper phrasing resemble real shoppers.
- Ollama option names against your installed version (`format`, `options.num_ctx/num_predict/seed`).
- That temperature 0 with a fixed seed reproduces replies on your machine.
- Statistical power: a few dozen scenarios give wide intervals.

**Known limitations:**
- The oracle is independent in code but not in semantics: it mirrors the agent gate's notion of
  product type (category-word containment), departments and exact prices, so it catches
  implementation bugs and state-extraction errors, not a shared conceptual mistake. Spot-check
  some acceptable samples by hand before relying on "grounded".
- Family clustering is a word-sharing heuristic, so overlap between clusters can remain (for
  example products tagged with two unrelated types); check it again before a learning study.
- `accept` and `give_up` come from the shopper and end the session, so shopper behaviour can
  shorten conversations; termination counts are reported but not corrected for.
- The kind mix cycles feasible, underspecified, feasible, no-valid, underspecified, feasible, so
  the default held-out set has only 4 no-valid-product scenarios (wide intervals); `--limit` takes
  the first N in file order.
- A malformed-JSON retry appends the bad reply to the prompt without re-checking the token
  budget (unlikely to matter at the default 4096 context).
- Consistency checks are lexical (a paraphrased contradiction can pass; a benign colour word
  can trigger a false alarm). Negation is handled only for the three words after
  "not/no/without/n't"; prices in other currencies ("50 pounds") are not recognised; a 10-digit
  number counts as a possible product identifier. Product-type matching is category-word based;
acceptable sets use historical parent-product data and say nothing about stock or variants; the
shopper sees titles and prices of recommended cards, which is realistic but lets it react to
price; the generator cycles a fixed mix of kinds; there is no resume for interrupted runs.
