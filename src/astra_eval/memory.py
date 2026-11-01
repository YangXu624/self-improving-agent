"""Within-scenario memory for the simulated shopper (consistency only, never learning).

Three separate things:
  * the immutable hidden profile, sent on every model call;
  * a complete append-only transcript for replay/debugging, never sent whole to the model;
  * a deterministic ledger plus a bounded recent-dialogue window, sent each call under a
    token budget. The ledger is built by code from structured replies, not summarised by a
    model, so nothing generated can override the profile.
The shopper never sees ASTRA's memories, ground truth, scores or the evaluation condition.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .models import ShopperProfile, ShopperReply

CHARS_PER_TOKEN = (
    3  # conservative: overestimates tokens, so we trim rather than overflow
)
MAX_LEDGER_QUESTIONS = 12
MAX_PRODUCTS_SHOWN = 5


class ContextBudgetError(ValueError):
    """Essential context (profile, ledger, current message) does not fit the budget."""


def estimate_tokens(text):
    return -(-len(text) // CHARS_PER_TOKEN)


@dataclass(frozen=True)
class AssistantView:
    """What a real shopper sees of ASTRA's turn: its words and any product cards."""

    text: str
    products: tuple[dict, ...] = ()
    turn: int = 1
    turns_left: int = 0


@dataclass
class Transcript:
    """Append-only record of the whole conversation, optionally mirrored to JSONL."""

    path: Path | None = None
    _entries: list = field(default_factory=list)

    def append(self, entry):
        self._entries.append(entry)
        if self.path is not None:
            with Path(self.path).open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n"
                )
                handle.flush()

    @property
    def entries(self):
        return tuple(self._entries)


def questions_in(text):
    """Sentences of an assistant message that end in a question mark.

    Splits only at sentence punctuation followed by whitespace, so "$29.99" stays whole.
    """
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.strip() for s in sentences if s.strip().endswith("?")]


def matched_keys(profile, question):
    """Profile facts a question asks about (lexical keywords, deterministic)."""
    lowered = question.lower()
    return [
        f.key
        for f in profile.facts
        if any(re.search(rf"\b{re.escape(k.lower())}s?\b", lowered) for k in f.keywords)
    ]


