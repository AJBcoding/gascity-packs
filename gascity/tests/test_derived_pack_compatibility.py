"""Derived-pack compatibility evidence for GC-METH-012.

Each test inspects all four concrete derived packs (compound-engineering,
superpowers, bmad, gstack) and asserts one face of the external implementation
compatibility contract: import-as-`gc`, anchored `build-base` extension,
methodology metadata vocabulary, selector defaults, drain or convoy-step
strategy, providerless route targets, the shared claim protocol, the absence
of provider-native subagent dispatch, and the pack-local compatibility
ledgers. The matching ledger rows live in `gascity/REQUIREMENTS.md`
(GC-METH-012) and each pack's `REQUIREMENTS.md`.
`ShippedStampGuardAnalyzerTests` additionally unit-tests the shipped-stamp
analyzer itself against inline command spellings, resolves `@file` metadata
payloads, sweeps every Markdown asset in the repository for false positives,
and proves the analyzer fails its own table when any decoding stage is
weakened.
"""

from __future__ import annotations

import json
import pathlib
import re
import shlex
import sys
import tempfile
import tomllib
import typing
import unittest
from unittest import mock

import test_formula_assets as base_contract


PACKS_ROOT = pathlib.Path(__file__).resolve().parents[2]
GASCITY_ROOT = PACKS_ROOT / "gascity"

DERIVED_PACKS = base_contract.THIRD_PARTY_BUILD_PACKS
BUILD_BASE_ANCHORS = base_contract.BUILD_BASE_STEPS

CLAIM_PROTOCOL_INCLUDE = '{{ template "gc-role-worker" . }}'
PUBLIC_CLAIM_FRAGMENT = (
    GASCITY_ROOT / "template-fragments" / "gc-role-worker.template.md"
)

# Pack-local prompt surfaces that the factory actually executes. Vendored
# upstream trees under vendor/ are methodology source material, not prompts.
PROMPT_ASSET_DIRS = ("assets/workflows", "agents", "template-fragments")

# Active provider-native delegation markers. Guard sentences such as "Do not
# invoke provider-native subagents" are required, so the forbidden list only
# contains phrases that instruct a model to dispatch work natively.
FORBIDDEN_DISPATCH_PHRASES = (
    "also use `{{pack_root}}/vendor/superpowers/skills/subagent-driven-development/SKILL.md`",
    "Hand `{spec_file}` to a sub-agent/task and let it implement",
    "Dispatch implementer subagent",
    "Task tool (general-purpose):",
    "{{pack_root}}/vendor",
    "{{pack_root}}/assets/scripts",
    "/SKILL.md",
    "Launch or reuse",
    "base `implement` formula",
    "read vendored files by path",
    "formula expansion is required",
    "formula already created",
)

NATIVE_DISPATCH_GUARD = "Do not invoke provider-native subagents"

# Every pack ledger must anchor the GC-METH-012 evidence chain explicitly.
LEDGER_REQUIRED_FRAGMENTS = (
    "GC-METH-012",
    "## Compatibility Claims",
    "## Evidence Commands",
    "../gascity",
    "build-base",
    "gc.delivery_state=integration_ready",
    "gc.work_outcome=shipped",
)

IMPLEMENTATION_PROVENANCE_ASSETS = {
    "compound-engineering": {
        "assets/workflows/compound-work/implement.md": ("gc.work_base_commit", "gc.work_commit"),
        "assets/workflows/compound-work-item/implement-item.md": ("gc.work_base_commit", "gc.work_commit"),
    },
    "superpowers": {
        "assets/workflows/superpowers-development/implement-item.md": ("gc.work_base_commit",),
        "assets/workflows/superpowers-development/record-item-result.md": ("gc.work_commit",),
    },
    "bmad": {
        "assets/workflows/bmad-story-development/implement.md": ("gc.work_base_commit", "gc.work_commit"),
        "assets/workflows/bmad-story-development/implement-item.md": ("gc.work_base_commit", "gc.work_commit"),
    },
    "gstack": {
        "assets/workflows/gstack-work/implement.md": ("gc.work_base_commit", "gc.work_commit"),
        "assets/workflows/gstack-work-item/implement-item.md": ("gc.work_base_commit", "gc.work_commit"),
    },
}

IMPLEMENTATION_LIFECYCLE_ASSETS = {
    "compound-engineering": (
        "assets/workflows/compound-work/implement.md",
        "assets/workflows/compound-work-item/implement-item.md",
    ),
    "superpowers": (
        "assets/workflows/superpowers-development/implement.md",
        "assets/workflows/superpowers-development/implement-item.md",
        "assets/workflows/superpowers-development/record-item-result.md",
        "assets/workflows/superpowers-development/close-source-anchor.md",
    ),
    "bmad": (
        "assets/workflows/bmad-story-development/implement.md",
        "assets/workflows/bmad-story-development/implement-item.md",
    ),
    "gstack": (
        "assets/workflows/gstack-work/implement.md",
        "assets/workflows/gstack-work-item/implement-item.md",
    ),
}

# ---------------------------------------------------------------------------
# Shipped-stamp guard: a bounded command/payload analyzer.
#
# bd exposes exactly two metadata write flags and no short forms for either
# (`bd update --help`, `bd create --help`; `bd close` has no metadata flag):
# `--set-metadata key=value` and `--metadata <JSON object | @file.json>`.
# Both accept `--flag value` and `--flag=value`.
#
# Matching raw source text cannot decide this question, because a shell and a
# JSON decoder both rewrite the text before bd ever sees it:
# `gc.work_"outcome"=shipped`, `$'gc.work_outcome=shipped'` and
# `{"gc.work_outcome":"shipped"}` are three spellings of one argument.
# So the guard reconstructs the argument instead of grepping for it: it
# extracts bounded command regions from the Markdown, normalizes shell
# quoting, tokenizes with `shlex`, decodes payloads with `json`, and compares
# the decoded key and value exactly.
#
# It is deliberately NOT a shell. It performs no expansion, no substitution,
# no redirection, no control flow, and no word splitting beyond `shlex`.
# Anything it cannot decode to an exact literal -- a `$`/backtick-dynamic
# key, an unparseable payload, an unresolvable `@file` -- is reported as
# "unresolvable" and fails the guard closed rather than being cleared.
FORBIDDEN_STAMP_KEY = "gc.work_outcome"
FORBIDDEN_STAMP_VALUE = "shipped"

# Exact flag tokens. Comparison is by whole token, so the read-side filter
# `--metadata-field` is a different token and is never treated as a write.
METADATA_WRITE_FLAGS = ("--set-metadata", "--metadata")

# A physical line continuation is erased by the shell before word splitting.
# `shlex` does NOT do this -- it emits a literal "\n" token -- so the guard
# normalizes continuations itself before tokenizing.
_LINE_CONTINUATION = re.compile(r"\\\r?\n")

