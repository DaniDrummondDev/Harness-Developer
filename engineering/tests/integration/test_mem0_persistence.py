"""V0.3 exit criterion against a REAL self-hosted Mem0 server, across process restarts.

    process A: harness memory add     -> memory persisted in Mem0 (pgvector)
    process B: harness memory search  -> same memory found (new process, new adapter)
    process C: harness memory update  -> content replaced, lineage kept
    process D: harness memory search  -> updated content found; other scopes see nothing
    process E: harness memory delete  -> gone for process F

Every step is a separate `python -m orchestrator` process, so nothing survives
in Python memory between steps: retrieval can only come from Mem0.

Opt-in (external service required), skipped otherwise:

    export MEM0_API_KEY=<key accepted by the server>   # X-API-Key
    export HARNESS_MEM0_INTEGRATION=1
    export MEM0_BASE_URL=http://localhost:8888          # optional (default shown)
    pytest -m mem0 -v tests/integration/test_mem0_persistence.py

Each run uses a unique `run:<uuid>` scope and deletes what it created.
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
import uuid
from pathlib import Path
from typing import Any

import pytest

from orchestrator.utils.shell import run_command

pytestmark = [
    pytest.mark.mem0,
    pytest.mark.skipif(
        os.environ.get("HARNESS_MEM0_INTEGRATION") != "1" or not os.environ.get("MEM0_API_KEY"),
        reason="real Mem0 test is opt-in: set HARNESS_MEM0_INTEGRATION=1 and MEM0_API_KEY",
    ),
]


@pytest.fixture
def mem0_root(harness_root: Path) -> Path:
    base_url = os.environ.get("MEM0_BASE_URL", "http://localhost:8888")
    (harness_root / "config" / "memory.yaml").write_text(textwrap.dedent(f"""
        version: 1
        memory:
          enabled: true
          backend: mem0
          mem0: {{base_url: "{base_url}", api_key_env: MEM0_API_KEY, timeout_seconds: 60}}
    """).lstrip(), encoding="utf-8")
    return harness_root


def harness(root: Path, cwd: Path, *args: str) -> Any:
    """Run one CLI command in a brand-new Python process and return its JSON output."""
    result = run_command(
        [sys.executable, "-m", "orchestrator", "--root", str(root), "memory", *args],
        cwd=cwd,
        timeout=120,
    )
    assert result.exit_code == 0, f"{args[0]} failed: {result.stderr}"
    return json.loads(result.stdout)


def test_memory_survives_process_restart(mem0_root: Path, tmp_path: Path) -> None:
    run_scope = f"run:it-{uuid.uuid4().hex[:12]}"
    other_scope = f"run:it-{uuid.uuid4().hex[:12]}"
    content = "Integration fact: the harness stores long-term memory in Mem0 on pgvector"

    assert harness(mem0_root, tmp_path, "health")["status"] == "healthy"

    # Process A: write.
    added = harness(mem0_root, tmp_path, "add", content, "--scope", run_scope,
                    "--source", "implementation_note:V0.3-it")
    memory_id = added["id"]
    try:
        # Process B: a new process retrieves it from Mem0.
        hits = harness(mem0_root, tmp_path, "search", "where is long-term memory stored",
                       "--scope", run_scope)
        found = {hit["record"]["id"]: hit["record"] for hit in hits}
        assert memory_id in found
        assert found[memory_id]["content"] == content
        assert found[memory_id]["source"] == {"type": "implementation_note", "id": "V0.3-it"}
        assert found[memory_id]["scope"]["key"] == run_scope.split(":")[1]

        # Scope isolation on the real backend.
        assert harness(mem0_root, tmp_path, "search", "long-term memory pgvector",
                       "--scope", other_scope) == []

        # Process C + D: update, then retrieve the new content from yet another process.
        updated = harness(mem0_root, tmp_path, "update", memory_id,
                          "Integration fact: memory lives in Mem0 self-hosted (updated)")
        assert updated["id"] == memory_id and updated["source"] == added["source"]
        hits = harness(mem0_root, tmp_path, "search", "Mem0 self-hosted", "--scope", run_scope)
        assert {h["record"]["id"]: h["record"]["content"] for h in hits}.get(memory_id) == (
            "Integration fact: memory lives in Mem0 self-hosted (updated)"
        )
    finally:
        # Process E: delete (also cleans up after a failed assertion).
        harness(mem0_root, tmp_path, "delete", memory_id)

    # Process F: it is gone.
    hits = harness(mem0_root, tmp_path, "search", "Mem0 self-hosted", "--scope", run_scope)
    assert memory_id not in {hit["record"]["id"] for hit in hits}
