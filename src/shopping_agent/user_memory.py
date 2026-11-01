"""Evidence-linked user profiles. Markdown is authoritative; session logs stay separate.

The local application supplies the authenticated session owner (local labels are not
hosted authentication). Models propose records, never paths or filesystem operations.
"""

import fcntl
import hashlib
import json
import os
import re
import stat
import tempfile
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar, Literal
from uuid import uuid4

from pydantic import Field, model_validator

from .contracts import Decision, Event, Strict
from .sessions import Session

SECTIONS = {
    "fact": "Facts",
    "preference": "Preferences",
    "dislike": "Dislikes",
    "purchase": "Purchases",
}
MAX_PROFILE_BYTES = 512_000


class UserMemoryError(ValueError):
    """Safe, traceable validation/storage error without private file contents."""


class MemoryProposal(Strict):
    op: Literal["ADD", "REPLACE", "RETRACT"] = "ADD"
    category: Literal["fact", "preference", "dislike", "purchase"]
    attribute: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    value: str = Field(min_length=1, max_length=160)
    scope: str = Field(default="general", pattern=r"^[a-z][a-z0-9 /-]{0,79}$")
    basis: Literal["confirmed", "inferred"] = "confirmed"
    quote: str = Field(min_length=1, max_length=500)
    target_id: str | None = Field(default=None, pattern=r"^um-[a-f0-9]{32}$")

    @model_validator(mode="after")
    def operation_shape(self):
        if (self.op == "ADD") != (self.target_id is None):
            raise ValueError("ADD has no target; corrections/withdrawals require one")
        if not self.value.strip() or not self.quote.strip():
            raise ValueError("Memory content must not be blank")
        return self


class MemoryDecision(Decision):
    """Enabled-only policy contract; the baseline Decision remains unchanged."""

    user_memory_updates: list[MemoryProposal] = Field(
        default_factory=list, max_length=4
    )


class MemoryRecord(MemoryProposal):
    id: str = Field(pattern=r"^um-[a-f0-9]{32}$")
    status: Literal["active", "superseded", "retracted"] = "active"
    source_session_id: str
    source_event_id: str
    created_at: str
    closed_by_event_id: str | None = None


class UserProfile(Strict):
    user_id: str
    revision: int = Field(default=0, ge=0)
    records: list[MemoryRecord] = Field(default_factory=list, max_length=500)


def words(value: str) -> list[str]:
    return re.findall(r"[^\W_]+", value.casefold(), re.UNICODE)


def _contains(value: str, text: str) -> bool:
    needle, haystack = words(value), words(text)
    return bool(needle) and any(
        haystack[i : i + len(needle)] == needle
        for i in range(len(haystack) - len(needle) + 1)
    )