# Markdown structure. Commands in these assets live in fenced code blocks and
# in inline code spans; surrounding prose is not a command. Spans are matched
# per paragraph, not per line, because a real asset splits one span across a
# line break (gascity/assets/workflows/build-base/prepare.md).
_CODE_FENCE = re.compile(r"^[ \t]{0,3}(?:`{3,}|~{3,})")
_CODE_SPAN = re.compile(r"(`+)([^`][\s\S]*?)\1")

# Only tokenize regions that mention a metadata flag at all.
_METADATA_FLAG_HINT = re.compile(r"--(?:set-)?metadata\b")

# Shell constructs whose value is decided at runtime, not in the asset.
_SHELL_DYNAMIC = re.compile(r"[$`]")

# ANSI-C quoting, $'...'. `shlex` does not implement it (it yields a literal
# "$" glued to the quoted body), so the guard decodes the body itself and
# re-emits it through `shlex.quote` as an ordinary POSIX-quoted token. That
# keeps adjacent-token concatenation intact and lets `shlex` do the splitting.
_ANSI_C_QUOTED = re.compile(r"\$'((?:[^'\\]|\\.)*)'", re.DOTALL)
_ANSI_C_ESCAPES = {
    "a": "\a", "b": "\b", "e": "\x1b", "E": "\x1b", "f": "\f",
    "n": "\n", "r": "\r", "t": "\t", "v": "\v",
    "\\": "\\", "'": "'", '"': '"', "?": "?",
}


class MetadataFinding(typing.NamedTuple):
    """One decoded metadata write the guard has an opinion about.

    kind is "unsafe" (the decoded argument is exactly the forbidden stamp) or
    "unresolvable" (the guard could not decode the argument, so it cannot
    clear it). Both fail the lifecycle guard; only "unsafe" is a positive
    detection, which is what the repo-wide false-positive sweep counts.
    """

    kind: str
    detail: str


def _decode_ansi_c_body(body: str) -> str:
    """Decode the escape sequences bash expands inside $'...'."""
    decoded: list[str] = []
    index = 0
    while index < len(body):
        char = body[index]
        if char != "\\" or index + 1 >= len(body):
            decoded.append(char)
            index += 1
            continue
        escape = body[index + 1]
        if escape in _ANSI_C_ESCAPES:
            decoded.append(_ANSI_C_ESCAPES[escape])
            index += 2
        elif escape in ("x", "u", "U"):
            width = {"x": 2, "u": 4, "U": 8}[escape]
            digits = ""
            cursor = index + 2
            while (
                cursor < len(body)
                and len(digits) < width
                and body[cursor] in "0123456789abcdefABCDEF"
            ):
                digits += body[cursor]
                cursor += 1
            if digits:
                decoded.append(chr(int(digits, 16)))
                index = cursor
            else:
                decoded.append(escape)
                index += 2
        elif escape in "01234567":
            digits = ""
            cursor = index + 1
            while cursor < len(body) and len(digits) < 3 and body[cursor] in "01234567":
                digits += body[cursor]
                cursor += 1
            decoded.append(chr(int(digits, 8)))
            index = cursor
        else:
            decoded.append(escape)
            index += 2
    return "".join(decoded)


def normalize_line_continuations(text: str) -> str:
    """Erase backslash-newline the way the shell does before word splitting."""
    return _LINE_CONTINUATION.sub(" ", text)


def normalize_ansi_c_quoting(region: str) -> str:
    """Rewrite $'...' into an equivalent plain POSIX-quoted token."""
    return _ANSI_C_QUOTED.sub(
        lambda match: shlex.quote(_decode_ansi_c_body(match.group(1))), region
    )


def command_regions(text: str) -> list[str]:
    """Bounded command regions of a Markdown asset.

    A fenced code block is one region (so a quoted payload may span lines).
    Outside fences, each inline code span in a paragraph is a region; a
    paragraph with no span at all is treated as one region, which is how a
    bare command block or a self-test spelling is analyzed.
    """
    regions: list[str] = []
    fenced = False
    block: list[str] = []
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if not paragraph:
            return
        text_block = "\n".join(paragraph)
        paragraph.clear()
        spans = [match.group(2) for match in _CODE_SPAN.finditer(text_block)]
        regions.extend(spans if spans else [text_block])

    for line in normalize_line_continuations(text).split("\n"):
        if _CODE_FENCE.match(line):
            flush_paragraph()
            if fenced:
                regions.append("\n".join(block))
            block.clear()
            fenced = not fenced
        elif fenced:
            block.append(line)
        elif line.strip():
            paragraph.append(line)
        else:
            flush_paragraph()
    flush_paragraph()
    if block:
        regions.append("\n".join(block))
    return regions


def shell_tokens(region: str) -> list[str] | None:
    """Split a region into shell words, or None if it is not well formed."""
    try:
        return shlex.split(normalize_ansi_c_quoting(region), comments=False, posix=True)
    except ValueError:
        return None


def _decoded_object_findings(payload: object, where: str) -> list[MetadataFinding]:
    """Judge a decoded JSON metadata object by its top-level keys.

    bd stamps the object's top-level keys, so only those are compared; a
    nested `{"evidence": {"gc.work_outcome": "shipped"}}` sets no such key.
    """
    if not isinstance(payload, dict):
        return [MetadataFinding("unresolvable", f"{where}: payload is not a JSON object")]
    findings: list[MetadataFinding] = []
    for key, value in payload.items():
        if not isinstance(key, str):
            findings.append(MetadataFinding("unresolvable", f"{where}: non-string key"))
        elif key == FORBIDDEN_STAMP_KEY:
            if value == FORBIDDEN_STAMP_VALUE:
                findings.append(
                    MetadataFinding("unsafe", f"{where}: decoded {key}={value}")
                )
            elif isinstance(value, str) and _SHELL_DYNAMIC.search(value):
                findings.append(
                    MetadataFinding("unresolvable", f"{where}: dynamic value for {key!r}")
                )
        elif _SHELL_DYNAMIC.search(key):
            # The key itself is decided at runtime, so it may expand to the
            # forbidden one. Reported only if no exact detection was made.
            findings.append(
                MetadataFinding("unresolvable", f"{where}: dynamic key {key!r}")
            )
    unsafe = [finding for finding in findings if finding.kind == "unsafe"]
    return unsafe or findings[:1]


def _resolve_metadata_file(reference: str, asset_dir: pathlib.Path) -> pathlib.Path | None:
    """Resolve a literal repo-local `@file` payload, or None if it is not one."""
    if not reference or reference.startswith("/") or _SHELL_DYNAMIC.search(reference):
        return None
    if ".." in pathlib.PurePosixPath(reference).parts:
        return None
    for candidate in (asset_dir / reference, PACKS_ROOT / reference):
        if candidate.is_file():
            return candidate
    return None


