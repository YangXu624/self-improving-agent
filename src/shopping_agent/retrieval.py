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

from .category_matching import category_contains
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


def score_preferences(record, verdict, user_memory=None, state=None):
    base_score = float(len(verdict.get("matched_soft_ids", [])))
    matched_memory_ids = []

    if not user_memory or not isinstance(user_memory, dict):
        return base_score, matched_memory_ids

    memory_records = user_memory.get("records", [])
    if not isinstance(memory_records, list):
        return base_score, matched_memory_ids

    memory_score = 0.0
    record_text = normalized(record.get("text", ""))
    record_title = normalized(record.get("title", ""))
    record_facts = record.get("facts", {})

    # Detect active state requirements by field: current explicit preferences override contradictory memories
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

        matched = False
        # 1. Attribute fact match
        if attr in record_facts and record_facts[attr] is not None:
            fact_val = facet(attr, record_facts[attr])
            target_val = facet(attr, val)
            if (
                fact_val == target_val
                or target_val in fact_val
                or fact_val in target_val
            ):
                matched = True

        # 2. Text / title word-boundary match
        if not matched:
            val_words = [w for w in re.findall(r"\w+", val) if len(w) > 2]
            if val_words:
                all_in_title = all(w in record_title for w in val_words)
                all_in_text = all(w in record_text for w in val_words)
                if all_in_title or all_in_text:
                    matched = True

        if matched:
            mem_id = mem.get("id")
            if mem_id:
                matched_memory_ids.append(mem_id)
            if is_pref:
                memory_score += 1.0
            elif is_dislike:
                memory_score -= 1.0

    return base_score + memory_score, matched_memory_ids


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

    def search(self, action, state, *, user_memory=None, fallback=None):
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
            q = (" AND " if mode == "all" else " OR ").join(
                '"' + t + '"' for t in query_terms
            )
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
        for raw, score in cursor:
            matched += 1
            record = json.loads(raw)
            verdict = assess(record, state)
            unknown += bool(verdict["unknown_ids"])
            excluded += bool(verdict["failed_ids"])
            if not verdict["eligible"]:
                continue
            eligible += 1
            pref_score, matched_mem_ids = score_preferences(
                record, verdict, user_memory, state
            )
            eligible_pool.append(
                {
                    "record": record,
                    "score": score,
                    "verdict": verdict,
                    "pref_score": pref_score,
                    "matched_mem_ids": matched_mem_ids,
                }
            )

        fallback_triggered = False
        effective_mode = action.mode
        fallback_reason = None
        # Safe fallback enabled identically for both Memory OFF and Memory ON when use_fallback is True:
        # If action.mode == "all" and terms > 1 yields 0 eligible candidates,
        # relax over-constrained query terms while strictly enforcing all hard constraints via assess().
        if action.mode == "all" and len(terms) > 1 and len(eligible_pool) == 0 and use_fallback:
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
                        pref_score, matched_mem_ids = score_preferences(
                            record, verdict, user_memory, state
                        )
                        eligible_pool.append(
                            {
                                "record": record,
                                "score": score,
                                "verdict": verdict,
                                "pref_score": pref_score,
                                "matched_mem_ids": matched_mem_ids,
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
                    pref_score, matched_mem_ids = score_preferences(
                        record, verdict, user_memory, state
                    )
                    eligible_pool.append(
                        {
                            "record": record,
                            "score": score,
                            "verdict": verdict,
                            "pref_score": pref_score,
                            "matched_mem_ids": matched_mem_ids,
                        }
                    )
                matched, eligible, unknown, excluded = (
                    fb_matched,
                    fb_eligible,
                    fb_unknown,
                    fb_excluded,
                )

        # Stage 2: Soft preference-based ranking among verified eligible candidates
        eligible_pool.sort(
            key=lambda item: (
                -item["pref_score"],
                item["score"],
                item["record"]["id"],
            )
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
                    "preference_score": item["pref_score"],
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
            "applied_hard_filters": [r.model_dump() for r in hard_filters],
            "counts": {
                "lexical_matches": matched,
                "verified_eligible": eligible,
                "products_with_unknown_required_attributes": unknown,
                "products_failing_known_constraints": excluded,
            },
            "candidates": candidates,
        }

    def eligible(self, product_id, state):
        row = self.db.execute(
            "SELECT record FROM products WHERE id=?", (product_id,)
        ).fetchone()
        return bool(row) and assess(json.loads(row[0]), state)["eligible"]
