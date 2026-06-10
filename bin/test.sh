#!/bin/bash -e

THIS_DIR=$(dirname "${BASH_SOURCE[0]}")
PROJECT_ROOT=$(realpath "${THIS_DIR}/..")
cd "${PROJECT_ROOT}"

exec pdm run pytest \
    --cov=src \
    --cov-report=term-missing:skip-covered \
    --no-cov-on-fail \
    -ra \
    "${@:-tests/}"