def decode_metadata_payload(
    payload: str, asset_dir: pathlib.Path, where: str
) -> list[MetadataFinding]:
    """Decode one metadata argument and judge it, or report it unresolvable."""
    if payload.startswith("@"):
        resolved = _resolve_metadata_file(payload[1:], asset_dir)
        if resolved is None:
            return [MetadataFinding("unresolvable", f"{where}: unresolved {payload}")]
        try:
            return _decoded_object_findings(
                json.loads(resolved.read_text(encoding="utf-8")), f"{where} {payload}"
            )
        except (ValueError, OSError):
            return [MetadataFinding("unresolvable", f"{where}: undecodable {payload}")]
    stripped = payload.strip()
    if stripped.startswith("{"):
        try:
            return _decoded_object_findings(json.loads(stripped), where)
        except ValueError:
            return [MetadataFinding("unresolvable", f"{where}: undecodable JSON {payload!r}")]
    key, separator, value = payload.partition("=")
    if not separator:
        return [MetadataFinding("unresolvable", f"{where}: uninterpretable payload {payload!r}")]
    if _SHELL_DYNAMIC.search(key):
        return [MetadataFinding("unresolvable", f"{where}: dynamic key in {payload!r}")]
    if key != FORBIDDEN_STAMP_KEY:
        # A literal key that is not the forbidden one cannot stamp it, however
        # its value is spelled -- so a dynamic value here is not a finding.
        return []
    if value == FORBIDDEN_STAMP_VALUE:
        return [MetadataFinding("unsafe", f"{where}: {payload!r}")]
    if _SHELL_DYNAMIC.search(value):
        return [MetadataFinding("unresolvable", f"{where}: dynamic value in {payload!r}")]
    return []


def shipped_stamp_findings(
    text: str, asset_dir: pathlib.Path | None = None
) -> list[MetadataFinding]:
    """Every metadata write in `text` the guard rejects, unsafe or undecodable."""
    directory = asset_dir if asset_dir is not None else PACKS_ROOT
    findings: list[MetadataFinding] = []
    for region in command_regions(text):
        if not _METADATA_FLAG_HINT.search(region):
            continue
        tokens = shell_tokens(region)
        if tokens is None:
            findings.append(
                MetadataFinding("unresolvable", f"untokenizable region: {region.strip()[:80]!r}")
            )
            continue
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if token in METADATA_WRITE_FLAGS:
                following = tokens[index + 1] if index + 1 < len(tokens) else None
                if following is not None and not following.startswith("-"):
                    findings.extend(decode_metadata_payload(following, directory, token))
                    index += 2
                    continue
                # A trailing flag carries no payload, so it stamps nothing.
                index += 1
                continue
            for flag in METADATA_WRITE_FLAGS:
                if token.startswith(flag + "="):
                    findings.extend(
                        decode_metadata_payload(token[len(flag) + 1:], directory, flag)
                    )
                    break
            index += 1
    return findings


def unsafe_shipped_stamp_findings(
    text: str, asset_dir: pathlib.Path | None = None
) -> list[MetadataFinding]:
    """Only the positive detections, for the repo-wide false-positive sweep."""
    return [f for f in shipped_stamp_findings(text, asset_dir) if f.kind == "unsafe"]


# Exercised by ShippedStampGuardAnalyzerTests: command spellings the guard must
# reject, each with the verdict it must reach. "unsafe" means the analyzer
# decoded the exact forbidden argument; "unresolvable" means it could not
# decode the payload and therefore fails closed. Asserting the verdict, not
# merely "rejected", is what keeps each decoding stage load-bearing.
UNSAFE_SHIPPED_STAMP_SPELLINGS = (
    # -- key=value payloads, every quoting and separator variant ------------
    ("unsafe", "gc bd update gc-123 --set-metadata gc.work_outcome=shipped"),
    ("unsafe", "gc bd update gc-123 --set-metadata 'gc.work_outcome=shipped'"),
    ("unsafe", 'gc bd update gc-123 --set-metadata "gc.work_outcome=shipped"'),
    ("unsafe", "gc bd update gc-123 --set-metadata=gc.work_outcome=shipped"),
    ("unsafe", "gc bd update gc-123 --set-metadata='gc.work_outcome=shipped'"),
    ("unsafe", 'gc bd update gc-123 --set-metadata="gc.work_outcome=shipped"'),
    ("unsafe", "gc bd update gc-123 --set-metadata gc.work_outcome='shipped'"),
    ("unsafe", 'gc bd update gc-123 --set-metadata gc.work_outcome="shipped"'),
    ("unsafe", "gc bd update gc-123 --set-metadata\tgc.work_outcome=shipped"),
    ("unsafe", "gc bd update gc-123 --set-metadata  gc.work_outcome=shipped"),
    ("unsafe", "gc bd update gc-123 \\\n  --set-metadata \\\n  gc.work_outcome=shipped"),
    ("unsafe", "gc bd update gc-123 --metadata gc.work_outcome=shipped"),
    # -- whole-object JSON payloads -----------------------------------------
    ("unsafe", 'gc bd update gc-123 --metadata \'{"gc.work_outcome": "shipped"}\''),
    ("unsafe", 'gc bd update gc-123 --metadata \'{"gc.work_outcome":"shipped"}\''),
    ("unsafe", 'gc bd update gc-123 --metadata=\'{"gc.work_outcome": "shipped"}\''),
    ("unsafe", 'gc bd update gc-123 --metadata "{\\"gc.work_outcome\\": \\"shipped\\"}"'),
    ("unsafe", 'gc bd update gc-123 --metadata \'{ "gc.work_outcome" : "shipped" }\''),
    (
        "unsafe",
        "gc bd update gc-123 --metadata '{\"gc.delivery_state\": "
        "\"integration_ready\", \"gc.work_outcome\": \"shipped\"}'",
    ),
    (
        "unsafe",
        "gc bd update gc-123 --metadata '{\"evidence\": {\"tests\": \"pass\"}, "
        "\"gc.work_outcome\": \"shipped\"}'",
    ),
    ("unsafe", "gc bd update gc-123 --metadata '{\n  \"gc.work_outcome\": \"shipped\"\n}'"),
    # Not valid JSON, so the guard cannot clear the payload and fails closed.
    ("unresolvable", "gc bd update gc-123 --metadata '{gc.work_outcome: shipped}'"),
    # -- @file payloads ------------------------------------------------------
    # The heredoc writes the file at runtime, so no repo-local literal exists
    # to inspect; the guard must fail closed on the reference itself and not
    # on the co-located JSON text, which it never reads as a command.
    (
        "unresolvable",
        "cat > stamp.json <<'EOF'\n"
        '{"gc.work_outcome": "shipped"}\n'
        "EOF\n"
        "gc bd update gc-123 --metadata @stamp.json",
    ),
    # -- gas-ftv4 review findings: arguments a shell/JSON decoder produces ---
    # Shell quote splicing: the shell concatenates the fragments back into the
    # exact forbidden argument, so raw-text matching never sees it.
    ("unsafe", 'gc bd update gc-123 --set-metadata gc.work_"outcome"=shipped'),
    ("unsafe", 'gc bd update gc-123 --set-metadata gc.work_outcome=ship"ped"'),
    # ANSI-C quoting, which shlex does not implement.
    ("unsafe", "gc bd update gc-123 --set-metadata $'gc.work_outcome=shipped'"),
    # JSON \u escapes in the key and in the value.
    ("unsafe", 'gc bd update gc-123 --metadata \'{"gc.work_\\u006futcome":"shipped"}\''),
    ("unsafe", 'gc bd update gc-123 --metadata \'{"gc.work_outcome":"shi\\u0070ped"}\''),
    # A bare @file reference carrying no inline JSON at all.
    ("unresolvable", "gc bd update gc-123 --metadata @stamp.json"),
)

