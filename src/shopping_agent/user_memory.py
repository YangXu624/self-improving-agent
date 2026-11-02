"""Persistent user-specific semantic memory architecture.

Manages durable customer facts and preferences with vector-based semantic retrieval,
time-based decay ranking, atomic persistence, and end-of-session consolidation.
Python provides transactional integrity; LLM models interpret customer meaning.
"""

import fcntl
import hashlib
import html
import json
import math
import os
import re
import sqlite3
import tempfile
import threading
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar, Literal
from uuid import uuid4

from pydantic import Field, field_validator

from .contracts import Decision, Strict
from .embeddings import (
    EmbeddingProvider,
    cosine_similarity,
    get_default_embedding_provider,
)
from .sessions import Session


class MemoryProposal(Strict):
    op: Literal["ADD", "REPLACE", "RETRACT"] = "ADD"
    category: Literal["fact", "preference", "dislike", "purchase"] = "preference"
    attribute: str = Field(default="attribute", pattern=r"^[a-z][a-z0-9_]{0,39}$")
    value: str = Field(default="", min_length=1, max_length=160)
    scope: str = Field(default="general", pattern=r"^[a-z][a-z0-9 /-]{0,79}$")
    basis: Literal["confirmed", "inferred"] = "confirmed"
    quote: str = Field(default="", min_length=1, max_length=500)
    target_id: str | None = Field(default=None, pattern=r"^(?:um-[a-f0-9]{32}|memory\.\d+)$")


class MemoryDecision(Decision):
    """Enabled-only policy contract; the baseline Decision remains unchanged."""

    user_memory_updates: list[MemoryProposal] = Field(
        default_factory=list, max_length=4
    )


SECTIONS = {
    "fact": "Facts",
    "preference": "Preferences",
    "dislike": "Dislikes",
    "purchase": "Purchases",
}
MAX_PROFILE_BYTES = 512_000


class UserMemoryError(ValueError):
    """Safe, traceable user memory error without exposing private file contents."""


def utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_iso(dt_str: str) -> datetime:
    try:
        return datetime.fromisoformat(dt_str)
    except (ValueError, TypeError):
        return datetime.now(UTC)


class MemoryRecord(Strict):
    """A durable customer fact, preference, dislike, or purchase record."""

    id: str = Field(default_factory=lambda: "um-" + uuid4().hex)
    category: Literal["fact", "preference", "dislike", "purchase"] = "preference"
    attribute: str = Field(min_length=1, max_length=40)
    value: str = Field(min_length=1, max_length=200)
    scope: str = Field(default="general", max_length=80)
    basis: Literal["confirmed", "inferred"] = "confirmed"
    quote: str = Field(default="", max_length=1000)
    status: Literal["active", "superseded", "deleted", "retracted"] = "active"
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str | None = Field(default=None, exclude=True)
    last_confirmed_at: str | None = Field(default=None, exclude=True)
    source_session_id: str = ""
    source_event_id: str | None = None
    supersedes_id: str | None = None
    superseded_by_id: str | None = None
    closed_by_event_id: str | None = None
    embedding: list[float] | None = Field(default=None, exclude=True)
    target_id: str | None = Field(default=None, exclude=True)
    op: str | None = Field(default=None, exclude=True)

    def model_post_init(self, __context: Any) -> None:
        if self.target_id and not self.supersedes_id:
            self.supersedes_id = self.target_id
        elif self.supersedes_id and not self.target_id:
            self.target_id = self.supersedes_id

    @field_validator("attribute")
    @classmethod
    def clean_attribute(cls, v: str) -> str:
        cleaned = re.sub(r"[^a-z0-9_]", "_", v.strip().casefold())
        return cleaned[:40] or "attribute"

    def semantic_text(self) -> str:
        """Text used for generating vector embeddings."""
        scope_str = f" for {self.scope}" if self.scope and self.scope != "general" else ""
        return f"{self.category} {self.attribute}: {self.value}{scope_str}. {self.quote}".strip()


class UserProfile(Strict):
    """The complete user memory profile including active and archived audit history."""

    user_id: str
    revision: int = Field(default=0, ge=0)
    records: list[MemoryRecord] = Field(default_factory=list, max_length=500)
    last_consolidated_session_id: str | None = Field(default=None, exclude=True)
    updated_at: str | None = Field(default=None, exclude=True)


