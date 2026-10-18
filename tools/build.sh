#!/bin/bash

set -e
script=$(readlink -f "$0")
route=$(dirname "$script")

BUILD_CXX=false
for arg in "$@"; do
  case "$arg" in
    --build-cxx) BUILD_CXX=true ;;
  esac
done

# Rust may already be activated by CI or use a non-default CARGO_HOME.
if [ -f "${CARGO_HOME:-$HOME/.cargo}/env" ]; then
  source "${CARGO_HOME:-$HOME/.cargo}/env"
elif [ -f "$HOME/.cargo/env" ]; then
  source "$HOME/.cargo/env"
fi
command -v cargo >/dev/null || { echo "Rust/cargo is required" >&2; exit 1; }

git submodule update --init --recursive

IOX2_BUILD_CXX=OFF
if [ "$BUILD_CXX" = true ]; then
  IOX2_BUILD_CXX=ON
fi

# build cyclonedds with iceoryx2
cd ${route}/../iceoryx2
cargo build --locked --release --package iceoryx2-ffi-c
cmake -S . -B target/ffi/build -DCMAKE_INSTALL_PREFIX=/usr/local -DCMAKE_BUILD_TYPE=Release -DBUILD_CXX=${IOX2_BUILD_CXX} -DRUST_BUILD_ARTIFACT_PATH="$( pwd )/target/release"
cmake --build target/ffi/build &&  DESTDIR=${route}/../install cmake --install target/ffi/build

cd ${route}/../cyclonedds
cmake -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr/local -DENABLE_ICEORYX2=On -DCMAKE_PREFIX_PATH=${route}/../install/usr/local
cmake --build build --config Release
DESTDIR=${route}/../install cmake --install build

# build cyclonedds-cxx
if [ "$BUILD_CXX" = true ]; then
  cd ${route}/../cyclonedds-cxx
  cmake -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr/local -DBUILD_DDSLIB=ON -DENABLE_TYPELIB=YES -DENABLE_TOPIC_DISCOVERY=YES -DENABLE_QOS_PROVIDER=YES -DCMAKE_PREFIX_PATH=${route}/../install/usr/local
  cmake --build build --config Release
  DESTDIR=${route}/../install cmake --install build
fi
