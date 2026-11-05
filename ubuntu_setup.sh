#!/usr/bin/env bash
# Stop on errors, undefined variables, or a failed command in a pipeline.
set -euo pipefail

# Resolve paths relative to this script, even when called from another directory.
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
raw_directory="$project_root/data/raw"
mkdir -p -- "$raw_directory"

# Keep the download compressed; -c resumes an interrupted download.
# -P chooses the destination without changing the caller's working directory.
wget -c -P "$raw_directory" \
    "https://emi.nasdaq.com/ITCH/Nasdaq%20ITCH/12302019.NASDAQ_ITCH50.gz"
