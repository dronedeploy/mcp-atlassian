#!/usr/bin/env bash
# Build and push mcp-atlassian Docker image to Google Artifact Registry.
# Run from anywhere; script changes to repo root automatically.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="us-docker.pkg.dev/dronedeploy-code-delivery-0/docker-dronedeploy-us/mcp-atlassian:main"

cd "$SCRIPT_DIR"

echo "Authenticating to Google Artifact Registry..."
gcloud auth configure-docker us-docker.pkg.dev --quiet

echo "Building image..."
docker build -t "$IMAGE" .

echo "Pushing image..."
docker push "$IMAGE"

echo "Done. Restart Cursor to use the new image."
