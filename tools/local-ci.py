#!/usr/bin/env python3
"""Sequential local CI. Never creates Actions workflows or publishes artifacts."""
import importlib.util
import json
from pathlib import Path
import signal
import sys
from datetime import datetime, timezone

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parent.parent
spec=importlib.util.spec_from_file_location('phase6_local_ci',ROOT/'tools/run-phase6.py')
p6=importlib.util.module_from_spec(spec)
spec.loader.exec_module(p6)

def main():
    if sys.argv[1:]:
        print('LOCAL_CI INVALID_ARGUMENTS');return 2
    result={'schema_version':1,'status':'FAIL','started_at_utc':datetime.now(timezone.utc).isoformat(),
        'mode':'LOCAL_ONLY','github_actions':'FORBIDDEN','containers_started':0,'external_publications':0,
        'production_release':'BLOCKED','steps':[]}
    for event in (signal.SIGINT,signal.SIGTERM,signal.SIGALRM):signal.signal(event,p6.guard.interrupted)
    signal.alarm(2100)
    try:
        with p6.workspace() as (work,cleanup):
            result['cleanup']=cleanup
            for name,command,timeout,expected in (
                ('phase6',[sys.executable,'tools/run-phase6.py'],1860,0),
                ('verifier-contract',[sys.executable,'tools/test-phase6-verifier.py'],90,0),
                ('g6-local-gate',[sys.executable,'tools/verify-phase6.py'],60,0),
                ('inspect',[sys.executable,'tools/udak-cli.py','inspect','--format','json'],30,0),
                ('release-block',[sys.executable,'tools/release-gate.py','--format','json'],30,2)):
                result['steps'].append(p6.step(name,command,work,timeout=timeout,expected=expected))
            inspected=json.loads((work/'inspect.output').read_text())
            blocked=json.loads((work/'release-block.output').read_text())
            if inspected.get('status')!='VERIFIED_EVIDENCE' or blocked.get('status')!='BLOCKED' or blocked.get('authorize_publish') is not False:
                raise ValueError('Gate contract failed')
            result['evidence_sha512']=p6.hashes(('evidence/PHASE6-VALIDATION.json','evidence/PHASE6-VERIFIER-VALIDATION.json','evidence/PHASE6-GATE.json'))
            result['source_sha512']=p6.hashes(('tools/local-ci.py','tools/run-phase6.py'))
            result['status']='PASS'
    except BaseException as error:
        result['status']='FAIL';result['failure_type']=type(error).__name__
        if isinstance(error,RuntimeError):
            try:result['failed_step']=json.loads(str(error))
            except ValueError:pass
    finally:
        signal.alarm(0)
        p6.save('evidence/PHASE6-LOCAL-CI.json',result)
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result['status']=='PASS' else 1

if __name__=='__main__':raise SystemExit(main())
