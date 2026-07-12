#!/bin/zsh
set -eu

CONTAINER_BIN="${CONTAINER_BIN:-/usr/local/bin/container}"
IMAGE="${1:-ptilopsis-radar:latest}"
REPO="${REPO:-$HOME/PtilopsisRadar}"

cd "$REPO"

BUILD_COMMIT="$(git rev-parse --short=12 HEAD)"
BUILD_ID="${PTILOPSIS_BUILD_ID_OVERRIDE:-$(date -u +%Y%m%dT%H%M%SZ)}"

exec "$CONTAINER_BIN" build \
  --arch arm64 \
  --tag "$IMAGE" \
  --file docker/Dockerfile \
  --build-arg "PTILOPSIS_BUILD_COMMIT=$BUILD_COMMIT" \
  --build-arg "PTILOPSIS_BUILD_ID=$BUILD_ID" \
  --build-arg "PTILOPSIS_DEPLOYMENT_IMAGE_NAME=$IMAGE" \
  .
