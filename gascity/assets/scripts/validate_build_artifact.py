#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


FRONT_MATTER_RE = re.compile(r"\A---\n(?P<front>.*?)\n---(?:\n|\Z)(?P<body>.*)\Z", re.DOTALL)
SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "schemas" / "build"
FORBIDDEN_REQUIRED_FIELD_NAMES = {"owner", "stage-owner", "stage_owner", "persona", "role"}


class ValidationError(Exception):
    pass


YAML_ERROR_TYPES = (yaml.YAMLError,) if yaml is not None else ()
CLI_ERROR_TYPES = (OSError, UnicodeDecodeError, ValidationError) + YAML_ERROR_TYPES


@dataclass(frozen=True)
class BuildArtifact:
    schema_id: str
    front_matter: dict[str, Any]
    body: str
    upstream: list[dict[str, Any]]
    coverage: list[dict[str, Any]]


def validate_artifact_text(text: str, *, expected_schema: str = "") -> BuildArtifact:
    schema_id, front_matter, body = parse_front_matter(text)
    if expected_schema and schema_id != expected_schema:
        raise ValidationError(f"schema must be {expected_schema!r}, got {schema_id!r}")

    schema = load_schema(schema_id)
    validate_required_front_matter(front_matter, schema)
    validate_schema_contract(schema_id, front_matter)
    validate_status(front_matter, schema)
    trace = validate_trace(front_matter)
    upstream = validate_upstream(trace)
    coverage = validate_coverage(trace, schema)
    validate_coverage_completeness(upstream, coverage)
    validate_markdown_coverage(body, coverage)
    validate_required_sections(body, schema)
    return BuildArtifact(
        schema_id=schema_id,
        front_matter=front_matter,
        body=body,
        upstream=upstream,
        coverage=coverage,
    )


def parse_front_matter(text: str) -> tuple[str, dict[str, Any], str]:
    if yaml is None:
        raise ValidationError("PyYAML is required to parse build artifacts")
    match = FRONT_MATTER_RE.match(text)
    if not match:
        raise ValidationError("build artifact must start with YAML front matter")
    data = yaml.safe_load(match.group("front")) or {}
    if not isinstance(data, dict):
        raise ValidationError("build artifact front matter must be a mapping")
    schema_id = required_string(data, "schema")
    return schema_id, data, match.group("body")


