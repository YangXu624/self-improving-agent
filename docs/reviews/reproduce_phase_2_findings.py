"""Offline reproduction of reviewed baseline defects, not a regression/pass benchmark.

Run from the repository with .venv/bin/python. All product/state inputs are synthetic;
SQLite/source fixtures live only in a TemporaryDirectory. Assertions capture the baseline
bugs: after they are fixed, these observations should change and this snapshot may fail.
"""

import json
import tempfile
from pathlib import Path

from shopping_agent.contracts import Search, ShoppingState
from shopping_agent.retrieval import LexicalSearch, assess, build_index, project
from shopping_agent.state import apply_updates


def addition(field: str, value: str | float, quote: str) -> dict:
    return {
        "op": "ADD",
        "quote": quote,
        "requirement": {
            "field": field,
            "op": "lt" if field == "price" else "eq",
            "value": value,
            "quote": quote,
        },
    }


def edit(state: ShoppingState, updates: list[dict], message: str) -> ShoppingState:
    return apply_updates(
        state,
        updates,
        expected_version=state.version,
        user_message=message,
        source_event_id="synthetic-review-evidence",
    )


def main() -> None:
    state = edit(ShoppingState(), [addition("price", 60.0, " \t")], "show boots")
    assert len(state.requirements) == 1 and state.requirements[0].quote == " \t"
    print("F1 blank ADD accepted: state_version=1, hard price < 60")
    reset = edit(state, [{"op": "NEW_GOAL", "quote": "\n\t"}], "thank you")
    active = [r for r in reset.requirements if r.status == "active"]
    assert not active and reset.goal_epoch == 1
    print("F1 blank NEW_GOAL accepted on 'thank you': active_count=0, goal_epoch=1")

    row = {
        "parent_asin": "synthetic-review-boot",
        "title": "Hiking boots",
        "categories": ["Shoes", "Hiking Boots"],
        "features": [],
        "description": [],
        "details": {"Department": "mens"},
        "price": 45.0,
    }
    with tempfile.TemporaryDirectory(prefix="astra-review-") as temporary:
        source, index = (
            Path(temporary) / "source.jsonl",
            Path(temporary) / "index.sqlite",
        )
        source.write_text(json.dumps(row) + "\n")
        build_index(source, index)
        tool = LexicalSearch(index)
        try:
            for field, first, second in [
                ("department", "men", "mens"),
                ("product_type", "boots", "hiking boots"),
            ]:
                state = edit(
                    ShoppingState(),
                    [addition(field, first, first), addition(field, second, second)],
                    f"{first} and {second}",
                )
                verdict = assess(project(row), state)
                assert verdict["eligible"] and state.conflicts == [field]
                try:
                    tool.search(Search(type="SEARCH", query="boots"), state)
                except ValueError as error:
                    assert str(error) == "unresolved_state_conflicts"
                else:
                    raise AssertionError(
                        "Expected the baseline false-conflict rejection"
                    )
                print(f"F2 {field}: eligible=True, conflict={field}, search rejected")
        finally:
            tool.close()


if __name__ == "__main__":
    main()
