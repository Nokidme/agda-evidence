from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PilotWorkflowTests(unittest.TestCase):
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