def load_schema(schema_id: str) -> dict[str, Any]:
    if yaml is None:
        raise ValidationError("PyYAML is required to parse build schemas")
    for path in sorted(SCHEMA_ROOT.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(raw, dict) and raw.get("schema_id") == schema_id:
            validate_schema_definition(raw)
            return raw
    raise ValidationError(f"unknown build artifact schema {schema_id!r}")


def validate_schema_definition(schema: dict[str, Any]) -> None:
    schema_id = schema.get("schema_id", "<unknown>")
    fields = schema.get("required_front_matter", [])
    if not isinstance(fields, list):
        raise ValidationError(f"schema {schema_id}: required_front_matter must be a list")
    for field in fields:
        leaf = str(field).split(".")[-1].lower()
        if leaf in FORBIDDEN_REQUIRED_FIELD_NAMES:
            raise ValidationError(
                f"schema {schema_id}: base schemas must not require owner, stage-owner, persona, or role fields, got {field!r}"
            )


def validate_required_front_matter(front_matter: dict[str, Any], schema: dict[str, Any]) -> None:
    fields = schema.get("required_front_matter", [])
    if not isinstance(fields, list):
        raise ValidationError(f"schema {schema.get('schema_id', '<unknown>')}: required_front_matter must be a list")
    missing = [field for field in fields if get_path(front_matter, str(field)) is None]
    if missing:
        raise ValidationError(f"front matter missing required fields: {missing}")
    for field in fields:
        value = get_path(front_matter, str(field))
        if isinstance(value, str) and not value.strip():
            raise ValidationError(f"front matter field {field} must be non-empty")
    attempt = get_path(front_matter, "producer.attempt")
    if not isinstance(attempt, int) or attempt < 1:
        raise ValidationError("producer.attempt must be a positive integer")


def validate_schema_contract(schema_id: str, front_matter: dict[str, Any]) -> None:
    if schema_id == "gc.build.integration-manifest.v1":
        validate_integration_manifest(required_mapping(front_matter, "integration"))
    elif schema_id == "gc.build.integration-result.v1":
        validate_integration_result(required_mapping(front_matter, "integration"), front_matter)


def validate_integration_manifest(integration: dict[str, Any]) -> None:
    validate_absolute_path(required_string(integration, "repository"), "integration.repository")
    validate_absolute_path(required_string(integration, "artifact_root"), "integration.artifact_root")
    required_string(integration, "remote", prefix="integration")
    required_string(integration, "target_ref", prefix="integration")
    validate_git_sha(integration.get("base_sha"), "integration.base_sha")

    sources = integration.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValidationError("integration.sources must be a non-empty list")
    for index, source in enumerate(sources):
        prefix = f"integration.sources[{index}]"
        if not isinstance(source, dict):
            raise ValidationError(f"{prefix} must be a mapping")
        required_string(source, "bead_id", prefix=prefix)
        validate_git_sha(source.get("base_sha"), f"{prefix}.base_sha")
        validate_git_sha(source.get("result_sha"), f"{prefix}.result_sha")
        dependencies = source.get("dependencies")
        if not isinstance(dependencies, list) or not all(
            isinstance(item, str) and item.strip() for item in dependencies
        ):
            raise ValidationError(f"{prefix}.dependencies must be a list of non-empty strings")
        validate_absolute_path(required_string(source, "worktree", prefix=prefix), f"{prefix}.worktree")
        changed_paths = source.get("changed_paths")
        if not isinstance(changed_paths, list) or not all(
            isinstance(item, str) and item.strip() for item in changed_paths
        ):
            raise ValidationError(f"{prefix}.changed_paths must be a list of non-empty strings")
        summary = required_mapping(source, "summary", prefix=prefix)
        validate_absolute_path(required_string(summary, "path", prefix=f"{prefix}.summary"), f"{prefix}.summary.path")
        validate_hash(required_string(summary, "hash", prefix=f"{prefix}.summary"), f"{prefix}.summary.hash")

    topological_source_order(sources)
    validate_argv_list(integration.get("verification"), "integration.verification")


def validate_integration_result(integration: dict[str, Any], front_matter: dict[str, Any]) -> None:
    outcome = required_string(integration, "outcome", prefix="integration")
    if outcome not in {"ready", "needs_rework", "failed"}:
        raise ValidationError("integration.outcome must be ready, needs_rework, or failed")
    validate_absolute_path(required_string(integration, "manifest_path", prefix="integration"), "integration.manifest_path")
    validate_hash(required_string(integration, "manifest_hash", prefix="integration"), "integration.manifest_hash")
    validate_git_sha(integration.get("base_sha"), "integration.base_sha")
    validate_absolute_path(required_string(integration, "scratch_worktree", prefix="integration"), "integration.scratch_worktree")

    source_map = integration.get("source_map")
    if not isinstance(source_map, list) or not source_map:
        raise ValidationError("integration.source_map must be a non-empty list")
    seen: set[str] = set()
    for index, record in enumerate(source_map):
        prefix = f"integration.source_map[{index}]"
        if not isinstance(record, dict):
            raise ValidationError(f"{prefix} must be a mapping")
        bead_id = required_string(record, "bead_id", prefix=prefix)
        if bead_id in seen:
            raise ValidationError(f"{prefix}.bead_id duplicates {bead_id!r}")
        seen.add(bead_id)
        validate_git_sha(record.get("source_sha"), f"{prefix}.source_sha")
        validate_git_sha(record.get("integrated_sha"), f"{prefix}.integrated_sha")

    verification = integration.get("verification")
    if not isinstance(verification, list):
        raise ValidationError("integration.verification must be a list")
    for index, record in enumerate(verification):
        if not isinstance(record, dict):
            raise ValidationError(f"integration.verification[{index}] must be a mapping")
        validate_argv_list([record.get("argv")], f"integration.verification[{index}].argv")
        exit_code = record.get("exit_code")
        if not isinstance(exit_code, int) or isinstance(exit_code, bool):
            raise ValidationError(f"integration.verification[{index}].exit_code must be an integer")

    for field in ("push_performed", "pr_opened", "target_ref_updated"):
        if integration.get(field) is not False:
            raise ValidationError(f"integration.{field} must be false for a shadow integration result")

    if outcome == "ready":
        validate_git_sha(integration.get("candidate_sha"), "integration.candidate_sha")
        validate_git_sha(integration.get("tree_sha"), "integration.tree_sha")
        if any(record["exit_code"] != 0 for record in verification):
            raise ValidationError("ready integration.verification exit_code values must be zero")
    elif outcome == "needs_rework":
        conflicts = integration.get("conflict_paths")
        if not isinstance(conflicts, list) or not conflicts or not all(
            isinstance(item, str) and item.strip() for item in conflicts
        ):
            raise ValidationError("needs_rework integration.conflict_paths must be a non-empty list")
        validate_git_sha(integration.get("last_clean_candidate_sha"), "integration.last_clean_candidate_sha")
    elif not any(record["exit_code"] != 0 for record in verification):
        raise ValidationError("failed integration requires a non-zero exit_code")

    status = required_string(front_matter, "status")
    expected_status = "approved" if outcome == "ready" else "blocked"
    if status != expected_status:
        raise ValidationError(f"{outcome} integration result status must be {expected_status}")


def validate_git_sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise ValidationError(f"{field} must be a 40 lowercase hexadecimal Git SHA")
    return value


def validate_hash(value: str, field: str) -> str:
    if re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise ValidationError(f"{field} must be a sha256 hash")
    return value


def validate_absolute_path(value: str, field: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ValidationError(f"{field} must be an absolute path")
    return path


def validate_argv_list(value: Any, field: str) -> list[list[str]]:
    if not isinstance(value, list):
        raise ValidationError(f"{field} must be a list of argv lists")
    result: list[list[str]] = []
    for index, argv in enumerate(value):
        if not isinstance(argv, list) or not argv or not all(
            isinstance(item, str) and item for item in argv
        ):
            raise ValidationError(f"{field}[{index}] argv must be a non-empty list of strings")
        result.append(argv)
    return result


def topological_source_order(sources: list[dict[str, Any]]) -> list[str]:
    records: dict[str, list[str]] = {}
    manifest_order: list[str] = []
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            raise ValidationError(f"integration.sources[{index}] must be a mapping")
        bead_id = required_string(source, "bead_id", prefix=f"integration.sources[{index}]")
        if bead_id in records:
            raise ValidationError(f"integration.sources[{index}].bead_id duplicates {bead_id!r}")
        dependencies = source.get("dependencies")
        if not isinstance(dependencies, list) or not all(
            isinstance(item, str) and item.strip() for item in dependencies
        ):
            raise ValidationError(f"integration.sources[{index}].dependencies must be a list of non-empty strings")
        records[bead_id] = dependencies
        manifest_order.append(bead_id)

    known = set(records)
    for bead_id, dependencies in records.items():
        unknown = [dependency for dependency in dependencies if dependency not in known]
        if unknown:
            raise ValidationError(f"integration source {bead_id!r} has unknown dependency {unknown[0]!r}")

    ordered: list[str] = []
    completed: set[str] = set()
    while len(ordered) < len(records):
        ready = [
            bead_id
            for bead_id in manifest_order
            if bead_id not in completed and set(records[bead_id]).issubset(completed)
        ]
        if not ready:
            raise ValidationError("integration source dependency graph contains a cycle")
        for bead_id in ready:
            completed.add(bead_id)
            ordered.append(bead_id)
    return ordered


def required_mapping(data: dict[str, Any], key: str, *, prefix: str = "") -> dict[str, Any]:
    value = data.get(key)
    field = f"{prefix}.{key}" if prefix else key
    if not isinstance(value, dict):
        raise ValidationError(f"{field} must be a mapping")
    return value


def validate_status(front_matter: dict[str, Any], schema: dict[str, Any]) -> None:
    status = required_string(front_matter, "status")
    allowed = schema.get("allowed_statuses", [])
    if not isinstance(allowed, list) or not all(isinstance(item, str) for item in allowed):
        raise ValidationError(f"schema {schema.get('schema_id', '<unknown>')}: allowed_statuses must be strings")
    if status not in allowed:
        raise ValidationError(f"status must be one of {sorted(allowed)}, got {status!r}")


def validate_trace(front_matter: dict[str, Any]) -> dict[str, Any]:
    trace = front_matter.get("trace")
    if not isinstance(trace, dict):
        raise ValidationError("trace must be a mapping")
    if "upstream" not in trace:
        raise ValidationError("trace.upstream must be present")
    if "coverage" not in trace:
        raise ValidationError("trace.coverage must be present")
    if not isinstance(trace["upstream"], list):
        raise ValidationError("trace.upstream must be a list")
    if not isinstance(trace["coverage"], list):
        raise ValidationError("trace.coverage must be a list")
    return trace


def validate_upstream(trace: dict[str, Any]) -> list[dict[str, Any]]:
    upstream: list[dict[str, Any]] = []
    for index, raw in enumerate(trace["upstream"]):
        if not isinstance(raw, dict):
            raise ValidationError(f"trace.upstream[{index}] must be a mapping")
        path = required_string(raw, "path", prefix=f"trace.upstream[{index}]")
        hash_value = required_string(raw, "hash", prefix=f"trace.upstream[{index}]")
        validate_upstream_path(path, index)
        if ":" not in hash_value:
            raise ValidationError(f"trace.upstream[{index}].hash must include a hash or revision scheme")
        ids = raw.get("ids")
        if ids is not None:
            if not isinstance(ids, list) or not all(isinstance(item, str) and item.strip() for item in ids):
                raise ValidationError(f"trace.upstream[{index}].ids must be a list of non-empty strings")
        upstream.append(raw)
    return upstream


def validate_coverage_completeness(upstream: list[dict[str, Any]], coverage: list[dict[str, Any]]) -> None:
    covered_ids = {str(entry["id"]) for entry in coverage}
    missing = [
        item_id
        for entry in upstream
        for item_id in entry.get("ids") or []
        if str(item_id).strip() not in covered_ids
    ]
    if missing:
        raise ValidationError(f"coverage must account for every upstream ID, missing: {missing}")


def validate_upstream_path(path: str, index: int) -> None:
    parsed = Path(path)
    if not parsed.is_absolute() and ".." in parsed.parts:
        raise ValidationError(f"trace.upstream[{index}].path must not escape the artifact root")


def validate_coverage(trace: dict[str, Any], schema: dict[str, Any]) -> list[dict[str, Any]]:
    allowed = schema.get("coverage_statuses", [])
    if not isinstance(allowed, list) or not all(isinstance(item, str) for item in allowed):
        raise ValidationError(f"schema {schema.get('schema_id', '<unknown>')}: coverage_statuses must be strings")
    allowed_set = set(allowed)
    seen: set[str] = set()
    coverage: list[dict[str, Any]] = []
    for index, raw in enumerate(trace["coverage"]):
        if not isinstance(raw, dict):
            raise ValidationError(f"trace.coverage[{index}] must be a mapping")
        item_id = required_string(raw, "id", prefix=f"trace.coverage[{index}]")
        status = required_string(raw, "status", prefix=f"trace.coverage[{index}]")
        if item_id in seen:
            raise ValidationError(f"trace.coverage[{index}].id duplicates {item_id!r}")
        seen.add(item_id)
        if status not in allowed_set:
            raise ValidationError(f"trace.coverage[{index}].status must be one of {sorted(allowed_set)}, got {status!r}")
        if status != "covered":
            required_string(raw, "rationale", prefix=f"trace.coverage[{index}]")
        coverage.append(raw)
    return coverage


def validate_markdown_coverage(body: str, coverage: list[dict[str, Any]]) -> None:
    expected = {str(item["id"]): str(item["status"]) for item in coverage}
    if not expected:
        return
    actual = parse_markdown_coverage(body)
    if not actual:
        raise ValidationError("markdown coverage matrix is missing")
    if actual != expected:
        raise ValidationError(f"markdown coverage matrix must match YAML coverage, got {actual!r}, expected {expected!r}")


def parse_markdown_coverage(body: str) -> dict[str, str]:
    coverage: dict[str, str] = {}
    lines = body.splitlines()
    index = 0
    while index < len(lines):
        cells = split_table_row(lines[index])
        header = [cell.lower() for cell in cells]
        if header and "id" in header and "status" in header:
            id_index = header.index("id")
            status_index = header.index("status")
            index += 1
            if index < len(lines) and is_separator_row(lines[index]):
                index += 1
            while index < len(lines):
                row = split_table_row(lines[index])
                if not row or len(row) <= max(id_index, status_index):
                    break
                item_id = clean_table_cell(row[id_index])
                status = clean_table_cell(row[status_index])
                if item_id and status:
                    coverage[item_id] = status
                index += 1
            continue
        index += 1
    return coverage


def split_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return []
    return [clean_table_cell(cell) for cell in stripped.strip("|").split("|")]


def is_separator_row(line: str) -> bool:
    cells = split_table_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def clean_table_cell(value: str) -> str:
    return value.strip().strip("`").strip()


def validate_required_sections(body: str, schema: dict[str, Any]) -> None:
    required = schema.get("required_sections", [])
    if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
        raise ValidationError(f"schema {schema.get('schema_id', '<unknown>')}: required_sections must be strings")
    positions: list[tuple[str, int]] = []
    for section in required:
        match = re.search(rf"^##\s+{re.escape(section)}\s*$", body, re.MULTILINE)
        if not match:
            raise ValidationError(f"missing required body section {section!r}")
        positions.append((section, match.start()))
    for (left_name, left_pos), (right_name, right_pos) in zip(positions, positions[1:]):
        if left_pos >= right_pos:
            raise ValidationError(f"body section {left_name!r} must appear before {right_name!r}")


def required_string(data: dict[str, Any], key: str, *, prefix: str = "") -> str:
    value = data.get(key)
    field = f"{prefix}.{key}" if prefix else key
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be a non-empty string")
    return value.strip()


def get_path(data: dict[str, Any], dotted_path: str) -> Any:
    current: Any = data
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a gc build artifact")
    parser.add_argument("--schema", required=True, help="Expected schema id")
    parser.add_argument("--path", required=True, type=Path, help="Artifact markdown path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        artifact = validate_artifact_text(args.path.read_text(encoding="utf-8"), expected_schema=args.schema)
    except CLI_ERROR_TYPES as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "schema": artifact.schema_id}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
