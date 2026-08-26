#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
source_root="$repo_root/redesign"
release_root="$source_root/release"

mkdir -p "$release_root/code/benchmark" "$release_root/code/analysis" \
  "$release_root/code/manuscript" "$release_root/framework" \
  "$release_root/protocol" "$release_root/data/raw" \
  "$release_root/data/processed" "$release_root/figures" \
  "$release_root/figure_sources" "$release_root/tables" \
  "$release_root/manuscript" "$release_root/audits" \
  "$release_root/HUMAN_PORTAL" "$release_root/tests"

cp "$source_root"/benchmark/*.py "$release_root/code/benchmark/"
cp "$source_root"/analysis/*.py "$release_root/code/analysis/"
cp "$source_root"/tests/*.py "$release_root/tests/"
cp "$source_root"/manuscript/build_manuscript.py \
  "$source_root"/manuscript/manuscript_template.md "$release_root/code/manuscript/"
cp "$source_root"/framework/*.json "$source_root"/framework/*.md \
  "$source_root"/framework/*.py "$release_root/framework/"
cp "$source_root"/protocol/*.json "$source_root"/protocol/*.md \
  "$release_root/protocol/"
cp "$source_root/results/final/raw/decisions_and_pairs.jsonl" \
  "$release_root/data/raw/"
find "$source_root/results/final/aggregates" -maxdepth 1 -type f \
  ! -name '*SUPERSEDED*' -exec cp {} "$release_root/data/processed/" \;
cp "$source_root"/results/final/figures/* "$release_root/figures/"
cp "$source_root"/results/final/figure_sources/* "$release_root/figure_sources/"
cp "$source_root"/results/final/tables/* "$release_root/tables/"
cp "$source_root"/manuscript/manuscript.md \
  "$source_root"/manuscript/manuscript_numbers.json \
  "$source_root"/manuscript/FINAL_MANUSCRIPT_FOR_REVIEW.pdf \
  "$release_root/manuscript/"
find "$source_root" -maxdepth 1 -type f \( -name '*.md' -o -name '*.csv' -o -name '*.json' \) \
  -exec cp {} "$release_root/audits/" \;
find "$source_root/HUMAN_PORTAL" -maxdepth 1 -type f -exec cp {} "$release_root/HUMAN_PORTAL/" \;

echo "public-only release tree assembled at $release_root"