@dataclass(frozen=True)
class DecayConfig:
    """Configurable half-lives and floors for memory decay."""

    preference_half_life_days: float = 60.0
    fact_half_life_days: float = 365.0
    dislike_half_life_days: float = 90.0
    purchase_half_life_days: float = 180.0
    min_decay_multiplier: float = 0.2


def calculate_decay_factor(
    record: MemoryRecord,
    now: datetime | None = None,
    config: DecayConfig = DecayConfig(),
) -> float:
    """Calculate recency decay factor (between min_decay_multiplier and 1.0)."""
    now = now or datetime.now(UTC)
    timestamp_str = record.last_confirmed_at or record.updated_at or record.created_at
    record_dt = parse_iso(timestamp_str)
    elapsed_days = max(0.0, (now - record_dt).total_seconds() / 86400.0)

    half_life = getattr(config, f"{record.category}_half_life_days", config.preference_half_life_days)
    if half_life <= 0:
        return 1.0

    decay = math.exp(-0.693147 * elapsed_days / half_life)
    return float(max(config.min_decay_multiplier, min(1.0, decay)))


def memory_text(record: dict) -> str:
    """Human-readable markdown summary line for a memory record."""
    category = record.get("category", "preference")
    attribute = record.get("attribute", "")
    value = record.get("value", "")
    scope = record.get("scope", "general")
    scope_str = f" (for {scope})" if scope and scope != "general" else ""

    if category == "preference":
        return f"Usually prefers {attribute}: {value}{scope_str}."
    elif category == "dislike":
        return f"Dislikes {attribute}: {value}{scope_str}."
    elif category == "fact":
        return f"{attribute.title()}: {value}{scope_str}."
    elif category == "purchase":
        return f"Past purchase: {value}{scope_str}."
    return f"{attribute}: {value}{scope_str}."


