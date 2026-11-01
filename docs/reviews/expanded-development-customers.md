# Expanded returning-customer development fixture

Base: merged main `d1dd409`; feature branch `feat/expanded-development-customers`.
Only development data, an offline inventory helper, deterministic tests and documentation change.
No production ASTRA, retrieval, model prompt, simulator, oracle or scoring code is modified.
No live DeepSeek/Ollama requests, lesson activation, held-out changes or automatic merge.

## Provenance and scope

`customers.dev-expanded.json` is a human-directed DEVELOPMENT fixture, not a held-out benchmark.
It preserves the original three customer objects exactly, and adds eight customers / 24 visits:
11 customers / 36 visits total. The original file and CLI default are unchanged.
All new visits use **preference** scoring. Exact witness IDs certify feasibility; they are
not instructions to find one arbitrary exact product. Existing target-item visits remain unchanged.
The oracle also computes compatible-set ambiguity evidence when validating; it is not a new
exact-target endpoint or a primary score for these added visits.

Input SHA-256:

```text
codex_expand_astra_customers.md: 0a2d17533632c967f6abd1c9b4296e6fff471a595079698b5b017aeeb2542c42
astra_customer_profile_blueprints.json: cb07fb1adbba37cb93aed76c1db533f4a4c78a23b8369012369396634a01c363
catalog.jsonl: da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67
customers.dev.json: 38f00c804c1062507429371cf7228f42dc3e55bffd29d94354ebcb9e14746c41
customers.dev-expanded.json: cc087acaf159c3d63a0cbc65fdb7934e6c12ce285d890280d4551874f3650dd4
```

## Catalogue coverage and suitability evidence

The [reproducible inventory](longitudinal-catalogue-inventory.md) covers all 50,000 rows and
800 exact leaf labels, including missing-price and structured color/material coverage.
The existing read-only index reports 50,000 products and the same source hash.
The 24 new visits cover **17 exact leaves and 18 distinct witnesses**: eight clothing visits,
six bag visits, three footwear visits, five jewelry visits, and two accessory controls.
Every chosen witness has a usable price and every scored color has structured `details.Color`
evidence. Size, current availability, fit and material are not asserted or scored.

Every visit has a hard category and strict `price < budget`; colors are soft.
Eligible = all products satisfying hard requirements; best = all satisfying hard + soft.
Both complete sorted ID sets are oracle-hashed into the fixture, with witness source paths.
Counts use the unchanged category-token ontology over the full path, so can exceed leaf counts.
For every new color-scored visit, `0 < best < eligible`; the two no-color controls intentionally
have best = eligible. Grade 1 remains possible for unknown/mismatching soft color, grade 3 for
a match. Thus suitability Success@K alone can hide missing preferences: inspect nDCG,
preference satisfaction, memory audits and actual dialogue as well. No scoring rule was changed.

