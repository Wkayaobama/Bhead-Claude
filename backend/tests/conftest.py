"""Shared fixtures: an in-memory stand-in for the Motor database and a
TestClient that skips the lifespan (no real Mongo, no scheduler).

The fake implements only the slice of the Motor surface the routes use, and
it evaluates queries literally enough that a bad `$regex` fails the way Mongo
would, so a regression in query building shows up as a failing test.
"""
from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient


def _match_value(value: Any, cond: Any) -> bool:
    if isinstance(cond, dict):
        for op, arg in cond.items():
            if op == "$regex":
                flags = re.IGNORECASE if "i" in cond.get("$options", "") else 0
                if not isinstance(value, str) or not re.search(arg, value, flags):
                    return False
            elif op == "$options":
                continue
            elif op == "$exists":
                if bool(value is not None) != bool(arg):
                    return False
            elif op == "$ne":
                if value == arg:
                    return False
            elif op == "$lte":
                if value is None or not value <= arg:
                    return False
            elif op == "$gte":
                if value is None or not value >= arg:
                    return False
            elif op == "$lt":
                if value is None or not value < arg:
                    return False
            elif op == "$gt":
                if value is None or not value > arg:
                    return False
            else:
                raise NotImplementedError(f"FakeCollection: operator {op}")
        return True
    return value == cond


def matches(doc: dict, query: dict | None) -> bool:
    for key, cond in (query or {}).items():
        if key == "$or":
            if not any(matches(doc, sub) for sub in cond):
                return False
        elif not _match_value(doc.get(key), cond):
            return False
    return True


class FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, *_args, **_kwargs):
        return self

    def skip(self, n):
        self._docs = self._docs[n:]
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    def __aiter__(self):
        self._it = iter(self._docs)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration

    async def to_list(self, n=None):
        return self._docs[:n] if n else self._docs


class FakeCollection:
    def __init__(self):
        self.docs: list[dict] = []
        self.calls: list[tuple[str, Any]] = []

    def find(self, query=None, projection=None):
        self.calls.append(("find", query))
        return FakeCursor([d for d in self.docs if matches(d, query)])

    async def find_one(self, query):
        self.calls.append(("find_one", query))
        return next((d for d in self.docs if matches(d, query)), None)

    async def count_documents(self, query):
        self.calls.append(("count_documents", query))
        return len([d for d in self.docs if matches(d, query)])

    async def insert_one(self, doc):
        doc.setdefault("_id", ObjectId())
        self.docs.append(doc)
        return SimpleNamespace(inserted_id=doc["_id"])

    async def update_one(self, flt, update, upsert=False):
        self.calls.append(("update_one", flt, update))
        for doc in self.docs:
            if matches(doc, flt):
                for k, v in update.get("$set", {}).items():
                    doc[k] = v
                for k, v in update.get("$inc", {}).items():
                    doc[k] = doc.get(k, 0) + v
                return SimpleNamespace(matched_count=1, modified_count=1)
        if upsert:
            new = {**flt, **update.get("$set", {}), **update.get("$setOnInsert", {})}
            await self.insert_one(new)
        return SimpleNamespace(matched_count=0, modified_count=0)

    async def delete_one(self, flt):
        for i, doc in enumerate(self.docs):
            if matches(doc, flt):
                del self.docs[i]
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)

    async def delete_many(self, flt):
        before = len(self.docs)
        self.docs = [d for d in self.docs if not matches(d, flt)]
        return SimpleNamespace(deleted_count=before - len(self.docs))

    def aggregate(self, _pipeline):
        return FakeCursor([])


class FakeDB:
    def __init__(self):
        self._collections: dict[str, FakeCollection] = {}

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._collections.setdefault(name, FakeCollection())

    def __getitem__(self, name):
        return getattr(self, name)


@pytest.fixture
def no_llm_credentials(monkeypatch):
    from app import llm
    from app.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    llm.reset_client()
    yield
    llm.reset_client()


@pytest.fixture
def api(no_llm_credentials):
    """(TestClient, FakeDB) with the lifespan skipped."""
    from app.main import app

    db = FakeDB()
    app.state.db = db
    if hasattr(app.state, "mongo"):
        del app.state.mongo
    return TestClient(app), db
