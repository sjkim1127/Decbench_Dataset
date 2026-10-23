FROM ubuntu@sha256:534baea6a22c03a63003dbc8dbe78fe34bc0d7e595d9a9dc9834884ff530eb55
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3 build-essential cmake ninja-build gfortran ldc nim git binutils ca-certificates pkg-config libssl-dev && dpkg-query -W > /toolchain-packages.txt && rm -rf /var/lib/apt/lists/*
