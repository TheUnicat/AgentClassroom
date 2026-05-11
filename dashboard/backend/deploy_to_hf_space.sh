#!/usr/bin/env bash
# Mirror the files HF Spaces needs into a sibling Space repo, then commit + push.
#
# Usage:
#   ./deploy_to_hf_space.sh /path/to/cloned/space/repo "commit message"
#
# Prereqs:
#   1. Created the Space on https://huggingface.co/new-space (Docker SDK).
#   2. Cloned it locally:
#        git clone https://huggingface.co/spaces/<user>/<space-name> ~/code/agentclassroom-space
#      (HF will prompt for username + a Write-scoped access token as the password.)
#   3. This script is run from the AgentClassroom repo root or from dashboard/backend/.

set -euo pipefail

SPACE_DIR="${1:-}"
MSG="${2:-update backend}"

if [[ -z "$SPACE_DIR" ]]; then
  echo "usage: $0 <space-repo-path> [commit-message]" >&2
  exit 1
fi
if [[ ! -d "$SPACE_DIR/.git" ]]; then
  echo "error: $SPACE_DIR is not a git repo (clone the HF Space first)" >&2
  exit 1
fi

# Resolve repo root regardless of where the script is run from.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "→ mirroring from $REPO_ROOT into $SPACE_DIR"

# 1. Dockerfile at Space root.
cp "$REPO_ROOT/dashboard/backend/Dockerfile" "$SPACE_DIR/Dockerfile"

# 2. Backend files at dashboard/backend/ (paths the Dockerfile COPYs).
mkdir -p "$SPACE_DIR/dashboard/backend"
cp "$REPO_ROOT/dashboard/backend/requirements.txt" "$SPACE_DIR/dashboard/backend/requirements.txt"
cp "$REPO_ROOT/dashboard/backend/app.py" "$SPACE_DIR/dashboard/backend/app.py"

# 3. The teachingbench env package, preserving the path.
rm -rf "$SPACE_DIR/environments/teachingbench"
mkdir -p "$SPACE_DIR/environments"
rsync -a --delete \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude '.venv' \
  --exclude '.pytest_cache' \
  --exclude 'dist' \
  --exclude '.cache' \
  --exclude 'outputs' \
  --exclude '*.egg-info' \
  "$REPO_ROOT/environments/teachingbench/" "$SPACE_DIR/environments/teachingbench/"

# 4. Seed rollouts. The dashboard reads RUNS_DIR/<run>/results.jsonl one level deep.
#    All 228 viewable rollouts live one level deep inside the 4 "batched_*" dirs.
#    Flatten them so the dashboard sees them as top-level runs, and rename so the
#    last '__'-separated chunk is the teacher model (the dashboard's parser convention).
SRC_RUNS="$REPO_ROOT/environments/teachingbench/outputs/runs"
SEED_RUNS="$SPACE_DIR/dashboard/backend/seed_runs"
rm -rf "$SEED_RUNS"
mkdir -p "$SEED_RUNS"

# Flatten the 4 batched dirs that make up the 228-rollout v0.1 baseline. We do NOT
# include the loose standalones at SRC_RUNS root — those are exploration/dev runs,
# not part of the published baseline.
for batch in \
    batched_gpt54_round1_v2 \
    batched_opus_round1_text \
    batched_opus_round1_materials \
    batch_realtime_round1; do
  for sub in "$SRC_RUNS/$batch"/*/; do
    [[ -f "$sub/results.jsonl" ]] || continue
    name=$(basename "$sub")
    # Source dirs are named <model>__<subject>__<task>; rewrite to
    # <batch>__<subject>__<task>__<model> so the dashboard's _model_from_run_id
    # (rsplit on "__") picks the teacher model.
    model="${name%%__*}"
    rest="${name#*__}"
    new="${batch}__${rest}__${model}"
    cp -R "$sub" "$SEED_RUNS/$new"
  done
done

echo "→ seeded $(ls -1 "$SEED_RUNS" | wc -l | tr -d ' ') rollouts ($(du -sh "$SEED_RUNS" | cut -f1))"

# 5. Space card (README.md with HF frontmatter). Only write if not present so
#    the user can customize emoji/title without it getting clobbered.
if [[ ! -f "$SPACE_DIR/README.md" ]]; then
  cat > "$SPACE_DIR/README.md" <<'EOF'
---
title: AgentClassroom Dashboard Backend
emoji: 🎓
colorFrom: indigo
colorTo: blue
sdk: docker
pinned: false
---

FastAPI backend for the AgentClassroom v0.1 dashboard. See
https://github.com/TheUnicat/AgentClassroom for the source.
EOF
fi

# 6. Commit locally (snapshot of what was deployed) + push via `hf upload`.
# `git push` to HF Spaces is flaky (silent stalls behind macOS credential helper);
# `hf upload` uses the Hub HTTPS API directly and Just Works. Requires `hf auth login`.
cd "$SPACE_DIR"
git add -A
if git diff --cached --quiet; then
  echo "→ no changes to commit; skipping upload"
  exit 0
fi
git commit -m "$MSG"

REPO_ID=$(git remote get-url origin | sed 's|.*spaces/||;s|\.git$||')
echo "→ uploading to https://huggingface.co/spaces/$REPO_ID"
hf upload "$REPO_ID" "$SPACE_DIR" . --repo-type=space --commit-message "$MSG"

echo "✓ uploaded. HF will rebuild the Space; watch logs at:"
echo "  https://huggingface.co/spaces/$REPO_ID"
