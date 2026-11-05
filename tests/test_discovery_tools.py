from __future__ import annotations
import ast
from pathlib import Path
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]


class DiscoveryToolTests(unittest.TestCase):
    def test_finite_pilot_parses_and_documents_lexical_limits(self):
        path=ROOT/'scripts/discovery-pilot.py'
        ast.parse(path.read_text())
        result=subprocess.run([sys.executable,str(path),'--help'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        for text in ('--expect-reuse','--dependency-root','--expected-version','not an SLA'):
            self.assertIn(text,result.stdout)

    def test_pilot_does_not_change_import_resolution_or_native_policy(self):
        script=(ROOT/'scripts/discovery-pilot.py').read_text()
        for text in ("timeout_seconds=180","timeout_seconds=20",'--ignore-interfaces','--no-libraries',
                     'sameMetadataNonSourceEditRejected','repeatedSearchEquality',
                     "'not-established'","'not-tested'",'validate_source_observation',
                     "workspace.notify_buffers(dirty=True)","workspace.notify_buffers(dirty=False)"):
            self.assertIn(text,script)
        for text in ('sys.path.insert','pip install','git clone','--allow-unsolved-metas'):
            self.assertNotIn(text,script)

    def test_exact_native_workflow_preserves_fixed_discovery_baseline_and_isolated_consumers(self):
        workflow=(ROOT/'.github/workflows/native-conformance.yml').read_text()
        for text in ('d1f56692d4ecc48adaff26c63a7fe26b662f470e','git archive "$DISCOVERY_BASELINE"',
                     '1-before 1-after 2-after 2-before','--no-deps --no-index','--expect-reuse',
                     '-I "$runner"','discovery-consumers','discovery-before-dist',
                     '--expected-version "$EXPECTED_AGDA_VERSION"'):
            self.assertIn(text,workflow)
        self.assertNotIn('continue-on-error',workflow)

    def test_installed_smoke_requires_repeated_search_and_unchanged_assurances(self):
        smoke=(ROOT/'scripts/package-smoke.py').read_text()
        for text in ('first_search','second_search','scan.call_count == first_scans',
                     'verified-byte repeated discovery','candidateUsability','not-tested'):
            self.assertIn(text,smoke)


if __name__=='__main__':
    unittest.main()
