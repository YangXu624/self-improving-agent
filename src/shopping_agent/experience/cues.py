"""Conservative, evidence-scoped decision cues. Never edits shopping state or searches.

Unknown category/extra words fail closed for the category-only lesson. The vocabulary is
catalogue metadata, not target labels; no model call or new retrieval strategy is involved.
"""

import json
import re
import unicodedata
from types import SimpleNamespace

from ..attributes import _scope_events, attribute_ledger, canonical_attribute
from ..contracts import ShoppingState

RESET = re.compile(
    r"^\s*(?:new (?:shopping )?goal\s*:|(?:start|starting) (?:a )?new (?:shopping )?goal\s*[:,-]?)\s*",
    re.I,
)
REQUEST = re.compile(
    r"^(?:i(?:'m| am) (?:looking|shopping) for|i (?:need|want|would like)(?: to (?:buy|find))?|(?:please )?(?:find|show)(?: me)?|(?:looking|shopping) for)\s+",
    re.I,
)


def words(text: str) -> tuple[str, ...]:
    text = unicodedata.normalize("NFKC", text).casefold().replace("’", "'")

    # Small inflection support, not semantic category guessing.
    def singular(w):
        if w.endswith(("ches", "shes", "sses")):
            return w[:-2]
        return (
            w[:-1]
            if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us"))
            else w
        )

    return tuple(singular(w) for w in re.findall(r"[\w]+", text))


def catalogue_categories(search) -> frozenset[tuple[str, ...]]:
    """Project documented category labels from the existing read-only index once per agent.

    Alternative tool adapters lacking catalogue metadata do not activate category-only
    guidance until a category has been established by validated state.
    """
    db = getattr(search, "db", None)
    if db is None:
        return frozenset()
    categories = set()
    for (encoded,) in db.execute(
        "SELECT DISTINCT json_extract(record, '$.categories') FROM products"
    ):
        for label in json.loads(encoded or "[]"):
            if isinstance(label, str) and 0 < len(label) <= 120:
                tokenized = words(label)
                if tokenized and tokenized not in {
                    ("men",),
                    ("women",),
                    ("boy",),
                    ("girl",),
                    ("unisex",),
                }:
                    categories.add(tokenized)
    return frozenset(categories)


def _category(message, vocabulary):
    tokens = words(message)
    candidates = [
        tokens[a:b]
        for a in range(len(tokens))
        for b in range(a + 1, min(len(tokens), a + 12) + 1)
        if tokens[a:b] in vocabulary
    ]
    return max(candidates, key=len, default=None)


def decision_cues(
    session, message: str, result, searches: int, calls: int, vocabulary
) -> tuple[dict, str, dict]:
    """First decision is derived from the current goal's event timeline, never turn counters."""
    current = next(e for e in reversed(session.events) if e.type == "user_message")
    scoped = _scope_events(session)
    committed_reset = any(
        e.type == "state_committed"
        and e.turn_id == current.turn_id
        and any(u.get("op") == "NEW_GOAL" for u in e.payload.get("updates", []))
        for e in scoped
    )
    transition = re.match(r"^\s*(?:now|instead)[, ]+", message, re.I)
    old_category = next(
        (
            words(r.value)
            for r in session.state.requirements
            if r.status == "active"
            and r.field == "product_type"
            and isinstance(r.value, str)
        ),
        None,
    )
    new_category = _category(message, vocabulary)
    explicit_transition = bool(
        transition and new_category and new_category != old_category
    )
    provisional = (
        bool(RESET.match(message) or explicit_transition) and not committed_reset
    )
    if provisional:
        scoped = [e for e in scoped if e.seq >= current.seq]
        view = SimpleNamespace(
            events=scoped, state=ShoppingState(goal_epoch=session.state.goal_epoch + 1)
        )
    else:
        view = session
    requirements = [r for r in view.state.requirements if r.status == "active"]
    known = set(vocabulary)
    known.update(
        words(r.value)
        for r in requirements
        if r.field == "product_type" and isinstance(r.value, str)
    )
    category = _category(message, known)
    if category is None:
        category = next(
            (
                words(r.value)
                for r in requirements
                if r.field == "product_type" and isinstance(r.value, str)
            ),
            None,
        )
    first_user = next(
        (
            e
            for e in scoped
            if e.type == "user_message"
            and (
                _category(e.payload["message"], known)
                or REQUEST.match(e.payload["message"])
                or RESET.match(e.payload["message"])
            )
        ),
        None,
    )
    if first_user is None and requirements:
        source_ids = {
            r.source_event_id for r in requirements if r.field == "product_type"
        }
        first_user = next((e for e in scoped if e.event_id in source_ids), None)
    initial = bool(
        first_user
        and not any(
            e.type == "model_request" and e.seq >= first_user.seq for e in scoped
        )
    )
    opening = RESET.sub("", unicodedata.normalize("NFKC", message).replace("’", "'"))
    if explicit_transition:
        opening = re.sub(r"^\s*(?:now|instead)[, ]+", "", opening, flags=re.I)
    opening = re.sub(r"^\s*(?:hi|hello|hey)[,!]\s*", "", opening, flags=re.I)
    opening = REQUEST.sub("", opening.strip())
    opening = re.sub(r"^(?:a|an|some)\s+", "", opening)
    ledger = attribute_ledger(view)
    non_category = {canonical_attribute(r.field) for r in requirements} - {
        "product_type"
    }
    non_category |= set(ledger["disclosed_attributes"]) - {"product_type"}
    non_category |= set(ledger["asked_attributes"]) - {"product_type"}
    category_only = bool(category and words(opening) == category and not non_category)
    has_candidates = bool(not provisional and result and result.get("candidates"))
    cues = {
        "is_initial": initial,
        "is_underspecified": bool(initial and category_only),
        "category_only": category_only,
        "searches": searches,
        "calls": calls,
        "has_search": result is not None and not provisional,
        "has_candidates": has_candidates,
        "candidate_count": len(result.get("candidates", []))
        if result and not provisional
        else 0,
        "empty_search": result is not None and not provisional and not has_candidates,
    }
    return (
        cues,
        next((str(r.value) for r in requirements if r.field == "product_type"), "*"),
        {
            "goal_epoch": view.state.goal_epoch,
            "provisional_goal": provisional,
            "identified_category": " ".join(category) if category else None,
            "source_user_event_id": current.event_id,
        },
    )
