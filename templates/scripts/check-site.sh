#!/usr/bin/env bash
set -euo pipefail

if [[ ! -d site || -L site || ! -f site/index.html || -L site/index.html ]]; then
  echo "::error::Provide a regular site/index.html inside a real site/ directory."
  exit 1
fi
link=$(find site -type l -print -quit)
if [[ -n "$link" ]]; then
  echo "::error::Remove symbolic links from site/ before deploying to GitHub Pages."
  exit 1
fi
