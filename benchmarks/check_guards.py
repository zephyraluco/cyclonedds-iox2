#!/usr/bin/env python3
"""Verify that an accidentally disabled plugin cannot pass as a SHM result."""
import argparse
import json
import os
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build',type=Path,default=ROOT/'build/benchmarks')
    p.add_argument('--prefix',type=Path,default=Path(os.environ.get('CYCLONEDDS_HOME',ROOT/'install/usr/local')))
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ,CYCLONEDDS_URI=str(ROOT/'config/udp.xml'))
    env['LD_LIBRARY_PATH']=os.pathsep.join([str(args.prefix/'lib'),str(args.build),env.get('LD_LIBRARY_PATH','')])
    results=[]
    for lang,exe in [('c','bench_c'),('cpp','bench_cpp'),('rust','rust/release/shm-bench-rust')]:
        proc=subprocess.run([str(args.build/exe),'client','64','8','0','1','0','1','75','negative'],
            env=env,cwd=ROOT,capture_output=True,text=True,timeout=10)
        (args.output/f'{lang}.log').write_text(proc.stdout+proc.stderr)
        if proc.returncode==0 or not any(word in proc.stderr.lower() for word in ['shared-memory','shm mismatch']):
            raise RuntimeError(f'{lang} did not reject the UDP/shared-memory mismatch')
        results.append(dict(language=lang,outcome='rejected_wrong_transport',exit_code=proc.returncode))
    (args.output/'results.json').write_text(json.dumps(results,indent=2))
    print('Passed 3 negative transport guards')

if __name__=='__main__':main()