| Task | Exact leaf | Budget < USD | Color / scope | Eligible / best | Witness |
| --- | --- | ---: | --- | ---: | --- |
| capsule-wardrobe-01 | Active Shirts & Tees | 45 | Black / clothing | 86 / 1 | `B08L5CNVZ6` |
| capsule-wardrobe-02 | Active Hoodies | 110 | Black / clothing | 30 / 1 | `B09SS262CG` |
| capsule-wardrobe-03 | Pants | 60 | Black / clothing | 159 / 1 | `B0BWJKZ9GX` |
| office-basics-01 | Button-Down Shirts | 75 | Cool Grey / shirts | 190 / 1 | `B00QRVNPJE` |
| office-basics-02 | Button-Down Shirts | 65 | Cool Grey / shirts | 187 / 1 | `B00QRVNPJE` |
| office-basics-03 | Belts | 45 | none / not applied | 78 / 78 | `B07LGRDWPN` |
| activewear-01 | Tanks Tops | 50 | Black / workout clothing | 117 / 1 | `B088LHSNW4` |
| activewear-02 | Active Shirts & Tees | 45 | Black / workout clothing | 86 / 1 | `B08L5CNVZ6` |
| activewear-03 | Pants | 65 | Black / workout clothing | 162 / 2 | `B0BWJKZ9GX` |
| footwear-01 | Cycling | 95 | Black / shoes | 4 / 1 | `B08KDD82VV` |
| footwear-02 | Equestrian Sport Boots | 230 | Black / shoes | 2 / 1 | `B087R16HCP` |
| footwear-03 | Industrial & Construction Boots | 190 | Black / shoes | 9 / 1 | `B07XQY112X` |
| commuter-bags-01 | Casual Daypacks | 85 | Black / bags | 28 / 1 | `B001MUKWQ4` |
| commuter-bags-02 | Briefcases | 70 | Black / bags | 2 / 1 | `B00JGQXM90` |
| commuter-bags-03 | Totes | 60 | Black / bags | 43 / 1 | `B00GDOUL92` |
| jewelry-simple-01 | Anklets | 60 | Silver / jewelry | 26 / 5 | `B00OV69Q3Q` |
| jewelry-simple-02 | Necklaces | 70 | Silver / jewelry | 394 / 3 | `B07CBQ79F9` |
| jewelry-simple-03 | Bangle | 65 | Silver / jewelry | 46 / 7 | `B001ULD8OS` |
| gift-shopper-01 | Necklaces | 60 | Silver / recipient only | 383 / 3 | `B07CBQ79F9` |
| gift-shopper-02 | Bangle | 70 | Gold / recipient only | 46 / 2 | `B00KV7CERY` |
| gift-shopper-03 | Wallets | 50 | none / not applied | 241 / 241 | `B016QUDKCW` |
| bag-style-change-01 | Totes | 75 | Black / bags | 45 / 1 | `B00GDOUL92` |
| bag-style-change-02 | Briefcases | 85 | Black / bags | 3 / 1 | `B00JGQXM90` |
| bag-style-change-03 | Crossbody Bags | 90 | Cream / bags | 34 / 1 | `B096NDXZ3X` |

## Customer timelines and memory probes

1. **Capsule wardrobe:** Black clothing disclosed with a casual top; warm hoodie then casual
   pants omit color. Broad cross-category recall; first and later budgets remain distinct.
2. **Office basics:** Cool Grey shirts disclosed on a relaxed-office shirt visit; another casual
   shirt omits color. A belt visit has no persistent keys or color requirement: shirt-only scope
   must not transfer. The same shirt witness recurs; this is a scoped-recall probe, not broad
   within-shirt diversity or a formal-office suitability benchmark.
3. **Activewear:** Black workout clothing disclosed with a casual tank top; a workout top and
   yoga/training pants omit color. No unverified performance/fabric claim is made.
4. **Footwear:** Black shoes disclosed with cycling shoes, then horse-riding boots and outdoor
   work boots omit color. The cycling visit adds the documented `Athletic` taxonomy requirement
   to exclude cycling clothing. The witness titles corroborate shoe/boot identity.
5. **Commuter bags:** Black bags disclosed with a mesh daypack, then folio and tote omit color.
   Laptop protection, waterproofness and size are not hidden hard requirements.
6. **Simple jewelry:** Silver jewelry disclosed with an anklet, then necklace and bangle omit
   color. These are wearable jewelry witnesses, not keychains labeled as pendants.
7. **Gift shopper:** Silver necklace for a friend, Gold bangle for a family member, then own
   wallet with no color preference. No personal preferences, changes or persistent keys are
   defined. Recipient facts belong only to that visit, and are explicitly gift disclosures.
8. **Bag style change:** Black tote, Black folio recall probe, then an explicit Cream bag update
   and crossbody phone bag. Only this added customer changes a stable personal preference.
   The correction says “Actually, I now generally prefer Cream bags.”; it contains no future
   change information in earlier contexts. An unknown old color is not manufactured as evidence.

Both conditions start without preseeded user profiles. Only ordinary quoted, current-user
memory proposals can create ASTRA memory. Private roleplay receives current-boundary context;
the agent receives conversation and its own state/profile only. Future visits, witnesses and
evidence hashes are excluded from compiled shopper contexts; existing runner privacy/isolation
regressions are retained. This tests configuration boundaries, not the behavior of a live model.

## Substitutions and limitations

All budgets not listed below retain the blueprint thresholds. All exact category labels below
were observed locally; goals/openings were adjusted with them rather than promising unsupported
product functions. Personalities and the stable-vs-change distinction remain as designed.

