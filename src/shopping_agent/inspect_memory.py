"""CLI and programmatic inspector for user memory and centralized experience memory.

Allows developers and evaluators to inspect active/superseded/deleted customer memories,
similarity rankings, change histories, and centralized procedural lessons.
"""

import argparse
import json
from pathlib import Path

from .experience.store import ExperienceStore
from .user_memory import UserMemoryStore


def inspect_user_memory(user_id: str, root: str | Path = "data/user-memory") -> dict:
    """Return a structured summary of a customer's active, superseded, and history records."""
    store = UserMemoryStore(root)
    profile = store.read(user_id)
    active = [r.model_dump() for r in profile.records if r.status == "active"]
    superseded = [r.model_dump() for r in profile.records if r.status == "superseded"]
    deleted = [r.model_dump() for r in profile.records if r.status in ("deleted", "retracted")]

    # Exclude raw float embeddings from CLI json display
    for group in (active, superseded, deleted):
        for rec in group:
            rec.pop("embedding", None)

    return {
        "user_id": profile.user_id,
        "revision": profile.revision,
        "last_consolidated_session_id": profile.last_consolidated_session_id,
        "active_count": len(active),
        "superseded_count": len(superseded),
        "deleted_count": len(deleted),
        "active": active,
        "superseded": superseded,
        "deleted": deleted,
    }


def inspect_experience_memory(db_path: str | Path = "data/experience/lessons.db") -> dict:
    """Return a structured summary of centralized procedural lessons."""
    store = ExperienceStore(db_path)
    lessons = store.list_lessons()
    summaries = []
    for les in lessons:
        d = les.to_dict()
        d.pop("embedding", None)
        summaries.append(d)

    return {
        "total_lessons": len(lessons),
        "active_lessons": len([les for les in lessons if les.status == "active"]),
        "candidate_lessons": len([les for les in lessons if les.status == "candidate"]),
        "lessons": summaries,
    }


def main():
    parser = argparse.ArgumentParser(description="ASTRA Memory Inspector")
    subparsers = parser.add_subparsers(dest="command", required=True)

    user_parser = subparsers.add_parser("user", help="Inspect customer semantic memory")
    user_parser.add_argument("user_id", help="Customer user ID")
    user_parser.add_argument("--root", default="data/user-memory", help="User memory root directory")

    query_parser = subparsers.add_parser("query", help="Test semantic retrieval for a user")
    query_parser.add_argument("user_id", help="Customer user ID")
    query_parser.add_argument("text", help="Query text to match")
    query_parser.add_argument("--root", default="data/user-memory", help="User memory root directory")
    query_parser.add_argument("--limit", type=int, default=5)
    query_parser.add_argument("--min-similarity", type=float, default=0.50)

    exp_parser = subparsers.add_parser("experience", help="Inspect centralized experience memory")
    exp_parser.add_argument("--db", default="data/experience/lessons.db", help="Path to experience database")

    args = parser.parse_args()

    if args.command == "user":
        info = inspect_user_memory(args.user_id, args.root)
        print(json.dumps(info, indent=2))
    elif args.command == "query":
        store = UserMemoryStore(args.root)
        results = store.retrieve(args.user_id, args.text, limit=args.limit, min_similarity=args.min_similarity)
        output = [
            {
                "id": r.id,
                "category": r.category,
                "attribute": r.attribute,
                "value": r.value,
                "scope": r.scope,
                "score": round(score, 4),
                "quote": r.quote,
            }
            for r, score in results
        ]
        print(json.dumps(output, indent=2))
    elif args.command == "experience":
        info = inspect_experience_memory(args.db)
        print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
