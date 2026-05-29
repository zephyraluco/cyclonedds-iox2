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

source $HOME/.cargo/env

git submodule update --init --recursive

IOX2_BUILD_CXX=OFF
if [ "$BUILD_CXX" = true ]; then
  IOX2_BUILD_CXX=ON
fi

# build cyclonedds with iceoryx2
cd ${route}/../iceoryx2
cargo build --release --package iceoryx2-ffi-c
cmake -S . -B target/ffi/build -DCMAKE_INSTALL_PREFIX=/usr/local -DCMAKE_BUILD_TYPE=Release -DBUILD_CXX=${IOX2_BUILD_CXX} -DRUST_BUILD_ARTIFACT_PATH="$( pwd )/target/release"
cmake --build target/ffi/build &&  DESTDIR=${route}/../install cmake --install target/ffi/build

cd ${route}/../cyclonedds
cmake -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr/local -DENABLE_ICEORYX2=On -DCMAKE_PREFIX_PATH=${route}/../install/usr/local
cmake --build build --config Release
DESTDIR=${route}/../install cmake --install build

# build cyclonedds-cxx
if [ "$BUILD_CXX" = true ]; then
  cd ${route}/../cyclonedds-cxx
  cmake -B build -DCMAKE_INSTALL_PREFIX=/usr/local -DBUILD_DDSLIB=ON -DENABLE_TYPELIB=YES -DENABLE_TOPIC_DISCOVERY=YES -DENABLE_QOS_PROVIDER=YES -DCMAKE_PREFIX_PATH=${route}/../install/usr/local
  cmake --build build --config Release
  DESTDIR=${route}/../install cmake --install build
fi
