#!/bin/bash

set -e
script=$(readlink -f "$0")
route=$(dirname "$script")

source $HOME/.cargo/env

git submodule update --init --recursive

# build cyclonedds with iceoryx2
cd ${route}/../iceoryx2
cargo build --release --package iceoryx2-ffi-c
cmake -S . -B target/ffi/build -DCMAKE_INSTALL_PREFIX=../install -DBUILD_CXX_BINDING=OFF -DRUST_BUILD_ARTIFACT_PATH="$( pwd )/target/release"
cmake --build target/ffi/build &&  cmake --install target/ffi/build

cd ${route}/../cyclonedds
cmake -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=../install -DENABLE_ICEORYX2=On -DCMAKE_PREFIX_PATH=../install
cmake --build build --config Release --target install

# build cyclonedds-cxx
cd ${route}/../cyclonedds-cxx
cmake -B build -DCMAKE_INSTALL_PREFIX=../install -DBUILD_DDSLIB=ON -DENABLE_TYPELIB=YES -DENABLE_TOPIC_DISCOVERY=YES -DENABLE_QOS_PROVIDER=YES
cmake --build build --config Release --target install