# Further spellings the analyzer rejects. Kept separate from the review table
# above so that table stays the exact gas-ftv4 evidence set; these lock in the
# coverage the decoding stages give for free, so a later simplification that
# quietly drops one is caught here.
ADDITIONAL_UNSAFE_SHIPPED_STAMP_SPELLINGS = (
    # ANSI-C hex and octal escapes decoding to the forbidden value.
    ("unsafe", "gc bd update gc-123 --set-metadata $'gc.work_outcome=shi\\x70ped'"),
    ("unsafe", "gc bd update gc-123 --set-metadata $'gc.work_outcome=shi\\160ped'"),
    # ANSI-C quoting used for only one fragment of a spliced argument.
    ("unsafe", "gc bd update gc-123 --set-metadata gc.work_$'outcome'=shipped"),
    # Backslash escaping and alternating quote styles inside one argument.
    ("unsafe", "gc bd update gc-123 --set-metadata gc.work_\\outcome=shipped"),
    ("unsafe", "gc bd update gc-123 --set-metadata 'gc.work_'\"outcome\"'=ship'ped"),
    # A JSON object handed to the key=value flag: same intent, so same verdict.
    ("unsafe", 'gc bd update gc-123 --set-metadata \'{"gc.work_outcome":"shipped"}\''),
    # A fenced block that is never closed is still analyzed.
    ("unsafe", "```bash\ngc bd update gc-123 --set-metadata gc.work_outcome=shipped"),
    # A Markdown table cell is an inline code span like any other.
    (
        "unsafe",
        "| stamp | `gc bd update gc-123 --set-metadata gc.work_outcome=shipped` |",
    ),
)

# Exercised by ShippedStampGuardAnalyzerTests: spellings from real assets and
# ledgers the guard must keep legal. The first two are required verbatim by
# the positive assertions and the ledger fragment list. The rest are the
# over-matching hazards decoding introduces: near-miss keys and values, the
# read-side filters, prose that names the flags, and the forbidden pair
# appearing somewhere that does not stamp a top-level key.
SAFE_SHIPPED_PROSE_SPELLINGS = (
    "Leave the source anchor open. Never set `gc.work_outcome=shipped` "
    "from a passing test or task review.",
    "Only a later exact-record transition may request shipped after "
    "portable\npost-landing stamping succeeds.",
    "gc.work_outcome=shipped",
    "gc bd update <id> --set-metadata gc.delivery_state=integration_ready",
    "gc bd list --metadata-field gc.work_outcome=shipped --status=closed",
    # Read-side filters, both separator spellings, are not writes.
    "gc bd list --metadata-field=gc.work_outcome=shipped",
    'gc bd list --all --metadata-field "gc.work_outcome=shipped" --json',
    # Prose naming the flags, verbatim from the base workflow assets.
    "Do not pass `--metadata` or `--set-metadata` to `gc bd close`.",
    # Near-miss keys: a superstring, a prefixed key, and a different key.
    "gc bd update <id> --set-metadata gc.work_outcome_note=shipped",
    "gc bd update <id> --set-metadata pack.gc.work_outcome=shipped",
    "gc bd update <id> --set-metadata gc.delivery_state=shipped",
    # Near-miss values: a superstring and a prefixed value.
    "gc bd update <id> --set-metadata gc.work_outcome=shipped-after-landing",
    "gc bd update <id> --set-metadata gc.work_outcome=not-shipped",
    "gc bd update <id> --set-metadata gc.work_outcome=integration_ready",
    # The forbidden pair as JSON, but not as a top-level stamped key.
    'gc bd update <id> --metadata \'{"evidence": {"gc.work_outcome": "shipped"}}\'',
    'gc bd update <id> --metadata \'{"note": "never gc.work_outcome=shipped"}\'',
    # A real JSON metadata write from gastown/agents/deacon/prompt.template.md.
    "gc bd create --type=task --metadata "
    '\'{"target":"<session>","reason":"<reason>","requester":"deacon"}\'',
    # A literal key that is not the forbidden one, with a runtime value.
    "gc bd update <id> --set-metadata gc.github.review_report_path=$REPORT_PATH",
    # A double-backtick span naming the flag is still only prose.
    "Use ``--metadata`` and ``--set-metadata`` only on the integration record.",
    # A read-side filter in a Markdown table cell.
    "| audit | `gc bd list --metadata-field gc.work_outcome=shipped --json` |",
    # The forbidden pair nested inside a JSON list value stamps no top-level key.
    'gc bd update <id> --metadata \'{"history": [{"gc.work_outcome": "shipped"}]}\'',
)


def pack_formula_dirs(pack_name: str) -> list[pathlib.Path]:
    return [GASCITY_ROOT / "formulas", PACKS_ROOT / pack_name / "formulas"]


def resolved_build_formula(pack_name: str, expected: dict) -> dict:
    return base_contract.resolve_formula_from_dirs(
        pack_formula_dirs(pack_name),
        expected["formula"],
    )


def expansion_default_vars(formula: dict) -> dict[str, str]:
    defaults: dict[str, str] = {}
    for name, definition in formula.get("vars", {}).items():
        if isinstance(definition, dict) and "default" in definition:
            defaults[name] = definition["default"]
    return defaults


def render_expansion_placeholders(value: str, variables: dict[str, str]) -> str:
    for name, variable_value in variables.items():
        value = value.replace(f"{{{name}}}", variable_value)
    return value


