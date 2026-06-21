#!/bin/bash
# update-and-push.sh — Run the README generator and push to GitHub
# This script is called by the cron job every 6 hours

set -e

REPO_DIR="/home/joaosbp/one-day-i-will-try-this"
cd "$REPO_DIR"

# Pull latest changes first
git pull origin main 2>/dev/null || true

# Run the generator
python3 update_readme.py

# Check if there are changes
if git diff --quiet README.md; then
    echo "No changes to README.md"
    exit 0
fi

# Commit and push
git add README.md
git commit -m "auto: daily update v$(date +%y) | $(git diff --stat README.md | tail -1 | awk '{print $4}')"
git push origin main

echo "README.md updated and pushed successfully!"
