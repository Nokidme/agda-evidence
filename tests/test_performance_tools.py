from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


class PerformanceToolTests(unittest.TestCase):
    def test_scripts_parse_and_expose_finite_cli(self):
        for name in ('profile-native-conformance.py','compare-native-conformance.py'):
            path=ROOT/'scripts'/name
            ast.parse(path.read_text())
            result=subprocess.run([sys.executable,str(path),'--help'],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('--output',result.stdout)
            self.assertIn('--expected-version',result.stdout)
            self.assertIn('SLA',result.stdout)

    def test_comparison_rejects_unbounded_repetition_before_creating_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)/'must-not-exist'
            command=[sys.executable,str(ROOT/'scripts/compare-native-conformance.py'),
                     '--before-wheel','missing.whl','--after-wheel','missing.whl',
                     '--runner',str(ROOT/'scripts/native-conformance.py'),'--agda-bin','missing',
                     '--expected-version','2.6.4.3','--repetitions','4','--output',str(output)]
            result=subprocess.run(command,capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('repetitions must be 1..3',result.stderr)
            self.assertFalse(output.exists())

    def test_comparison_cannot_modify_existing_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)
            marker=output/'notes.txt'
            marker.write_bytes(b'original bytes')
            result=subprocess.run([sys.executable,str(ROOT/'scripts/compare-native-conformance.py'),
                '--before-wheel','missing.whl','--after-wheel','missing.whl',
                '--runner',str(ROOT/'scripts/native-conformance.py'),'--agda-bin','missing',
                '--expected-version','2.6.4.3','--output',str(output)],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('new external directory',result.stderr)
            self.assertEqual(marker.read_bytes(),b'original bytes')

    def test_profile_cannot_write_into_repository(self):
        output=ROOT/'must-not-create-profile-output'
        result=subprocess.run([sys.executable,str(ROOT/'scripts/profile-native-conformance.py'),
            '--runner',str(ROOT/'scripts/native-conformance.py'),'--agda-bin','missing',
            '--expected-version','2.6.4.3','--output',str(output)],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('not overlapping sources',result.stderr)
        self.assertFalse(output.exists())

    def test_isolation_and_timing_claims_remain_explicit(self):
        compare=(ROOT/'scripts/compare-native-conformance.py').read_text()
        for item in ("'-I'","'PYTHONPATH'","'PYTHONHOME'","'--no-index'",
                     "['before','after']","['after','before']","'20'",
                     "'beforeSamples'","'afterSamples'","statistical significance"):
            self.assertIn(item,compare)
        profile=(ROOT/'scripts/profile-native-conformance.py').read_text()
        for item in ('cProfile.Profile()', 'profiler.runcall', 'cumulative spans overlap', 'not unprofiled latency'):
            self.assertIn(item,profile)
        for script in (profile,compare):
            self.assertNotIn('sys.path.insert',script)
            self.assertNotIn('requests.get',script)
            self.assertNotIn('git clone',script)

    def test_exact_native_lane_pins_immutable_performance_baseline(self):
        workflow=(ROOT/'.github/workflows/native-conformance.yml').read_text()
        for item in ('c1f3a58b772619be561e58b6ea2d7d509e5db4ec',
                     'git archive "$PERFORMANCE_BASELINE"','--wheel --outdir',
                     'python scripts/compare-native-conformance.py','--repetitions 2',
                     '--timeout-seconds 20','native-performance-comparison'):
            self.assertIn(item,workflow)
        self.assertNotIn('continue-on-error',workflow)


if __name__=='__main__':
    unittest.main()
