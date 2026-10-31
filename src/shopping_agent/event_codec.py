"""Lossless disk projections. Session consumers still receive complete canonical events.

Version 2 references only earlier events in the same log. State deltas contain changed
requirements, not LLM-generated summaries. Legacy version-1 records remain readable.
"""

import base64
import zlib
from copy import deepcopy

from .contracts import Decision, Event, Requirement, ShoppingState


class CodecError(ValueError):
    pass


MAX_TEXT_BYTES = 512_000
_ANY_TURN = object()


def _pack_message(message):
    """Long exact prompt strings compress well; ordinary dialogue stays plain JSON."""
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        return message
    raw = message["content"].encode()
    if len(raw) < 1024 or "content_zlib" in message:
        return message
    packed = base64.b64encode(zlib.compress(raw)).decode("ascii")
    if len(packed) >= len(raw):
        return message
    result = {key: value for key, value in message.items() if key != "content"}
    result["content_zlib"] = packed
    return result


def _unpack_message(message):
    if not isinstance(message, dict) or "content_zlib" not in message:
        return message
    if "content" in message or not isinstance(message["content_zlib"], str):
        raise CodecError("invalid_compressed_message")
    try:
        packed = base64.b64decode(message["content_zlib"], validate=True)
        decoder = zlib.decompressobj()
        content = decoder.decompress(packed, MAX_TEXT_BYTES + 1)
        if (
            len(content) > MAX_TEXT_BYTES
            or not decoder.eof
            or decoder.unused_data
            or decoder.unconsumed_tail
        ):
            raise CodecError("compressed_message_size_or_stream_limit")
        content = content.decode("utf-8")
    except (ValueError, zlib.error) as exc:
        raise CodecError("invalid_compressed_message") from exc
    result = {key: value for key, value in message.items() if key != "content_zlib"}
    result["content"] = content
    return result


def _previous(events, event, kind):
    return next(
        (e for e in reversed(events) if e.type == kind and e.turn_id == event.turn_id),
        None,
    )


def _reference(events, sequence, kind, *, turn_id=_ANY_TURN):
    if type(sequence) is not int or not 1 <= sequence <= len(events):
        raise CodecError("invalid_event_reference")
    source = events[sequence - 1]
    if source.type != kind or turn_id is not _ANY_TURN and source.turn_id != turn_id:
        raise CodecError("invalid_event_reference_type_or_turn")
    return source


def _state_delta(before, after):
    """Append/order-preserving ledger changes; unusual external commits use full state."""
    old = {r.id: r for r in before.requirements}
    old_ids = [r.id for r in before.requirements]
    new_ids = [r.id for r in after.requirements]
    if len(set(new_ids)) != len(new_ids) or old_ids != new_ids[: len(old_ids)]:
        return None
    return {
        "version": after.version,
        "goal_epoch": after.goal_epoch,
        "conflicts": after.conflicts,
        "requirements": [
            r.model_dump(exclude_defaults=True, exclude_none=True)
            for r in after.requirements
            if r.id not in old or r != old[r.id]
        ],
    }


def encode_event(event: Event, events: list[Event], state: ShoppingState) -> dict:
    """Encode repeated payloads by backward reference without changing event semantics."""
    raw = event.model_dump(exclude_defaults=True)
    payload = deepcopy(event.payload)
    changed = False
    if event.type == "state_committed":
        after = ShoppingState.model_validate(payload["state"])
        delta = _state_delta(state, after)
        if delta is not None:
            payload.pop("state")
            payload["state_delta"] = delta
        else:
            payload["state"] = after.model_dump(
                exclude_defaults=True, exclude_none=True
            )
        source = _previous(events, event, "decision_validated")
        if source and source.payload["updates"] == payload.get("updates"):
            payload.pop("updates")
            payload["updates_event"] = source.seq
        changed = True
    elif event.type == "model_request" and "messages" in payload:
        messages = []
        for message in payload["messages"]:
            reference = next(
                (
                    (e.seq, i)
                    for e in reversed(events)
                    if e.type == "model_request"
                    for i, previous in enumerate(e.payload.get("messages", []))
                    if previous == message
                ),
                None,
            )
            stored = (
                {"message_ref": list(reference)}
                if reference
                else _pack_message(message)
            )
            messages.append(stored)
            changed |= stored != message
        payload["messages"] = messages
    elif event.type == "decision_validated":
        source = _previous(events, event, "model_response")
        if source:
            try:
                decision = Decision.model_validate_json(
                    source.payload["content"]
                ).model_dump()
            except (KeyError, ValueError):
                decision = None
            if decision == payload:
                payload = {"response_event": source.seq}
                changed = True
    elif event.type == "assistant_response" and payload.get("products"):
        source = next(
            (
                e
                for e in reversed(events)
                if e.type == "search_result"
                and e.payload["search_id"] == payload.get("search_id")
            ),
            None,
        )
        if source:
            candidates = {p["id"]: p for p in source.payload["candidates"]}
            ids = [p["id"] for p in payload["products"]]
            if all(candidates.get(p["id"]) == p for p in payload["products"]):
                payload.pop("products")
                payload["products_ref"] = {"event": source.seq, "ids": ids}
                changed = True
    elif event.type == "turn_completed":
        source = _previous(events, event, "assistant_response")
        if source and payload == {"response": source.payload}:
            payload = {"response_event": source.seq}
            changed = True
    raw["payload"] = payload
    if changed:
        raw["storage_version"] = 2
    return raw


