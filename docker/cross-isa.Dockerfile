FROM ubuntu:24.04@sha256:534baea6a22c03a63003dbc8dbe78fe34bc0d7e595d9a9dc9834884ff530eb55

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    python3 gcc-arm-linux-gnueabihf g++-arm-linux-gnueabihf \
    gcc-riscv64-linux-gnu g++-riscv64-linux-gnu clang lld llvm \
    binutils-arm-linux-gnueabihf binutils-riscv64-linux-gnu strace ca-certificates && \
    rm -rf /var/lib/apt/lists/*
