#!/usr/bin/env python3
"""Run finite native conformance against fresh wheel/source installs, not a checkout.

Compiler/library provisioning is separate. Source install may fetch build tools;
this is not an offline replay, SLA, production deployment or benchmark service.
"""
from __future__ import annotations

import argparse
from email.parser import Parser
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import venv
import zipfile


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dist-dir', type=Path, required=True)
    parser.add_argument('--runner', type=Path, required=True)
    parser.add_argument('--agda-bin', required=True)
    parser.add_argument('--expected-version', required=True)
    parser.add_argument('--dependency-root', type=Path, help='optional already-provisioned stdlib Function.Base profile')
    parser.add_argument('--timeout-seconds', type=int, default=20)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    directory, script = args.dist_dir.resolve(strict=True), args.runner.resolve(strict=True)
    output = args.output.resolve()
    wheels, sources = sorted(directory.glob('*.whl')), sorted(directory.glob('*.tar.gz'))
    if len(wheels) != 1 or len(sources) != 1:
        parser.error('dist-dir must contain exactly one wheel and one source archive')
    if not 1 <= args.timeout_seconds <= 300:
        parser.error('timeout-seconds must be 1..300')
    if args.output.exists() or args.output.is_symlink() or output.is_relative_to(script.parent.parent):
        parser.error('output must be a new external directory')
    dependency = args.dependency_root.resolve(strict=True) if args.dependency_root else None
    if dependency is not None and (not dependency.is_dir() or output.is_relative_to(dependency)):
        parser.error('dependency must be a directory outside output')
    binary = shutil.which(args.agda_bin)
    if binary is None:
        parser.error('native compiler must be separately provisioned')
    binary = str(Path(binary).resolve())
    with zipfile.ZipFile(wheels[0]) as archive:
        names = [n for n in archive.namelist() if n.endswith('.dist-info/METADATA')]
        if len(names) != 1 or Parser().parsestr(archive.read(names[0]).decode('utf-8')).get_all('Requires-Dist'):
            parser.error('wheel must have unambiguous metadata and no runtime dependencies')
    output.mkdir(parents=True)
    environment = dict(os.environ)
    for key in ('PYTHONPATH', 'PYTHONHOME'):
        environment.pop(key, None)
    environment['PIP_DISABLE_PIP_VERSION_CHECK'] = '1'
    reports = []
    result = 0
    for artifact in (wheels[0], sources[0]):
        kind = 'wheel' if artifact.suffix == '.whl' else 'sdist'
        with tempfile.TemporaryDirectory(prefix='agda-native-consumer-') as temporary:
            root = Path(temporary)
            venv.EnvBuilder(with_pip=True).create(root / 'venv')
            python = root / 'venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
            consumer = root / 'consumer'
            consumer.mkdir()
            install = [str(python), '-I', '-m', 'pip', 'install', '--no-deps']
            if kind == 'wheel':
                install.append('--no-index')
            with (output / f'{kind}-install.log').open('w', encoding='utf-8') as log:
                subprocess.run([*install, str(artifact)], cwd=consumer, env=environment,
                               stdout=log, stderr=subprocess.STDOUT, check=True)
                subprocess.run([str(python), '-I', '-m', 'pip', 'check'], cwd=consumer, env=environment,
                               stdout=log, stderr=subprocess.STDOUT, check=True)
            profiles = [('builtin', None)]
            if dependency is not None:
                profiles.append(('stdlib-function', dependency))
            for profile, source in profiles:
                destination = output / f'{kind}-{profile}'
                command = [str(python), '-I', str(script), '--agda-bin', binary,
                           '--expected-version', args.expected_version, '--profile', profile,
                           '--timeout-seconds', str(args.timeout_seconds), '--output', str(destination)]
                if source is not None:
                    command.extend(['--dependency-root', str(source)])
                print(f'CONFORMANCE {kind} / {profile} / expected Agda {args.expected_version}', flush=True)
                with (output / f'{kind}-{profile}.log').open('w', encoding='utf-8') as log:
                    completed = subprocess.run(command, cwd=consumer, env=environment,
                                               stdout=log, stderr=subprocess.STDOUT, check=False)
                reports.append({'artifact': artifact.name, 'consumer': kind, 'profile': profile,
                                'exitCode': completed.returncode, 'report': f'{destination.name}/summary.json'})
                (output / 'consumers.json').write_text(json.dumps(reports, indent=2) + '\n', encoding='utf-8')
                if completed.returncode:
                    result = 1
                print(f'CONFORMANCE {kind} / {profile}: exitCode={completed.returncode}; retained output={destination.name}', flush=True)
    return result


if __name__ == '__main__':
    raise SystemExit(main())
