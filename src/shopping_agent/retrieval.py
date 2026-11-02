"""Deterministic lexical retrieval; the model never supplies SQL or FTS syntax."""

import hashlib
import json
import math
import os
import re
import sqlite3
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from .category_matching import category_contains, forms
from .contracts import Search, ShoppingState
from .sessions import dumps
from .state import normalized

INDEX_VERSION = "fts5-v1"
TEXT_FIELDS = {
    "department": ["Department"],
    "brand": ["Brand", "Brand Name"],
    "color": ["Color", "Colour"],
    "material": ["Material", "Material Type"],
    "size": ["Size"],
}


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def facet(field, value):
    text = normalized(str(value))
    if field == "department":
        return {
            "mens": "men",
            "men's": "men",
            "womens": "women",
            "women's": "women",
            "unisex-adult": "unisex",
            "unisex adult": "unisex",
        }.get(text, text)
    return text


def exact_price(value):
    if isinstance(value, str):
        if not re.fullmatch(r"\d+(?:\.\d{1,2})?", value.strip()):
            return None
        value = float(value)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and value > 0 else None


def project(row, image_url=None):
    details = row.get("details") if isinstance(row.get("details"), dict) else {}
    facts = {
        "price": exact_price(row.get("price")),
        "rating": row.get("average_rating"),
        "rating_count": row.get("rating_number"),
    }
    for field, names in TEXT_FIELDS.items():
        facts[field] = next(
            (
                str(details[k]).strip()
                for k in names
                if isinstance(details.get(k), (str, int, float))
                and str(details[k]).strip()
            ),
            None,
        )
    for field in ["rating", "rating_count"]:
        value = facts[field]
        if (
            isinstance(value, bool)
            or not isinstance(value, (float, int))
            or not math.isfinite(value)
            or value < 0
            or field == "rating"
            and value > 5
            or field == "rating_count"
            and not float(value).is_integer()
        ):
            facts[field] = None
    categories = [v for v in row.get("categories", []) if isinstance(v, str)]
    title = str(row.get("title") or "")
    text = " ".join(
        [
            title,
            *categories,
            *[str(x) for x in row.get("features", [])],
            *[str(x) for x in row.get("description", [])],
        ]
    )
    return {
        "id": row["parent_asin"],
        "title": title,
        "facts": facts,
        "categories": categories,
        "text": text,
        "image_url": image_url,
        "evidence": {
            **{
                k: {
                    "source": "price"
                    if k == "price"
                    else "average_rating"
                    if k == "rating"
                    else "rating_number",
                    "value": v,
                }
                for k, v in facts.items()
                if k in {"price", "rating", "rating_count"} and v is not None
            },
            **{
                field: {
                    "source": "details."
                    + next(
                        k
                        for k in names
                        if k in details and str(details[k]).strip() == str(facts[field])
                    ),
                    "value": facts[field],
                }
                for field, names in TEXT_FIELDS.items()
                if facts[field] is not None
            },
        },
    }


