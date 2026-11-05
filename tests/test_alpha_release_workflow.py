from __future__ import annotations

import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AlphaReleaseWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workflow = (ROOT / '.github/workflows/native-conformance.yml').read_text(encoding='utf-8')

    def step(self, name):
        marker = f'      - name: {name}\n'
        self.assertEqual(self.workflow.count(marker), 1)
        return self.workflow.split(marker, 1)[1].split('\n      - ', 1)[0]

    def test_same_commit_full_ci_evidence_is_required_before_download_and_provision(self):
        name = 'Require completed successful same-commit CI and unique live artifact'
        guard = self.step(name)
        self.assertIn("if: ${{ inputs.ci_run_id != '' }}", guard)
        for required in ('CI_RUN_ID: ${{ inputs.ci_run_id }}', 'GH_TOKEN: ${{ github.token }}',
                         '*[!0-9]*', '/jobs?filter=latest&per_page=100', '/artifacts?per_page=100',
                         '--metadata', '--jobs', '--artifacts', '--repository "$GITHUB_REPOSITORY"',
                         '--commit "$GITHUB_SHA"', '--run-id "$CI_RUN_ID"'):
            self.assertIn(required, guard)
        self.assertLess(self.workflow.index(name), self.workflow.index('actions/download-artifact@v4'))
        self.assertLess(self.workflow.index(name), self.workflow.index('haskell-actions/setup@v2'))
        self.assertNotIn('continue-on-error', self.workflow)
        self.assertNotIn('|| true', guard)
        self.assertNotIn('${{ inputs.ci_run_id }}', guard.split('run: |', 1)[1])

    def test_download_is_same_repository_run_and_named_sha_artifact(self):
        block = self.workflow.split('      - uses: actions/download-artifact@v4\n', 1)[1].split('\n      - ', 1)[0]
        for required in ("if: ${{ inputs.ci_run_id != '' }}", 'github-token: ${{ github.token }}',
                         'repository: ${{ github.repository }}', 'run-id: ${{ inputs.ci_run_id }}',
                         'name: alpha-distributions-${{ github.sha }}',
                         'path: ${{ runner.temp }}/conformance-dist'):
            self.assertIn(required, block)
        self.assertIn('permissions:\n  contents: read\n  actions: read\n', self.workflow)
        self.assertNotIn('actions: write', self.workflow)
        self.assertNotIn('contents: write', self.workflow)

    def test_release_never_rebuilds_distribution_or_old_comparison_wheels(self):
        for name in ('Build development distributions and record checksums',
                     'Build the immutable pre-optimization wheel outside the checkout',
                     'Compare finite installed-wheel runs in alternating order',
                     'Build and install fixed pre-discovery and current wheels separately',
                     'Validate repeated discovery in alternating installed consumers'):
            self.assertIn("if: ${{ inputs.ci_run_id == '' }}", self.step(name))
        check = self.step('Validate exact distribution metadata checksums and canonical contents')
        self.assertNotIn('if:', check)
        for required in ('check-release-inputs.py distributions', '--expected-version "$version"',
                         '--repository-root "$GITHUB_WORKSPACE"', '--dist-dir "$RUNNER_TEMP/conformance-dist"'):
            self.assertIn(required, check)
        native = self.step('Run mandatory versioned conformance in fresh wheel and source consumers')
        self.assertNotIn('if:', native)
        for required in ('--dist-dir "$RUNNER_TEMP/conformance-dist"', '--timeout-seconds 20',
                         '--expected-version "$EXPECTED_AGDA_VERSION"', '--dependency-root'):
            self.assertIn(required, native)
        release = self.step('Validate release discovery in the exact installed CI wheel')
        self.assertIn("if: ${{ inputs.ci_run_id != '' }}", release)
        self.assertIn('--no-deps --no-index "$RUNNER_TEMP"/conformance-dist/*.whl', release)
        self.assertIn('--expect-reuse', release)
        self.assertIn('-I "$runner"', release)
        self.assertNotIn('python -m build', release)

    def test_input_metadata_reports_and_exact_distribution_copies_are_retained(self):
        for name in ('release-ci-run.json', 'release-ci-jobs.json', 'release-ci-artifacts.json',
                     'release-ci-validation.json', 'release-distribution-validation.json',
                     'native-conformance-consumers', 'conformance-dist', 'discovery-consumers'):
            self.assertIn('${{ runner.temp }}/' + name, self.workflow)
        self.assertIn('retention-days: 30', self.workflow)
        self.assertIn('if: always()', self.workflow)

    def test_source_archive_supplies_workflow_tests_without_private_configuration(self):
        manifest = (ROOT / 'MANIFEST.in').read_text(encoding='utf-8')
        self.assertIn('recursive-include .github/workflows *.yml', manifest)
        self.assertIn('exclude .env\n', manifest)
        self.assertIn('exclude .env.*\n', manifest)
        self.assertIn('global-exclude __pycache__ *.py[cod] *.agdai', manifest)
        self.assertNotIn('recursive-include .git ', manifest)

    def test_package_version_has_single_literal_source_and_docs_distinguish_release_limits(self):
        tree = ast.parse((ROOT / 'src/agda_evidence/__init__.py').read_text(encoding='utf-8'))
        values = [ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == '__version__' for t in n.targets)]
        self.assertEqual(values, ['0.1.0a2'])
        config = (ROOT / 'pyproject.toml').read_text(encoding='utf-8')
        self.assertIn('version = {attr = "agda_evidence.__version__"}', config)
        docs = (ROOT / 'docs/alpha-release.md').read_text(encoding='utf-8')
        for required in ('13 canonical JSON schemas', 'historical support guide', 'all eight expected jobs',
                         'does not publish to PyPI', 'contextual-elaboration-only', '3% slower',
                         'same ordinary-CI wheel/source bytes', 'not a new evidence certificate'):
            self.assertIn(required, docs)


if __name__ == '__main__':
    unittest.main()
