"""Derived-pack compatibility evidence for GC-METH-012.

Each test inspects all four concrete derived packs (compound-engineering,
superpowers, bmad, gstack) and asserts one face of the external implementation
compatibility contract: import-as-`gc`, anchored `build-base` extension,
methodology metadata vocabulary, selector defaults, drain or convoy-step
strategy, providerless route targets, the shared claim protocol, the absence
of provider-native subagent dispatch, and the pack-local compatibility
ledgers. The matching ledger rows live in `gascity/REQUIREMENTS.md`
(GC-METH-012) and each pack's `REQUIREMENTS.md`.
`ShippedStampGuardPatternTests` additionally unit-tests the shipped-stamp
guard patterns themselves against inline command spellings, without reading
any pack asset.
"""

from __future__ import annotations

import json
import pathlib
import re
import shlex
import tomllib
import unittest

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

# bd exposes exactly two metadata write flags and no short forms for either
# (`bd update --help`, `bd create --help`; `bd close` has no metadata flag):
# `--set-metadata key=value` and `--metadata <JSON object | @file.json>`.
# Both accept `--flag value` and `--flag=value`, either quote style around
# the pair, the key, or the value alone, tabs, and backslash-newline line
# continuations. A bare newline ends a shell command, so it is deliberately
# not a valid separator; that also keeps the read-side list filter
# `--metadata-field ...` legal, because `-` never follows the flag here.
SHIPPED_STAMP_FLAG = r"--(?:set-)?metadata(?:=|(?:[ \t]|\\\r?\n)+)"

# Every command spelling that would stamp `gc.work_outcome=shipped` on a
# source anchor from an implementation override. Guard prose such as
# "Never set `gc.work_outcome=shipped`", the bare ledger fragment, and
# post-landing transition prose all stay legal because scanning starts only at
# a shell command beginning with `gc bd update` or `gc bd create`.
SHIPPED_STAMP_COMMAND_PATTERNS = (
    # key=value payload: --set-metadata gc.work_outcome=shipped in any
    # quoting/equals/continuation variant, or the same payload handed to
    # --metadata by mistake -- the intent is identical.
    re.compile(
        SHIPPED_STAMP_FLAG + r"[\"'\\]*gc\.work_outcome[\"'\\]*=[\"'\\]*shipped"
    ),
    # Whole-object JSON payload fallback for malformed JSON. Valid JSON is
    # parsed below so Unicode escapes normalize before the key/value check.
    re.compile(
        SHIPPED_STAMP_FLAG
        + r"[\"'\\]*\{(?:[^{}]|\{[^{}]*\})*"
        + r"gc\.work_outcome[\"'\\]*\s*:\s*[\"'\\]*shipped"
    ),
)

SHELL_WORD_SEPARATOR = r"(?:[ \t]|\\\r?\n)+"
MUTATING_COMMAND_CONTEXT = re.compile(
    r"(?m)(?:^|[;&|])[ \t]*gc"
    + SHELL_WORD_SEPARATOR
    + r"bd"
    + SHELL_WORD_SEPARATOR
    + r"(?:update|create)\b"
)
HEREDOC_FILE = re.compile(
    r"(?ms)^[ \t]*cat[ \t]+>[ \t]*[\"']?(?P<path>[^ \t\"';]+)[\"']?"
    r"[ \t]+<<[ \t]*[\"']?(?P<delimiter>[A-Za-z_][\w-]*)[\"']?[ \t]*\n"
    r"(?P<body>.*?)^[ \t]*(?P=delimiter)[ \t]*$"
)


def _shell_command_spans(text: str):
    """Yield executable gc bd update/create command spans, including continuations."""
    for match in MUTATING_COMMAND_CONTEXT.finditer(text):
        start = match.start()
        index = match.end()
        quote: str | None = None
        escaped = False
        braces = 0
        while index < len(text):
            char = text[index]
            if escaped:
                escaped = False
            elif char == "\\" and quote != "'":
                escaped = True
            elif quote:
                if char == quote:
                    quote = None
            elif char in "'\"":
                quote = char
            elif char == "{":
                braces += 1
            elif char == "}" and braces:
                braces -= 1
            elif char in "\n;" and not braces:
                break
            index += 1
        yield text[start:index]


def _declared_heredoc_files(text: str) -> dict[str, str]:
    return {
        match.group("path"): match.group("body")
        for match in HEREDOC_FILE.finditer(text)
    }


def _json_ships(payload: str) -> bool:
    try:
        value = json.loads(payload)
    except (TypeError, ValueError):
        return False
    return isinstance(value, dict) and value.get("gc.work_outcome") == "shipped"


def contains_unsafe_shipped_stamp(text: str) -> bool:
    """Reject shipped metadata only when attached to an executable mutation."""
    heredoc_files = _declared_heredoc_files(text)
    for command in _shell_command_spans(text):
        if SHIPPED_STAMP_COMMAND_PATTERNS[0].search(command):
            return True
        if SHIPPED_STAMP_COMMAND_PATTERNS[1].search(command):
            return True
        try:
            tokens = [token for token in shlex.split(command) if token != "\n"]
        except ValueError:
            tokens = []
        for index, token in enumerate(tokens):
            if token in ("--metadata", "--set-metadata"):
                payload = tokens[index + 1] if index + 1 < len(tokens) else ""
            elif token.startswith("--metadata=") or token.startswith("--set-metadata="):
                payload = token.split("=", 1)[1]
            else:
                continue
            resolved_file = payload.startswith("@")
            if resolved_file:
                payload = heredoc_files.get(payload[1:], "")
            if resolved_file:
                fallback_text = token.split("=", 1)[0] + " " + payload
            elif "=" in token:
                fallback_text = token
            else:
                fallback_text = token + " " + payload
            if _json_ships(payload) or SHIPPED_STAMP_COMMAND_PATTERNS[1].search(
                fallback_text
            ):
                return True
    return False

