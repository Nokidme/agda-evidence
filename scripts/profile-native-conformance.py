#!/usr/bin/env python3
"""Profile finite native conformance in an installed consumer; not an SLA benchmark.

The supplied runner imports the installed package normally. Profiling changes
execution overhead; use separate unprofiled runs for latency comparisons.
Compiler/library provisioning is external. No freshness checks are bypassed.
"""
from __future__ import annotations

import argparse
import cProfile
import importlib.util
import json
from pathlib import Path
import pstats
import sys
import time


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runner', type=Path, required=True)
    parser.add_argument('--agda-bin', required=True)
    parser.add_argument('--expected-version', required=True)
    parser.add_argument('--profile', choices=('builtin','stdlib-function'), default='builtin')
    parser.add_argument('--dependency-root', type=Path)
    parser.add_argument('--timeout-seconds', type=int, default=20)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    runner = args.runner.resolve(strict=True)
    output = args.output.resolve()
    protected = [runner.parent.parent]
    if args.dependency_root:
        protected.append(args.dependency_root.resolve(strict=True))
    if args.output.is_symlink() or output.exists() or any(output.is_relative_to(p) or p.is_relative_to(output) for p in protected):
        parser.error('output must be a new external directory, not overlapping sources')
    spec = importlib.util.spec_from_file_location('agda_finite_conformance_runner', runner)
    if spec is None or spec.loader is None:
        parser.error('runner must be a loadable finite Python script')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output.mkdir(parents=True)
    profiler = cProfile.Profile()
    started = time.perf_counter()
    result = None
    try:
        result = profiler.runcall(module.run_conformance, agda_binary=args.agda_bin,
            expected_version=args.expected_version, profile=args.profile,
            dependency_root=args.dependency_root, timeout_seconds=args.timeout_seconds,
            output=output / 'conformance')
    finally:
        elapsed = time.perf_counter() - started
        profiler.dump_stats(str(output / 'conformance.pstats'))
        stats = pstats.Stats(profiler)
        functions = []
        for (filename,line,function), (primitive,total,self_seconds,cumulative,callers) in stats.stats.items():
            functions.append({'filename':filename,'line':line,'function':function,
                              'primitiveCalls':primitive,'totalCalls':total,
                              'selfSeconds':self_seconds,'cumulativeSeconds':cumulative})
        functions.sort(key=lambda v:(-v['cumulativeSeconds'],v['filename'],v['line']))
        report = {'format':'agda-evidence/development-profile-v1','conformanceStatus':result['status'] if result else 'failed',
                  'elapsedSeconds':elapsed,'timingMeaning':'cProfile-instrumented finite run; cumulative spans overlap; not unprofiled latency or CPU',
                  'python':sys.version,'functions':functions}
        (output / 'profile.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
        print(f"PROFILE {report['conformanceStatus']}: {output / 'profile.json'}",flush=True)
        for value in functions:
            if 'agda_evidence' in value['filename'] and value['cumulativeSeconds'] > 0.2:
                print(f"{value['function']}: calls={value['totalCalls']} cumulative={value['cumulativeSeconds']:.3f}s self={value['selfSeconds']:.3f}s",flush=True)
    return 0 if result and result['status']=='passed' else 1


if __name__=='__main__':
    raise SystemExit(main())