def artifact_validation_node(pack_name: str, step: dict) -> dict:
    if "check" in step:
        return step
    expansion = step.get("expand")
    if not expansion:
        return step

    formula = base_contract.resolve_formula_from_dirs(
        pack_formula_dirs(pack_name),
        expansion,
    )
    terminal = next(
        (
            template
            for template in formula.get("template", [])
            if template.get("id") == "{target}"
        ),
        None,
    )
    if terminal is None:
        return step

    variables = expansion_default_vars(formula)
    variables.update(step.get("expand_vars", {}))
    rendered = dict(terminal)
    metadata = dict(terminal.get("metadata", {}))
    rendered["metadata"] = {
        key: render_expansion_placeholders(value, variables)
        for key, value in metadata.items()
    }
    return rendered


def pack_methodology_metadata(pack_name: str, expected: dict) -> dict:
    data = base_contract.load_formula(PACKS_ROOT / pack_name, expected["formula"])
    methodology = data.get("metadata", {}).get("gc", {}).get("methodology")
    if methodology is None:
        raise AssertionError(
            f"{expected['formula']} must declare [metadata.gc.methodology]"
        )
    return methodology


class DerivedPackCompatibilityTests(unittest.TestCase):
    def test_gstack_publish_override_preserves_verified_landing_boundary(self) -> None:
        text = (PACKS_ROOT / "gstack/assets/workflows/gstack-build/publish.md").read_text(encoding="utf-8")
        for fragment in (
            "gc.build.integration_result_path",
            ".gc/scripts/record_landing.py record-direct",
            "gc.build.landing_status=landed",
            "gc.build.landing_status=pending_external_merge",
            "Opening a PR is published, not landed",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, text)

    maxDiff = None

    def test_implementation_overrides_record_source_commit_provenance(self) -> None:
        for pack_name, assets in IMPLEMENTATION_PROVENANCE_ASSETS.items():
            for relative_path, required_fragments in assets.items():
                with self.subTest(pack=pack_name, asset=relative_path):
                    text = (PACKS_ROOT / pack_name / relative_path).read_text(encoding="utf-8")
                    for fragment in required_fragments:
                        self.assertIn(fragment, text)
                    self.assertIn("source-worktree", text)

    def test_implementation_overrides_submit_open_work_for_integration(self) -> None:
        """A methodology override may finish its control step, but it may not
        turn a tested source commit into a branch-only shipped close."""
        for pack_name, relative_paths in IMPLEMENTATION_LIFECYCLE_ASSETS.items():
            for relative_path in relative_paths:
                with self.subTest(pack=pack_name, asset=relative_path):
                    asset = PACKS_ROOT / pack_name / relative_path
                    text = asset.read_text(encoding="utf-8")
                    self.assertIn("gc.work_commit", text)
                    self.assertIn("gc.delivery_state=integration_ready", text)
                    self.assertIn("Leave the source anchor open", text)
                    self.assertIn("Never set `gc.work_outcome=shipped`", text)
                    # Fail closed: an unsafe decoded stamp and a payload the
                    # analyzer cannot decode are both rejected here. No safe
                    # case is carved out, because none of these ten assets
                    # issues a metadata write at all.
                    self.assertEqual([], shipped_stamp_findings(text, asset.parent))
                    self.assertNotIn("close only the source anchor", text.lower())

    def test_packs_import_gascity_base_as_gc(self) -> None:
        for pack_name, expected in DERIVED_PACKS.items():
            with self.subTest(pack=pack_name):
                pack_data = tomllib.loads(
                    (PACKS_ROOT / pack_name / "pack.toml").read_text(encoding="utf-8")
                )
                self.assertEqual(pack_data["pack"]["name"], pack_name)
                self.assertEqual(expected["base_import_binding"], "gc")
                base_import = pack_data["imports"]["gc"]
                self.assertEqual(base_import["source"], "../gascity")

    def test_build_formulas_extend_build_base_with_anchors_in_order(self) -> None:
        for pack_name, expected in DERIVED_PACKS.items():
            with self.subTest(pack=pack_name):
                raw = base_contract.load_formula(
                    PACKS_ROOT / pack_name, expected["formula"]
                )
                self.assertEqual(raw["extends"], ["build-base"])

                resolved = resolved_build_formula(pack_name, expected)
                step_ids = [step["id"] for step in resolved["steps"]]
                self.assertEqual(
                    len(step_ids),
                    len(set(step_ids)),
                    f"{expected['formula']} resolves duplicate step ids",
                )
                previous_index = -1
                for anchor in BUILD_BASE_ANCHORS:
                    with self.subTest(pack=pack_name, anchor=anchor):
                        self.assertIn(
                            anchor,
                            step_ids,
                            f"{expected['formula']} drops base anchor {anchor!r}",
                        )
                        anchor_index = step_ids.index(anchor)
                        self.assertGreater(
                            anchor_index,
                            previous_index,
                            f"{expected['formula']} reorders base anchor {anchor!r}",
                        )
                        previous_index = anchor_index

    def test_build_formulas_declare_methodology_metadata_with_allowed_vocabulary(
        self,
    ) -> None:
        vocabulary = base_contract.METHODOLOGY_METADATA_VOCABULARY
        for pack_name, expected in DERIVED_PACKS.items():
            with self.subTest(pack=pack_name):
                methodology = pack_methodology_metadata(pack_name, expected)
                unknown_keys = set(methodology) - set(vocabulary)
                self.assertFalse(
                    unknown_keys,
                    f"unknown methodology metadata keys: {sorted(unknown_keys)}",
                )
                strategy = methodology.get("implementation_strategy")
                self.assertIn(strategy, vocabulary["implementation_strategy"])
                drain_policies = methodology.get("allowed_drain_policies", [])
                self.assertLessEqual(
                    set(drain_policies),
                    vocabulary["allowed_drain_policies"],
                )
                if strategy != "convoy-step":
                    self.assertTrue(
                        drain_policies,
                        "allowed_drain_policies may be empty only when "
                        'implementation_strategy = "convoy-step"',
                    )
                interaction_modes = methodology.get("interaction_modes", [])
                self.assertTrue(interaction_modes)
                self.assertLessEqual(
                    set(interaction_modes),
                    vocabulary["interaction_modes"],
                )
                review_modes = methodology.get("review_modes", [])
                self.assertTrue(review_modes)
                self.assertLessEqual(set(review_modes), vocabulary["review_modes"])

    def test_build_formulas_pin_methodology_selector_defaults(self) -> None:
        for pack_name, expected in DERIVED_PACKS.items():
            resolved = resolved_build_formula(pack_name, expected)
            selector_defaults = base_contract.methodology_selector_defaults(expected)
            for var_name, default in selector_defaults.items():
                with self.subTest(pack=pack_name, selector=var_name):
                    self.assertIn(var_name, resolved["vars"])
                    self.assertEqual(resolved["vars"][var_name]["default"], default)
                    formula_path = (
                        PACKS_ROOT
                        / pack_name
                        / "formulas"
                        / f"{default}.formula.toml"
                    )
                    self.assertTrue(
                        formula_path.is_file(),
                        f"selector default {default!r} must be a pack-local formula",
                    )
                    # The default must resolve through the layered formula dirs.
                    base_contract.resolve_formula_from_dirs(
                        pack_formula_dirs(pack_name), default
                    )

    def test_build_formulas_define_drain_policies_or_convoy_step_strategy(
        self,
    ) -> None:
        for pack_name, expected in DERIVED_PACKS.items():
            with self.subTest(pack=pack_name):
                methodology = pack_methodology_metadata(pack_name, expected)
                if methodology["implementation_strategy"] == "convoy-step":
                    # Convoy-step packs replace drains entirely; an empty drain
                    # policy list is the declared strategy.
                    self.assertEqual(
                        methodology.get("allowed_drain_policies", []), []
                    )
                    continue

                self.assertEqual(
                    set(methodology["allowed_drain_policies"]),
                    {"separate", "same-session"},
                )
                raw = base_contract.load_formula(
                    PACKS_ROOT / pack_name, expected["formula"]
                )
                step_by_id = {step["id"]: step for step in raw["steps"]}
                implement = step_by_id["implement"]
                self.assertEqual(
                    implement["condition"], "{{drain_policy}} == separate"
                )
                self.assertEqual(implement["drain"]["context"], "separate")
                self.assertEqual(
                    implement["drain"]["formula"],
                    expected["implementation_formula"],
                )
                same_session = step_by_id["implement-same-session"]
                self.assertEqual(
                    same_session["condition"], "{{drain_policy}} == same-session"
                )
                self.assertEqual(same_session["drain"]["context"], "shared")
                self.assertEqual(
                    same_session["drain"]["formula"],
                    expected["implementation_item_formula"],
                )

    def test_route_targets_resolve_to_providerless_agents(self) -> None:
        for pack_name in DERIVED_PACKS:
            pack_root = PACKS_ROOT / pack_name
            for path in sorted((pack_root / "formulas").glob("*.formula.toml")):
                formula_name = path.name.removesuffix(".formula.toml")
                raw = tomllib.loads(path.read_text(encoding="utf-8"))
                resolved = base_contract.resolve_formula_from_dirs(
                    pack_formula_dirs(pack_name), formula_name
                )
                for node in base_contract.formula_nodes(raw):
                    target = node.get("metadata", {}).get("gc.run_target", "")
                    if not target:
                        continue
                    with self.subTest(
                        pack=pack_name,
                        formula=formula_name,
                        node=node["id"],
                        target=target,
                    ):
                        resolved_target = base_contract.route_target_default(
                            target, resolved.get("vars", {})
                        )
                        if resolved_target.startswith("gc."):
                            self.assertIn(
                                resolved_target.removeprefix("gc."),
                                base_contract.ROLE_AGENTS,
                            )
                            continue
                        prefix = f"{pack_name}."
                        self.assertTrue(
                            resolved_target.startswith(prefix),
                            f"{resolved_target!r} must target {prefix}* or gc.*",
                        )
                        agent_dir = (
                            pack_root
                            / "agents"
                            / resolved_target.removeprefix(prefix)
                        )
                        agent_data = tomllib.loads(
                            (agent_dir / "agent.toml").read_text(encoding="utf-8")
                        )
                        self.assertNotIn(
                            "provider",
                            agent_data,
                            f"{agent_dir.name} must inherit the city/workspace provider",
                        )
                        self.assertEqual(agent_data["scope"], "rig")
                        self.assertTrue(agent_data["fallback"])
                        self.assertTrue(
                            (agent_dir / "prompt.template.md").is_file()
                        )

    def test_agent_prompts_use_public_claim_protocol_without_overrides(self) -> None:
        roles_pack = tomllib.loads(
            (GASCITY_ROOT / "roles" / "pack.toml").read_text(encoding="utf-8")
        )
        self.assertTrue(PUBLIC_CLAIM_FRAGMENT.is_file())
        self.assertEqual(roles_pack["imports"]["gc"]["source"], "..")

        for pack_name in DERIVED_PACKS:
            pack_root = PACKS_ROOT / pack_name
            pack_override = (
                pack_root / "template-fragments" / "gc-role-worker.template.md"
            )
            with self.subTest(pack=pack_name, fragment=str(pack_override)):
                self.assertFalse(
                    pack_override.exists(),
                    f"{pack_name} must use the public gc-role-worker fragment",
                )

            agent_dirs = sorted(
                agent_toml.parent
                for agent_toml in (pack_root / "agents").glob("*/agent.toml")
            )
            self.assertGreater(
                len(agent_dirs), 0, f"{pack_name} must define agents"
            )
            for agent_dir in agent_dirs:
                with self.subTest(pack=pack_name, agent=agent_dir.name):
                    prompt = agent_dir / "prompt.template.md"
                    self.assertTrue(
                        prompt.is_file(),
                        f"{pack_name}.{agent_dir.name} must ship a prompt template",
                    )
                    text = prompt.read_text(encoding="utf-8")
                    self.assertIn(CLAIM_PROTOCOL_INCLUDE, text)
                    self.assertEqual(text.count(CLAIM_PROTOCOL_INCLUDE), 1)
                    agent_override = (
                        agent_dir
                        / "template-fragments"
                        / "gc-role-worker.template.md"
                    )
                    self.assertFalse(
                        agent_override.exists(),
                        f"{pack_name}.{agent_dir.name} must use the public gc-role-worker fragment",
                    )

    def test_prompt_assets_do_not_dispatch_provider_native_subagents(self) -> None:
        for pack_name in DERIVED_PACKS:
            pack_root = PACKS_ROOT / pack_name
            paths: list[pathlib.Path] = []
            for sub_dir in PROMPT_ASSET_DIRS:
                paths.extend(sorted((pack_root / sub_dir).glob("**/*.md")))
            self.assertGreater(
                len(paths), 0, f"{pack_name} must ship prompt assets"
            )

            combined: list[str] = []
            for path in paths:
                text = path.read_text(encoding="utf-8")
                combined.append(text)
                for phrase in FORBIDDEN_DISPATCH_PHRASES:
                    with self.subTest(
                        pack=pack_name,
                        path=str(path.relative_to(PACKS_ROOT)),
                        phrase=phrase,
                    ):
                        self.assertNotIn(phrase, text)
            with self.subTest(pack=pack_name, guard=NATIVE_DISPATCH_GUARD):
                self.assertIn(NATIVE_DISPATCH_GUARD, "\n".join(combined))

    def test_pack_ledgers_prove_gc_meth_012(self) -> None:
        for pack_name in DERIVED_PACKS:
            pack_root = PACKS_ROOT / pack_name
            ledger_path = pack_root / "REQUIREMENTS.md"
            with self.subTest(pack=pack_name):
                self.assertTrue(
                    ledger_path.is_file(),
                    f"{pack_name} must ship a pack-local compatibility ledger",
                )
                ledger = ledger_path.read_text(encoding="utf-8")
                for fragment in LEDGER_REQUIRED_FRAGMENTS:
                    with self.subTest(pack=pack_name, fragment=fragment):
                        self.assertIn(fragment, ledger)
                readme = (pack_root / "README.md").read_text(encoding="utf-8")
                self.assertIn(
                    "REQUIREMENTS.md",
                    readme,
                    f"{pack_name}/README.md must reference the pack ledger",
                )

    def test_derived_producer_stages_keep_artifact_validation_gates(self) -> None:
        """Step overrides replace base steps wholesale, so every derived
        producer override must re-declare the shared artifact-validation gate
        (GC-BF-BR-010). bmad's drain item formulas deliberately swap in the
        implementation-review-approved.sh methodology check and are asserted
        as such."""
        build_gates = {
            "requirements": base_contract.REQUIREMENTS_GATE,
            "plan": base_contract.PLAN_GATE,
            "decompose": base_contract.DECOMPOSITION_GATE,
            "review": base_contract.BUILD_REVIEW_GATE,
            "finalize": base_contract.FINAL_REPORT_GATE,
        }
        for pack_name, expected in DERIVED_PACKS.items():
            review_report_gate = base_contract.REVIEW_REPORT_GATE
            if pack_name in {"superpowers", "compound-engineering", "gstack", "bmad"}:
                review_report_gate = (
                    base_contract.REVIEW_REPORT_GATE[0],
                    "gc.build.code_review_report_path,"
                    + base_contract.REVIEW_REPORT_GATE[1],
                )
            formula_gates = {
                expected["formula"]: build_gates,
                expected["planning_formula"]: {
                    "requirements": base_contract.REQUIREMENTS_GATE,
                    "plan": base_contract.PLAN_GATE,
                },
                expected["decomposition_formula"]: {
                    "decompose": base_contract.DECOMPOSITION_GATE,
                },
                expected["code_review_entry_formula"]: {
                    "write-report": review_report_gate,
                },
            }
            if pack_name != "bmad":
                formula_gates[expected["implementation_formula"]] = {
                    "implement": base_contract.ITEM_SUMMARY_GATE,
                }
                formula_gates[expected["implementation_item_formula"]] = {
                    "implement-item": base_contract.ITEM_SUMMARY_GATE,
                }
            for formula_name, gates in formula_gates.items():
                resolved = resolved_build_formula(
                    pack_name, {"formula": formula_name}
                )
                steps = {step["id"]: step for step in resolved["steps"]}
                for step_id, (schema, path_keys) in gates.items():
                    if step_id not in steps:
                        continue
                    step = artifact_validation_node(pack_name, steps[step_id])
                    with self.subTest(
                        pack=pack_name, formula=formula_name, step=step_id
                    ):
                        self.assertIn(
                            "check",
                            step,
                            f"{pack_name}/{formula_name}.{step_id} lost its "
                            "build-artifact validation gate",
                        )
                        self.assertEqual(
                            step["check"]["max_attempts"],
                            base_contract.BUILD_ARTIFACT_GATE_MAX_ATTEMPTS,
                        )
                        self.assertEqual(
                            step["check"]["check"],
                            {
                                "mode": "exec",
                                "path": base_contract.BUILD_ARTIFACT_CHECK_SCRIPT,
                                "timeout": "5m",
                            },
                        )
                        self.assertEqual(
                            step["metadata"]["gc.build.artifact_schema"], schema
                        )
                        self.assertEqual(
                            step["metadata"]["gc.build.artifact_path_keys"],
                            path_keys,
                        )
        for formula_name, step_id in (
            ("bmad-story-development", "implement"),
            ("bmad-story-development-item", "implement-item"),
        ):
            resolved = resolved_build_formula("bmad", {"formula": formula_name})
            steps = {step["id"]: step for step in resolved["steps"]}
            with self.subTest(pack="bmad", formula=formula_name, step=step_id):
                self.assertEqual(
                    steps[step_id]["check"]["check"]["path"],
                    ".gc/scripts/checks/implementation-review-approved.sh",
                    "bmad story development must keep its methodology "
                    "review check",
                )


