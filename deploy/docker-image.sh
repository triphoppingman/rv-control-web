#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
default_image="docker.io/triphoop/rv-control-web:latest"
case "${1:-}" in
  build)
    [[ $# -ge 1 && $# -le 2 ]] || { echo "Usage: $0 build [IMAGE:TAG]" >&2; exit 2; }
    platform_args=()
    if [[ -n "${RV_WEB_PLATFORM:-}" ]]; then
      platform_args=(--platform "$RV_WEB_PLATFORM")
    fi
    exec docker build "${platform_args[@]}" -f "$root/deploy/Dockerfile" -t "${2:-$default_image}" "$root"
    ;;
  tag)
    [[ $# -eq 3 ]] || { echo "Usage: $0 tag SOURCE:TAG DESTINATION:TAG" >&2; exit 2; }
    exec docker tag "$2" "$3"
    ;;
  push)
    [[ $# -ge 1 && $# -le 2 ]] || { echo "Usage: $0 push [IMAGE:TAG]" >&2; exit 2; }
    exec docker push "${2:-$default_image}"
    ;;
  *)
    echo "Usage: $0 {build [IMAGE:TAG]|tag SOURCE:TAG DESTINATION:TAG|push [IMAGE:TAG]}" >&2
    exit 2
    ;;
esac