def render_profile(profile: UserProfile) -> str:
    """Readable active memories, with portable audit data in one collapsed section."""
    from .memory_views import memory_text

    def escaped(text):
        text = html.escape(text.replace("\n", " "), quote=False)
        return re.sub(r"([\\`*_{}\[\]#+|])", r"\\\1", text)

    lines = [
        "# ASTRA user memory",
        "<!-- astra-user-memory-v2 -->",
        "",
        "User: " + escaped(profile.user_id),
    ]
    for category, heading in SECTIONS.items():
        lines.extend(["", "## " + heading])
        active = [
            r
            for r in profile.records
            if r.status == "active" and r.category == category
        ]
        lines.extend("- " + escaped(memory_text(r.model_dump())) for r in active)
        if not active:
            lines.append("- None recorded.")

    dumpable_profile = profile.model_dump(exclude_defaults=True, exclude_none=True)
    if "records" in dumpable_profile:
        for r in dumpable_profile["records"]:
            r.pop("embedding", None)

    data = {"format": 2, "profile": dumpable_profile}
    payload = (
        json.dumps(data, ensure_ascii=True, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
    lines.extend(
        [
            "",
            "<details>",
            "<summary>Audit metadata (managed by ASTRA)</summary>",
            "",
            "```json",
            payload,
            "```",
            "</details>",
        ]
    )
    return "\n".join(lines) + "\n"


def _render_legacy_profile(profile: UserProfile) -> str:
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


def _parse_legacy_profile(text: str) -> UserProfile:
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
    try:
        profile = UserProfile.model_validate({**header, "records": records})
    except Exception as exc:
        raise UserMemoryError("invalid_profile_markdown") from exc
    if _render_legacy_profile(profile) != text:
        raise UserMemoryError("invalid_profile_markdown")
    if len({r.id for r in profile.records}) != len(profile.records):
        raise UserMemoryError("duplicate_memory_record_id")
    return profile


def parse_profile(text: str) -> UserProfile:
    """Read both historical bullet profiles and the prose/audit representation."""
    if not text.startswith("# ASTRA user memory\n<!-- astra-user-memory-v2 -->\n"):
        return _parse_legacy_profile(text)
    try:
        body = text.split("\n```json\n", 1)[1].split("\n```\n</details>\n", 1)[0]
        data = json.loads(body)
        if data.get("format") != 2 or set(data) != {"format", "profile"}:
            raise ValueError("invalid_profile_format")
        profile = UserProfile.model_validate(data["profile"])
        if (
            len({r.id for r in profile.records}) != len(profile.records)
            or render_profile(profile) != text
        ):
            raise ValueError("profile_content_mismatch")
        return profile
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        raise UserMemoryError("invalid_profile_markdown") from exc


def words(value: str) -> list[str]:
    return re.findall(r"[^\W_]+", value.casefold(), re.UNICODE)


def _contains(value: str, text: str) -> bool:
    needle, haystack = words(value), words(text)
    return bool(needle) and any(
        haystack[i : i + len(needle)] == needle
        for i in range(len(haystack) - len(needle) + 1)
    )


def _check_first_person_ownership(evidence: str, proposal: MemoryProposal) -> bool:
    if proposal.op == "RETRACT":
        return bool(re.search(r"\b(?:forget|remove|withdraw)\s+my\b", evidence))

    if re.search(
        r"\b(?:he|she|they|someone|anyone|dad|mom|mum|father|mother|"
        r"friend|sister|brother|wife|husband|partner|boss|coworker|colleague|trainer)\s+"
        r"(?:said|says|told|thinks|thought|believes|claims|suggested|recommended)\b",
        evidence,
    ):
        return False

    leading = re.match(
        r"^(?:(?:actually|remember(?: that)?|from now on|going forward|usually|generally|typically|normally)[,: ]+)?"
        r"(?:(?:for|as for|when it comes to|in)\s+[a-z0-9_\- ']+[,: ]+)?"
        r"(?:(?:actually|remember(?: that)?|from now on|going forward)[,: ]+)?",
        evidence,
    )
    clause = evidence[leading.end() :] if leading else evidence

    if re.match(r"^(?:i\b|i'm\b|i've\b)", clause):
        return True

    if re.match(
        r"^my\s+(?:usual\s+|general\s+|personal\s+)?(?:preference|dislike|size|go-to|goto|favorite|favourite|choice)\b",
        clause,
    ):
        return True

    inverted = re.match(
        r"^([a-z0-9_\- ']+?)\s+(?:is|are|isn't|is not|aren't|are not|was|were|used to be|would be|could be)\s+"
        r"(?:(?:always|usually|generally|typically|normally|regularly|simply|definitely|currently|just|previously|formerly|not|never)\s+)?"
        r"my\s+(?:usual\s+|general\s+|personal\s+)?(?:go-to|goto|favorite|favourite|choice|preference)\b",
        clause,
    )
    if inverted:
        subject = inverted.group(1).strip()
        if re.search(
            r"\b(?:he|she|they|someone|anyone|everybody|everyone|dad|mom|mum|father|mother|"
            r"friend|sister|brother|wife|husband|partner|boss|coworker|colleague|trainer|"
            r"said|says|told|thinks|thought|believes|claims)\b",
            subject,
        ):
            return False
        if _contains(proposal.value, subject) or _contains(subject, proposal.value):
            return True
        if proposal.scope != "general" and (
            _contains(proposal.scope, subject) or _contains(subject, proposal.scope)
        ):
            return True

    return False


def validate_proposal(
    proposal: MemoryProposal,
    message: str,
    *,
    bypass_semantic: bool = False,
) -> None:
    quote = proposal.quote
    if quote not in message and quote.strip() not in message:
        raise UserMemoryError("memory_requires_current_literal_evidence")
    if bypass_semantic:
        return
    if not _contains(proposal.value, quote):
        raise UserMemoryError("memory_requires_current_literal_evidence")
    if proposal.scope != "general" and not _contains(proposal.scope, quote):
        raise UserMemoryError("memory_scope_requires_literal_evidence")
    text = message.casefold().replace("’", "'")
    evidence = quote.casefold().replace("’", "'")
    offset = message.index(quote)
    prefix = message[:offset].rstrip()
    if prefix and prefix[-1] not in ".!?;\n":
        raise UserMemoryError("memory_quote_requires_own_statement")
    if proposal.op != "RETRACT" and re.search(
        r"\b(?:do not|don't|never) (?:remember|save|store)\b", text
    ):
        raise UserMemoryError("user_declined_memory_storage")
    if re.search(
        r"\b(?:gift|present|for (?:my |a |the )?(?:dad|mom|mum|mother|father|friend|wife|husband|partner|daughter|son|sister|brother|colleague|coworker|boss)|"
        r"this (?:time|trip|purchase|order|occasion|season)|just (?:for )?today|only (?:for )?today|one[- ]off|temporar(?:y|ily))\b",
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
    if re.search(
        r"\b(?:would|could)\s+(?:be|prefer|like|love|choose|pick|go)\b|\bif\s+(?:i|he|she|they|one|we|you)\b|\b(?:suppose|supposing|assuming|hypothetically)\b",
        evidence,
    ):
        raise UserMemoryError("hypothetical_preference_not_persistent")
    if proposal.op == "ADD" and re.search(
        r"\b(?:used to|formerly|previously|in the past|back then|no longer)\b",
        evidence,
    ):
        raise UserMemoryError("former_preference_not_persistent")
    negation = r"\b(?:not|never|no|don't|cannot|can't|isn't|aren't|neither|nor)\b"
    if (
        proposal.category != "dislike"
        and re.search(negation, evidence)
        and not re.search(negation, proposal.value.casefold())
    ):
        raise UserMemoryError("memory_value_must_preserve_negation")
    if not _check_first_person_ownership(evidence, proposal):
        raise UserMemoryError("memory_requires_first_person_ownership")
    positive_pref = (
        r"\b(?:prefer|prefers|preference|like|likes|love|loves|"
        r"go[- ]to|goto|favorite|favourite|go with|goes with|choice)\b"
    )
    if proposal.category == "preference" and not re.search(
        positive_pref, evidence
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
        quote_words, value_words = words(quote), words(proposal.value)
        try:
            end = next(
                i + len(value_words)
                for i in range(len(quote_words))
                if quote_words[i : i + len(value_words)] == value_words
            )
            neutral = {
                "always", "usually", "generally", "typically", "regularly", "in", "general", "now", "on",
                "i", "my", "think", "prefer", "preference", "like", "love", "dislike", "hate", "avoid",
                "remember", "that", "from", "going", "forward", "actually", "instead", "of", "rather",
                "the", "a", "an", "do", "not", "dont", "is", "are", "favorite", "favourite", "go", "to",
                "goto", "with", "tend", "tends", "choice", "for", "stuff", "items", "things",
            }
            start = end - len(value_words)
            if set(quote_words[:start] + quote_words[end:]) - neutral:
                raise UserMemoryError("specific_preference_requires_scope")
        except StopIteration:
            pass
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
            r"remember|from now on|going forward|no longer|now prefer|now dislike|"
            r"tend to|tends to|favorite|favourite|go[- ]to|goto)\b",
            evidence,
        )
        if not persistent:
            raise UserMemoryError("memory_requires_explicit_persistence")
    if proposal.op == "REPLACE" and not re.search(
        r"\b(?:actually|instead|now|no longer|changed|change|correction|rather)\b",
        evidence,
    ):
        raise UserMemoryError("memory_correction_requires_explicit_change")


class UserMemoryStore:
    """Thread-safe and process-safe transactional store for user memory profiles.

    Uses SQLite as the transactional store for embeddings and audit history,
    and maintains atomic rendered markdown profiles for backward compatibility and readability.
    """

    _locks: ClassVar[dict[str, threading.RLock]] = {}
    _guard = threading.Lock()

    def __init__(
        self,
        root: str | Path = "data/user-memory",
        *,
        embedding_provider: EmbeddingProvider | None = None,
        bypass_semantic_validation: bool = False,
        decay_config: DecayConfig = DecayConfig(),
    ):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.embedding_provider = embedding_provider or get_default_embedding_provider()
        self.bypass_semantic_validation = bypass_semantic_validation
        self.decay_config = decay_config

    def directory(self, user_id: str) -> Path:
        if not isinstance(user_id, str) or not user_id.strip() or len(user_id) > 128:
            raise UserMemoryError("invalid_user_id")
        path = self.root / hashlib.sha256(user_id.encode("utf-8")).hexdigest()
        if path.is_symlink():
            raise UserMemoryError("unsafe_user_memory_directory")
        return path

    _local: ClassVar[threading.local] = threading.local()

    @contextmanager
    def _locked(self, user_id: str):
        path = self.directory(user_id)
        path.mkdir(mode=0o700, exist_ok=True)
        key = str(path)
        with self._guard:
            lock = self._locks.setdefault(key, threading.RLock())

        active_counts = getattr(self._local, "counts", None)
        if active_counts is None:
            active_counts = {}
            self._local.counts = active_counts

        depth = active_counts.get(key, 0)
        with lock:
            if depth > 0:
                active_counts[key] = depth + 1
                try:
                    yield path
                finally:
                    active_counts[key] -= 1
            else:
                active_counts[key] = 1
                fd = os.open(path / ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX)
                    yield path
                finally:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_UN)
                    except OSError:
                        pass
                    os.close(fd)
                    active_counts[key] = 0

    def _init_db(self, path: Path) -> sqlite3.Connection:
        db_path = path / "profile.db"
        conn = sqlite3.connect(db_path, autocommit=False)
        conn.row_factory = sqlite3.Row
        with conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            CREATE TABLE IF NOT EXISTS records (
                id TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                attribute TEXT NOT NULL,
                value TEXT NOT NULL,
                scope TEXT NOT NULL,
                basis TEXT NOT NULL,
                quote TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT,
                last_confirmed_at TEXT,
                source_session_id TEXT NOT NULL,
                source_event_id TEXT,
                supersedes_id TEXT,
                superseded_by_id TEXT,
                closed_by_event_id TEXT,
                embedding_json TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_records_status ON records(status);
            """)
        return conn

    def _sync_legacy_markdown(self, path: Path, user_id: str, conn: sqlite3.Connection) -> None:
        """Migrate legacy profile.md to SQLite if SQLite is empty and profile.md exists."""
        cur = conn.execute("SELECT COUNT(*) as cnt FROM records")
        if cur.fetchone()["cnt"] > 0:
            return

        md_path = path / "profile.md"
        if not md_path.exists():
            return

        try:
            profile = parse_profile(md_path.read_text(encoding="utf-8"))
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO meta (key, value) VALUES ('revision', ?), ('user_id', ?)",
                    (str(profile.revision), user_id),
                )
                for r in profile.records:
                    emb_json = json.dumps(r.embedding) if r.embedding else None
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO records (
                            id, category, attribute, value, scope, basis, quote,
                            status, created_at, updated_at, last_confirmed_at,
                            source_session_id, source_event_id, supersedes_id,
                            superseded_by_id, closed_by_event_id, embedding_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            r.id,
                            r.category,
                            r.attribute,
                            r.value,
                            r.scope,
                            r.basis,
                            r.quote,
                            r.status,
                            r.created_at,
                            r.updated_at,
                            r.last_confirmed_at,
                            r.source_session_id,
                            r.source_event_id,
                            r.supersedes_id,
                            r.superseded_by_id,
                            r.closed_by_event_id,
                            emb_json,
                        ),
                    )
        except Exception:
            pass

    def read(self, user_id: str) -> UserProfile:
        """Read the full user profile."""
        with self._locked(user_id) as path:
            md_path = path / "profile.md"
            if md_path.is_symlink():
                raise OSError("symlinks are not permitted")
            if md_path.exists():
                parse_profile(md_path.read_text(encoding="utf-8"))
            conn = self._init_db(path)
            try:
                self._sync_legacy_markdown(path, user_id, conn)
                cur = conn.execute("SELECT value FROM meta WHERE key = 'revision'")
                row = cur.fetchone()
                revision = int(row["value"]) if row else 0

                cur = conn.execute("SELECT value FROM meta WHERE key = 'last_consolidated_session_id'")
                row = cur.fetchone()
                last_sid = row["value"] if row else None

                cur = conn.execute("SELECT * FROM records ORDER BY created_at ASC")
                records = []
                for r in cur.fetchall():
                    emb = json.loads(r["embedding_json"]) if r["embedding_json"] else None
                    rec_dict = dict(r)
                    rec_dict.pop("embedding_json", None)
                    rec_dict["embedding"] = emb
                    records.append(MemoryRecord(**rec_dict))

                return UserProfile(
                    user_id=user_id,
                    revision=revision,
                    records=records,
                    last_consolidated_session_id=last_sid,
                )
            finally:
                conn.close()

    def write_profile(self, profile: UserProfile, path: Path, conn: sqlite3.Connection) -> None:
        """Atomically persist profile to SQLite and sync readable profile.md."""
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('revision', ?), ('user_id', ?), ('last_consolidated_session_id', ?)",
                (str(profile.revision), profile.user_id, profile.last_consolidated_session_id or ""),
            )
            for r in profile.records:
                emb_json = json.dumps(r.embedding) if r.embedding else None
                conn.execute(
                    """
                    INSERT OR REPLACE INTO records (
                        id, category, attribute, value, scope, basis, quote,
                        status, created_at, updated_at, last_confirmed_at,
                        source_session_id, source_event_id, supersedes_id,
                        superseded_by_id, closed_by_event_id, embedding_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        r.id,
                        r.category,
                        r.attribute,
                        r.value,
                        r.scope,
                        r.basis,
                        r.quote,
                        r.status,
                        r.created_at,
                        r.updated_at,
                        r.last_confirmed_at,
                        r.source_session_id,
                        r.source_event_id,
                        r.supersedes_id,
                        r.superseded_by_id,
                        r.closed_by_event_id,
                        emb_json,
                    ),
                )

        # Sync markdown
        md_text = render_profile(profile)
        fd, temp = tempfile.mkstemp(dir=path, prefix=".profile-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(md_text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path / "profile.md")
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def retrieve(
        self,
        user_id: str,
        query: str,
        *,
        min_similarity: float = 0.58,
        limit: int = 5,
        now: datetime | None = None,
    ) -> list[tuple[MemoryRecord, float]]:
        """Retrieve relevant active memories for a customer using vector similarity and recency decay.

        DOES NOT USE HARD LEXICAL SUBSET MATCHING. Recognizes semantic matches across paraphrases.
        """
        now = now or datetime.now(UTC)
        profile = self.read(user_id)
        active_records = [r for r in profile.records if r.status == "active"]
        if not active_records:
            return []

        # Ensure embeddings exist for active records
        missing_emb = [r for r in active_records if not r.embedding]
        if missing_emb:
            texts = [r.semantic_text() for r in missing_emb]
            embeddings = self.embedding_provider.embed(texts)
            with self._locked(user_id) as path:
                conn = self._init_db(path)
                try:
                    for r, emb in zip(missing_emb, embeddings, strict=False):
                        r.embedding = emb
                        conn.execute(
                            "UPDATE records SET embedding_json = ? WHERE id = ?",
                            (json.dumps(emb), r.id),
                        )
                    conn.commit()
                finally:
                    conn.close()

        query_emb = self.embedding_provider.embed_query(query)
        scored: list[tuple[MemoryRecord, float]] = []

        query_words = set(re.findall(r"[^\W_]+", query.casefold()))

        for record in active_records:
            if not record.embedding:
                continue
            sim = cosine_similarity(query_emb, record.embedding)
            decay = calculate_decay_factor(record, now, self.decay_config)

            # Optional lexical reinforcement if scope or value explicitly appears
            scope_words = set(re.findall(r"[^\W_]+", record.scope.casefold()))
            val_words = set(re.findall(r"[^\W_]+", record.value.casefold()))
            overlap_bonus = 0.05 if (query_words & scope_words) or (query_words & val_words) else 0.0

            combined_score = (sim + overlap_bonus) * decay

            # Check general scope fallback or similarity threshold
            if combined_score >= min_similarity or record.scope == "general":
                scored.append((record, combined_score))

        # Sort by score descending
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:limit]

    def context(
        self,
        session: Session,
        message: str,
        *,
        limit: int = 5,
        min_similarity: float = 0.58,
    ) -> dict:
        """Build model-visible user_memory context block before agent turn processing."""
        user_id = session.user_id
        # Combine current user message with any active goal/product_type requirements
        context_query = message
        for req in session.state.requirements:
            if req.status == "active" and req.field == "product_type":
                context_query += f" {req.value}"

        results = self.retrieve(user_id, context_query, min_similarity=min_similarity, limit=limit)
        profile = self.read(user_id)

        return {
            "revision": profile.revision,
            "records": [
                {
                    "id": record.id,
                    "category": record.category,
                    "attribute": record.attribute,
                    "value": record.value,
                    "scope": record.scope,
                    "quote": record.quote,
                    "basis": record.basis,
                    "score": round(score, 4),
                    "created_at": record.created_at,
                    "last_confirmed_at": record.last_confirmed_at,
                }
                for record, score in results
            ],
        }

    def withdraw_matching(
        self,
        user_id: str,
        *,
        attribute: str | None = None,
        category: str | None = None,
        query: str | None = None,
    ) -> list[str]:
        """Immediately withdraw matching active memories upon explicit customer request."""
        with self._locked(user_id) as path:
            conn = self._init_db(path)
            try:
                profile = self.read(user_id)
                now_str = utc_now_iso()
                withdrawn_ids = []

                for r in profile.records:
                    if r.status != "active":
                        continue
                    match = False
                    if attribute and r.attribute == attribute.casefold():
                        match = True
                    elif category and r.category == category.casefold():
                        match = True
                    elif query and (query.casefold() in r.value.casefold() or query.casefold() in r.scope.casefold()):
                        match = True
                    elif not attribute and not category and not query:
                        # Withdraw all active if no filter specified
                        match = True

                    if match:
                        r.status = "deleted"
                        r.updated_at = now_str
                        withdrawn_ids.append(r.id)

                if withdrawn_ids:
                    profile.revision += 1
                    self.write_profile(profile, path, conn)
                return withdrawn_ids
            finally:
                conn.close()

    def check_and_apply_explicit_forgetting(self, user_id: str, message: str) -> list[str]:
        """Check for explicit user instruction to forget or remove preferences and withdraw immediately."""
        text = message.casefold()
        forget_patterns = [
            r"\b(?:forget|delete|remove|clear)\s+(?:all\s+)?(?:my\s+)?(?:preferences|memories|memory|profile)\b",
            r"\b(?:forget|delete|remove)\s+(?:my\s+)?(?:favorite|preferred|usual)?\s*([a-z]+)\s*(?:preference|choice)?\b",
            r"\b(?:don't|do not)\s+remember\s+(?:my\s+)?([a-z]+)\b",
        ]
        for pattern in forget_patterns:
            m = re.search(pattern, text)
            if m:
                target_attr = m.group(1) if m.groups() and m.group(1) else None
                if target_attr in {"preferences", "memories", "memory", "profile"}:
                    target_attr = None
                return self.withdraw_matching(user_id, attribute=target_attr)
        return []

    def apply_consolidation_operations(
        self,
        user_id: str,
        session_id: str,
        operations: Sequence[dict],
        *,
        source_event_id: str | None = None,
    ) -> dict:
        """Apply a batch of end-of-session consolidation operations atomically."""
        with self._locked(user_id) as path:
            conn = self._init_db(path)
            try:
                profile = self.read(user_id)
                now_str = utc_now_iso()
                changed_ids = []

                for op_dict in operations:
                    op = op_dict.get("op", "ADD")
                    if op == "NOOP":
                        continue

                    target_id = op_dict.get("target_id")
                    target = next((r for r in profile.records if r.id == target_id and r.status == "active"), None)

                    if op == "REINFORCE":
                        if target:
                            target.last_confirmed_at = now_str
                            target.updated_at = now_str
                            changed_ids.append(target.id)
                    elif op in ("SUPERSEDE", "UPDATE", "REPLACE"):
                        if target:
                            target.status = "superseded"
                            target.updated_at = now_str
                            target.closed_by_event_id = source_event_id
                            new_rec = MemoryRecord(
                                category=op_dict.get("category", target.category),
                                attribute=op_dict.get("attribute", target.attribute),
                                value=op_dict.get("value", target.value),
                                scope=op_dict.get("scope", target.scope),
                                basis=op_dict.get("basis", target.basis),
                                quote=op_dict.get("quote", target.quote),
                                status="active",
                                created_at=target.created_at,
                                updated_at=now_str,
                                last_confirmed_at=now_str,
                                source_session_id=session_id,
                                source_event_id=source_event_id,
                                supersedes_id=target.id,
                            )
                            target.superseded_by_id = new_rec.id
                            profile.records.append(new_rec)
                            changed_ids.extend([target.id, new_rec.id])
                    elif op in ("DELETE", "RETRACT"):
                        if target:
                            target.status = "deleted"
                            target.updated_at = now_str
                            target.closed_by_event_id = source_event_id
                            changed_ids.append(target.id)
                    elif op == "ADD":
                        # Check duplicate
                        existing = next(
                            (
                                r
                                for r in profile.records
                                if r.status == "active"
                                and r.category == op_dict.get("category")
                                and r.attribute == op_dict.get("attribute")
                                and r.scope == op_dict.get("scope", "general")
                                and r.value.casefold() == op_dict.get("value", "").casefold()
                            ),
                            None,
                        )
                        if existing:
                            existing.last_confirmed_at = now_str
                            changed_ids.append(existing.id)
                        else:
                            new_rec = MemoryRecord(
                                category=op_dict.get("category", "preference"),
                                attribute=op_dict.get("attribute", "attribute"),
                                value=op_dict.get("value", ""),
                                scope=op_dict.get("scope", "general"),
                                basis=op_dict.get("basis", "confirmed"),
                                quote=op_dict.get("quote", ""),
                                status="active",
                                created_at=now_str,
                                updated_at=now_str,
                                last_confirmed_at=now_str,
                                source_session_id=session_id,
                                source_event_id=source_event_id,
                            )
                            profile.records.append(new_rec)
                            changed_ids.append(new_rec.id)

                if changed_ids:
                    profile.revision += 1
                profile.last_consolidated_session_id = session_id
                profile.updated_at = now_str
                self.write_profile(profile, path, conn)
                return {
                    "revision": profile.revision,
                    "ids": changed_ids,
                    "idempotent": False,
                }
            finally:
                conn.close()

    def apply(
        self,
        session: Session,
        event: Any,
        proposals: Sequence[Any],
        *,
        expected_revision: int,
        visible_ids: set[str] | None = None,
    ) -> dict:
        """All-or-nothing proposal batch, grounded in this owner's actual user event."""
        event_type = getattr(event, "type", None) if hasattr(event, "type") else (event.get("type") if isinstance(event, dict) else None)
        user_id = getattr(event, "user_id", None) if hasattr(event, "user_id") else (event.get("user_id") if isinstance(event, dict) else None)
        session_id = getattr(event, "session_id", None) if hasattr(event, "session_id") else (event.get("session_id") if isinstance(event, dict) else None)
        event_id = getattr(event, "event_id", None) if hasattr(event, "event_id") else (event.get("event_id") if isinstance(event, dict) else None)
        payload = getattr(event, "payload", {}) if hasattr(event, "payload") else (event.get("payload", {}) if isinstance(event, dict) else {})
        msg = payload.get("message", "")

        if (
            event_type != "user_message"
            or user_id != session.user_id
            or session_id != session.id
            or not any(
                e.event_id == event_id for e in session.events
            )
        ):
            raise UserMemoryError("memory_requires_owned_user_event")

        converted_proposals = [
            p if isinstance(p, MemoryProposal) else MemoryProposal.model_validate(p)
            for p in proposals
        ]

        for proposal in converted_proposals:
            validate_proposal(
                proposal,
                msg,
                bypass_semantic=self.bypass_semantic_validation,
            )
            if (
                proposal.target_id is not None
                and visible_ids is not None
                and proposal.target_id not in visible_ids
            ):
                raise UserMemoryError("memory_correction_requires_visible_target")

        with self._locked(session.user_id) as path:
            conn = self._init_db(path)
            try:
                profile = self.read(session.user_id)
                processed = [
                    r
                    for r in profile.records
                    if r.source_event_id == event_id
                    or r.closed_by_event_id == event_id
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
                now_str = utc_now_iso()
                for proposal in converted_proposals:
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
                        target.closed_by_event_id = event_id
                        target.updated_at = now_str
                        changed.append(target.id)
                        if proposal.op == "RETRACT":
                            continue
                    elif proposal.category != "purchase" and not self.bypass_semantic_validation:
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
                        id="um-" + uuid4().hex,
                        category=proposal.category,
                        attribute=proposal.attribute,
                        value=proposal.value,
                        scope=proposal.scope,
                        basis=proposal.basis,
                        quote=proposal.quote,
                        status="active",
                        created_at=now_str,
                        updated_at=now_str,
                        last_confirmed_at=now_str,
                        source_session_id=session.id,
                        source_event_id=event_id,
                        supersedes_id=target.id if target else None,
                    )
                    if target:
                        target.superseded_by_id = record.id
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
                if positive & negative and not self.bypass_semantic_validation:
                    raise UserMemoryError("memory_conflict_requires_explicit_correction")
                if len(profile.records) > 500:
                    raise UserMemoryError("profile_record_limit")

                profile.revision += 1
                profile.updated_at = now_str
                text = render_profile(profile)
                if len(text.encode()) > MAX_PROFILE_BYTES:
                    raise UserMemoryError("profile_size_limit")
                self.write_profile(profile, path, conn)
                return {
                    "revision": profile.revision,
                    "ids": changed,
                    "idempotent": False,
                }
            finally:
                conn.close()