# Every unsafe spelling asserted by the superseded pattern-based guard
# (packs fad14d16, developed in parallel with this analyzer). The analyzer
# replaced that implementation, so its table is pinned here to prove the
# replacement lost none of its coverage. Extracted from that revision
# mechanically, never retyped.
PATTERN_ERA_UNSAFE_SPELLINGS = (
    'gc bd update gc-123 --set-metadata gc.work_outcome=shipped',
    "gc bd update gc-123 --set-metadata 'gc.work_outcome=shipped'",
    'gc bd update gc-123 --set-metadata "gc.work_outcome=shipped"',
    'gc bd update gc-123 --set-metadata=gc.work_outcome=shipped',
    "gc bd update gc-123 --set-metadata='gc.work_outcome=shipped'",
    'gc bd update gc-123 --set-metadata="gc.work_outcome=shipped"',
    "gc bd update gc-123 --set-metadata gc.work_outcome='shipped'",
    'gc bd update gc-123 --set-metadata gc.work_outcome="shipped"',
    'gc bd update gc-123 --set-metadata\tgc.work_outcome=shipped',
    'gc bd update gc-123 --set-metadata  gc.work_outcome=shipped',
    'gc bd update gc-123 \\\n  --set-metadata \\\n  gc.work_outcome=shipped',
    'gc bd update gc-123 --metadata gc.work_outcome=shipped',
    'gc bd update gc-123 --metadata \'{"gc.work_outcome": "shipped"}\'',
    'gc bd update gc-123 --metadata \'{"gc.work_outcome":"shipped"}\'',
    'gc bd update gc-123 --metadata=\'{"gc.work_outcome": "shipped"}\'',
    'gc bd update gc-123 --metadata "{\\"gc.work_outcome\\": \\"shipped\\"}"',
    'gc bd update gc-123 --metadata \'{ "gc.work_outcome" : "shipped" }\'',
    'gc bd update gc-123 --metadata \'{"gc.delivery_state": "integration_ready", "gc.work_outcome": "shipped"}\'',
    'gc bd update gc-123 --metadata \'{"evidence": {"tests": "pass"}, "gc.work_outcome": "shipped"}\'',
    'gc bd update gc-123 --metadata \'{\n  "gc.work_outcome": "shipped"\n}\'',
    "gc bd update gc-123 --metadata '{gc.work_outcome: shipped}'",
    'gc bd update gc-123 --metadata={gc.work_outcome: shipped}',
    'gc \\\n  bd update gc-123 --set-metadata gc.work_outcome=shipped',
    'gc bd \\\n  update gc-123 --set-metadata gc.work_outcome=shipped',
    'gc bd update gc-123 --metadata \'{"gc\\u002ework_outcome":"shipped"}\'',
    'gc bd update gc-123 --metadata \'{"gc.work_outcome":"shipp\\u0065d"}\'',
    'cat > stamp.json <<\'EOF\'\n{"gc.work_outcome": "shipped"}\nEOF\ngc bd update gc-123 --metadata @stamp.json',
    "cat > stamp.json <<'EOF'\n{gc.work_outcome: shipped}\nEOF\ngc bd update gc-123 --metadata=@stamp.json",
)


