#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

forbidden_paths='(^|/)(\.env|data|.*\.duckdb|.*\.db|.*\.lance|.*\.arrow|.*\.jsonl)(/|$)'
if git ls-files | grep -E "$forbidden_paths" >/dev/null; then
  echo "Public scan failed: forbidden runtime or source-data file is tracked."
  git ls-files | grep -E "$forbidden_paths"
  exit 1
fi

secret_pattern='(AIza[0-9A-Za-z_-]{20,}|Bearer[[:space:]]+[0-9A-Za-z._-]{20,}|(QUIP_TOKEN|GEMINI_API_KEY|API_KEY)[[:space:]]*=[[:space:]]*[^[:space:]#]+)'
if git grep -n -I -E "$secret_pattern" -- ':!scripts/scan-public.sh' ':!.env.example' >/dev/null; then
  echo "Public scan failed: possible credential found."
  git grep -n -I -E "$secret_pattern" -- ':!scripts/scan-public.sh' ':!.env.example'
  exit 1
fi

internal_pattern='(platform\.quip-apple\.com|quip-apple\.com|interpublic)'
if git grep -n -I -i -E "$internal_pattern" -- ':!scripts/scan-public.sh' >/dev/null; then
  echo "Public scan failed: internal organization or domain reference found."
  git grep -n -I -i -E "$internal_pattern" -- ':!scripts/scan-public.sh'
  exit 1
fi

echo "Public scan passed: no forbidden files, likely credentials, or internal domains found."
