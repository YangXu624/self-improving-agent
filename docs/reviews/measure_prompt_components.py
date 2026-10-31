"""Count saved baseline-v2 prompt components offline using a supplied tokenizer.

Usage: PYTHONPATH=/path/to/temporary/tokenizers-install python THIS_FILE \
    /path/to/events.jsonl /path/to/published/tokenizer.json

Requires tokenizers only in the audit environment, not the application. Reads the
supplied trace and tokenizer; prints counts, never prompt contents. Makes no API
requests and writes no session, index or source files.
"""

import argparse
import collections
import hashlib
import json
from pathlib import Path


def field_spans(raw):
    """Locate each top-level JSON value, including whitespace after its colon."""
    decoder, position, spans = json.JSONDecoder(), 1, []
    while position < len(raw):
        while raw[position] in " ,\n\t":
            position += 1
        if raw[position] == "}":
            break
        key, position = decoder.raw_decode(raw, position)
        while raw[position].isspace():
            position += 1
        if raw[position] != ":":
            raise ValueError("Expected JSON field separator")
        position += 1
        start = position
        while raw[position].isspace():
            position += 1
        _, position = decoder.raw_decode(raw, position)
        spans.append((start, position, key))
    return spans


def count_components(tokenizer, raw, spans):
    """Assign by first character offset; unassigned separators go to other."""
    counts = collections.Counter({key: 0 for _, _, key in spans})
    for start, _ in tokenizer.encode(raw, add_special_tokens=False).offsets:
        label = next(
            (key for left, right, key in spans if left <= start < right), "other"
        )
        counts[label] += 1
    return counts


def main():
    from tokenizers import Tokenizer

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("tokenizer", type=Path)
    args = parser.parse_args()
    tokenizer = Tokenizer.from_file(str(args.tokenizer))
    events = [json.loads(line) for line in args.trace.read_text().splitlines()]
    responses = {
        (e["turn_id"], e["payload"]["ordinal"]): e["payload"]
        for e in events
        if e["type"] == "model_response"
    }
    totals = collections.defaultdict(collections.Counter)
    turns = {}
    print(
        json.dumps(
            {
                "tokenizer_sha256": hashlib.sha256(
                    args.tokenizer.read_bytes()
                ).hexdigest()
            }
        )
    )
    for event in events:
        if event["type"] != "model_request":
            continue
        request = event["payload"]
        if request["prompt_version"] != "shopping-baseline-v2":
            raise ValueError("This diagnostic supports saved baseline-v2 prompts only")
        messages = request["messages"]
        if [m["role"] for m in messages] != ["system", "user"]:
            raise ValueError("Unexpected baseline message layout")
        system, payload = (m["content"] for m in messages)
        marker = "\nDecision JSON schema:\n"
        before, separator, after = system.partition(marker)
        if not separator:
            raise ValueError("Missing saved schema marker")
        _, schema_length = json.JSONDecoder().raw_decode(after)
        schema_start = len(before) + len(separator)
        system_counts = count_components(
            tokenizer,
            system,
            [
                (0, len(before), "instructions"),
                (schema_start, schema_start + schema_length, "schema"),
            ],
        )
        counts = count_components(tokenizer, payload, field_spans(payload))
        response = responses[(event["turn_id"], request["ordinal"])]
        usage = response["metadata"]["usage"]
        groups = {
            "system_instructions": system_counts["instructions"],
            "schema_example_separators": system_counts["schema"]
            + system_counts["other"],
            "session_state_message_dialogue": sum(
                counts[k] for k in ("state", "current_user_message", "recent_dialogue")
            ),
            "latest_search": counts["latest_search"],
            "other_payload": sum(
                counts[k]
                for k in (
                    "validation_feedback",
                    "remaining_budget",
                    "edits_allowed",
                    "prompt_version",
                    "other",
                )
            ),
        }
        groups["unattributed_api_difference"] = usage["prompt_tokens"] - sum(
            groups.values()
        )
        turn = turns.setdefault(event["turn_id"], len(turns) + 1)
        totals[turn].update(groups)
        print(
            json.dumps(
                {
                    "turn": turn,
                    "seq": event["seq"],
                    "call": request["ordinal"],
                    "components": groups,
                    "api_input": usage["prompt_tokens"],
                    "api_output": usage["completion_tokens"],
                }
            )
        )
    print(json.dumps({"totals": {turn: dict(value) for turn, value in totals.items()}}))


if __name__ == "__main__":
    main()
