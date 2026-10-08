#!/usr/bin/env python3
"""Build a deterministic identity manifest for the V1.3 refactor baseline.

This tool is deliberately independent from the generator.  It records the exact
runtime sources, tests, validation tools, formal workbook, seed-resource
candidates, repository state, and external compiler executables used by an R0
baseline.  An optional snapshot copies only those selected inputs into a new,
previously non-existent directory; it never deletes or overwrites a directory.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Iterable


SCHEMA_VERSION = "v13-refactor-baseline/v2"
FORMAL_MASTER = Path("test_data/program_PCD009_V0.9_V1.3.xlsx")
ROOT_RUNTIME_FILES = (
    Path("analog_sweep.py"),
    Path("main.py"),
    Path("console.py"),
    Path("fb_map.py"),
    Path("flow_recipe.py"),
    Path("pattern_bundle.py"),
)
SOURCE_TREES = (Path("program_gen"), Path("preflight"))
SEED_TREES = tuple(
    Path(platform) / seed
    for platform in ("Chroma_program", "S100_program")
    for seed in ("pat_temp", "fbist_pattern", "code")
)
EXTERNAL_COMPILERS = (
    Path(r"C:\CRAFT\bin\patcmp.exe"),
    Path(r"C:\CRAFT\bin\deccmp.exe"),
    Path(r"C:\CRAFT\bin\plncmp.exe"),
    Path("S100_Compiler/app/S100/YT5100_Pre.exe"),
)
IGNORED_PARTS = {"__pycache__", ".pytest_cache"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _selected_file(path: Path) -> bool:
    return (
        path.is_file()
        and not any(part in IGNORED_PARTS for part in path.parts)
        and path.suffix.casefold() not in IGNORED_SUFFIXES
    )


def _walk_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return ()
    return (path for path in sorted(root.rglob("*")) if _selected_file(path))


def selected_inputs(repo: Path) -> list[tuple[str, Path]]:
    selected: list[tuple[str, Path]] = []
    for relative in ROOT_RUNTIME_FILES:
        if (repo / relative).is_file():
            selected.append(("runtime_source", relative))
    for tree in SOURCE_TREES:
        for path in _walk_files(repo / tree):
            selected.append(("runtime_source", path.relative_to(repo)))
    for path in _walk_files(repo / "tests"):
        selected.append(("regression_test", path.relative_to(repo)))
    for path in _walk_files(repo / "tools"):
        selected.append(("validation_tool", path.relative_to(repo)))
    if (repo / FORMAL_MASTER).is_file():
        selected.append(("formal_workbook", FORMAL_MASTER))
    for tree in SEED_TREES:
        for path in _walk_files(repo / tree):
            selected.append(("seed_candidate", path.relative_to(repo)))
    return sorted(set(selected), key=lambda item: (item[0], item[1].as_posix()))


def git_output(repo: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, stdout=subprocess.PIPE
    ).stdout


def git_identity(repo: Path) -> dict[str, object]:
    branch = git_output(repo, "branch", "--show-current").decode().strip()
    head = git_output(repo, "rev-parse", "HEAD").decode().strip()
    raw_status = git_output(
        repo, "-c", "core.quotepath=false", "status", "--porcelain=v1", "-z", "-uall"
    )
    counts: dict[str, int] = {}
    status_by_path: dict[str, str] = {}
    records = raw_status.split(b"\0")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        status = record[:2].decode("ascii", "replace")
        path = record[3:].decode("utf-8", "surrogateescape").replace("\\", "/")
        counts[status] = counts.get(status, 0) + 1
        status_by_path[path] = status
        if "R" in status or "C" in status:
            index += 1
    return {
        "branch": branch,
        "head": head,
        "status_sha256": hashlib.sha256(raw_status).hexdigest().upper(),
        "status_counts": dict(sorted(counts.items())),
        "status_by_path": status_by_path,
    }


def aggregate_identity(entries: Iterable[dict[str, object]]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda item: (str(item["category"]), str(item["path"]))):
        digest.update(str(entry["category"]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(entry["path"]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(entry["size"]).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(entry["sha256"]).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest().upper()


def external_compiler_entries(repo: Path) -> list[dict[str, object]]:
    entries = []
    for configured in EXTERNAL_COMPILERS:
        path = configured if configured.is_absolute() else repo / configured
        item: dict[str, object] = {
            "configured_path": str(configured),
            "resolved_path": str(path.resolve()),
            "present": path.is_file(),
        }
        if path.is_file():
            stat = path.stat()
            item.update(size=stat.st_size, sha256=sha256_file(path))
        entries.append(item)
    return entries


def build_manifest(repo: Path) -> dict[str, object]:
    repo = repo.resolve()
    git = git_identity(repo)
    status_by_path = git.pop("status_by_path")
    entries: list[dict[str, object]] = []
    for category, relative in selected_inputs(repo):
        path = repo / relative
        entries.append(
            {
                "category": category,
                "path": relative.as_posix(),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
                "git_status": status_by_path.get(relative.as_posix(), "  "),
            }
        )
    category_counts: dict[str, int] = {}
    for entry in entries:
        category = str(entry["category"])
        category_counts[category] = category_counts.get(category, 0) + 1
    source_entries = [
        entry for entry in entries
        if entry["category"] in {"runtime_source", "regression_test", "validation_tool"}
    ]
    seed_entries = [entry for entry in entries if entry["category"] == "seed_candidate"]
    workbook_entries = [entry for entry in entries if entry["category"] == "formal_workbook"]
    category_identities = {
        category: aggregate_identity(
            entry for entry in entries if entry["category"] == category
        )
        for category in sorted(category_counts)
    }
    external = external_compiler_entries(repo)
    identity_material = {
        "source_snapshot_sha256": aggregate_identity(source_entries),
        "seed_snapshot_sha256": aggregate_identity(seed_entries),
        "workbook_snapshot_sha256": aggregate_identity(workbook_entries),
        "external_compilers": external,
    }
    baseline_id = hashlib.sha256(
        json.dumps(identity_material, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest().upper()
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "repo": str(repo),
        "python": sys.version,
        "git": git,
        "ownership_rules": {
            "authoritative_inputs": [
                "runtime_source", "regression_test", "validation_tool", "formal_workbook"
            ],
            "candidate_inputs_requiring_golden_proof": ["seed_candidate"],
            "excluded": [
                "generated Chroma/S100 product directories and LAB outputs",
                "golden/** and outputs/** evidence",
                ".Codex/** reports/cache/session data",
                "__pycache__ and Python bytecode",
                "backup, scratch, and temporary workbooks",
            ],
        },
        "category_counts": dict(sorted(category_counts.items())),
        "category_snapshot_sha256": category_identities,
        "source_snapshot_sha256": identity_material["source_snapshot_sha256"],
        "seed_snapshot_sha256": identity_material["seed_snapshot_sha256"],
        "workbook_snapshot_sha256": identity_material["workbook_snapshot_sha256"],
        "baseline_id": baseline_id,
        "external_compilers": external,
        "entries": entries,
    }


def create_snapshot(repo: Path, destination: Path, manifest: dict[str, object]) -> None:
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError(f"snapshot destination already exists: {destination}")
    destination.mkdir(parents=True)
    for entry in manifest["entries"]:
        relative = Path(str(entry["path"]))
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo / relative, target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--snapshot-dir", type=Path)
    args = parser.parse_args()

    manifest = build_manifest(args.repo)
    if args.snapshot_dir:
        create_snapshot(args.repo.resolve(), args.snapshot_dir, manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"baseline_id={manifest['baseline_id']}")
    print(f"source_snapshot_sha256={manifest['source_snapshot_sha256']}")
    print(
        "runtime_source_sha256="
        f"{manifest['category_snapshot_sha256']['runtime_source']}"
    )
    print(f"seed_snapshot_sha256={manifest['seed_snapshot_sha256']}")
    print(f"entries={len(manifest['entries'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
