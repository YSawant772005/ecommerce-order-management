"""Data-source isolation: Screen 3 is Elasticsearch-only.

Asserted by parsing the import graph (catches aliased and from-imports),
not by grepping one file.
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]

PG_FORBIDDEN = {"orders_repo", "users_repo", "outbox_repo", "sync_state_repo"}
MONGO_FORBIDDEN = {"products_repo"}


def imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.rsplit(".", 1)[-1])
            names.update(a.name.rsplit(".", 1)[-1] for a in node.names)
        elif isinstance(node, ast.Import):
            names.update(a.name.rsplit(".", 1)[-1] for a in node.names)
    return names


def test_search_service_imports_no_pg_or_mongo_repo():
    got = imports_of(BACKEND_ROOT / "app" / "services" / "search_service.py")
    assert got & PG_FORBIDDEN == set()
    assert got & MONGO_FORBIDDEN == set()
    assert "search_repo" in got


def test_search_service_opens_no_pg_or_mongo_client():
    src = (BACKEND_ROOT / "app" / "services" / "search_service.py").read_text()
    for forbidden in ("get_pool", "get_db", "get_mongo"):
        assert forbidden not in src


def test_search_router_imports_no_pg_or_mongo_repo():
    got = imports_of(BACKEND_ROOT / "app" / "api" / "search.py")
    assert got & PG_FORBIDDEN == set()
    assert got & MONGO_FORBIDDEN == set()


def test_detector_catches_a_violation():
    """Negative control: the AST walk is not a tautology."""
    import tempfile

    with tempfile.NamedTemporaryFile(
        "w", suffix=".py", delete=False
    ) as f:
        f.write("from app.repositories import orders_repo, search_repo\n")
        probe = Path(f.name)
    try:
        got = imports_of(probe)
        assert got & PG_FORBIDDEN == {"orders_repo"}
    finally:
        probe.unlink()
