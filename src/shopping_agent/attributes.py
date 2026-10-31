"""Replayable, goal-scoped working-memory projection; requirements own all values.

No model-maintained duplicate state and no evaluation dependency. Original events retain
full evidence; the snapshot/context cache can always be rebuilt from them.
"""

import re
from types import SimpleNamespace

REVISION = 1
ALIASES = {
    "budget": "price",
    "colour": "color",
    "category": "product_type",
    "shoe_width": "width",
}
MENTIONS = {
    "price": r"\b(budget|price|spend|cost)\b",
    "currency": r"\b(currency|usd|sgd|eur|gbp)\b",
    "color": r"\b(colou?r|shade)\b",
    "material": r"\b(material|fabric)\b",
    "size": r"\bsize\b",
    "width": r"\bwidth\b",
    "brand": r"\bbrand\b",
    "product_type": r"\b(type|category|kind)\b",
    "recipient": r"\brecipient\b",
    "use_case": r"\b(use|occasion|purpose)\b",
    "department": r"\b(department|gender)\b",
}
NO_PREFERENCE = r"\b(no (?:colou?r |brand |size |material |currency |width )?preference|any (?:color|colour|brand|size|material)|don'?t care(?! for)|do not care(?! for)|doesn'?t matter|does not matter|not picky)\b"
DECLINED = r"\b(prefer not to (?:say|answer)|rather not (?:say|answer)|don'?t want to (?:say|answer)|do not want to (?:say|answer)|skip (?:that|this question))\b"
UNCERTAIN = r"\b(can answer|ready to answer|not sure|unsure|uncertain|haven'?t decided|have not decided|maybe|either|approximately|around)\b"


def canonical_attribute(name: str) -> str:
    return ALIASES.get(name, name)


def _scope_events(session):
    # Fixture/custom contexts may have lightweight legacy event views without IDs.
    events = [
        SimpleNamespace(
            type=e.type,
            payload=e.payload,
            event_id=getattr(e, "event_id", f"legacy-{i}"),
            seq=i,
            turn_id=getattr(e, "turn_id", None),
        )
        for i, e in enumerate(session.events, 1)
    ]
    start, epoch = 0, 0
    for i, event in enumerate(events):
        if event.type == "state_committed":
            after = event.payload["state"].get("goal_epoch", 0)
            if after > epoch:
                start = next(
                    (
                        j
                        for j in range(i, -1, -1)
                        if events[j].type == "user_message"
                        and events[j].turn_id == event.turn_id
                    ),
                    i,
                )
            epoch = after
    return events[start:]