def build_index(catalogue, destination, images=None, *, replace=False):
    catalogue, destination = Path(catalogue), Path(destination)
    if destination.resolve() in {
        catalogue.resolve(),
        Path(images).resolve() if images else None,
    }:
        raise ValueError("Index cannot overwrite source assets")
    if destination.exists() and not replace:
        raise FileExistsError("Index exists; explicitly rebuild")
    destination.parent.mkdir(parents=True, exist_ok=True)
    catalogue_hash = file_hash(catalogue)
    images_hash = file_hash(images) if images else "none"
    image_map = json.loads(Path(images).read_text()) if images else {}
    fd, temp = tempfile.mkstemp(dir=destination.parent, suffix=".sqlite")
    os.close(fd)
    db = sqlite3.connect(temp)
    try:
        db.executescript("""
            CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE products(id TEXT PRIMARY KEY, record TEXT NOT NULL);
            CREATE VIRTUAL TABLE product_fts USING fts5(title, taxonomy, features, description);
        """)
        count = 0
        with db, catalogue.open(encoding="utf-8") as source:
            for line in source:
                row = json.loads(line)
                record = project(row, image_map.get(row["parent_asin"]))
                db.execute(
                    "INSERT INTO products VALUES (?,?)", (record["id"], dumps(record))
                )
                db.execute(
                    "INSERT INTO product_fts(rowid,title,taxonomy,features,description) VALUES (?,?,?,?,?)",
                    (
                        db.execute(
                            "SELECT rowid FROM products WHERE id=?", (record["id"],)
                        ).fetchone()[0],
                        record["title"],
                        " ".join(record["categories"]),
                        " ".join(str(x) for x in row.get("features", [])),
                        " ".join(str(x) for x in row.get("description", [])),
                    ),
                )
                count += 1
            metadata = {
                "catalogue_sha256": catalogue_hash,
                "index_version": INDEX_VERSION,
                "count": str(count),
                "images_sha256": images_hash,
            }
            db.executemany("INSERT INTO metadata VALUES (?,?)", metadata.items())
        if file_hash(catalogue) != catalogue_hash:
            raise ValueError("Catalogue changed during build")
        if images and file_hash(images) != images_hash:
            raise ValueError("Image mapping changed during build")
        db.execute("INSERT INTO product_fts(product_fts) VALUES ('integrity-check')")
        db.close()
        os.replace(temp, destination)
        return metadata
    finally:
        db.close()
        if os.path.exists(temp):
            os.unlink(temp)


def compare(value, op, expected):
    if isinstance(value, (int, float)):
        a, b = Decimal(str(value)), Decimal(str(expected))
        return {
            "eq": a == b,
            "neq": a != b,
            "lt": a < b,
            "lte": a <= b,
            "gt": a > b,
            "gte": a >= b,
        }[op]
    values = expected if isinstance(expected, list) else [expected]
    if op == "eq":
        return value == values[0]
    if op == "neq":
        return value != values[0]
    if op == "in":
        return value in values
    if op == "not_in":
        return value not in values
    present = set(re.findall(r"\w+", values[0])).issubset(
        set(re.findall(r"\w+", value))
    )
    return present if op == "contains" else not present


def assess(record, state):
    failed, unknown, hard, soft = [], [], [], []
    for r in state.requirements:
        if r.status != "active":
            continue
        if r.field == "product_type":
            value = (
                normalized(" ".join(record["categories"]))
                if record["categories"]
                else None
            )
            op = (
                "not_contains"
                if r.op in {"neq", "not_contains", "not_in"}
                else "contains"
            )
        elif r.field == "keyword":
            value, op = normalized(record["text"]), r.op
        elif r.field == "brand":
            value, op = record["facts"].get("brand"), r.op
            if value is None and record.get("title"):
                tb = str(r.value).strip().lower()
                tw = set(re.findall(r"\w+", (record.get("title") or "").lower()))
                st_name = (record.get("store") or "").lower()
                if tb and (tb in tw or tb in st_name):
                    value = r.value
            if isinstance(value, str):
                value = facet(r.field, value)
        elif r.field == "department":
            value, op = record["facts"].get("department"), r.op
            if value is None and record.get("categories"):
                tb = str(r.value).strip().lower()
                cw = set(re.findall(r"\w+", " ".join(record["categories"]).lower()))
                tw = set(re.findall(r"\w+", (record.get("title") or "").lower()))
                df = forms(tb)
                if any(d in cw or d in tw for d in df):
                    value = r.value
            if isinstance(value, str):
                value = facet(r.field, value)
        else:
            value, op = record["facts"].get(r.field), r.op
            if isinstance(value, str):
                value = facet(r.field, value)
        expected = (
            [facet(r.field, v) for v in r.value]
            if isinstance(r.value, list)
            else (facet(r.field, r.value) if isinstance(r.value, str) else r.value)
        )
        if value is None:
            if r.strength == "hard":
                unknown.append(r.id)
            continue
        # Category product-type matching is explicitly lexical evidence, not an inferred ontology.
        if r.field == "product_type" and isinstance(expected, list):
            matches = [category_contains(value, v) for v in expected]
            passed = not any(matches) if r.op == "not_in" else any(matches)
        elif r.field == "product_type":
            present = category_contains(value, expected)
            passed = not present if op == "not_contains" else present
        else:
            passed = compare(value, op, expected)
        if passed:
            (hard if r.strength == "hard" else soft).append(r.id)
        elif r.strength == "hard":
            failed.append(r.id)
    return {
        "eligible": not failed and not unknown,
        "matched_hard_ids": hard,
        "matched_soft_ids": soft,
        "unknown_ids": unknown,
        "failed_ids": failed,
    }