class ShippedStampGuardAnalyzerTests(unittest.TestCase):
    """Unit-test the shipped-stamp analyzer directly, so the fail-closed
    assertion in test_implementation_overrides_submit_open_work_for_integration
    keeps rejecting every bd metadata spelling of a branch-only shipped close
    without rejecting the prose that documents the rule. Spellings are
    constructed inline; the asset sweep is the only test that reads files."""

    def test_analyzer_rejects_every_shipped_stamp_command_spelling(self) -> None:
        for expected_kind, spelling in (
            UNSAFE_SHIPPED_STAMP_SPELLINGS + ADDITIONAL_UNSAFE_SHIPPED_STAMP_SPELLINGS
        ):
            with self.subTest(spelling=spelling):
                findings = shipped_stamp_findings(spelling)
                self.assertTrue(
                    findings, f"guard must reject shipped-stamp spelling {spelling!r}"
                )
                self.assertEqual(
                    [expected_kind],
                    sorted({finding.kind for finding in findings}),
                    f"wrong verdict for {spelling!r}: {findings}",
                )

    def test_analyzer_keeps_guard_prose_and_read_filters_legal(self) -> None:
        for spelling in SAFE_SHIPPED_PROSE_SPELLINGS:
            with self.subTest(spelling=spelling):
                self.assertEqual(
                    [],
                    shipped_stamp_findings(spelling),
                    f"guard must keep safe spelling {spelling!r} legal",
                )

    def test_analyzer_resolves_repo_local_metadata_files(self) -> None:
        """A literal @file reference is followed and its decoded object judged;
        a reference the guard cannot follow fails closed."""
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = pathlib.Path(raw_directory)
            (directory / "unsafe.json").write_text(
                '{"gc.work_outcome": "shipped"}', encoding="utf-8"
            )
            (directory / "escaped.json").write_text(
                '{"gc.work_\\u006futcome": "shipped"}', encoding="utf-8"
            )
            (directory / "safe.json").write_text(
                '{"gc.delivery_state": "integration_ready"}', encoding="utf-8"
            )
            (directory / "broken.json").write_text("{not json", encoding="utf-8")
            cases = (
                ("unsafe.json", ["unsafe"]),
                ("escaped.json", ["unsafe"]),
                ("safe.json", []),
                ("broken.json", ["unresolvable"]),
                ("missing.json", ["unresolvable"]),
                ("$GENERATED.json", ["unresolvable"]),
                ("../outside.json", ["unresolvable"]),
                ("/etc/outside.json", ["unresolvable"]),
            )
            for reference, expected in cases:
                with self.subTest(reference=reference):
                    findings = shipped_stamp_findings(
                        f"gc bd update gc-123 --metadata @{reference}", directory
                    )
                    self.assertEqual(expected, [finding.kind for finding in findings])

    def test_no_markdown_asset_in_the_repository_trips_the_guard(self) -> None:
        """Full-repo false-positive sweep: no Markdown asset anywhere in the
        packs tree may produce an unsafe detection."""
        assets = sorted(
            path
            for path in PACKS_ROOT.rglob("*.md")
            if ".git" not in path.parts
        )
        self.assertGreater(len(assets), 500, "sweep should cover the whole packs tree")
        tripped = {
            str(path.relative_to(PACKS_ROOT)): unsafe_shipped_stamp_findings(
                path.read_text(encoding="utf-8"), path.parent
            )
            for path in assets
        }
        self.assertEqual({}, {k: v for k, v in tripped.items() if v})

    def test_guard_fails_when_any_decoding_stage_is_weakened(self) -> None:
        """Teeth: every normalization and decoding stage is load-bearing.

        Each weakening replaces one stage with a plausible weaker version and
        must break at least one spelling in the table -- either by missing it
        entirely or by downgrading an exact "unsafe" decode to a fail-closed
        "unresolvable" guess.
        """
        weakenings = {
            # Raw-text matching instead of shell tokenization.
            "shell_tokens": lambda region: region.split(),
            # Ignore ANSI-C quoting, as shlex alone does.
            "normalize_ansi_c_quoting": lambda region: region,
            # Leave backslash-newline in place, as shlex alone does.
            "normalize_line_continuations": lambda text: text,
            # Compare payload text without decoding it.
            "decode_metadata_payload": lambda payload, asset_dir, where: (
                [MetadataFinding("unsafe", where)]
                if payload == f"{FORBIDDEN_STAMP_KEY}={FORBIDDEN_STAMP_VALUE}"
                else []
            ),
        }
        for stage, weaker in weakenings.items():
            with self.subTest(stage=stage):
                with mock.patch.object(sys.modules[__name__], stage, weaker):
                    mismatches = [
                        spelling
                        for expected_kind, spelling in UNSAFE_SHIPPED_STAMP_SPELLINGS
                        if sorted({f.kind for f in shipped_stamp_findings(spelling)})
                        != [expected_kind]
                    ]
                self.assertTrue(
                    mismatches,
                    f"weakening {stage} must break the table, but nothing changed",
                )


    def test_analyzer_rejects_every_pattern_era_spelling(self) -> None:
        """The analyzer supersedes a parallel pattern-based guard; every
        spelling that guard rejected must still be rejected here, or the
        replacement silently narrowed coverage."""
        # The table is frozen history, so its size is pinned: an emptied or
        # truncated corpus would make the loop below pass vacuously.
        self.assertEqual(28, len(PATTERN_ERA_UNSAFE_SPELLINGS))
        for spelling in PATTERN_ERA_UNSAFE_SPELLINGS:
            with self.subTest(spelling=spelling):
                self.assertTrue(
                    shipped_stamp_findings(spelling),
                    f"analyzer must reject pattern-era spelling {spelling!r}",
                )

if __name__ == "__main__":
    unittest.main()