| Customer | Blueprint → grounded change | Reason |
| --- | --- | --- |
| Capsule | T-Shirts → Active Shirts & Tees; Hoodies/Sweatshirts → Active Hoodies; Sweatpants/Joggers → Pants; hoodie budget 65 → 110 | T-Shirts hits the existing literal-disclosure negation defect; the other proposed leaves lack usable Black color evidence. Only priced exact-Black active hoodie is 103.99. |
| Office | Blue → Cool Grey; both shirt visits → Button-Down Shirts; goals relaxed office/casual | No priced structured Blue in proposed shirt leaves. Cool Grey witness is 37.50, with a casual/offshore title; no formal-office appropriateness claim. No verified common exact color across two proposed shirt leaves. Belt remains Belts. |
| Activewear | Athletic/Running Shorts → Tanks Tops; Athletic Shirts/Tank Tops → Active Shirts & Tees; Track/Athletic Pants → Pants | Candidate shorts/pants labels are absent or lack priced Black evidence. Tanks Tops is the exact catalogue spelling; the witness is a casual printed tank, not technical sportswear. |
| Footwear | White → Black; athletic shoes scope → shoes; sneakers/running/walking → Cycling, Equestrian Sport Boots, Industrial & Construction Boots; budgets 110 → 230 and 90 → 190 | Proposed leaves are absent or have no priced White evidence. Distinct actual shoe/boot categories have Black evidence. Riding witness 219.95 and work boot 180 require higher budgets. A Volleyball alternative was excluded because its single priced eligible product would make color irrelevant. Background/goals now cover activity-specific and outdoor footwear. |
| Commuter bags | Backpacks/Laptop Backpacks → Casual Daypacks; Crossbody/Shoulder Bags → Briefcases; Tote Bags/Totes → Totes | No priced Black backpack in proposed exact leaves; real Black daypack exists. Only priced Black shoulder witness is an organizer insert, not a full bag; crossbody has Cream only. Black folio and tote are genuine bags. |
| Jewelry | Earrings/Stud Earrings → Anklets; Pendant/Chain Necklaces → Necklaces; Bracelets/Bangles → Bangle | Proposed earrings lack priced structured Silver. Pendant Necklaces has a Silver cremation-urn set; Pendants Only Silver examples are keychains. Verified ordinary anklet, necklace and bangle chosen instead. Bangle is the exact singular leaf. |
| Gift shopper | Pendant/Earrings → Necklaces; Earrings/Bracelets → Bangle; Wallets retained | Wearable Silver necklace and Gold bangle have real detail evidence; avoid keychains/urn sets. Gift colors and budgets unchanged. |
| Bag style change | Red → Black; Blue → Cream; Crossbody/Shoulder → Totes; Tote/Handbags → Briefcases; Handbags/Shoulder → Crossbody Bags | No priced structured Red/Blue full-bag evidence in candidate leaves. Black tote/folio and Cream crossbody phone bag support an actual explicit change. Broad bag background replaces “small bags” because tote/folio are not verified small. |

Current limitations stay visible:

- Category matching tokenizes the entire path, including the root `Clothing, Shoes & Jewelry`.
  A generic Shoes requirement cannot isolate footwear. Cycling + Athletic is verified on every
  eligible row in a regression, and all those rows contain the separate Shoes branch.
- `validate_statement` interprets the T in T-Shirts as negation. This task avoids that category;
  it does not fix or suppress the underlying validator issue.
- Attribute sparsity and reused witnesses make this a development pilot, not 24 independent
  generalization tasks. The new customers share some products; original ones also overlap.
- Current memory selection is lexical scope matching, not semantic category inheritance.
  Broad clothing/workout-clothing/jewelry scopes may not be selected for a hoodie, pants or
  necklace query without the scope words. No openings are padded with artificial retrieval
  hints to force memory benefit. Observe missed retrieval separately from storage/learning.
- The gift control checks unwanted writes/transfers; it cannot prove global recipient filtering.
  It starts with no personal preference, so does not test suppression of a pre-existing personal
  color on a gift. The old traveler/fashion gift probes are preserved unchanged.
- Unknown size/material remains unknown; no variant inventory or live purchase is verified.
- No live recommendation suitability, retention, correction reliability, efficiency improvement
  or negative-transfer rate has been measured. Fixture validity is not effectiveness evidence.

