#!/bin/bash
set -e

echo "Running post-merge setup..."

cd /home/runner/workspace/frontend
npm install --legacy-peer-deps

cd /home/runner/workspace
pip install -r backend/requirements.txt --quiet

echo "Post-merge setup complete."
