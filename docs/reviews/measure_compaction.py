"""Read-only trace re-encoding and current-context comparison; never calls a provider.

python docs/reviews/measure_compaction.py /path/to/events.jsonl
Optional offline counts: --tokenizer /path/to/tokenizer.json (requires audit-only tokenizers).
Raw session/catalogue records and generated outputs must remain outside Git.
"""

import argparse
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from shopping_agent.context import build_context
from shopping_agent.contracts import ShoppingState
from shopping_agent.event_codec import decode_event, encode_event
from shopping_agent.sessions import dumps


def measure(trace, tokenizer=None):
    """Verify exact canonical event equality, including prompt strings, under new encoding."""
    original = trace.read_bytes()
    state, events, reconstructed, output, requests = ShoppingState(), [], [], [], []
    turns = {}
    for line in original.splitlines():
        event = decode_event(json.loads(line), events, state)
        if event.seq != len(events) + 1:
            raise ValueError("Noncontiguous source trace")
        encoded = encode_event(event, reconstructed, state)
        recovered = decode_event(encoded, reconstructed, state)
        if recovered != event:
            raise ValueError("Lossless event roundtrip failed")
        output.append(dumps(encoded, compact=True) + "\n")
        if event.type == "model_request":
            old = event.payload["messages"]
            context = json.loads(old[-1]["content"])
            # Use replayed canonical state, including history, never reverse-engineer
            # authoritative state from a compact model-facing projection.
            session = SimpleNamespace(state=state, events=events)
            new = (
                build_context(
                    session,
                    context["current_user_message"],
                    context["latest_search"],
                    context["validation_feedback"],
                    context["remaining_budget"],
                    context["edits_allowed"],
                )
                if context["prompt_version"] == "shopping-baseline-v2"
                else old
            )
            turn = turns.setdefault(event.turn_id, len(turns) + 1)
            item = {
                "turn": turn,
                "call": event.payload["ordinal"],
                "before_characters": sum(len(m["content"]) for m in old),
                "after_characters": sum(len(m["content"]) for m in new),
            }
            if tokenizer:
                item.update(
                    before_content_tokens=sum(
                        len(
                            tokenizer.encode(m["content"], add_special_tokens=False).ids
                        )
                        for m in old
                    ),
                    after_content_tokens=sum(
                        len(
                            tokenizer.encode(m["content"], add_special_tokens=False).ids
                        )
                        for m in new
                    ),
                )
            requests.append(item)
        if event.type == "state_committed":
            state = ShoppingState.model_validate(event.payload["state"])
        events.append(event)
        reconstructed.append(recovered)
    if trace.read_bytes() != original:
        raise ValueError("Source trace changed during read-only measurement")
    # Check compact snapshots are semantically identical, including retired requirements.
    snapshot = state.model_dump(exclude_defaults=True, exclude_none=True)
    if ShoppingState.model_validate(snapshot) != state:
        raise ValueError("Snapshot roundtrip failed")
    return {
        "source_sha256": hashlib.sha256(original).hexdigest(),
        "events": len(events),
        "lossless_event_roundtrip": True,
        "original_log_bytes": len(original),
        "reencoded_log_bytes": len("".join(output).encode()),
        "canonical_state_bytes": len(dumps(state.model_dump()).encode()),
        "compact_state_bytes": len(dumps(snapshot, compact=True).encode()),
        "requests": requests,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--tokenizer", type=Path)
    args = parser.parse_args()
    tokenizer = None
    if args.tokenizer:
        from tokenizers import Tokenizer

        tokenizer = Tokenizer.from_file(str(args.tokenizer))
    print(json.dumps(measure(args.trace, tokenizer), indent=2))


if __name__ == "__main__":
    main()