# Exercised by ShippedStampGuardPatternTests: command spellings the guard
# must reject even though none appears in a current asset.
UNSAFE_SHIPPED_STAMP_SPELLINGS = (
    "gc bd update gc-123 --set-metadata gc.work_outcome=shipped",
    "gc bd update gc-123 --set-metadata 'gc.work_outcome=shipped'",
    'gc bd update gc-123 --set-metadata "gc.work_outcome=shipped"',
    "gc bd update gc-123 --set-metadata=gc.work_outcome=shipped",
    "gc bd update gc-123 --set-metadata='gc.work_outcome=shipped'",
    'gc bd update gc-123 --set-metadata="gc.work_outcome=shipped"',
    "gc bd update gc-123 --set-metadata gc.work_outcome='shipped'",
    'gc bd update gc-123 --set-metadata gc.work_outcome="shipped"',
    "gc bd update gc-123 --set-metadata\tgc.work_outcome=shipped",
    "gc bd update gc-123 --set-metadata  gc.work_outcome=shipped",
    "gc bd update gc-123 \\\n  --set-metadata \\\n  gc.work_outcome=shipped",
    "gc bd update gc-123 --metadata gc.work_outcome=shipped",
    'gc bd update gc-123 --metadata \'{"gc.work_outcome": "shipped"}\'',
    'gc bd update gc-123 --metadata \'{"gc.work_outcome":"shipped"}\'',
    'gc bd update gc-123 --metadata=\'{"gc.work_outcome": "shipped"}\'',
    'gc bd update gc-123 --metadata "{\\"gc.work_outcome\\": \\"shipped\\"}"',
    'gc bd update gc-123 --metadata \'{ "gc.work_outcome" : "shipped" }\'',
    "gc bd update gc-123 --metadata '{\"gc.delivery_state\": "
    "\"integration_ready\", \"gc.work_outcome\": \"shipped\"}'",
    "gc bd update gc-123 --metadata '{\"evidence\": {\"tests\": \"pass\"}, "
    "\"gc.work_outcome\": \"shipped\"}'",
    "gc bd update gc-123 --metadata '{\n  \"gc.work_outcome\": \"shipped\"\n}'",
    "gc bd update gc-123 --metadata '{gc.work_outcome: shipped}'",
    "gc bd update gc-123 --metadata={gc.work_outcome: shipped}",
    "gc \\\n  bd update gc-123 --set-metadata gc.work_outcome=shipped",
    "gc bd \\\n  update gc-123 --set-metadata gc.work_outcome=shipped",
    # Unicode-escaped JSON key/value must decode to the same prohibited stamp.
    'gc bd update gc-123 --metadata \'{"gc\\u002ework_outcome":"shipped"}\'',
    'gc bd update gc-123 --metadata \'{"gc.work_outcome":"shipp\\u0065d"}\'',
    "cat > stamp.json <<'EOF'\n"
    '{"gc.work_outcome": "shipped"}\n'
    "EOF\n"
    "gc bd update gc-123 --metadata @stamp.json",
    "cat > stamp.json <<'EOF'\n"
    "{gc.work_outcome: shipped}\n"
    "EOF\n"
    "gc bd update gc-123 --metadata=@stamp.json",
)

# Exercised by ShippedStampGuardPatternTests: legitimate spellings from real
# assets and ledgers the guard must keep legal. The first two are required
# verbatim by the positive assertions and the ledger fragment list.
SAFE_SHIPPED_PROSE_SPELLINGS = (
    "Leave the source anchor open. Never set `gc.work_outcome=shipped` "
    "from a passing test or task review.",
    "Only a later exact-record transition may request shipped after "
    "portable\npost-landing stamping succeeds.",
    "gc.work_outcome=shipped",
    "gc bd update <id> --set-metadata gc.delivery_state=integration_ready",
    "gc bd list --metadata-field gc.work_outcome=shipped --status=closed",
    # A warning about the forbidden command is prose, not a mutation.
    'Never run --metadata \'{"gc.work_outcome": "shipped"}\' on the source anchor.',
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
                    text = (PACKS_ROOT / pack_name / relative_path).read_text(
                        encoding="utf-8"
                    )
                    self.assertIn("gc.work_commit", text)
                    self.assertIn("gc.delivery_state=integration_ready", text)
                    self.assertIn("Leave the source anchor open", text)
                    self.assertIn("Never set `gc.work_outcome=shipped`", text)
                    self.assertFalse(contains_unsafe_shipped_stamp(text))
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


class ShippedStampGuardPatternTests(unittest.TestCase):
    """Unit-test contains_unsafe_shipped_stamp directly so the negative
    assertion in test_implementation_overrides_submit_open_work_for_integration
    keeps rejecting every bd metadata spelling of a branch-only shipped close.
    Spellings are constructed inline; no pack asset is read."""

    def test_patterns_reject_every_shipped_stamp_command_spelling(self) -> None:
        for spelling in UNSAFE_SHIPPED_STAMP_SPELLINGS:
            with self.subTest(spelling=spelling):
                self.assertTrue(
                    contains_unsafe_shipped_stamp(spelling),
                    f"guard must reject shipped-stamp spelling {spelling!r}",
                )

    def test_patterns_keep_guard_prose_and_read_filters_legal(self) -> None:
        for spelling in SAFE_SHIPPED_PROSE_SPELLINGS:
            with self.subTest(spelling=spelling):
                self.assertFalse(contains_unsafe_shipped_stamp(spelling))


if __name__ == "__main__":
    unittest.main()