def attribute_ledger(session) -> dict:
    """Return current-goal questions, response dispositions and active confirmed values."""
    events = _scope_events(session)
    positions = {e.event_id: e.seq for e in events}
    asked, observations = {}, {}
    pending = None
    for e in events:
        if (
            e.type == "assistant_response"
            and e.payload.get("status") == "ok"
            and e.payload.get("action") == "CLARIFY"
        ):
            key = canonical_attribute(e.payload["attribute"])
            asked[key] = {
                "asked": True,
                "status": "asked_unanswered",
                "question": {"event_id": e.event_id, "text": e.payload["message"]},
            }
            pending = key
        elif e.type == "user_message":
            text = e.payload["message"]
            # Do not interpret quoted or negated meta-discussion as a disposition.
            if re.search(
                r"[\"“”]|\b(?:didn'?t say|did not say|not saying)\b", text, re.I
            ):
                continue
            previous_status = None
            for clause in re.split(
                r"[,;!?]|(?<=\.)\s+|\b(?:but|and)\b", text, flags=re.I
            ):
                status = (
                    "declined"
                    if re.search(DECLINED, clause, re.I)
                    else "no_preference"
                    if re.search(NO_PREFERENCE, clause, re.I)
                    else "needs_followup"
                    if re.search(UNCERTAIN, clause, re.I)
                    else None
                )
                if (
                    status is None
                    and previous_status
                    and re.fullmatch(
                        r"\s*(?:colou?r|material|brand|size|width|currency|department|type)\s*",
                        clause,
                        re.I,
                    )
                ):
                    status = previous_status
                previous_status = status
                mentioned = [
                    k
                    for k, pattern in MENTIONS.items()
                    if re.search(pattern, clause, re.I)
                ]
                keys = mentioned or ([pending] if pending else [])
                if status and not re.search(
                    r"\b(?:not|never)\s+(?:no (?:colou?r |brand |size |material |currency |width )?preference|any|not picky)",
                    clause,
                    re.I,
                ):
                    # Resolve only a single attribute per disposition clause.
                    if len(keys) == 1:
                        observations[keys[0]] = {
                            "status": status,
                            "answer": {"event_id": e.event_id, "quote": clause.strip()},
                            "seq": e.seq,
                        }
                if (
                    pending == "currency"
                    or "currency" in mentioned
                    or re.search(r"\b(?:in|\d+)\s+(?:USD|SGD|EUR|GBP)\b", clause, re.I)
                ):
                    codes = re.findall(r"\b(?:USD|SGD|EUR|GBP)\b", clause, re.I)
                    affirmative = (
                        pending == "currency"
                        and re.fullmatch(
                            r"\s*(?:USD|SGD|EUR|GBP)[.!]?\s*", clause, re.I
                        )
                    ) or re.search(
                        r"\b(?:in|currency is|please use|\d+)\s+(?:USD|SGD|EUR|GBP)\b|\b(?:USD|SGD|EUR|GBP)\s+please\b",
                        clause,
                        re.I,
                    )
                    if (
                        status is None
                        and not re.match(
                            r"\s*(?:can|could|would|should|may|is|are|do|does|what|which|how|will)\b",
                            clause,
                            re.I,
                        )
                        and not re.search(r"\b(?:wonder|whether|if)\b", clause, re.I)
                        and affirmative
                        and len(set(c.upper() for c in codes)) == 1
                        and not re.search(
                            r"\b(?:not|no|maybe|unsure|undecided)\b", clause, re.I
                        )
                    ):
                        observations["currency"] = {
                            "status": "answered",
                            "value": codes[0].upper(),
                            "answer": {"event_id": e.event_id, "quote": clause.strip()},
                            "seq": e.seq,
                        }
                if pending == "width" or "width" in mentioned:
                    match = re.fullmatch(
                        r"\s*(?:width (?:is )?)?(extra wide|wide|narrow|regular|medium|EE|D|B)(?: please)?[.!]?\s*",
                        clause,
                        re.I,
                    )
                    if match:
                        observations["width"] = {
                            "status": "answered",
                            "value": match.group(1).lower(),
                            "answer": {"event_id": e.event_id, "quote": clause.strip()},
                            "seq": e.seq,
                        }
            pending = None
    disclosed = {}
    for r in session.state.requirements:
        if r.status != "active":
            continue
        key = canonical_attribute(r.field)
        row = disclosed.setdefault(key, {"status": "answered", "requirements": []})
        row["requirements"].append(
            {
                "id": r.id,
                "op": r.op,
                "value": r.value,
                "strength": r.strength,
                "source_event_id": r.source_event_id,
                "quote": r.quote,
            }
        )
    for key, obs in observations.items():
        row = disclosed.setdefault(key, {"requirements": []})
        latest = max(
            (
                positions.get(r["source_event_id"], 0)
                for r in row.get("requirements", [])
            ),
            default=0,
        )
        if obs["seq"] >= latest:
            row.update({k: v for k, v in obs.items() if k != "seq"})
            positives = [
                r
                for r in row.get("requirements", [])
                if r["op"] in {"eq", "in", "contains", "lt", "lte", "gt", "gte"}
            ]
            if positives and obs["status"] == "no_preference":
                row["status"] = (
                    "needs_followup"  # old constraints need explicit withdrawal
                )
    if "product_subtype" in asked:
        question_id = asked["product_subtype"]["question"]["event_id"]
        rows = [
            r
            for r in disclosed.get("product_type", {}).get("requirements", [])
            if positions.get(r["source_event_id"], 0) > positions.get(question_id, 0)
        ]
        if rows:
            disclosed["product_subtype"] = {"status": "answered", "requirements": rows}
    for key, row in disclosed.items():
        if (
            row.get("status") == "answered"
            and row.get("requirements")
            and all(
                r["op"] in {"neq", "not_in", "not_contains"}
                for r in row["requirements"]
            )
        ):
            row["status"] = (
                "needs_followup"  # exclusions do not answer positive preferences
            )
        if key in session.state.conflicts:
            row["status"] = "needs_followup"
        if (
            key == "price"
            and row.get("requirements")
            and not any(r["op"] in {"lt", "lte", "eq"} for r in row["requirements"])
        ):
            row["status"] = (
                "needs_followup"  # lower bound alone does not answer maximum budget
            )
        if key in asked:
            asked[key]["status"] = row["status"]
            if "answer" in row:
                asked[key]["answer"] = row["answer"]
            elif row.get("requirements"):
                asked[key]["answer"] = {
                    "event_id": row["requirements"][-1]["source_event_id"],
                    "quote": row["requirements"][-1]["quote"],
                }
    return {
        "revision": REVISION,
        "goal_epoch": session.state.goal_epoch,
        "asked_attributes": asked,
        "disclosed_attributes": disclosed,
    }


def redundant_clarification(session, attribute: str) -> bool:
    """Only resolved exact attributes are blocked; unanswered/uncertain ones remain usable."""
    key = canonical_attribute(attribute)
    row = attribute_ledger(session)["disclosed_attributes"].get(key, {})
    return row.get("status") in {"answered", "declined", "no_preference"}


def compact_ledger(session) -> dict:
    """Values stay in compact active requirements; ledgers reference them without duplication."""
    ledger = attribute_ledger(session)
    return {
        "goal_epoch": ledger["goal_epoch"],
        "asked_attributes": {
            k: v["status"] for k, v in ledger["asked_attributes"].items()
        },
        "disclosed_attributes": {
            k: {
                **{"status": v["status"]},
                **(
                    {"requirement_ids": [r["id"] for r in v["requirements"]]}
                    if v.get("requirements")
                    else {}
                ),
                **({"value": v["value"]} if "value" in v else {}),
            }
            for k, v in ledger["disclosed_attributes"].items()
        },
    }
