#!/usr/bin/env python3
"""Probe the upstream high-level API without disguising a fallback as SHM."""
import argparse
import json
import os
from pathlib import Path
import resource
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build', type=Path, default=ROOT/'build/benchmarks')
    p.add_argument('--prefix', type=Path, default=Path(os.environ.get('CYCLONEDDS_HOME', ROOT/'install/usr/local')))
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    for mode in ['udp', 'iox2']:
        env = dict(os.environ, CYCLONEDDS_URI=str(ROOT/'config'/f'{mode}.xml'))
        env['LD_LIBRARY_PATH'] = os.pathsep.join([str(args.prefix/'lib'), str(args.build), env.get('LD_LIBRARY_PATH', '')])
        binary = str(args.build/'rust/release/high_level_probe')
        session = uuid.uuid4().hex[:16]
        with (args.output/f'{mode}-server.log').open('w') as log:
            server = subprocess.Popen([binary, 'server', session], env=env, cwd=ROOT,
                stdout=log, stderr=subprocess.STDOUT,
                preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_CORE, (0,0)))
            try:
                client = subprocess.run([binary, 'client', session], env=env, cwd=ROOT,
                    capture_output=True, text=True, timeout=15,
                    preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_CORE, (0,0)))
                (args.output/f'{mode}-client.log').write_text(client.stdout+client.stderr)
                server.wait(timeout=15)
            finally:
                if server.poll() is None:
                    server.kill()
                    server.wait()
        logs = (args.output/f'{mode}-server.log').read_text()+client.stdout+client.stderr
        if client.returncode == server.returncode == 0:
            outcome = 'passed'
        elif mode == 'iox2' and ('serdata_ops::from_psmx' in logs or 'serdata_ops::from_loaned_sample' in logs):
            outcome = 'unsupported_upstream_psmx_callback'
        else:
            raise RuntimeError(f'unexplained high-level {mode} failure; inspect {args.output}')
        result = dict(mode=mode, outcome=outcome, client_exit=client.returncode, server_exit=server.returncode)
        results.append(result)
        print(result, flush=True)
    (args.output/'results.json').write_text(json.dumps(results, indent=2))
    if results[0]['outcome'] != 'passed':
        raise RuntimeError('high-level UDP control did not pass')

if __name__ == '__main__':
    main()
