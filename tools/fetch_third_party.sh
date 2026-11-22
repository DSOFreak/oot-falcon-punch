#!/bin/sh
# Fetch third-party tools that are not redistributed in this repo (no license file upstream).
set -e
cd "$(dirname "$0")/.."
mkdir -p third_party
[ -d third_party/asb ] || git clone -q --depth 1 https://github.com/dt-12345/asb.git third_party/asb