def score_preferences(
    record,
    verdict,
    user_memory=None,
    state=None,
    *,
    personalization_strength=0.5,
    max_bonus=2.0,
):
    base_score = float(len(verdict.get("matched_soft_ids", [])))
    matched_memory_ids = []
    audit_entries = []

    if (
        not user_memory
        or not isinstance(user_memory, dict)
        or personalization_strength <= 0.0
    ):
        return base_score, matched_memory_ids, audit_entries

    memory_records = user_memory.get("records", [])
    if not isinstance(memory_records, list):
        return base_score, matched_memory_ids, audit_entries

    total_preference_bonus = 0.0
    record_text = normalized(record.get("text", ""))
    record_title = normalized(record.get("title", ""))
    record_facts = record.get("facts", {})

    state_reqs_by_field = {}
    if state and hasattr(state, "requirements"):
        for r in state.requirements:
            if getattr(r, "status", None) == "active":
                state_reqs_by_field.setdefault(r.field, []).append(r)

    for mem in memory_records:
        if not isinstance(mem, dict):
            continue
        if mem.get("status", "active") != "active":
            continue
        category = mem.get("category")
        val = normalized(str(mem.get("value") or ""))
        attr = normalized(str(mem.get("attribute") or ""))
        if not val or val in {"none", "unknown", "n/a"}:
            continue

        is_dislike = category == "dislike"
        is_pref = category in {"preference", "fact"}
        if not is_dislike and not is_pref:
            continue

        # Current explicit preference always overrides contradictory historical memory
        if attr in state_reqs_by_field:
            contradicted = False
            for req in state_reqs_by_field[attr]:
                req_val = normalized(str(req.value or ""))
                # If current state explicitly excludes this memory value
                if req.op in {"neq", "not_contains", "not_in"} and (
                    val in req_val or req_val in val
                ):
                    contradicted = True
                    break
                # If current state explicitly specifies a different positive value for this attribute
                if req.op in {"eq", "contains", "in"}:
                    if val != req_val and val not in req_val and req_val not in val:
                        contradicted = True
                        break
            if contradicted:
                continue

        # Check scope relevance if provided
        scope_val = normalized(str(mem.get("scope") or ""))
        if scope_val and scope_val not in {"general", "all", "any", "none"}:
            scope_words = [w for w in re.findall(r"\w+", scope_val) if len(w) > 2]
            if scope_words:
                scope_matched = any(
                    w in record_text or w in record_title for w in scope_words
                )
                if not scope_matched:
                    continue

        # Memory importance calculation:
        # Hard = 1.0, Soft = 0.6, Inferred = 0.3, scaled by confidence
        strength = mem.get("strength", "soft")
        importance = (
            1.0
            if strength == "hard"
            else (
                0.3 if strength == "inferred" or mem.get("basis") == "inferred" else 0.6
            )
        )
        confidence = float(mem.get("confidence", 1.0))
        weight = importance * confidence

        # Verified product attribute matching vs unknown
        match_score = 0.0
        match_type = "unknown"
        if attr in record_facts and record_facts[attr] is not None:
            fact_val = facet(attr, record_facts[attr])
            target_val = facet(attr, val)
            if (
                fact_val == target_val
                or target_val in fact_val
                or fact_val in target_val
            ):
                match_score = 1.0 if is_pref else -1.0
                match_type = "verified_fact_match"
            else:
                match_score = -0.5 if is_pref else 0.5
                match_type = "verified_fact_mismatch"
        else:
            # Fact is unknown in structured details; check text
            val_words = [w for w in re.findall(r"\w+", val) if len(w) > 2]
            if val_words:
                all_in_title = all(w in record_title for w in val_words)
                all_in_text = all(w in record_text for w in val_words)
                if all_in_title:
                    match_score = 0.5 if is_pref else -0.5
                    match_type = "verified_title_match"
                elif all_in_text:
                    match_score = 0.25 if is_pref else -0.25
                    match_type = "verified_text_match"

        if match_score != 0.0:
            delta = weight * match_score
            total_preference_bonus += delta
            mem_id = mem.get("id")
            if mem_id:
                matched_memory_ids.append(mem_id)
                audit_entries.append(
                    {
                        "memory_id": mem_id,
                        "application": "soft_reranking",
                        "attribute": attr,
                        "value": val,
                        "match_type": match_type,
                        "delta": round(delta, 3),
                        "reason": f"{match_type.replace('_', ' ').title()}: matches relevant preference",
                    }
                )

    bounded_bonus = max(-max_bonus, min(max_bonus, total_preference_bonus))
    scaled_bonus = personalization_strength * bounded_bonus
    return base_score + scaled_bonus, matched_memory_ids, audit_entries


