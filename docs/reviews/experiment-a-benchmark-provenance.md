# Experiment A benchmark provenance and the proposed v3 replacement

31 October 2026. Investigated from the transferred ignored artifacts under
`data/benchmarks/experiment-a/`, their manifests/certificate, and Git history. Nothing in
`data/` was modified or regenerated in place; every regeneration below was written to a
scratch directory. No provider request was made.

## Artifacts found

| Directory | Contents | Status |
| --- | --- | --- |
| `frozen-v1` | Earlier pool; `tasks.json` hash differs (`527090ed…`); qrels are unreviewed seeds | Superseded; unused |
| `frozen-v2` | Reviewed labels; manifest `3a6d66eb…`; **has a verification certificate** bound to its tasks/qrels/baseline/review hashes | Independently verified. Requirement IDs look like `literal-01:r0` |
| `frozen-v3` | Same `tasks.json`, `qrels.json`, `reviewed_labels.json` hashes as v2; `baseline.json` differs (`e03a035a…` vs `81c7167c…`); manifest `e7532a49…` | **No certificate** |
| `draft-v2`, `draft-v3` | The `prepare.py` outputs that `finalize.py` froze into v2/v3 | Unfrozen drafts |

The catalogue (`da979b05…`) and image map (`c492bfb3…`) match `manifest.json`.

## Which `prepare.py` produced which version

Both versions were regenerated from the catalogue and a fresh BM25 index into scratch
directories using each code version:

- `ba5c435` (original Experiment A branch, requirement IDs `<task>:r<i>`) reproduces
  `draft-v2`.
- The recovered WIP `prepare.py` (opaque SHA-256 requirement IDs) reproduces `draft-v3`.

"Reproduces" is exact for `tasks.json` and `qrels.json` and exact for `baseline.json`
**after masking two expected sources of difference**: the random per-run `search_id` and
27 last-digit BM25 float differences (maximum relative error 2.3e-16). The float noise
comes from a different SQLite build (3.46.1 here, 3.51.2 on the machine that froze the
data). Candidate IDs, order, counts, requirement content and card facts are identical.

## Why v2 cannot be used by the recovered runner

The runner's leakage guard rejects any prompt containing the task ID. In v2 the task ID is
part of every requirement ID, which is model-visible, so `run.py offline` fails with
`Evaluator metadata leaked into prompt`. This is the reason the WIP `prepare.py` introduced
opaque IDs. v3 passes the guard but lacks a certificate, and `run.py` refuses uncertified
directories.

## Evidence that v3 differs from v2 only in identifiers

`python -m experiments.experiment_a.verify_equivalence frozen-v2 frozen-v3` (read-only)
reports true for every check: identical `tasks.json`, `qrels.json`, `reviewed_labels.json`;
same task set; identical candidate IDs, order and counts; requirement content equal except
IDs; IDs map one-to-one; and all card evidence equal once the same ID mapping is applied
(IDs also appear inside cards as `matched_hard_ids` and `applied_hard_filters`). BM25
floats agree within a relative 1e-9. This is mechanical evidence, **not** an independent
verification.

## Proposal (requires approval; nothing has been done)

1. Keep `frozen-v2` and its certificate untouched as the verified original.
2. Treat `frozen-v3` as a versioned replacement. An independent reviewer re-checks, without
   seeing results, that v3 differs from v2 only as above (running `verify_equivalence` is
   part of that check) and writes a `verification.json` bound to v3's hashes.
3. Place that certificate in `frozen-v3`, or in a copy named for the verified version, only
   after the review. Adding a file is an explicit approved step, not a regeneration.
4. A live run requires that certificate; this checkpoint's offline validation used a
   scratch copy with a mechanical, clearly labelled non-evidentiary hash binding, which is
   never committed and carries no verification claim.

## Caveats

- The BM25 score tolerance only absorbs float rounding. Candidate IDs, order, counts and
  every other field are still compared exactly.
- Different SQLite builds could in principle change tie ordering. None was observed here
  (all 36 tasks' candidate order matched), but a future build should re-run the offline
  replay check before any live run.
