from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PilotWorkflowTests(unittest.TestCase):
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
