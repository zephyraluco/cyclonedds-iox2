#!/usr/bin/env python3
"""Run isolated pairs, validate data/transport, retain every measured trial."""
import argparse
import hashlib
import itertools
import json
import os
from pathlib import Path
import platform
import random
import selectors
import statistics
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
MODES = {"udp": (0, 0, "udp.xml"), "iox2-copy": (0, 1, "iox2.xml"),
         "iox2-loan": (1, 1, "iox2.xml")}


def tx_bytes():
    for line in Path("/proc/net/dev").read_text().splitlines():
        if line.split(":")[0].strip() == "lo":
            return int(line.split(":")[1].split()[8])
    raise RuntimeError("Linux loopback network counters unavailable")


def revision(path):
    return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()


def cpu_stat():
    path = Path("/sys/fs/cgroup/cpu.stat")
    if not path.exists():
        return {}
    return {key: int(value) for key, value in (line.split() for line in path.read_text().splitlines())}


def wait_ready(proc, timeout, marker="READY"):
    deadline = time.monotonic() + timeout
    lines = []
    # Each executable emits READY only after discovery AND warmup complete.
    with selectors.DefaultSelector() as selector:
        selector.register(proc.stdout, selectors.EVENT_READ)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                raise TimeoutError(f"process did not reach {marker}")
            line = proc.stdout.readline()
            if not line:
                raise RuntimeError(f"process exited before {marker}; inspect stderr logs")
            lines.append(line)
            if line.strip() == marker:
                return "".join(lines)


def run_pair(args, language, mode, size, window, repeat, server_language=None):
    server_language = server_language or language
    loan, shm, config = MODES[mode]
    session = uuid.uuid4().hex[:16]
    label = f"{language}-{server_language}-{mode}-{size}-w{window}-r{repeat}"
    executables = {"c": args.build / "bench_c", "cpp": args.build / "bench_cpp",
                   "rust": args.build / "rust/release/shm-bench-rust"}
    env = dict(os.environ)
    env["CYCLONEDDS_URI"] = str(ROOT / "config" / config)
    env["LD_LIBRARY_PATH"] = os.pathsep.join(
        [str(args.prefix / "lib"), str(args.prefix / "lib64"), str(args.build), env.get("LD_LIBRARY_PATH", "")])
    common = [str(size), str(args.samples), str(args.warmup), str(window), str(loan),
              str(shm), str(args.domain), session]
    with (args.output / f"{label}.server.stderr").open("w") as server_err, \
         (args.output / f"{label}.client.stderr").open("w") as client_err, \
         (args.output / f"{label}.server.stdout").open("w") as server_out:
        server = subprocess.Popen([str(executables[server_language]), "server", *common],
                                  env=env, cwd=ROOT, stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=server_err, text=True)
        client = None
        try:
            client = subprocess.Popen([str(executables[language]), "client", *common],
                env=env, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=client_err, text=True)
            # A local match does not prove the remote reader has discovered us.
            # Both sides must confirm bidirectional matches before any data.
            server_prefix = wait_ready(server, args.timeout, "DISCOVERED")
            prefix = wait_ready(client, args.timeout, "DISCOVERED")
            server.stdin.write("\n")
            server.stdin.flush()
            client.stdin.write("\n")
            client.stdin.flush()
            prefix += wait_ready(client, args.timeout)
            network_start = tx_bytes()
            cpu_start = cpu_stat()
            stdout, _ = client.communicate("\n", timeout=args.timeout)
            network_end = tx_bytes()
            cpu_end = cpu_stat()
            server.wait(timeout=args.timeout)
            server_out.write(server_prefix + server.stdout.read())
            (args.output / f"{label}.client.stdout").write_text(prefix + stdout)
            if client.returncode or server.returncode:
                raise RuntimeError(f"{label}: client={client.returncode}, server={server.returncode}")
            diagnostics = (args.output / f"{label}.server.stderr").read_text() + \
                          (args.output / f"{label}.client.stderr").read_text()
            if "=== [ICEORYX2]Failed" in diagnostics:
                raise RuntimeError(f"{label}: plugin reported a receive/delivery error; inspect stderr logs")
            rows = [json.loads(line) for line in stdout.splitlines() if line.startswith("{")]
            if len(rows) != 1:
                raise RuntimeError(f"{label}: expected one JSON result")
            result = rows[0]
            expected = {"samples": args.samples, "size_bytes": size, "window": window,
                        "loan": loan, "shm": shm, "language": language}
            if any(result.get(key) != value for key, value in expected.items()):
                raise RuntimeError(f"{label}: result parameters differ from requested case")
            result.update(mode=mode, repeat=repeat, server_language=server_language,
                          loopback_tx_bytes=network_end-network_start,
                          log_prefix=label, status="passed")
            result["cgroup_cpu_stat_delta"] = {key: cpu_end[key] - cpu_start.get(key, 0) for key in cpu_end}
            # Observational network evidence, not a pass/fail speed threshold.
            return result
        finally:
            for proc in [client, server]:
                if proc is not None and proc.poll() is None:
                    proc.kill()
                    proc.wait()