class ShopperMemory:
    def __init__(
        self,
        profile: ShopperProfile,
        *,
        window_turns=8,
        transcript=None,
        disclosure_protocol="legacy",
        private_context=None,
    ):
        if window_turns < 1:
            raise ValueError("window_turns must be at least 1")
        self.profile = profile
        self.private_context = (
            json.loads(json.dumps(private_context))
            if private_context is not None
            else None
        )
        self.disclosure_protocol = disclosure_protocol
        self.window_turns = window_turns
        self.transcript = transcript or Transcript()
        self.revealed = {}  # key -> {"turn": n, "statement": text}
        self.questions = []  # {"turn", "question", "facts", "repeat"}
        self.repeat_counts = {}
        self.unmatched_questions = 0  # questions about nothing in the profile
        self.products_seen = []
        self.turn = 0

    # ---- recording ------------------------------------------------------------
    def record_shopper(self, turn, message, reveals=(), *, action="reply", flags=()):
        for key in reveals:
            fact = self.profile.fact(key)
            if fact is not None and key not in self.revealed:
                self.revealed[key] = {"turn": turn, "statement": fact.statement}
        self.transcript.append(
            {
                "turn": turn,
                "role": "shopper",
                "text": message,
                "reveals": list(reveals),
                "action": action,
                "flags": list(flags),
            }
        )

    def record_assistant(self, view: AssistantView, extra=None):
        """Log ASTRA's message; note which of its questions were already answered."""
        self.turn = view.turn
        for question in questions_in(view.text):
            keys = matched_keys(self.profile, question)
            repeat = bool(keys) and all(k in self.revealed for k in keys)
            self.unmatched_questions += not keys
            for key in keys:
                if key in self.revealed:
                    self.repeat_counts[key] = self.repeat_counts.get(key, 0) + 1
            self.questions.append(
                {
                    "turn": view.turn,
                    "question": question[:200],
                    "facts": keys,
                    "repeat": repeat,
                }
            )
        for product in view.products:
            self.products_seen.append(
                {
                    "title": str(product.get("title", ""))[:80],
                    "price": product.get("price"),
                }
            )
        self.transcript.append(
            {
                "turn": view.turn,
                "role": "assistant",
                "text": view.text,
                "products": list(view.products),
                **(extra or {}),
            }
        )

    def current_questions(self, view: AssistantView):
        """Questions in this assistant message, as (text, matched keys, already answered)."""
        return [
            (
                q,
                matched_keys(self.profile, q),
                bool(matched_keys(self.profile, q))
                and all(k in self.revealed for k in matched_keys(self.profile, q)),
            )
            for q in questions_in(view.text)
        ]

    # ---- model context --------------------------------------------------------
    def ledger(self):
        return {
            "revealed_so_far": self.revealed,
            "questions_asked_by_assistant": self.questions[-MAX_LEDGER_QUESTIONS:],
            "times_assistant_repeated_an_answered_question": dict(self.repeat_counts),
            "products_shown_recently": self.products_seen[-MAX_PRODUCTS_SHOWN:],
        }

    def system_prompt(self):
        """Identical on every call for a scenario (immutable profile and rules)."""
        facts = [
            {
                "key": f.key,
                "importance": "firm" if f.kind == "hard" else "flexible",
                "what_you_would_say": f.statement,
            }
            for f in self.profile.facts
        ]
        return (
            (
                "Use reveals=[] when this message states no profile facts. Ask a specific useful question, accept suitable options when satisfied, or give up; do not repeat browsing acknowledgments. Do not disclose model numbers or distinctive product-name fragments. "
                if self.disclosure_protocol == "target-v1"
                else ""
            )
            + "You are role-playing a shopper talking to a shopping assistant. Stay in "
            "character. Your hidden profile below is fixed and is the only truth about what "
            "you want; the notes and dialogue you are given never override it.\n"
            f"Persona: {self.profile.persona}\n"
            + (
                f"Current-visit private roleplay context (JSON): {json.dumps(self.private_context, ensure_ascii=False)}\n"
                if self.private_context is not None
                else ""
            )
            + f"Hidden profile (JSON): {json.dumps(facts, ensure_ascii=False)}\n"
            f"Allowed disclosure keys: {json.dumps([f.key for f in self.profile.facts])}. "
            "Only these hidden-profile keys may appear in reveals; names from the private "
            "roleplay context (such as current_goal) and ledger are never disclosure keys. "
            "Context goals describe the situation; they do not replace or broaden the "
            "fixed requirements in the hidden profile. "
            "Use reveals=[] for questions, acknowledgments, or comments that state no "
            "profile fact value. Mentioning 'my budget' without its amount does not disclose "
            "a budget. Never claim a disclosure unless your message communicates that fact. "
            "Repeating an already-disclosed fact is allowed if you actually state it again. "
            f"If asked about something not in the profile say: {self.profile.no_preference_reply!r}\n"
            "Rules: reveal information progressively, at most two profile facts per message, "
            "preferably only what the assistant asked about. Never invent a requirement, "
            "price, colour, brand or size that is not in the profile. Never change an earlier "
            "answer. If asked something you already answered, repeat the same answer briefly. "
            "Do not say you have no preference about an attribute that the profile specifies. "
            "Do not name or guess a specific product. Use action 'accept' only if the "
            "products shown fit your firm needs, 'give_up' only if you want to stop, "
            "otherwise 'reply'. Respond with ONLY a JSON object: "
            '{"message": string, "reveals": [profile keys you stated in this message], '
            '"action": "reply"|"accept"|"give_up"}.'
        )

    def window(self):
        """Recent dialogue entries, at most window_turns of shopper+assistant exchanges."""
        entries = [
            e for e in self.transcript.entries if e["role"] in {"shopper", "assistant"}
        ]
        return entries[-2 * self.window_turns :]

    def build_messages(self, view: AssistantView, budget_tokens, feedback=()):
        """System + user messages under a token budget; oldest dialogue is dropped first."""
        recent = [
            {"role": e["role"], "text": e["text"][:500]}
            for e in self.window()
            if not (e["role"] == "assistant" and e["turn"] == view.turn)
        ]
        now = {
            "assistant_message": view.text,
            "products_shown": [
                {"title": str(p.get("title", ""))[:100], "price": p.get("price")}
                for p in view.products[:MAX_PRODUCTS_SHOWN]
            ],
            "questions": [
                {"question": q, "answered_before": answered}
                for q, _keys, answered in self.current_questions(view)
            ],
            "your_turn": view.turn,
            "turns_left": view.turns_left,
        }
        system = self.system_prompt()
        if feedback:
            system += (
                "\nCORRECTION REQUIRED: the previous response was rejected and did not "
                "update the disclosure ledger. Every key you claim must be supported in "
                "the corrected message, including keys that were valid previously. "
                "For this correction, include each claimed key's what_you_would_say "
                "sentence verbatim in your message, with optional surrounding prose; "
                "or use reveals=[] if you only comment or ask a question. Choose the "
                "facts yourself; do not reveal more than two. Validation feedback: "
                + "\n".join(feedback)
            )

        def render(dialogue):
            payload = {
                "valid_disclosure_keys": [f.key for f in self.profile.facts],
                "ledger_of_what_you_already_said": self.ledger(),
                "recent_dialogue": dialogue,
                "now": now,
            }
            if feedback:
                payload["fix_these_problems_in_your_previous_attempt"] = list(feedback)
            return json.dumps(payload, ensure_ascii=False)

        essential = estimate_tokens(system) + estimate_tokens(render([]))
        if essential > budget_tokens:
            raise ContextBudgetError("simulator_context_overflow")
        dropped = 0
        while (
            recent
            and estimate_tokens(system) + estimate_tokens(render(recent))
            > budget_tokens
        ):
            recent.pop(0)
            dropped += 1
        user = render(recent)
        return (
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            {
                "dialogue_entries_sent": len(recent),
                "dialogue_entries_dropped_for_budget": dropped,
                "estimated_prompt_tokens": estimate_tokens(system)
                + estimate_tokens(user),
            },
        )

    def apply(self, turn, reply: ShopperReply, flags=(), unverified=()):
        """Record a reply. Keys the message did not actually state stay out of the ledger."""
        confirmed = [k for k in reply.reveals if k not in set(unverified)]
        self.record_shopper(
            turn, reply.message, confirmed, action=reply.action, flags=flags
        )
