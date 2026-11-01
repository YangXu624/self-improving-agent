# Returning-customer development fixtures

`customers.dev.json` is a small manually directed development set: three invented customers,
four ordered shopping visits each. It is not a held-out benchmark or effectiveness result.
Only derived requirements, witness IDs and evidence hashes are stored here, not raw catalogue
rows or personal data. All witnesses are from the approved 50k TechJam catalogue. Existing
`data/eval/scenarios/target_v1` is untouched.

| Customer | Visit 1 | Visit 2 | Visit 3 | Visit 4 |
| --- | --- | --- | --- | --- |
| Traveler | Yellow folding umbrella; disclose persistent color | Yellow stick umbrella; recall probe | Travel wallet; umbrella preference irrelevant | Blue umbrella gift for a friend |
| Fashion | Silver bangle; jewelry preference | Silver pendant necklace; recall probe | Gold bangle gift | Change personal jewelry preference to Gold |
| Changing needs | Leather wallet; disclose preference | Second wallet; recall probe | Change to Nylon wallet | Pendant gift; wallet preference irrelevant |

Private backgrounds and current preferences are available only to the shopper. Changes become
effective at their `before_sequence` boundary; no future visit or target identity is put in the
shopper context. ASTRA receives only conversation messages and its own learned profile.

## Input shape

`CustomerDataset`: version, development-only label, catalogue SHA-256, provenance, customers.
Each `Customer`: stable safe `user_id`, personality, background, interests, scoped preferences/
dislikes, boundary changes and ordered visits. Each visit has a unique `task_id` (the frozen
session blueprint), sequence, current goal/category/recipient, evaluation mode, opening,
disclosure plan, hard/soft facts, relevant persistent keys, witness ID and evidence hashes.
The actual ASTRA `session_id` is newly generated at execution and recorded separately.

`customers.validate_dataset()` verifies the catalogue hash, literal disclosure/value/operator
consistency, current-boundary state, hard/soft separation, grounded witnesses, complete match
sets and frozen evidence hashes. It compiles into existing `Scenario`, `GroundTruth` and
`TargetGroundTruth` contracts; no model calls are made. Compatibility follows the existing
category-token ontology, not necessarily an exact leaf category. Ambiguity is explicit: a
witness can share its complete documented profile with other products. Exact-target metrics
must therefore remain distinct from graded suitability.

The input contracts, thin timeline runner, isolated user-memory conditions and reports are
implemented. See [commands, architecture and limits](../../docs/longitudinal-evaluation.md).
The source fixture should be reviewed/refined before a separately frozen held-out set is
designed. No live model experiment has been run and no effectiveness claim is made.
