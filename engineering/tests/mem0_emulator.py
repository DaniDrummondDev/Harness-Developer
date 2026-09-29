"""Offline emulation of the self-hosted Mem0 REST routes used by `Mem0MemoryProvider`.

It is a `Transport` (method, path, body) -> (status, json), so the real adapter
code runs end to end without sockets. Behaviour mirrors the server source the
adapter was written against (mem0/server/main.py, mem0ai 2.2.1):

- auth: wrong `X-API-Key` -> 401 {"detail": "Invalid API key."};
- POST /memories with infer=false stores each message verbatim and adds `role`
  to the metadata; response {"results": [{"id", "memory", "event": "ADD", ...}]};
- GET /memories/{id} -> the item or null (200); GET /memories?user_id= -> {"results"};
- POST /search requires filters.user_id; results carry a `score`;
- PUT/DELETE of an unknown id -> 404 {"detail": "Memory with id ... not found"};
- PUT keeps existing metadata and bumps `updated_at`.

Search scoring is lexical (the real server uses embeddings + BM25); tests
assert membership and isolation, not exact scores. Importable because pytest
puts the rootdir `tests/` (where conftest.py lives) on sys.path.
"""

from __future__ import annotations

import copy
import re
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

from orchestrator.core.exceptions import MemoryUnavailableError

VALID_KEY = "test-key-not-a-secret"


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


class Mem0Emulator:
    def __init__(self, *, api_key: str = VALID_KEY) -> None:
        self.api_key = api_key
        self.expected_key = VALID_KEY
        self.down = False  # simulate connection refused (raised like HttpTransport does)
        self.fail_status: tuple[int, dict[str, Any]] | None = None  # force a response
        self.items: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, str, Mapping[str, Any] | None]] = []

    # Transport protocol
    def __call__(self, method: str, path: str, body: Mapping[str, Any] | None) -> tuple[int, Any]:
        self.calls.append((method, path, copy.deepcopy(dict(body)) if body is not None else None))
        if self.down:
            raise MemoryUnavailableError(
                "cannot reach memory backend at emulator: ConnectionRefusedError"
            )
        if self.api_key != self.expected_key:
            return 401, {"detail": "Invalid API key."}
        if self.fail_status is not None:
            return self.fail_status
        url = urlsplit(path)
        parts = [p for p in url.path.split("/") if p]
        if method == "POST" and parts == ["memories"]:
            return self._add(body or {})
        if method == "GET" and parts == ["memories"]:
            user_id = parse_qs(url.query).get("user_id", [None])[0]
            return 200, {"results": [i for i in self.items.values() if i["user_id"] == user_id]}
        if method == "POST" and parts == ["search"]:
            return self._search(body or {})
        if len(parts) == 2 and parts[0] == "memories":
            memory_id = parts[1]
            if method == "GET":
                return 200, copy.deepcopy(self.items.get(memory_id))
            if memory_id not in self.items:
                return 404, {"detail": f"Memory with id {memory_id} not found"}
            if method == "PUT":
                item = self.items[memory_id]
                item["memory"] = (body or {})["text"]
                item["updated_at"] = datetime.now(UTC).isoformat()
                return 200, {"message": "Memory updated successfully!"}
            if method == "DELETE":
                del self.items[memory_id]
                return 200, {"message": "Memory deleted successfully"}
        return 404, {"detail": "Not Found"}

    def _add(self, body: Mapping[str, Any]) -> tuple[int, Any]:
        if not body.get("user_id"):
            return 400, {
                "detail": "At least one identifier (user_id, agent_id, run_id) is required."
            }
        results = []
        for message in body["messages"]:
            memory_id = str(uuid.uuid4())
            now = datetime.now(UTC).isoformat()
            metadata = dict(body.get("metadata") or {})
            metadata["role"] = message["role"]
            self.items[memory_id] = {
                "id": memory_id,
                "memory": message["content"],
                "user_id": body["user_id"],
                "metadata": metadata,
                "created_at": now,
                "updated_at": now,
            }
            results.append({"id": memory_id, "memory": message["content"], "event": "ADD"})
        return 200, {"results": results}

    def _search(self, body: Mapping[str, Any]) -> tuple[int, Any]:
        user_id = (body.get("filters") or {}).get("user_id")
        if not user_id:
            return 400, {
                "detail": "filters must contain at least one of: user_id, agent_id, run_id."
            }
        wanted = _words(body["query"])
        scored = []
        for item in self.items.values():
            if item["user_id"] != user_id:
                continue
            score = len(wanted & _words(item["memory"])) / max(len(wanted), 1)
            if score > 0:
                scored.append({**copy.deepcopy(item), "score": score})
        scored.sort(key=lambda i: i["score"], reverse=True)
        return 200, {"results": scored[: body.get("top_k") or 20]}