def decode_event(raw: dict, events: list[Event], state: ShoppingState) -> Event:
    """Expand v2 before ordinary owner/sequence/state-history checks and presentation."""
    raw = deepcopy(raw)
    version = raw.pop("storage_version", 1)
    if type(version) is not int or version not in {1, 2}:
        raise CodecError("unsupported_storage_version")
    event = Event.model_validate(raw)
    if version == 1:
        return event
    payload = event.payload
    if event.type == "state_committed":
        if "state_delta" in payload:
            if "state" in payload:
                raise CodecError("ambiguous_state_encoding")
            delta = payload.pop("state_delta")
            if not isinstance(delta, dict) or set(delta) != {
                "version",
                "goal_epoch",
                "conflicts",
                "requirements",
            }:
                raise CodecError("invalid_state_delta")
            rows = [r.model_copy(deep=True) for r in state.requirements]
            positions = {r.id: i for i, r in enumerate(rows)}
            seen = set()
            for item in delta["requirements"]:
                row = Requirement.model_validate(item)
                if row.id in seen:
                    raise CodecError("duplicate_state_delta_requirement")
                seen.add(row.id)
                if row.id in positions:
                    rows[positions[row.id]] = row
                else:
                    positions[row.id] = len(rows)
                    rows.append(row)
            payload["state"] = ShoppingState(
                version=delta["version"],
                goal_epoch=delta["goal_epoch"],
                conflicts=delta["conflicts"],
                requirements=rows,
            ).model_dump()
        else:
            payload["state"] = ShoppingState.model_validate(
                payload["state"]
            ).model_dump()
        if "updates_event" in payload:
            if "updates" in payload:
                raise CodecError("ambiguous_updates_encoding")
            source = _reference(
                events,
                payload.pop("updates_event"),
                "decision_validated",
                turn_id=event.turn_id,
            )
            payload["updates"] = deepcopy(source.payload["updates"])
    elif event.type == "model_request":
        messages = []
        for message in payload["messages"]:
            if (
                isinstance(message, dict)
                and "message_ref" in message
                and set(message) != {"message_ref"}
            ):
                raise CodecError("ambiguous_message_reference")
            if isinstance(message, dict) and set(message) == {"message_ref"}:
                reference = message["message_ref"]
                if not isinstance(reference, list) or len(reference) != 2:
                    raise CodecError("invalid_message_reference")
                source = _reference(events, reference[0], "model_request")
                index = reference[1]
                if type(index) is not int or not 0 <= index < len(
                    source.payload["messages"]
                ):
                    raise CodecError("invalid_message_reference_index")
                message = source.payload["messages"][index]
            messages.append(deepcopy(_unpack_message(message)))
        payload["messages"] = messages
    elif event.type == "decision_validated":
        if set(payload) != {"response_event"}:
            raise CodecError("invalid_decision_reference")
        source = _reference(
            events, payload["response_event"], "model_response", turn_id=event.turn_id
        )
        payload = Decision.model_validate_json(source.payload["content"]).model_dump()
    elif event.type == "assistant_response":
        if "products" in payload:
            raise CodecError("ambiguous_product_encoding")
        reference = payload.pop("products_ref")
        if not isinstance(reference, dict) or set(reference) != {"event", "ids"}:
            raise CodecError("invalid_product_reference")
        source = _reference(events, reference["event"], "search_result")
        if source.payload["search_id"] != payload.get("search_id"):
            raise CodecError("product_reference_search_mismatch")
        ids = reference["ids"]
        if (
            not isinstance(ids, list)
            or not ids
            or any(not isinstance(p, str) for p in ids)
        ):
            raise CodecError("invalid_product_reference_ids")
        candidates = {p["id"]: p for p in source.payload["candidates"]}
        if any(ident not in candidates for ident in ids):
            raise CodecError("unseen_product_reference")
        payload["products"] = [deepcopy(candidates[ident]) for ident in ids]
    elif event.type == "turn_completed":
        if set(payload) != {"response_event"}:
            raise CodecError("invalid_completion_reference")
        source = _reference(
            events,
            payload["response_event"],
            "assistant_response",
            turn_id=event.turn_id,
        )
        payload = {"response": deepcopy(source.payload)}
    else:
        raise CodecError("unsupported_compact_event_type")
    return event.model_copy(update={"payload": payload})
