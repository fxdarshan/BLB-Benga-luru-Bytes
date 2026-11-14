"""Checks the Dockerfile's data stage copies every module ingestion needs.

The data stage copies only the modules `recommender.ingest` imports, so that changes to the API
don't rebuild the data. If ingestion starts importing another module, this test names it.
"""

from __future__ import annotations

import ast
import re

from recommender.config import PROJECT_ROOT

SRC = PROJECT_ROOT / "src" / "recommender"


def imported_modules(module: str) -> set[str]:
    """`module` and every recommender module it imports, directly or not."""
    seen: set[str] = set()
    todo = [module]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        tree = ast.parse((SRC / f"{name}.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module == "recommender":
                    todo.extend(alias.name for alias in node.names)
                elif node.module.startswith("recommender."):
                    todo.append(node.module.split(".")[1])
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("recommender."):
                        todo.append(alias.name.split(".")[1])
    return seen


def copied_in_data_stage() -> set[str]:
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    data_stage = dockerfile.split("# ---------- Stage 2")[0]
    return set(re.findall(r"src/recommender/(\w+)\.py", data_stage))


def test_the_data_stage_copies_every_module_ingestion_imports():
    needed = imported_modules("ingest") | {"__init__"}
    missing = needed - copied_in_data_stage()
    assert not missing, f"Add these to the data stage's COPY in the Dockerfile: {sorted(missing)}"


def test_the_data_stage_copies_nothing_ingestion_doesnt_use():
    # Extra modules would rebuild the data whenever they change.
    extra = copied_in_data_stage() - imported_modules("ingest") - {"__init__"}
    assert not extra, f"Ingestion doesn't use these; drop them from the data stage: {sorted(extra)}"
