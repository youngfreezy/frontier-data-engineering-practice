from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "src" / "frontier_control_plane"
SKILL = ROOT / ".cursor" / "skills" / "frontier-data-engineering"
PRACTICE = ROOT / "practice" / "incremental-order-etl"


def imported_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(
                "frontier_control_plane"
                if node.level
                else node.module.split(".")[0]
            )
    return roots


def test_reusable_core_has_no_task_or_third_party_imports() -> None:
    allowed = set(sys.stdlib_module_names) | {"frontier_control_plane"}
    imports = set().union(*(imported_roots(path) for path in CORE.glob("*.py")))
    assert imports <= allowed
    assert not imports & {"duckdb", "practice_pipeline", "feather"}


def test_reusable_skill_does_not_name_consumers_or_practice_fixture() -> None:
    text = "\n".join(
        path.read_text(encoding="utf-8").lower()
        for path in SKILL.rglob("*")
        if path.is_file()
    )
    for forbidden in ("feather", "duckdb", "practice_pipeline", "incremental-order"):
        assert forbidden not in text


def test_reusable_skill_local_markdown_references_resolve() -> None:
    skill_text = SKILL.joinpath("SKILL.md").read_text(encoding="utf-8")
    targets = re.findall(r"\[[^]]+\]\(([^)]+\.md)\)", skill_text)
    assert targets
    for target in targets:
        assert SKILL.joinpath(target).is_file(), target


def test_root_package_is_dependency_free_and_practice_owns_duckdb() -> None:
    root_project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    practice_project = tomllib.loads(
        (PRACTICE / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert root_project["project"]["dependencies"] == []
    practice_dependencies = practice_project["project"]["dependencies"]
    assert any(item.startswith("duckdb") for item in practice_dependencies)
    assert "frontier-data-engineering-toolkit" in practice_dependencies


def test_task_files_live_only_under_the_practice_boundary() -> None:
    assert PRACTICE.joinpath("fixtures").is_dir()
    assert PRACTICE.joinpath("src", "practice_pipeline").is_dir()
    assert PRACTICE.joinpath("tests", "test_pipeline.py").is_file()
    assert not ROOT.joinpath("fixtures", "base.jsonl").exists()
    assert not ROOT.joinpath("src", "practice_pipeline", "__init__.py").exists()
    assert not ROOT.joinpath("tests", "test_pipeline.py").exists()
