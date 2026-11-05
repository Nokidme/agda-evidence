#!/usr/bin/env python3
"""Finite verified-byte discovery pilot; lexical reuse is not freshness or scope.

Use installed packages normally, with explicit externally provisioned Agda and
stdlib. Native timeout is 20 seconds; dependency gate budget is 180 seconds.
Retain warm/cold scan counts and host-call timings, not an SLA or CPU benchmark.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from unittest.mock import patch

from agda_evidence import core
from agda_evidence.catalog import create_catalog
from agda_evidence.source_research import SourceResearchWorkspace
from agda_evidence.sources import validate_source_observation

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise core.EvidenceError(message)


def run_pilot(*, dependency_root: Path, agda_binary: str, expected_version: str,
              output: Path, expect_reuse: bool = False) -> dict:
    require(re.fullmatch(r'[0-9]+(?:\.[0-9]+){2,7}', expected_version) is not None, 'exact numeric compiler version required')
    dependency = dependency_root.resolve()
    destination = output.resolve()
    require(not dependency_root.is_symlink() and dependency.is_dir() and
            (dependency/'src/Function/Base.agda').is_file(), 'explicit regular stdlib Function.Base source required')
    require(not output.is_symlink() and not destination.exists(), 'new output directory required')
    for protected in (ROOT,dependency):
        require(not destination.is_relative_to(protected) and not protected.is_relative_to(destination),
                'output must not overlap protected source')
    binary = shutil.which(agda_binary)
    require(binary is not None, 'explicit native compiler not found')
    binary = str(Path(binary).resolve())
    process = subprocess.run([binary,'--version'], capture_output=True,text=True,timeout=20,check=True)
    require(process.stdout.strip()=='Agda version '+expected_version, 'actual compiler differs from explicit expected version')
    destination.mkdir(parents=True)
    report = {'format':'agda-evidence/discovery-pilot-report-v1','status':'failed',
              'actualVersion':expected_version,'expectReuse':expect_reuse,'nativeTimeoutSeconds':20,
              'gateTimeoutSeconds':180,'timings':[],'records':{},'originalSourcesUnchanged':False,
              'limits':'Finite single-host samples; scanner counts omit only repeated lexical work, never byte checks. Timings include observations/validation; not compiler CPU, statistical significance or SLA.'}
    exchanges=[]
    def save(path,value):
        path.write_bytes(core.canonical_json_bytes(value)+b'\n')
    try:
        registry=destination/'registry';registry.mkdir()
        client=destination/'client';client.mkdir()
        (client/'Main.agda').write_text('{-# OPTIONS --safe #-}\nmodule Main where\n'
            'open import Agda.Builtin.Nat using (Nat)\nopen import Function.Base using (id)\n'
            'goal : Nat → Nat\ngoal n = {! !}\n',encoding='utf-8')
        (client/'notes.txt').write_bytes(b'non-indexed original input\n')
        client_before=core.build_snapshot(client)[0]
        dependency_before=core.build_snapshot(dependency)[0]
        with patch.dict(os.environ,{'AGDA_DIR':str(registry)}):
            index=core.build_declaration_index(dependency,dependency_before)
            core.write_declaration_index(destination/'dependency.index.json',index)
            bundle=destination/'dependency.evidence'
            core.capture_bundle(dependency,bundle,[binary,'--safe','--no-libraries','--ignore-interfaces','-i','src','src/Function/Base.agda'],
                                agda_binary=binary,scope='native discovery pilot: explicit Function.Base check, not all stdlib',
                                index_reference=destination/'dependency.index.json',timeout_seconds=180)
            manifest,components=core.load_verified_bundle(bundle)
            require(components['attestation.json']['outcome']['status']=='passed','native dependency gate did not pass')
            catalog=destination/'catalog.json'
            create_catalog(catalog,[('stdlib',bundle)])
            workspace=SourceResearchWorkspace(client,{'main':'Main.agda'},dependency_root=dependency,
                dependency_bundle=bundle,dependency_includes=['src'],agda_binary=binary,safe=True,
                catalog=catalog,timeout_seconds=20,max_stored_bytes=134217728)
            def call(op,revision=None,expected='ok',**params):
                request={'apiVersion':2,'requestId':f'discovery-{len(exchanges)+1}',
                         'op':op,'revision':revision,'args':params}
                with patch.object(core,'_lexical_candidates_for_file',wraps=core._lexical_candidates_for_file) as scan, \
                     patch.object(core,'sha256_file',wraps=core.sha256_file) as hashes:
                    started=time.monotonic()
                    response=workspace.handle(request)
                    elapsed=time.monotonic()-started
                exchanges.append({'request':request,'response':response})
                report['timings'].append({'op':op,'scope':params.get('scope'),'elapsedSeconds':elapsed,
                                          'scannerCalls':scan.call_count,'fileHashCalls':hashes.call_count,
                                          'status':response['status']})
                save(destination/'exchanges.json',exchanges)
                save(destination/'summary.json',report)
                require(response['status']==expected,f'{op} returned {response}')
                return response
            def listing(revision,name):
                listed=call('goals.list',revision,documentId='main')
                require(listed['result']['outcome']['status']=='listed','native client did not list a goal')
                fetched=call('record.get',recordId=listed['recordId'])
                value=validate_source_observation(fetched['result']['artifact'])
                require(fetched['result']['freshness']=='current','new listing is not current')
                save(destination/name,value)
                report['records'][name]={'sourceObservationId':value['sourceObservationId'],'recordId':listed['recordId']}
                return listed,listed['result']['outcome']['goals'][0]['id']
            state=call('workspace.status');revision=state['currentRevision']
            report['initialWorkspace']=state['workspace']
            report['dependencyBundleId']=manifest['bundleId']
            selected,goal=listing(revision,'listing.source.json')
            first={}
            for round in range(2):
                for scope in ('dependency','project','all'):
                    name='Main' if scope=='project' else 'Function.Base'
                    response=call('library.search',revision,listingId=selected['recordId'],goalId=goal,
                                  prefix=name,scope=scope,limit=100)
                    result=response['result']
                    require(result['entries'] and result['contextualRanking'] is False,'expected lexical candidates absent')
                    require(all(hit['scopeStatus']=='not-established' and hit['candidateUsability']=='not-tested' for hit in result['entries']),
                            'discovery implied scope or candidate usability')
                    if round==0:
                        first[scope]=result
                    else:
                        require(core.canonical_json_bytes(result)==core.canonical_json_bytes(first[scope]),
                                'repeated search changed candidates/provenance/context')
                        if expect_reuse:require(report['timings'][-1]['scannerCalls']==0,'warm search repeated lexical scanning')
                    if scope=='all':
                        require({'dependency','catalog'} <= {hit['origin'] for hit in result['entries']},'cross-origin discovery lost provenance')
            report['repeatedSearchEquality']=True
            workspace.notify_buffers(dirty=True);workspace.notify_buffers(dirty=False)
            stale=call('library.search',revision,expected='stale',listingId=selected['recordId'],goalId=goal,prefix='Function.Base',scope='dependency')
            require(stale['error']['code']=='workspace-changed','dirty/clean notification failed to invalidate selection')
            state=call('workspace.status');revision=state['currentRevision']
            selected,goal=listing(revision,'relisted.source.json')
            for round in range(2):
                call('library.search',revision,listingId=selected['recordId'],goalId=goal,prefix='Function.Base',scope='dependency')
                count=report['timings'][-1]['scannerCalls']
                if expect_reuse:require(count>0 if round==0 else count==0,'new generation did not cold/warm scan correctly')
            # Mutate a non-indexed client input without notification, preserving length/mtime.
            marker=client/'notes.txt';before=marker.stat();original=marker.read_bytes()
            marker.write_bytes(original.replace(b'original',b'ORIGINAL'));os.utime(marker,ns=(before.st_atime_ns,before.st_mtime_ns))
            try:
                refused=call('library.search',revision,expected='stale',listingId=selected['recordId'],goalId=goal,prefix='Function.Base',scope='dependency')
                require(refused['error']['code']=='workspace-changed','same-metadata non-source edit was not detected')
                history=call('record.get',recordId=selected['recordId'])
                require(history['result']['freshness']=='stale','changed input promoted prior evidence')
            finally:
                marker.write_bytes(original);os.utime(marker,ns=(before.st_atime_ns,before.st_mtime_ns))
            workspace.notify_buffers(dirty=False)
            report['sameMetadataNonSourceEditRejected']=True
            report['catalogStillVerified']=True
        report['originalSourcesUnchanged']=(core.build_snapshot(client)[0]['sourceId']==client_before['sourceId'] and
                                            core.build_snapshot(dependency)[0]['sourceId']==dependency_before['sourceId'])
        require(report['originalSourcesUnchanged'],'pilot changed original inputs')
        report['status']='passed'
    except Exception as error:
        report['error']={'type':type(error).__name__,'message':str(error)}
        raise
    finally:
        save(destination/'summary.json',report)
        print(f"DISCOVERY {report['status']}: {destination/'summary.json'}",flush=True)
        for timing in report['timings']:
            if timing['op']=='library.search':
                print(f"SEARCH {timing['scope']}: status={timing['status']} elapsed={timing['elapsedSeconds']:.3f}s scannerCalls={timing['scannerCalls']} hashCalls={timing['fileHashCalls']}",flush=True)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dependency-root',type=Path,required=True)
    parser.add_argument('--agda-bin',required=True)
    parser.add_argument('--expected-version',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--expect-reuse',action='store_true')
    args=parser.parse_args()
    run_pilot(dependency_root=args.dependency_root,agda_binary=args.agda_bin,
              expected_version=args.expected_version,output=args.output,expect_reuse=args.expect_reuse)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
