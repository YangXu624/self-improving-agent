# Conversation reliability hardening

Scope: reproduce complete lifecycles, preserve historical evidence and scoring, spend no API tokens.

## Checkpoint 1: presented-offer context

V3 now verifies against accepted RECOMMEND cards in the current session and goal epoch,
including offers before text-only follow-ups. It excludes search-only results and prior
session/customer/condition history; a shopper cannot substitute another memory object in a
bound session. The runner records the actual ASTRA goal epoch with each assistant event.
The PR #27 price/acceptance failure is reproduced with its wording/price and synthetic IDs,
without reading or altering protected official scores. Unknown prices and invented identifiers
remain rejected. Free-form semantic identity checking remains bounded, not a proof of meaning.

Six offer-context tests passed; the existing 44 V3/provider tests also passed. Further
retrieval/state/loop and stopping-policy work is in progress; no readiness claim yet.