def validate_proposal(proposal: MemoryProposal, message: str) -> None:
    """Conservative English evidence gate, not a semantic proof of a user's beliefs.

    Values must be literal evidence. Persistence, first-person ownership, uncertainty,
    task/gift scope and explicit purchase/withdrawal are checked independently.
    """
    quote = proposal.quote
    if quote not in message or not _contains(proposal.value, quote):
        raise UserMemoryError("memory_requires_current_literal_evidence")
    if proposal.scope != "general" and not _contains(proposal.scope, quote):
        raise UserMemoryError("memory_scope_requires_literal_evidence")
    text = message.casefold().replace("’", "'")
    evidence = quote.casefold().replace("’", "'")
    offset = message.index(quote)
    prefix = message[:offset].rstrip()
    if prefix and prefix[-1] not in ".!?;\n":
        raise UserMemoryError("memory_quote_requires_own_statement")
    owner = re.match(
        r"^(?:(?:actually|remember(?: that)?|from now on|going forward)[,: ]+)?"
        r"(?:i\b|i'm\b|my (?:usual |general )?(?:preference|dislike|size)\b|"
        r"(?:forget|remove|withdraw) my\b)",
        evidence,
    )
    if not owner:
        raise UserMemoryError("memory_requires_first_person_ownership")
    if proposal.op != "RETRACT" and re.search(
        r"\b(?:do not|don't|never) (?:remember|save|store)\b", text
    ):
        raise UserMemoryError("user_declined_memory_storage")
    # A mixed gift/one-off turn fails closed; the model can ask for a separate statement.
    if re.search(
        r"\b(?:gift|for (?:my |a |the )?(?:dad|mom|mum|mother|father|friend|wife|husband|partner|daughter|son)|"
        r"this (?:time|trip|purchase|order|occasion)|just today|only today|one[- ]off|temporar(?:y|ily))\b",
        text,
    ):
        raise UserMemoryError("temporary_or_recipient_information_not_persistent")
    if proposal.op == "RETRACT":
        if not re.search(
            r"\b(?:forget|remove|withdraw|no longer|don't remember|do not remember)\b",
            evidence,
        ):
            raise UserMemoryError("memory_withdrawal_requires_explicit_request")
        return
    negation = r"\b(?:not|never|no|don't|cannot|can't|isn't|aren't)\b"
    if (
        proposal.category != "dislike"
        and re.search(negation, evidence)
        and not re.search(negation, proposal.value.casefold())
    ):
        raise UserMemoryError("memory_value_must_preserve_negation")
    if proposal.category == "preference" and not re.search(
        r"\b(?:prefer|like|love|preference)\b", evidence
    ):
        raise UserMemoryError("preference_requires_positive_preference_evidence")
    if proposal.category == "dislike" and not re.search(
        r"\b(?:dislike|hate|avoid)\b|\b(?:don't|do not) (?:like|prefer)\b", evidence
    ):
        raise UserMemoryError("dislike_requires_negative_preference_evidence")
    if proposal.category == "dislike" and re.search(
        r"\b(?:don't|do not|not|never) (?:generally |usually |really )?(?:dislike|hate|avoid)\b",
        evidence,
    ):
        raise UserMemoryError("negated_dislike_is_not_a_dislike")
    if proposal.scope == "general" and proposal.category in {"preference", "dislike"}:
        # Check the full complement, including an object before the value.
        quote_words, value_words = words(quote), words(proposal.value)
        end = next(
            i + len(value_words)
            for i in range(len(quote_words))
            if quote_words[i : i + len(value_words)] == value_words
        )
        neutral = {
            "always",
            "usually",
            "generally",
            "typically",
            "regularly",
            "in",
            "general",
            "now",
            "on",
        }
        neutral.update(
            {
                "i",
                "my",
                "think",
                "prefer",
                "preference",
                "like",
                "love",
                "dislike",
                "hate",
                "avoid",
                "remember",
                "that",
                "from",
                "going",
                "forward",
                "actually",
                "instead",
                "of",
                "rather",
                "the",
                "a",
                "an",
                "do",
                "not",
                "dont",
            }
        )
        start = end - len(value_words)
        if set(quote_words[:start] + quote_words[end:]) - neutral:
            raise UserMemoryError("specific_preference_requires_scope")
    if (
        re.search(r"\b(?:maybe|perhaps|might|i think|probably)\b", evidence)
        and proposal.basis == "confirmed"
    ):
        raise UserMemoryError("uncertain_information_cannot_be_confirmed")
    if proposal.category == "purchase":
        if proposal.basis != "confirmed" or not re.search(
            r"\bi (?:have |already )?(?:bought|purchased|ordered)\b", evidence
        ):
            raise UserMemoryError("purchase_requires_explicit_user_confirmation")
    else:
        persistent = re.search(
            r"\b(?:always|usually|generally|typically|regularly|frequent|frequently|in general|"
            r"remember|from now on|going forward|no longer|now prefer|now dislike)\b",
            evidence,
        )
        if not persistent:
            raise UserMemoryError("memory_requires_explicit_persistence")
    if proposal.op == "REPLACE" and not re.search(
        r"\b(?:actually|instead|now|no longer|changed|change|correction|rather)\b",
        evidence,
    ):
        raise UserMemoryError("memory_correction_requires_explicit_change")


