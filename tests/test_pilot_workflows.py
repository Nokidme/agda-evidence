from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PilotWorkflowTests(unittest.TestCase):
    def test_candidate_pilot_keeps_trials_non_filling_and_records_failures(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "candidates-pilot.yml").read_text(encoding="utf-8")
        for required in ("workflow_dispatch:", "ubuntu-24.04", "python -m pip install -e .",
                         "python scripts/candidates-pilot.py", "agda-evidence goals verify-check",
                         "git diff --exit-code", "native-candidates-pilot-${{ github.sha }}"):
            self.assertIn(required, workflow)

    def test_goals_pilot_keeps_inspection_read_only_and_retains_records(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "goals-pilot.yml").read_text(encoding="utf-8")
        for required in ("workflow_dispatch:", "ubuntu-24.04", "python -m pip install -e .",
                         "python scripts/goals-pilot.py", "agda-evidence goals verify",
                         "git diff --exit-code", "native-goals-pilot-${{ github.sha }}"):
            self.assertIn(required, workflow)

    def test_client_pilot_preserves_native_source_and_failure_cases(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "client-pilot.yml").read_text(encoding="utf-8")
        for required in ("workflow_dispatch:", "ubuntu-24.04", "--no-install-recommends agda-bin",
                         "python scripts/client-pilot.py", "imported alias no-import private homonym",
                         "python -m pip install -e .", "git status --short",
                         "agda-evidence client verify", "git diff --exit-code", "actions/upload-artifact@v4"):
            self.assertIn(required, workflow)

    def test_algebra_pilot_adds_discovery_without_changing_its_native_gate(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "agda-algebras-pilot.yml").read_text(encoding="utf-8")
        for required in (
            "c7617677f0e4233939660aa42e7fafb2f68e95e0",
            "probe-nix-resolution", "--resolution-file", "agda-evidence index build",
            '--index-reference "$RUNNER_TEMP/agda-algebras.index.json"',
            "nix flake check --no-write-lock-file",
            "nix develop --no-write-lock-file --command make check",
            "agda-evidence catalog create", "agda-evidence catalog verify",
            "agda-evidence catalog query", "expected verified algebra module candidates",
        ):
            self.assertIn(required, workflow)

    def test_standard_library_pilot_binds_and_queries_a_source_index(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "agda-stdlib-pilot.yml").read_text(encoding="utf-8")
        required = (
            "565739a4d82b8bb47d2f15cb99178db15ca60e9b",
            "Configure direct HTTPS Hackage access",
            "url: https://hackage.haskell.org/",
            "secure: False",
            "cabal v2-install --install-method=copy --overwrite-policy=always",
            "agda-evidence index build",
            "--output \"$RUNNER_TEMP/agda-stdlib.index.json\"",
            "--index-reference \"$RUNNER_TEMP/agda-stdlib.index.json\"",
            "agda-evidence index query \"$GITHUB_WORKSPACE/agda-stdlib.evidence\"",
            "--prefix Data.Nat --kind module",
            "expected at least one Data.Nat lexical module candidate",
            "agda-evidence checker infer",
            "--file src/Data/Nat/Base.agda --include src --expression '_+_' --safe",
            '--bundle "$GITHUB_WORKSPACE/agda-stdlib.evidence"',
            'agda-evidence checker verify "$RUNNER_TEMP/stdlib-addition.type.json"',
            "agda-stdlib-type-observation-${{ inputs.stdlib_ref }}",
        )
        for value in required:
            self.assertIn(value, workflow)

    def test_formal_ledger_pilot_preserves_the_pinned_primary_gate(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "formal-ledger-pilot.yml").read_text(encoding="utf-8")
        required = (
            "workflow_dispatch:",
            "7d4956e92bfa7cc472dca79c6eaf496677c24ea5",
            "formal-ledger-specifications",
            "probe-nix-resolution",
            "--resolution-file",
            "nix build --no-write-lock-file -o outputs .#formal-ledger",
            "formal-ledger-agda: full Ledger specification typecheck at $LEDGER_REF",
            "agda-evidence verify",
            "actions/upload-artifact@v4",
        )
        for value in required:
            self.assertIn(value, workflow)

        # The core package gate must not be inflated to downstream artifacts or
        # two-repository conformance claims in this first pilot.
        self.assertNotIn("fls-shake --trace -j8 hs", workflow)
        self.assertNotIn("cardano-ledger-conformance", workflow)


if __name__ == "__main__":
    unittest.main()
