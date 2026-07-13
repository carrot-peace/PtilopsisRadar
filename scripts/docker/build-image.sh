#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
IMAGE=${1:-wantcat/trendradar:latest}

cd "$ROOT"

PTILOPSIS_BUILD_COMMIT=$(git rev-parse --short=12 HEAD)
RANDOM_BUILD_ID=$(od -An -N16 -tx1 /dev/urandom | tr -d '[:space:]')
GENERATED_BUILD_ID="docker-$RANDOM_BUILD_ID"
PTILOPSIS_BUILD_ID=${PTILOPSIS_BUILD_ID_OVERRIDE:-$GENERATED_BUILD_ID}
PTILOPSIS_DEPLOYMENT_IMAGE_NAME=$IMAGE

export PTILOPSIS_BUILD_COMMIT
export PTILOPSIS_BUILD_ID
export PTILOPSIS_DEPLOYMENT_IMAGE_NAME

exec docker compose -f docker/docker-compose-build.yml build trendradar
