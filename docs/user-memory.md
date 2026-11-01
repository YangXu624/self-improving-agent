# Persistent user memory — Stage 1

Session history remains authoritative in `events.jsonl`; `state.json` remains its cache.
User memory is a separate, opt-in profile, not a second transcript or procedural lesson store.

`UserMemoryStore` stores `data/user-memory/<SHA256(user_id)>/profile.md`. A single readable
Markdown file has Facts, Preferences, Dislikes and Purchases sections. JSON-escaped bullets
preserve exact values and provenance without additional dependencies or a companion database.
One file permits an atomic replacement for a complete update batch; four independent files
would need a multi-file transaction. Files are read/updated through the store, not arbitrary
model file operations. Manual edits outside the canonical format fail closed.

`MemoryProposal` supports ADD, REPLACE and RETRACT. Records include confirmed/inferred basis,
scope, exact current-user quote, source session/event, timestamps and lifecycle status.
Corrections preserve superseded records; withdrawals retain a source-event link. Current
profile revision and per-user thread/process locks protect simultaneous sessions. A durable
source-event check makes a committed batch idempotent. A profile has at most 500 historical
records and 512,000 bytes; it is not silently truncated.

Evidence checks are conservative English rules, not a semantic proof. A literal value and
scope must be supported by the quote, personal ownership must be expressed, and ordinary
preferences require an explicit persistence cue. Gift/one-off turns fail closed. Purchase
records require an explicit user statement that they bought, purchased or ordered the item.
Recommendations never create purchases. Uncertain statements cannot be stored as confirmed.
Changed or outdated information is explicitly superseded/retracted; there is no automatic
expiry or LLM deletion. The source session supplies the complete audit conversation.

Profiles are private ignored data. Local owner IDs provide the same boundary as existing
sessions; this does not add hosted authentication or protection against another local process
with filesystem access. User IDs are hashed into directory names, never used as paths.

The initial store checkpoint is verified by `tests/test_user_memory.py`. Policy/context and
normal-interface integration are subsequent checkpoints in this same Stage 1 feature.
