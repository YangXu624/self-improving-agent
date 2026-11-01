"""Local CLI for index construction, chat, and session inspection."""

import argparse
import json
import sqlite3
import sys

from .agent import ShoppingAgent
from .cards import PROFILES
from .configuration import load_env
from .context import builder_for_profile
from .memory_views import FORMATS
from .provider import DeepSeekPolicy, ProviderError
from .retrieval import LexicalSearch, build_index, file_hash
from .sessions import SessionError, SessionStore
from .user_memory import UserMemoryStore


def parser():
    p = argparse.ArgumentParser(
        description="Conversational shopping with optional persistent user memory"
    )
    commands = p.add_subparsers(dest="command", required=True)
    index = commands.add_parser("index", help="Build the local catalogue's FTS5 index")
    index.add_argument("--catalogue", default="data/catalogue/catalog.jsonl")
    index.add_argument("--images", default="data/catalogue/product_images.json")
    index.add_argument("--index", default="data/index/catalogue.sqlite")
    index.add_argument("--rebuild", action="store_true")
    chat = commands.add_parser(
        "chat", help="Start or resume a DeepSeek shopping session"
    )
    chat.add_argument("--user", required=True)
    chat.add_argument(
        "--session", help="Resume this session UUID (same owner required)"
    )
    chat.add_argument("--sessions-root", default="data/sessions")
    chat.add_argument("--index", default="data/index/catalogue.sqlite")
    chat.add_argument("--catalogue", default="data/catalogue/catalog.jsonl")
    chat.add_argument("--env-file", default=".env")
    chat.add_argument("--cards-profile", choices=tuple(PROFILES), default="baseline")
    chat.add_argument(
        "--memory-format",
        choices=FORMATS,
        default="compact",
        help="Compact state/text memories, or historical legacy policy format",
    )
    chat.add_argument(
        "--user-memory",
        action="store_true",
        help="Read/update this user's persistent Markdown profile (default OFF)",
    )
    chat.add_argument("--user-memory-root", default="data/user-memory")
    chat.add_argument("--message", help="One turn instead of interactive chat")
    chat.add_argument("--request-id", help="Idempotency key; only with --message")
    chat.add_argument(
        "--json", action="store_true", help="Print a complete JSON response"
    )
    inspect = commands.add_parser(
        "inspect", help="Inspect state/history without model calls"
    )
    inspect.add_argument("--user", required=True)
    inspect.add_argument("--session", required=True)
    inspect.add_argument("--sessions-root", default="data/sessions")
    inspect.add_argument(
        "--events", action="store_true", help="Include the full event history"
    )
    return p


def display(response, as_json):
    if as_json:
        print(json.dumps(response, ensure_ascii=False, indent=2))
        return
    print(response["message"])
    for p in response["products"]:
        f = p["facts"]
        price = f"USD {f['price']:.2f}" if f["price"] is not None else "price unknown"
        print(f"\n{p['id']} | {p['title']} | {price}")
        print(
            "  "
            + "; ".join(
                f"{k}: {v if v is not None else 'unknown'}"
                for k, v in f.items()
                if k != "price"
            )
        )
        print("  Categories: " + " > ".join(p["categories"]))
        print("  Image URL: " + (p["image_url"] or "unknown"))
        print("  Verified hard requirement IDs: " + ", ".join(p["matched_hard_ids"]))
    if response["status"] == "error":
        print("Error code: " + response["error"])
    used = response["budget_used"]
    print(
        f"[state v{response['state_version']}; calls {used['model_calls']}; searches {used['searches']}]"
    )


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "index":
            meta = build_index(
                args.catalogue, args.index, args.images, replace=args.rebuild
            )
            print(json.dumps(meta, indent=2))
            return 0
        if args.command == "inspect":
            with SessionStore(args.sessions_root).open(
                args.user, args.session
            ) as session:
                value = {
                    "session_id": session.id,
                    "user_id": session.user_id,
                    "state": session.state.model_dump(),
                    "event_count": len(session.events),
                }
                if args.events:
                    value["events"] = [e.model_dump() for e in session.events]
                print(json.dumps(value, ensure_ascii=False, indent=2))
            return 0
        if args.request_id and args.message is None:
            raise ValueError("--request-id requires --message")
        load_env(args.env_file)
        policy = DeepSeekPolicy()
        search = LexicalSearch(
            args.index, expected_catalogue_hash=file_hash(args.catalogue)
        )
        try:
            store = SessionStore(args.sessions_root, snapshot_format=args.memory_format)
            sid = args.session or store.create(args.user)
            # Validate ownership even when the interactive user exits immediately.
            with store.open(args.user, sid):
                pass
            agent = ShoppingAgent(
                store,
                search,
                policy,
                context_builder=builder_for_profile(
                    args.cards_profile, memory_format=args.memory_format
                ),
                memory_format=args.memory_format,
                user_memory=UserMemoryStore(args.user_memory_root)
                if args.user_memory
                else None,
            )
            if args.message is not None:
                response = agent.turn(
                    args.user, sid, args.message, request_id=args.request_id
                )
                display(response, args.json)
                return 0 if response["status"] == "ok" else 1
            print(f"Session: {sid}\nCommands: /state, /quit")
            while True:
                try:
                    message = input("You> ")
                except EOFError:
                    break
                if message.strip() == "/quit":
                    break
                if message.strip() == "/state":
                    with store.open(args.user, sid) as session:
                        print(
                            json.dumps(
                                session.state.model_dump(), ensure_ascii=False, indent=2
                            )
                        )
                elif message.strip():
                    display(agent.turn(args.user, sid, message), args.json)
            return 0
        finally:
            search.close()
    except ProviderError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except (SessionError, PermissionError, ValueError, OSError, sqlite3.Error) as exc:
        # No exception repr/traceback or remote error body on the CLI. Local messages are
        # actionable but filenames and catalogue contents are not echoed by library errors.
        if isinstance(exc, (SessionError, ValueError)) and not isinstance(
            exc, json.JSONDecodeError
        ):
            message = str(exc)
        else:
            message = "Local file/index access failed; check paths, ownership and file integrity"
        print("Error: " + message, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(
            "\nInterrupted. Inspect the session trace before retrying.", file=sys.stderr
        )
        return 130