def aggregate(results):
    groups = {}
    for row in results:
        key = (row["language"], row["server_language"], row["size_bytes"], row["window"], row["mode"])
        groups.setdefault(key, []).append(row)
    summary = []
    for (language, server, size, window, mode), rows in sorted(groups.items()):
        out = dict(language=language, server_language=server, size_bytes=size, window=window,
                   mode=mode, repeats=len(rows))
        for name in ["p50_rtt_us", "p99_rtt_us", "samples_per_s", "payload_mib_per_s", "loopback_tx_bytes"]:
            values = [row[name] for row in rows]
            out[name] = statistics.median(values)
            out[name + "_min"] = min(values)
            out[name + "_max"] = max(values)
        summary.append(out)
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--build", type=Path, default=ROOT / "build/benchmarks")
    p.add_argument("--prefix", type=Path, default=Path(os.environ.get("CYCLONEDDS_HOME", ROOT / "install/usr/local")))
    p.add_argument("--output", type=Path, default=ROOT / "benchmarks/results")
    p.add_argument("--languages", nargs="+", choices=["c", "cpp", "rust"], default=["c", "cpp", "rust"])
    p.add_argument("--modes", nargs="+", choices=MODES, default=list(MODES))
    p.add_argument("--sizes", nargs="+", type=int, choices=[64, 4096, 65536], default=[64, 4096, 65536])
    p.add_argument("--windows", nargs="+", type=int, choices=range(1, 17), default=[1, 16])
    p.add_argument("--samples", type=int, default=1024)
    p.add_argument("--warmup", type=int, default=128)
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--domain", type=int, default=71)
    p.add_argument("--timeout", type=float, default=40)
    p.add_argument("--seed", type=int, default=20261018)
    p.add_argument("--interop", action="store_true", help="also test all directed language pairs (64 B, window 1)")
    args = p.parse_args()
    if not (1 <= args.samples <= 1000000 and 0 <= args.warmup <= 1000000 and
            args.repeats >= 1 and 0 <= args.domain <= 200 and args.timeout > 0):
        p.error("invalid count, domain, or timeout")
    for key in ["build", "prefix", "output"]:
        setattr(args, key, getattr(args, key).resolve())
    args.output.mkdir(parents=True, exist_ok=True)
    if (args.output / "raw.jsonl").exists():
        p.error("output already contains a run; choose a new --output directory")
    metadata = {"timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "platform": platform.platform(), "machine": platform.machine(),
                "cpu_affinity": sorted(os.sched_getaffinity(0)),
                "versions": {name: revision(ROOT / name) for name in ["cyclonedds", "cyclonedds-cxx", "iceoryx2"]},
                "parent_commit": revision(ROOT), "working_tree": subprocess.check_output(
                    ["git", "-C", str(ROOT), "status", "--short"], text=True),
                "parameters": {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()}}
    metadata["cyclonedds_rust_revision"] = "ef0dd5cc1477b29449aba1f717d9496db5953b2a"
    metadata["toolchains"] = {}
    for tool in ["cc", "c++", "rustc", "cmake"]:
        metadata["toolchains"][tool] = subprocess.check_output([tool, "--version"], text=True).splitlines()[0]
    metadata["config_sha256"] = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                   for path in sorted((ROOT / "config").glob("*")) if path.is_file()}
    source_files = [path for path in (ROOT / "benchmarks").rglob("*") if path.is_file()
                    and "results" not in path.relative_to(ROOT / "benchmarks").parts
                    and path.suffix in {".c", ".cpp", ".h", ".rs", ".idl", ".toml", ".lock", ".py"}]
    source_files += [ROOT / "benchmarks/CMakeLists.txt", ROOT / "tools/build_benchmarks.sh"]
    metadata["source_sha256"] = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                   for path in sorted(source_files)}
    metadata["binary_sha256"] = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in [args.build / "bench_c", args.build / "bench_cpp",
                     args.build / "rust/release/shm-bench-rust"] if path.is_file()}
    metadata["library_sha256"] = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((args.prefix / "lib").glob("*.so")) if path.is_file()}
    for path in ["/sys/fs/cgroup/cpu.max", "/sys/fs/cgroup/memory.max", "/proc/cpuinfo"]:
        if Path(path).exists():
            metadata[path] = Path(path).read_text()
    (args.output / "metadata.json").write_text(json.dumps(metadata, indent=2))
    cases = list(itertools.product(args.languages, args.modes, args.sizes, args.windows, range(args.repeats)))
    random.Random(args.seed).shuffle(cases)
    results = []
    with (args.output / "raw.jsonl").open("w") as raw:
        def record(row):
            results.append(row)
            raw.write(json.dumps(row) + "\n")
            raw.flush()
            print(f"PASS {row['log_prefix']}: p50={row['p50_rtt_us']:.2f} us, {row['payload_mib_per_s']:.2f} MiB/s", flush=True)
        try:
            for case in cases:
                record(run_pair(args, *case))
            if args.interop:
                for client, server in itertools.permutations(args.languages, 2):
                    for mode in args.modes:
                        record(run_pair(args, client, mode, 64, 1, 0, server))
        except Exception as error:
            (args.output / "failure.txt").write_text(str(error))
            raise
    (args.output / "summary.json").write_text(json.dumps(aggregate(results), indent=2))
    print(f"Completed {len(results)} process-pair tests; results: {args.output}")


if __name__ == "__main__":
    main()
