"""Mem0 self-hosted adapter: Harness `MemoryProvider` <-> Mem0 REST server.

Target: the official self-hosted server (`mem0/server` in the Mem0 repository,
FastAPI + pgvector), verified against mem0ai 2.2.1 / commit 94c3fe9f. Only these
routes are used:

    GET    /memories?user_id=<ns>&top_k=1   health (auth + datastore round trip)
    POST   /memories                         add   {messages, user_id, metadata, infer: false}
    GET    /memories/{id}                    read back (returns null when unknown)
    POST   /search                           search {query, filters: {user_id}, top_k}
    PUT    /memories/{id}                    update {text}   (404 when unknown)
    DELETE /memories/{id}                    delete          (404 when unknown)

Authentication: `X-API-Key` header (a per-user key or the server's ADMIN_API_KEY).
The server's own LLM/embedder credentials stay inside the server.

Translation rules (all Mem0 details stay in this module):

- scope    -> Mem0 `user_id` = `MemoryScope.namespace` (e.g. `demo/task/T-1`); Mem0
              scopes search/get_all by exact user_id, which gives scope isolation;
- lineage  -> Mem0 metadata `harness_*` keys; records are rebuilt from them;
- `infer: false` stores the content verbatim (no LLM fact extraction, no rewrite);
- ids are Mem0 UUIDs; a non-UUID id is reported as not found without a request;
- HTTP 401/403 -> MemoryConfigurationError; 404 on an id -> MemoryNotFoundError;
  5xx / connection errors / timeouts -> MemoryUnavailableError; other 4xx or a
  malformed body -> MemoryStoreError. Messages carry status codes and the
  server's error *code*, never request bodies, memory content or the API key.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, Final
from urllib.parse import quote, urlencode

from pydantic import ValidationError as PydanticValidationError

from orchestrator.core.exceptions import (
    MemoryConfigurationError,
    MemoryNotFoundError,
    MemoryStoreError,
    MemoryUnavailableError,
)
from orchestrator.memory.models import (
    HealthStatus,
    MemoryHealth,
    MemoryHit,
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
    MemorySource,
    NewMemory,
)

logger = logging.getLogger(__name__)

HEALTH_NAMESPACE: Final = "harness-healthcheck"
_SCHEMA_VERSION: Final = 1
# Mem0 metadata keys carrying Harness scope and lineage (prefixed to avoid clashes).
_META_SCHEMA = "harness_schema"
_META_PROJECT = "harness_project"
_META_SCOPE = "harness_scope"
_META_SCOPE_KEY = "harness_scope_key"
_META_SOURCE_TYPE = "harness_source_type"
_META_SOURCE_ID = "harness_source_id"

# (method, path-with-query, json body) -> (HTTP status, parsed JSON body or None)
Transport = Callable[[str, str, Mapping[str, Any] | None], tuple[int, Any]]


class HttpTransport:
    """Default transport: stdlib urllib, JSON in/out, `X-API-Key` auth, hard timeout."""

    def __init__(self, base_url: str, api_key: str, *, timeout: float) -> None:
        if not base_url.startswith(("http://", "https://")):
            raise MemoryConfigurationError(f"memory base_url must be http(s): {base_url!r}")
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout

    def __call__(self, method: str, path: str, body: Mapping[str, Any] | None) -> tuple[int, Any]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(  # noqa: S310 - scheme restricted to http(s) above
            self._base_url + path, data=data, method=method
        )
        request.add_header("Accept", "application/json")
        request.add_header("Content-Type", "application/json")
        request.add_header("X-API-Key", self._api_key)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310
                return response.status, _parse_json(response.read())
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, _parse_json(exc.read())
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise MemoryUnavailableError(
                f"cannot reach memory backend at {self._base_url}: {type(reason).__name__}"
            ) from exc


def _parse_json(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


class Mem0MemoryProvider:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout: float = 10.0,
        api_key_env: str = "MEM0_API_KEY",
        transport: Transport | None = None,
    ) -> None:
        self._base_url = base_url
        self._api_key_env = api_key_env  # only for error messages; the key itself is never shown
        self._transport = transport or HttpTransport(base_url, api_key, timeout=timeout)

    @property
    def backend_id(self) -> str:
        return "mem0"

    # --- HTTP boundary ---------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        body: Mapping[str, Any] | None = None,
        *,
        memory_id: str | None = None,
    ) -> Any:
        status, payload = self._transport(method, path, body)
        logger.debug("mem0 %s %s -> %s", method, path.split("?")[0], status)
        if 200 <= status < 300:
            return payload
        if status in (401, 403):
            raise MemoryConfigurationError(
                f"memory backend rejected the credentials (HTTP {status}); "
                f"check ${self._api_key_env}"
            )
        if status == 404 and memory_id is not None:
            raise MemoryNotFoundError(f"memory '{memory_id}' not found")
        code = payload.get("code") if isinstance(payload, dict) else None
        suffix = f", code={code}" if isinstance(code, str) else ""
        if status >= 500:
            raise MemoryUnavailableError(f"memory backend failed (HTTP {status}{suffix})")
        if status == 404:
            raise MemoryConfigurationError(
                f"memory backend endpoint not found (HTTP 404); check base_url {self._base_url}"
            )
        raise MemoryStoreError(f"memory backend rejected the request (HTTP {status}{suffix})")

    # --- translation -------------------------------------------------------------------

    @staticmethod
    def _metadata(memory: NewMemory) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            _META_SCHEMA: _SCHEMA_VERSION,
            _META_PROJECT: memory.scope.project,
            _META_SCOPE: memory.scope.kind.value,
            _META_SOURCE_TYPE: memory.source.type.value,
            _META_SOURCE_ID: memory.source.id,
        }
        if memory.scope.key is not None:
            metadata[_META_SCOPE_KEY] = memory.scope.key
        return metadata

    @staticmethod
    def _to_record(item: Any) -> MemoryRecord:
        """Rebuild a Harness record from a Mem0 memory item. Raises on missing lineage."""
        if not isinstance(item, dict):
            raise MemoryStoreError("memory backend returned a malformed memory item")
        metadata = item.get("metadata") or {}
        try:
            return MemoryRecord(
                id=str(item.get("id")),
                content=item.get("memory") or "",
                scope=MemoryScope(
                    project=metadata.get(_META_PROJECT),
                    kind=metadata.get(_META_SCOPE),
                    key=metadata.get(_META_SCOPE_KEY),
                ),
                source=MemorySource(
                    type=metadata.get(_META_SOURCE_TYPE), id=metadata.get(_META_SOURCE_ID)
                ),
                created_at=_parse_timestamp(item.get("created_at")),
                updated_at=_parse_timestamp(item.get("updated_at")),
            )
        except PydanticValidationError as exc:
            raise MemoryStoreError(
                "memory backend returned a memory without valid Harness scope/lineage metadata"
            ) from exc

    def _get(self, memory_id: str) -> MemoryRecord:
        item = self._request("GET", f"/memories/{quote(memory_id)}", memory_id=memory_id)
        if item is None:
            raise MemoryNotFoundError(f"memory '{memory_id}' not found")
        return self._to_record(item)

    def _require_known_format(self, memory_id: str) -> None:
        if not _is_uuid(memory_id):
            raise MemoryNotFoundError(f"memory '{memory_id}' not found")

    # --- MemoryProvider ----------------------------------------------------------------

    def health(self) -> MemoryHealth:
        path = "/memories?" + urlencode({"user_id": HEALTH_NAMESPACE, "top_k": 1})
        try:
            self._request("GET", path)
        except MemoryUnavailableError as exc:
            return MemoryHealth(status=HealthStatus.UNAVAILABLE, detail=str(exc))
        except MemoryStoreError as exc:
            return MemoryHealth(status=HealthStatus.MISCONFIGURED, detail=str(exc))
        return MemoryHealth(
            status=HealthStatus.HEALTHY,
            detail=f"Mem0 at {self._base_url}: reachable, credentials accepted, datastore queried",
        )

    def add(self, memory: NewMemory) -> MemoryRecord:
        payload = self._request(
            "POST",
            "/memories",
            {
                "messages": [{"role": "user", "content": memory.content}],
                "user_id": memory.scope.namespace,
                "metadata": self._metadata(memory),
                "infer": False,
            },
        )
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list) or len(results) != 1 or not results[0].get("id"):
            raise MemoryStoreError("memory backend returned an unexpected add response")
        return self._get(str(results[0]["id"]))

    def search(self, query: MemoryQuery) -> tuple[MemoryHit, ...]:
        payload = self._request(
            "POST",
            "/search",
            {
                "query": query.text,
                "filters": {"user_id": query.scope.namespace},
                "top_k": query.limit,
            },
        )
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list):
            raise MemoryStoreError("memory backend returned an unexpected search response")
        hits = []
        for item in results:
            try:
                record = self._to_record(item)
            except MemoryStoreError:
                logger.warning("mem0: skipping a search result without Harness lineage metadata")
                continue
            if record.scope != query.scope:  # defence in depth: never leak across scopes
                continue
            score = item.get("score")
            hits.append(MemoryHit(record=record, score=float(score) if score is not None else 0.0))
        return tuple(hits)

    def update(self, memory_id: str, content: str) -> MemoryRecord:
        self._require_known_format(memory_id)
        self._request(
            "PUT", f"/memories/{quote(memory_id)}", {"text": content}, memory_id=memory_id
        )
        return self._get(memory_id)

    def delete(self, memory_id: str) -> None:
        self._require_known_format(memory_id)
        self._request("DELETE", f"/memories/{quote(memory_id)}", memory_id=memory_id)
