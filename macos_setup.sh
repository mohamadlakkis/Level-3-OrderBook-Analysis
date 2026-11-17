#!/usr/bin/env bash
# Run in macOS Terminal, from the repository root.
# Command: bash macos_setup.sh
set -euo pipefail

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
raw_directory="$project_root/data/raw"
mkdir -p -- "$raw_directory"

source_url="${1:-https://emi.nasdaq.com/ITCH/Nasdaq%20ITCH/12302019.NASDAQ_ITCH50.gz}"
curl --fail --location --retry 3 --continue-at - \
    --output "$raw_directory/12302019.NASDAQ_ITCH50.gz" "$source_url"