def render_profile(profile: UserProfile) -> str:
    """One authoritative Markdown document; JSON-escaped bullets are safely reversible."""
    lines = [
        "# ASTRA user memory",
        f"- user_id: {json.dumps(profile.user_id)}",
        f"- revision: {profile.revision}",
    ]
    for category, heading in SECTIONS.items():
        lines.extend(["", f"## {heading}"])
        for record in profile.records:
            if record.category != category:
                continue
            lines.extend(["", f"### {record.id}"])
            lines.extend(
                f"- {key}: {json.dumps(value, ensure_ascii=False)}"
                for key, value in record.model_dump().items()
            )
    return "\n".join(lines) + "\n"


def parse_profile(text: str) -> UserProfile:
    header, records, current = {}, [], None
    for line in text.splitlines():
        if line.startswith("### "):
            current = {}
            records.append(current)
        elif line.startswith("- "):
            key, raw = line[2:].split(": ", 1)
            destination = header if current is None else current
            if key in destination:
                raise UserMemoryError("duplicate_profile_field")
            destination[key] = json.loads(raw)
    profile = UserProfile.model_validate({**header, "records": records})
    if render_profile(profile) != text:
        raise UserMemoryError("invalid_profile_markdown")
    if len({r.id for r in profile.records}) != len(profile.records):
        raise UserMemoryError("duplicate_memory_record_id")
    return profile


