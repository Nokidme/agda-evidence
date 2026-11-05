#!/usr/bin/env python3
"""Compare finite conformance in two fresh installed wheels; not an SLA benchmark.

Alternates before/after order. No caching, policies or native timeouts are changed.
Single-host measurements have noise and warming effects, not statistical proof.
"""
from __future__ import annotations

import argparse
from email.parser import Parser
import json
import os
from pathlib import Path
import statistics
import subprocess
import tempfile
import venv
import zipfile


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before-wheel', type=Path, required=True)
    parser.add_argument('--after-wheel', type=Path, required=True)
    parser.add_argument('--runner', type=Path, required=True)
    parser.add_argument('--agda-bin', required=True)
    parser.add_argument('--expected-version', required=True)
    parser.add_argument('--profile', choices=('builtin','stdlib-function'), default='builtin')
    parser.add_argument('--dependency-root', type=Path)
    parser.add_argument('--repetitions', type=int, default=2)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.repetitions <= 3:
        parser.error('repetitions must be 1..3')
    if (args.profile=='stdlib-function') != (args.dependency_root is not None):
        parser.error('dependency-root is required only for stdlib-function')
    runner = args.runner.resolve(strict=True)
    output = args.output.resolve()
    protected = [runner.parent.parent]
    if args.dependency_root:
        protected.append(args.dependency_root.resolve(strict=True))
    if args.output.is_symlink() or output.exists() or any(output.is_relative_to(p) or p.is_relative_to(output) for p in protected):
        parser.error('output must be a new external directory not overlapping sources')
    wheels = {'before':args.before_wheel.resolve(strict=True),'after':args.after_wheel.resolve(strict=True)}
    identities = {}
    for label,path in wheels.items():
        if path.suffix != '.whl':
            parser.error('before/after inputs must be built wheels')
        with zipfile.ZipFile(path) as archive:
            metadata = [n for n in archive.namelist() if n.endswith('.dist-info/METADATA')]
            if len(metadata)!=1:
                parser.error('wheel must have exactly one metadata file')
            parsed = Parser().parsestr(archive.read(metadata[0]).decode('utf-8'))
            if parsed.get_all('Requires-Dist'):
                parser.error('wheel must have no runtime dependencies')
            import hashlib
            identities[label]={'filename':path.name,'version':parsed['Version'],
                               'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    environment = dict(os.environ)
    for name in ('PYTHONPATH','PYTHONHOME'):
        environment.pop(name,None)
    environment['PIP_DISABLE_PIP_VERSION_CHECK']='1'
    output.mkdir(parents=True)
    runs=[]
    failed=False
    with tempfile.TemporaryDirectory(prefix='agda-comparison-consumers-') as temporary:
        root=Path(temporary)
        interpreters={}
        for label,wheel in wheels.items():
            venv.EnvBuilder(with_pip=True).create(root/label)
            python=root/label/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
            interpreters[label]=str(python)
            with (output/f'{label}-install.log').open('w',encoding='utf-8') as log:
                subprocess.run([str(python),'-I','-m','pip','install','--no-deps','--no-index',str(wheel)],
                               cwd=root,env=environment,stdout=log,stderr=subprocess.STDOUT,check=True)
                subprocess.run([str(python),'-I','-m','pip','check'],cwd=root,env=environment,
                               stdout=log,stderr=subprocess.STDOUT,check=True)
        for repetition in range(args.repetitions):
            order=['before','after'] if repetition%2==0 else ['after','before']
            for label in order:
                name=f'{repetition+1}-{label}'
                command=[interpreters[label],'-I',str(runner),'--agda-bin',args.agda_bin,
                         '--expected-version',args.expected_version,'--profile',args.profile,
                         '--timeout-seconds','20','--output',str(output/name)]
                if args.dependency_root:
                    command.extend(['--dependency-root',str(args.dependency_root.resolve())])
                print(f'COMPARE sample={repetition+1} variant={label} profile={args.profile}',flush=True)
                with (output/f'{name}.log').open('w',encoding='utf-8') as log:
                    result=subprocess.run(command,cwd=root,env=environment,stdout=log,stderr=subprocess.STDOUT,check=False)
                runs.append({'sample':repetition+1,'variant':label,'exitCode':result.returncode,'report':f'{name}/summary.json'})
                (output/'runs.json').write_text(json.dumps(runs,indent=2)+'\n',encoding='utf-8')
                failed |= result.returncode != 0
                print(f'COMPARE sample={repetition+1} variant={label} exitCode={result.returncode}',flush=True)
    measurements={}
    for run in runs:
        report_path=output/run['report']
        if not report_path.is_file():
            failed=True
            continue
        report=json.loads(report_path.read_text())
        if report['status']!='passed' or report['actualVersion']!=args.expected_version or report['nativeTimeoutSeconds']!=20:
            failed=True
            continue
        for timing in report['timings']:
            if timing['role']!='host-call':
                continue
            key=timing['caseId']+'/'+timing['label']
            measurements.setdefault(key,{'before':[],'after':[]})[run['variant']].append(timing['elapsedSeconds'])
    medians={}
    for key,data in measurements.items():
        if data['before'] and data['after']:
            before,after=statistics.median(data['before']),statistics.median(data['after'])
            medians[key]={'beforeSeconds':before,'afterSeconds':after,
                          'beforeSamples':data['before'],'afterSamples':data['after'],
                          'changePercent':(after/before-1)*100 if before else None}
    summary={'format':'agda-evidence/finite-comparison-v1','status':'failed' if failed else 'passed',
             'expectedVersion':args.expected_version,'profile':args.profile,'repetitions':args.repetitions,
             'nativeTimeoutSeconds':20,'wheels':identities,'runs':runs,'measurements':medians,
             'limits':'Alternating-order single-host samples; warmed filesystem/OS scheduling effects remain; no SLA, CPU, statistical significance or production equivalence claim.'}
    (output/'comparison.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    for key,data in medians.items():
        if key in ['source-list/v2:goals.list','source-context/v2:goals.inspect','source-elaborated/v2:candidate.check']:
            print(f"COMPARE {key}: before={data['beforeSeconds']:.3f}s after={data['afterSeconds']:.3f}s change={data['changePercent']:.1f}%",flush=True)
    return 1 if failed else 0


if __name__=='__main__':
    raise SystemExit(main())
