#!/usr/bin/env bash
# Build the whole website into one static folder (default build/site):
#
#   /        the landing page          (site/)
#   /docs/   the mkdocs documentation  (docs/, mkdocs.yml)
#   /demo/   a read-only web UI demo   (apps/web, data from scripts/export_demo.py)
#
# Vercel runs this (see vercel.json), and the docs workflow runs it on pull requests.
# Needs python3 and node; installs uv and pnpm itself if they are missing.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${SITE_OUT:-$ROOT/build/site}"
cd "$ROOT"

export PATH="$HOME/.local/bin:$PATH"

# --- tools ---------------------------------------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
  echo "==> Installing uv"
  python3 -m pip install --user --quiet uv \
    || curl -LsSf https://astral.sh/uv/install.sh | sh
fi

if ! command -v pnpm >/dev/null 2>&1; then
  echo "==> Installing pnpm"
  mkdir -p "$HOME/.local/bin"
  if command -v corepack >/dev/null 2>&1 && corepack enable --install-directory "$HOME/.local/bin"; then
    :
  else
    npm install --global --prefix "$HOME/.local" \
      "pnpm@$(node -p "require('./package.json').packageManager.split('@')[1]")"
  fi
fi

# --- python: docs group plus the workspace packages and dev tools the export needs ----
echo "==> Installing Python dependencies"
uv sync --locked --group docs

echo "==> Installing web dependencies"
pnpm install --frozen-lockfile

# --- build ---------------------------------------------------------------------------
rm -rf "$OUT"
mkdir -p "$OUT"

echo "==> Landing page"
cp -R site/. "$OUT/"
mkdir -p "$OUT/assets"
cp docs/assets/*.png "$OUT/assets/"
cp apps/web/public/favicon.svg "$OUT/favicon.svg"

echo "==> Docs"
if [ -n "${VERCEL_PROJECT_PRODUCTION_URL:-}" ]; then
  export SITE_URL="https://${VERCEL_PROJECT_PRODUCTION_URL}/docs/"
fi
uv run --no-sync mkdocs build --strict --site-dir "$OUT/docs"

echo "==> Demo"
# The UI build empties its output folder, so it goes first and the data goes in after.
pnpm --filter @openpipeline/web run build:demo --outDir "$OUT/demo" --emptyOutDir
uv run --no-sync python scripts/export_demo.py "$OUT/demo/data"

echo "==> Done: $OUT"