class UserMemoryStore:
    """Atomic per-user profiles with optimistic concurrency and append-preserving history."""

    _locks: ClassVar[dict[str, threading.RLock]] = {}
    _guard = threading.Lock()

    def __init__(self, root: str | Path = "data/user-memory"):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def directory(self, user_id: str) -> Path:
        if not isinstance(user_id, str) or not user_id.strip() or len(user_id) > 128:
            raise UserMemoryError("invalid_user_id")
        path = self.root / hashlib.sha256(user_id.encode()).hexdigest()
        if path.is_symlink():
            raise UserMemoryError("unsafe_user_memory_directory")
        return path

    @contextmanager
    def _locked(self, user_id):
        path = self.directory(user_id)
        path.mkdir(mode=0o700, exist_ok=True)
        with self._guard:
            lock = self._locks.setdefault(str(path), threading.RLock())
        with lock:
            fd = os.open(path / ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "a") as handle:
                fcntl.flock(handle, fcntl.LOCK_EX)
                yield path

    def _read(self, path, user_id):
        try:
            fd = os.open(path / "profile.md", os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return UserProfile(user_id=user_id)
        try:
            with os.fdopen(fd, "r") as handle:
                if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                    raise UserMemoryError("invalid_profile_file")
                text = handle.read(MAX_PROFILE_BYTES + 1)
            if len(text.encode()) > MAX_PROFILE_BYTES:
                raise UserMemoryError("profile_size_limit")
            profile = parse_profile(text)
            if profile.user_id != user_id:
                raise UserMemoryError("profile_owner_mismatch")
            return profile
        except (ValueError, KeyError, TypeError) as exc:
            raise UserMemoryError("invalid_user_profile") from exc

    def read(self, user_id: str) -> UserProfile:
        with self._locked(user_id) as path:
            return self._read(path, user_id)

    def context(self, session: Session, message: str, *, limit: int = 8) -> dict:
        """Relevant advisory records only; no automatic hard-state promotion."""
        profile = self.read(session.user_id)

        def terms_for(text):
            return {
                w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w
                for w in words(text)
            }

        terms = terms_for(message)
        for requirement in session.state.requirements:
            if requirement.status == "active" and requirement.field == "product_type":
                terms.update(terms_for(str(requirement.value)))
        active = [r for r in profile.records if r.status == "active"]
        scoped = [
            r for r in active if r.scope != "general" and terms_for(r.scope) <= terms
        ]
        general = [r for r in active if r.scope == "general"]
        relevant = list(reversed(scoped)) + list(reversed(general))
        relevant.sort(key=lambda r: not _contains(r.value, message))
        selected = relevant[:limit]
        return {
            "revision": profile.revision,
            "records": [
                {
                    k: getattr(r, k)
                    for k in ("id", "category", "attribute", "value", "scope", "basis")
                }
                for r in selected
            ],
        }

    def apply(
        self,
        session: Session,
        event: Event,
        proposals: list[MemoryProposal],
        *,
        expected_revision: int,
        visible_ids: set[str] | None = None,
    ) -> dict:
        """All-or-nothing proposal batch, grounded in this owner's actual user event."""
        if (
            event.type != "user_message"
            or event.user_id != session.user_id
            or event.session_id != session.id
            or not any(
                e.event_id == event.event_id and e == event for e in session.events
            )
        ):
            raise UserMemoryError("memory_requires_owned_user_event")
        for proposal in proposals:
            validate_proposal(proposal, event.payload["message"])
            if (
                proposal.target_id is not None
                and visible_ids is not None
                and proposal.target_id not in visible_ids
            ):
                raise UserMemoryError("memory_correction_requires_visible_target")
        with self._locked(session.user_id) as path:
            profile = self._read(path, session.user_id)
            # One durable transaction per user event, even across process restarts/retries.
            processed = [
                r
                for r in profile.records
                if r.source_event_id == event.event_id
                or r.closed_by_event_id == event.event_id
            ]
            if processed:
                return {
                    "revision": profile.revision,
                    "ids": [r.id for r in processed],
                    "idempotent": True,
                }
            if profile.revision != expected_revision:
                raise UserMemoryError("user_memory_revision_conflict")
            changed = []
            for proposal in proposals:
                target = next(
                    (
                        r
                        for r in profile.records
                        if r.id == proposal.target_id and r.status == "active"
                    ),
                    None,
                )
                key = (proposal.category, proposal.attribute, proposal.scope)
                if proposal.op != "ADD":
                    if (
                        target is None
                        or (target.category, target.attribute, target.scope) != key
                    ):
                        raise UserMemoryError("invalid_memory_correction_target")
                    target.status = (
                        "retracted" if proposal.op == "RETRACT" else "superseded"
                    )
                    target.closed_by_event_id = event.event_id
                    changed.append(target.id)
                    if proposal.op == "RETRACT":
                        continue
                elif proposal.category != "purchase":
                    existing = next(
                        (
                            r
                            for r in profile.records
                            if r.status == "active"
                            and (r.category, r.attribute, r.scope) == key
                        ),
                        None,
                    )
                    if existing:
                        if (
                            existing.value == proposal.value
                            and existing.basis == proposal.basis
                        ):
                            continue
                        raise UserMemoryError(
                            "memory_conflict_requires_explicit_correction"
                        )
                record = MemoryRecord(
                    **proposal.model_dump(),
                    id="um-" + uuid4().hex,
                    source_session_id=session.id,
                    source_event_id=event.event_id,
                    created_at=datetime.now(UTC).isoformat(),
                )
                profile.records.append(record)
                changed.append(record.id)
            if not changed:
                return {"revision": profile.revision, "ids": [], "idempotent": True}
            positive = {
                (r.attribute, r.scope, r.value.casefold())
                for r in profile.records
                if r.status == "active" and r.category == "preference"
            }
            negative = {
                (r.attribute, r.scope, r.value.casefold())
                for r in profile.records
                if r.status == "active" and r.category == "dislike"
            }
            if positive & negative:
                raise UserMemoryError("memory_conflict_requires_explicit_correction")
            if len(profile.records) > 500:
                raise UserMemoryError("profile_record_limit")
            profile.revision += 1
            UserProfile.model_validate(profile.model_dump())
            text = render_profile(profile)
            if len(text.encode()) > MAX_PROFILE_BYTES:
                raise UserMemoryError("profile_size_limit")
            fd, temp = tempfile.mkstemp(dir=path, prefix=".profile-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as handle:
                    handle.write(text)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp, path / "profile.md")
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
            return {"revision": profile.revision, "ids": changed, "idempotent": False}
