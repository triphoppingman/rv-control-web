#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
case "${1:-}" in
  build)
    [[ $# -eq 2 ]] || { echo "Usage: $0 build IMAGE:TAG" >&2; exit 2; }
    exec docker build --platform "${RV_WEB_PLATFORM:-linux/arm64}" -f "$root/deploy/Dockerfile" -t "$2" "$root"
    ;;
  tag)
    [[ $# -eq 3 ]] || { echo "Usage: $0 tag SOURCE:TAG DESTINATION:TAG" >&2; exit 2; }
    exec docker tag "$2" "$3"
    ;;
  push)
    [[ $# -eq 2 ]] || { echo "Usage: $0 push IMAGE:TAG" >&2; exit 2; }
    exec docker push "$2"
    ;;
  *)
    echo "Usage: $0 {build IMAGE:TAG|tag SOURCE:TAG DESTINATION:TAG|push IMAGE:TAG}" >&2
    exit 2
    ;;
esac