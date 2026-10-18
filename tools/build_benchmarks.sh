#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
prefix=${CYCLONEDDS_HOME:-"$root/install/usr/local"}
build=${BENCH_BUILD_DIR:-"$root/build/benchmarks"}
cmake -S "$root/benchmarks" -B "$build" -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH="$prefix"
cmake --build "$build" --parallel "${CMAKE_BUILD_PARALLEL_LEVEL:-4}"
export CYCLONEDDS_HOME="$prefix"
export BENCH_NATIVE_DIR="$build"
cargo build --locked --release --manifest-path "$root/benchmarks/rust/Cargo.toml" --target-dir "$build/rust"
