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


class ProductSearch(Protocol):
    catalogue_version: str
    strategy_version: str

    def search(self, action: Search, state: ShoppingState) -> dict: ...

    def eligible(self, product_id: str, state: ShoppingState) -> bool: ...


class LexicalSearch:
    def __init__(self, path, *, expected_catalogue_hash=None):
        path = Path(path).resolve()
        self.db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        meta = dict(self.db.execute("SELECT key,value FROM metadata"))
        if meta.get("index_version") != INDEX_VERSION:
            self.db.close()
            raise ValueError("Unsupported index version; rebuild required")
        self.catalogue_version = meta["catalogue_sha256"]
        self.strategy_version = meta["index_version"]
        self.count = int(meta["count"])
        if (
            expected_catalogue_hash
            and expected_catalogue_hash != self.catalogue_version
        ):
            self.db.close()
            raise ValueError("Stale catalogue index; rebuild required")

    def close(self):
        self.db.close()

    def search(self, action, state):
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
        query = (" AND " if action.mode == "all" else " OR ").join(
            '"' + t + '"' for t in terms
        )
        if terms:
            cursor = self.db.execute(
                """SELECT p.record,bm25(product_fts,5.0,3.0,2.0,1.0)
                FROM product_fts JOIN products p ON p.rowid=product_fts.rowid
                WHERE product_fts MATCH ? ORDER BY bm25(product_fts,5.0,3.0,2.0,1.0),p.id""",
                (query,),
            )
        else:
            cursor = self.db.execute("SELECT record,0.0 FROM products ORDER BY id")
        candidates, matched, eligible, unknown, excluded = [], 0, 0, 0, 0
        for raw, score in cursor:
            matched += 1
            record = json.loads(raw)
            verdict = assess(record, state)
            unknown += bool(verdict["unknown_ids"])
            excluded += bool(verdict["failed_ids"])
            if not verdict["eligible"]:
                continue
            eligible += 1
            if len(candidates) < action.limit:
                candidates.append(
                    {
                        "id": record["id"],
                        "title": record["title"][:500],
                        "facts": record["facts"],
                        "categories": record["categories"],
                        "evidence": record["evidence"],
                        "snippet": record["text"][:400],
                        "image_url": record["image_url"],
                        "bm25": score,
                        **verdict,
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
