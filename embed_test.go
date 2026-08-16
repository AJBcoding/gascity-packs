package gascitypacks

import (
	"io/fs"
	"testing"
)

func TestGastownEmbedsPackContent(t *testing.T) {
	pack := Gastown()
	for _, rel := range []string{
		"pack.toml",
		"agents/dog/agent.toml",
		"agents/dog/prompt.template.md",
		"formulas/mol-shutdown-dance.toml",
		"template-fragments/propulsion.template.md",
		"overlay/per-provider/codex/.codex/hooks.json",
	} {
		if _, err := fs.Stat(pack, rel); err != nil {
			t.Errorf("gastown pack missing %s: %v", rel, err)
		}
	}
}

func TestGascityEmbedsPackContent(t *testing.T) {
	pack := Gascity()
	for _, rel := range []string{
		"pack.toml",
		"formulas/implement.formula.toml",
		"formulas/build-base.formula.toml",
		"formulas/build-basic.formula.toml",
		"formulas/integration-base.formula.toml",
		"formulas/integrate.formula.toml",
		"skills/mayor/SKILL.md",
		"schemas/build/integration-manifest.v1.yaml",
		"schemas/build/integration-result.v1.yaml",
		"assets/scripts/integrate_candidate.py",
		"assets/scripts/checks/gap-analysis-approved.sh",
		"assets/scripts/checks/build-artifact-valid.sh",
		"roles/pack.toml",
		"roles/agents/integration-operator/agent.toml",
	} {
		if _, err := fs.Stat(pack, rel); err != nil {
			t.Errorf("gascity pack missing %s: %v", rel, err)
		}
	}
}

func TestEmbedHasNoUnexpectedRoots(t *testing.T) {
	entries, err := fs.ReadDir(packsFS, ".")
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]bool{"gastown": true, "gascity": true}
	if len(entries) != len(want) {
		names := make([]string, 0, len(entries))
		for _, e := range entries {
			names = append(names, e.Name())
		}
		t.Fatalf("embedded roots = %v, want gastown + gascity", names)
	}
	for _, e := range entries {
		if !want[e.Name()] {
			t.Fatalf("unexpected embedded root %q", e.Name())
		}
	}
}