## Reproduction and verification

Run from the repository root with the existing environment; no dependencies installed:

```sh
.venv/bin/python experiments/longitudinal/catalogue_inventory.py
.venv/bin/python -m unittest discover -s tests -p test_customers.py -v
.venv/bin/python -m unittest discover -s tests -p 'test_longitudinal*.py' -v
.venv/bin/python -m unittest discover -s tests -p test_expanded_customers.py -v
.venv/bin/python -W error::ResourceWarning -m unittest discover -s tests -v
.venv/bin/ruff check .
.venv/bin/ruff format --check src tests streamlit_app.py experiments/longitudinal/catalogue_inventory.py
git diff --check
.venv/bin/python -m astra_eval longitudinal \
  --customers experiments/longitudinal/customers.dev-expanded.json \
  --output /tmp/astra-expanded-plan-only --max-model-calls 1296
```

Results actually executed (2026-11-01):

- Customer contracts: **7 tests passed**.
- Existing longitudinal runner/report/CLI suite: **13 tests passed**.
- Expanded fixture suite: **9 tests passed**, including real local catalogue validation.
- Full suite: **540 tests run in 22.979s; OK**, comprising 537 ordinary passes,
  one skipped test (missing pinned tokenizer asset) and two existing expected failures
  (watch/wristwatch vocabulary). No new failure or skip.
- `ruff check .`: passed. Formatting: 95 files already formatted. `git diff --check`: passed.
- Non-live plan: 11 customers / 36 visits / 72 sessions / maximum 1,296 agent model calls;
  memory format `legacy`, both conditions development-only; output directory not created.
- Catalogue inventory regenerated successfully and reproduced byte-for-byte in its test.
- Paid API calls: **0**. Live Ollama calls: **0**.

Local-asset integration tests explicitly skip if the ignored catalogue/index is unavailable.
They were present for this verification. Tests check all 36 frozen records, literal disclosures,
chronology, duplicate/unsafe IDs, development-only split, old-customer equality, current-boundary
privacy, recipient scope, meaningful best sets, witness sources and byte-reproducible inventory.
No generated transcript, database, model asset, credential or raw catalogue row is committed.

Preservation check: all 171 files in the pre-task protected inventory (all local `data/` files
plus the original customer fixture) retained their SHA-256 values; no new data files appeared.
The sorted before/after path/hash mapping is identical (SHA-256, both checks: `e72572edc384fcdb3b4619ed9c6b4d1e041f326a0028c337aa08624243db3733`). The original catalogue and customer
fixture hashes are above. The index, experience database, learning transcripts, scenarios and
historical outputs are included in this check. AGENTS.md and all production source are unchanged.

## Planned evaluation cost — no live run approved or executed

The non-live plan reports **11 customers, 36 visits, 72 sessions** across user memory OFF/ON,
procedural memory OFF, primary K=5 and unchanged legacy memory-format default.
With six turns per visit, three decision calls/turn and the 18-call session cap:
`72 × min(6 × 3, 18) = 1,296` maximum ASTRA/DeepSeek calls. This is a call cap, not a prediction.
The full timelines run separately and condition order alternates by customer under the existing
runner. Local Ollama shopper calls consume additional compute/latency, not DeepSeek tokens;
early termination/retries and simulator failures affect their actual count.

For an illustrative budget only, assume 5,000 input + 300 output tokens per decision and all
1,296 calls: 6.48M input + 0.3888M output. At current default-model `deepseek-flash` cache-miss
rates, this is approximately **US$1.21 off-peak / US$2.41 peak**. Using the configured 2,000-output-
token maximum instead gives **US$2.53 / US$5.05**, still assuming 5,000 input tokens/call.
These are explicit assumptions, not measured token usage or a guaranteed financial upper bound.
The [official pricing page](https://api-docs.deepseek.com/quick_start/pricing/) was checked
2026-11-01: cache-miss input/output per 1M tokens are $0.15/$0.60 off-peak and $0.30/$1.20 peak.
Cache hits can reduce cost; a different configured model, longer prompts or changed pricing
changes it. Confirm actual provider/model/settings and a separately approved small pilot before
authorizing a full run. No key or local credential file was read for this estimate.