class ProductSearch(Protocol):
    catalogue_version: str
    strategy_version: str

    def search(
        self,
        action: Search,
        state: ShoppingState,
        *,
        user_memory: dict | None = None,
        fallback: bool | None = None,
        personalization_strength: float = 0.5,
        personalization_max_bonus: float = 2.0,
    ) -> dict: ...

    def eligible(self, product_id: str, state: ShoppingState) -> bool: ...


class LexicalSearch:
    def __init__(self, path, *, expected_catalogue_hash=None, fallback=False):
        path = Path(path).resolve()
        self.db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        meta = dict(self.db.execute("SELECT key,value FROM metadata"))
        if meta.get("index_version") != INDEX_VERSION:
            self.db.close()
            raise ValueError("Unsupported index version; rebuild required")
        self.catalogue_version = meta["catalogue_sha256"]
        self.strategy_version = meta["index_version"]
        self.count = int(meta["count"])
        self.fallback = fallback
        if (
            expected_catalogue_hash
            and expected_catalogue_hash != self.catalogue_version
        ):
            self.db.close()
            raise ValueError("Stale catalogue index; rebuild required")

    def close(self):
        self.db.close()

    def search(
        self,
        action,
        state,
        *,
        user_memory=None,
        fallback=None,
        personalization_strength=0.5,
        personalization_max_bonus=2.0,
    ):
        action = Search.model_validate(action.model_dump())
        state = ShoppingState.model_validate(state.model_dump())
        if state.conflicts:
            raise ValueError("unresolved_state_conflicts")
        terms = re.findall(r"\w+", action.query, flags=re.UNICODE)
        if len(terms) > 24:
            raise ValueError("query_term_limit")
        hard_filters = [
            r
            for r in state.requirements
            if r.status == "active" and r.strength == "hard"
        ]
        if not terms and not hard_filters:
            raise ValueError("query_or_hard_filter_required")

        use_fallback = self.fallback if fallback is None else fallback

        def _execute_query(query_terms, mode):
            expanded_clauses = []
            for t in query_terms:
                t_forms = sorted(forms(t))
                if len(t_forms) > 1:
                    expanded_clauses.append(
                        "(" + " OR ".join('"' + f + '"' for f in t_forms) + ")"
                    )
                else:
                    expanded_clauses.append('"' + t + '"')
            q = (" AND " if mode == "all" else " OR ").join(expanded_clauses)
            if query_terms:
                cur = self.db.execute(
                    """SELECT p.record,bm25(product_fts,5.0,3.0,2.0,1.0)
                    FROM product_fts JOIN products p ON p.rowid=product_fts.rowid
                    WHERE product_fts MATCH ? ORDER BY bm25(product_fts,5.0,3.0,2.0,1.0),p.id""",
                    (q,),
                )
            else:
                cur = self.db.execute("SELECT record,0.0 FROM products ORDER BY id")
            return cur

        cursor = _execute_query(terms, action.mode)
        eligible_pool, matched, eligible, unknown, excluded = [], 0, 0, 0, 0
        seen_ids = set()
        for raw, score in cursor:
            matched += 1
            record = json.loads(raw)
            verdict = assess(record, state)
            unknown += bool(verdict["unknown_ids"])
            excluded += bool(verdict["failed_ids"])
            if not verdict["eligible"]:
                continue
            eligible += 1
            seen_ids.add(record["id"])
            pref_score, matched_mem_ids, audit_entries = score_preferences(
                record,
                verdict,
                user_memory,
                state,
                personalization_strength=personalization_strength,
                max_bonus=personalization_max_bonus,
            )
            raw_bonus = sum(a.get("delta", 0.0) for a in audit_entries)
            bounded_bonus = max(
                -personalization_max_bonus,
                min(personalization_max_bonus, raw_bonus),
            )
            baseline_relevance = -score
            eligible_pool.append(
                {
                    "record": record,
                    "score": score,
                    "baseline_relevance": baseline_relevance,
                    "bounded_bonus": bounded_bonus,
                    "verdict": verdict,
                    "pref_score": pref_score,
                    "matched_mem_ids": matched_mem_ids,
                    "audit_entries": audit_entries,
                }
            )

        # Branch 2: Optional memory-assisted candidate retrieval
        # If user memory has active preferences, run memory-assisted queries to expand discovery
        if personalization_strength > 0.0 and user_memory and terms:
            records = (
                user_memory.get("records", []) if isinstance(user_memory, dict) else []
            )
            for mem in records:
                if not isinstance(mem, dict) or mem.get("status", "active") != "active":
                    continue
                if mem.get("category") not in {"preference", "fact"}:
                    continue
                val = str(mem.get("value") or "").strip()
                val_terms = [w for w in re.findall(r"\w+", val) if len(w) > 2]
                if not val_terms:
                    continue
                assisted_terms = terms + val_terms[:2]
                if assisted_terms == terms:
                    continue
                try:
                    cursor_mem = _execute_query(assisted_terms, action.mode)
                    for raw, score in cursor_mem:
                        record = json.loads(raw)
                        pid = record["id"]
                        if pid in seen_ids:
                            continue
                        verdict = assess(record, state)
                        if not verdict["eligible"]:
                            continue
                        seen_ids.add(pid)
                        matched += 1
                        eligible += 1
                        pref_score, matched_mem_ids, audit_entries = score_preferences(
                            record,
                            verdict,
                            user_memory,
                            state,
                            personalization_strength=personalization_strength,
                            max_bonus=personalization_max_bonus,
                        )
                        raw_bonus = sum(a.get("delta", 0.0) for a in audit_entries)
                        bounded_bonus = max(
                            -personalization_max_bonus,
                            min(personalization_max_bonus, raw_bonus),
                        )
                        baseline_relevance = -score
                        eligible_pool.append(
                            {
                                "record": record,
                                "score": score,
                                "baseline_relevance": baseline_relevance,
                                "bounded_bonus": bounded_bonus,
                                "verdict": verdict,
                                "pref_score": pref_score,
                                "matched_mem_ids": matched_mem_ids,
                                "audit_entries": audit_entries,
                            }
                        )
                except Exception:
                    pass

        fallback_triggered = False
        effective_mode = action.mode
        fallback_reason = None
        # Safe fallback enabled identically for both Memory OFF and Memory ON when use_fallback is True:
        # If action.mode == "all" and terms > 1 yields 0 eligible candidates,
        # relax over-constrained query terms while strictly enforcing all hard constraints via assess().
        if (
            action.mode == "all"
            and len(terms) > 1
            and len(eligible_pool) == 0
            and use_fallback
        ):
            if user_memory:
                memory_records = (
                    user_memory.get("records", [])
                    if isinstance(user_memory, dict)
                    else []
                )
                pref_words = set()
                for m in memory_records:
                    if isinstance(m, dict) and m.get("status", "active") == "active":
                        val = str(m.get("value") or "")
                        for w in re.findall(r"\w+", val, flags=re.UNICODE):
                            if len(w) > 1:
                                pref_words.add(w.lower())

                relaxed_terms = [t for t in terms if t.lower() not in pref_words]
                if relaxed_terms and len(relaxed_terms) < len(terms):
                    fallback_triggered = True
                    fallback_reason = "relaxed_remembered_preferences"
                    cursor_fb = _execute_query(relaxed_terms, "all")
                    fb_matched, fb_unknown, fb_excluded, fb_eligible = 0, 0, 0, 0
                    for raw, score in cursor_fb:
                        fb_matched += 1
                        record = json.loads(raw)
                        verdict = assess(record, state)
                        fb_unknown += bool(verdict["unknown_ids"])
                        fb_excluded += bool(verdict["failed_ids"])
                        if not verdict["eligible"]:
                            continue
                        fb_eligible += 1
                        pref_score, matched_mem_ids, audit_entries = score_preferences(
                            record,
                            verdict,
                            user_memory,
                            state,
                            personalization_strength=personalization_strength,
                            max_bonus=personalization_max_bonus,
                        )
                        raw_bonus = sum(a.get("delta", 0.0) for a in audit_entries)
                        bounded_bonus = max(
                            -personalization_max_bonus,
                            min(personalization_max_bonus, raw_bonus),
                        )
                        baseline_relevance = -score
                        eligible_pool.append(
                            {
                                "record": record,
                                "score": score,
                                "baseline_relevance": baseline_relevance,
                                "bounded_bonus": bounded_bonus,
                                "verdict": verdict,
                                "pref_score": pref_score,
                                "matched_mem_ids": matched_mem_ids,
                                "audit_entries": audit_entries,
                            }
                        )
                    if fb_eligible > 0:
                        matched, eligible, unknown, excluded = (
                            fb_matched,
                            fb_eligible,
                            fb_unknown,
                            fb_excluded,
                        )

            # Broad fallback to mode="any" for both Memory OFF and Memory ON:
            if len(eligible_pool) == 0:
                fallback_triggered = True
                fallback_reason = "relaxed_to_any_mode"
                effective_mode = "any"
                cursor_fb = _execute_query(terms, "any")
                fb_matched, fb_unknown, fb_excluded, fb_eligible = 0, 0, 0, 0
                for raw, score in cursor_fb:
                    fb_matched += 1
                    record = json.loads(raw)
                    verdict = assess(record, state)
                    fb_unknown += bool(verdict["unknown_ids"])
                    fb_excluded += bool(verdict["failed_ids"])
                    if not verdict["eligible"]:
                        continue
                    fb_eligible += 1
                    pref_score, matched_mem_ids, audit_entries = score_preferences(
                        record,
                        verdict,
                        user_memory,
                        state,
                        personalization_strength=personalization_strength,
                        max_bonus=personalization_max_bonus,
                    )
                    raw_bonus = sum(a.get("delta", 0.0) for a in audit_entries)
                    bounded_bonus = max(
                        -personalization_max_bonus,
                        min(personalization_max_bonus, raw_bonus),
                    )
                    baseline_relevance = -score
                    eligible_pool.append(
                        {
                            "record": record,
                            "score": score,
                            "baseline_relevance": baseline_relevance,
                            "bounded_bonus": bounded_bonus,
                            "verdict": verdict,
                            "pref_score": pref_score,
                            "matched_mem_ids": matched_mem_ids,
                            "audit_entries": audit_entries,
                        }
                    )
                matched, eligible, unknown, excluded = (
                    fb_matched,
                    fb_eligible,
                    fb_unknown,
                    fb_excluded,
                )

        # Baseline rankings (pure BM25 relevance before personalization)
        baseline_sorted = sorted(
            eligible_pool,
            key=lambda item: (
                item["score"],
                item["record"]["id"],
            ),
        )
        baseline_rankings = [
            it["record"]["id"] for it in baseline_sorted[: action.limit]
        ]

        # Stage 2: Memory-aware candidate reranking among verified eligible candidates
        if personalization_strength > 0.0 and user_memory and eligible_pool:
            max_base = max(
                (it["baseline_relevance"] for it in eligible_pool), default=1.0
            )
            if max_base <= 0.0:
                max_base = 1.0

            for it in eligible_pool:
                norm_rel = it["baseline_relevance"] / max_base
                it["normalized_relevance"] = norm_rel
                it["personalized_score"] = norm_rel + personalization_strength * it.get(
                    "bounded_bonus", 0.0
                )

            eligible_pool.sort(
                key=lambda item: (
                    -item["personalized_score"],
                    item["score"],
                    item["record"]["id"],
                )
            )
        else:
            eligible_pool = baseline_sorted

        personalized_rankings = [
            it["record"]["id"] for it in eligible_pool[: action.limit]
        ]

        decision_audit = []
        seen_audits = set()
        for item in eligible_pool[: action.limit]:
            for entry in item.get("audit_entries", []):
                audit_key = (entry["memory_id"], item["record"]["id"])
                if audit_key not in seen_audits:
                    seen_audits.add(audit_key)
                    decision_audit.append(
                        {
                            "memory_id": entry["memory_id"],
                            "application": entry["application"],
                            "attribute": entry["attribute"],
                            "value": entry["value"],
                            "affected_products": [item["record"]["id"]],
                            "match_type": entry["match_type"],
                            "reason": entry["reason"],
                        }
                    )

        candidates = []
        for item in eligible_pool[: action.limit]:
            record = item["record"]
            candidates.append(
                {
                    "id": record["id"],
                    "title": record["title"][:500],
                    "facts": record["facts"],
                    "categories": record["categories"],
                    "evidence": record["evidence"],
                    "snippet": record["text"][:400],
                    "image_url": record["image_url"],
                    "bm25": item["score"],
                    "baseline_relevance": item.get(
                        "baseline_relevance", -item["score"]
                    ),
                    "preference_score": item["pref_score"],
                    "personalized_score": item.get(
                        "personalized_score",
                        -item["score"] + item["pref_score"],
                    ),
                    "matched_memory_ids": item["matched_mem_ids"],
                    **item["verdict"],
                }
            )
        return {
            "search_id": uuid4().hex,
            "state_version": state.version,
            "catalogue_version": self.catalogue_version,
            "strategy_version": self.strategy_version,
            "category_match_version": "number-inflection-v2",
            "query": action.query,
            "match_mode": action.mode,
            "effective_match_mode": effective_mode,
            "fallback_triggered": fallback_triggered,
            "fallback_reason": fallback_reason,
            "applied_hard_filters": [r.model_dump() for r in hard_filters],
            "counts": {
                "lexical_matches": matched,
                "verified_eligible": eligible,
                "products_with_unknown_required_attributes": unknown,
                "products_failing_known_constraints": excluded,
            },
            "candidates": candidates,
            "initial_candidate_pool": [it["record"]["id"] for it in eligible_pool],
            "baseline_rankings": baseline_rankings,
            "personalized_rankings": personalized_rankings,
            "personalization_strength": personalization_strength,
            "memory_decision_audit": decision_audit,
        }

    def eligible(self, product_id, state):
        row = self.db.execute(
            "SELECT record FROM products WHERE id=?", (product_id,)
        ).fetchone()
        return bool(row) and assess(json.loads(row[0]), state)["eligible"]
