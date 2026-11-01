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
preferences and facts require an explicit persistence/frequency cue. Gift/one-off turns fail closed. Purchase
records require an explicit user statement that they bought, purchased or ordered the item.
Recommendations never create purchases. Uncertain statements cannot be stored as confirmed.
Changed or outdated information is explicitly superseded/retracted; there is no automatic
expiry or LLM deletion. The source session supplies the complete audit conversation.

Profiles are private ignored data. Local owner IDs provide the same boundary as existing
sessions; this does not add hosted authentication or protection against another local process
with filesystem access. User IDs are hashed into directory names, never used as paths.

## Runtime and controls

`ShoppingAgent(..., user_memory=UserMemoryStore(root))` enables the layer; `None` is OFF.
The local UI exposes **Remember me across chats** (default OFF). Use the same shopper label
to retain the same `user_id`; **New chat** changes only the session UUID. The CLI uses:

```bash
.venv/bin/python -m shopping_agent chat --user alice --user-memory
# Optional location: --user-memory-root data/user-memory
```

UI storage defaults to `data/user-memory`; process setting `ASTRA_USER_MEMORY_ROOT` overrides
it. OFF disables reads AND writes and preserves existing profiles. It does not delete them.
All normal chat commands still call DeepSeek; this checkpoint used only mocked providers.

Each decision selects at most eight active records: matching scopes, then general records,
with explicitly mentioned values prioritized to make older memories correctable. Matching
uses literal words and a small plural normalization, not embeddings. The full profile is
inspectable even when not all records are in context. Confirmed/inferred basis stays visible.
Remembered preferences are advisory for questions, queries and ranking: they never silently
become hard requirements. Current session requirements and gift recipients take precedence.

Enabled calls use prompt `shopping-baseline-v6-user-memory` and `MemoryDecision`, which adds
optional `user_memory_updates` to the existing decision. One DeepSeek response proposes both
session edits and profile updates; there is no extra extraction call. Disabled calls preserve
the original `Decision` schema and `shopping-baseline-v5-experience` prompt.

Python independently validates each profile-update batch against the actual owned current
user event, the profile revision, and (for corrections) IDs visible in that decision. A batch
is all-or-nothing. Valid updates can persist even if the subsequent shopping action is rejected,
as with existing session edits. Shopping and profile files are not a cross-file transaction;
source-event idempotency prevents repeated profile writes if execution is interrupted after
the profile replacement. Completed request retries return their saved response. No background
job re-extracts history or overwrites the profile.

Rejected profile writes do not invalidate an otherwise valid shopping action. They appear in
`user_memory_update_rejected` events and the response's `user_memory.rejected` field; the UI
displays a warning. Corrupt/unavailable profile reads stop before a provider call rather than
silently supplying an empty profile. Session history remains the source of the actual quote.

Trace events distinguish `user_memory_selection`, exact `user_memory_injection`, accepted
`user_memory_updated` and rejected updates. These establish data flow and persistence, not
whether DeepSeek used a memory beneficially. There is no automatic memory-effect score yet.

```mermaid
flowchart LR
    Input[Message + user ID + session ID] --> Session[Owned session replay]
    Session --> Read[Relevant profile records]
    Profile[(Per-user profile.md)] --> Read
    Read --> Context[Bounded context: state + ledger + dialogue + user memory]
    Procedures[(Procedural snapshot, if supplied)] --> Context
    Context --> Policy[DeepSeek: state edits + action + memory proposals]
    Policy --> State[Existing state and action validation]
    Policy --> Validation[Evidence + scope + revision + visible-target checks]
    Validation --> Atomic[Locked atomic profile update]
    Atomic --> Profile
    State --> Tools[Unchanged BM25 and recommendation gates]
    State --> Events[(Authoritative session events)]
    Validation --> Events
```

## Two-session example (illustrative excerpts)

Before Session 1 there is no profile file. An empty read has revision 0.

Session 1, Alice: **I generally prefer blue bags.** The model proposes preference/color/blue,
scope=bags, with that exact quote. After validation the file contains a record like:

```markdown
# ASTRA user memory
- user_id: "alice"
- revision: 1

## Preferences
### um-<record-1>
- status: "active"
- attribute: "color"
- value: "blue"
- scope: "bags"
- basis: "confirmed"
- quote: "I generally prefer blue bags."
```

Session 2 uses the same user ID and a new session ID. **I need a bag** receives the blue/bags
record without repeating it. **Actually I now generally prefer black bags instead of blue**
can then propose REPLACE using the visible old record ID. The resulting revision 2 contains:

```markdown
## Preferences
### um-<record-1>
- status: "superseded"
- value: "blue"
- quote: "I generally prefer blue bags."
- closed_by_event_id: "<session-2-user-event>"

### um-<record-2>
- status: "active"
- value: "black"
- scope: "bags"
- quote: "Actually I now generally prefer black bags instead of blue"
- target_id: "um-<record-1>"
- source_event_id: "<session-2-user-event>"
```

These excerpts omit other required fields for clarity; real files also contain category,
operation, source-session IDs and UTC timestamps. They are not replacement profile files.
There is still no purchase record unless Alice explicitly confirms buying something.

## Existing evaluator and future seams

The current single-session evaluator is unchanged and constructs agents with user memory OFF,
even when procedural memory is ON. Existing frozen tasks/results are not migrated or rescored.
Stage 1 does not implement a longitudinal evaluator or a four-condition experiment CLI.

Proposed future interfaces (documentation only, no placeholder implementations):

- **Customer timeline input:** stable `user_id`, private persona/background, ordered frozen
  shopping goals, optional dated preference changes and per-goal scoring truth.
- **Longitudinal runner:** calls existing `agent.turn(user_id, session_id, message, ...)` with
  a fresh session for each goal and the same user ID; each condition has its own profile root.
  Shopper-private persona never seeds ASTRA's learned profile. Freeze the allowed history,
  ordering, warm-up and reset policy before comparisons.
- **Condition composition:** independent `user_memory` and `experience` arguments already
  exist on `ShoppingAgent`; future orchestration can select OFF/OFF, ON/OFF, OFF/ON, ON/ON.
- **External learner:** verified learning-split traces plus sanitized outcome feedback in;
  candidate `Lesson` records out through existing validation and `add_candidate()`. No direct
  activation, target identifiers, private user-profile ingestion or source-code edits. Current
  procedural extraction remains template-based; no external LLM learner is implemented.

## Verification and limits

`test_user_memory.py` covers persistence, ownership, evidence, scope, temporary/gift inputs,
negation, uncertainty, purchase confirmation, corrections, withdrawal, stale revisions,
idempotency, corrupted/symlinked files, atomic failure and limits. `test_user_memory_agent.py`
covers real executor contexts and compatibility. `test_user_memory_ui.py` exercises opt-in
cross-chat recall via mocked HTTP, the OFF switch and CLI defaults.

Conservative English parsing can reject valid paraphrases or mixed personal/gift statements.
It is not complete semantic validation. An explicit persistence cue is necessary but not
proof of everlasting truth. The operator must keep IDs stable; local labels are not accounts.
No live formation quality, shopping improvement, longitudinal behaviour or token-cost effect
has been measured in Stage 1.
