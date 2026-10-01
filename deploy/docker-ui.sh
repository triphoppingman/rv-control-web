#!/usr/bin/env bash
set -euo pipefail

# Run the UI without Docker Compose; configuration stays host-mounted and read-only.
container="${RV_WEB_CONTAINER:-rv-control-web-ui}"
action="${1:-}"
docker info >/dev/null

case "$action" in
  start)
    config_dir="${RV_WEB_CONFIG_DIR:-}"
    image="${RV_WEB_IMAGE:-rv-control-web:local}"
    bind="${RV_WEB_BIND:-127.0.0.1}"
    port="${RV_WEB_PORT:-8000}"
    if [[ -z "$config_dir" || ! -f "$config_dir/config.yaml" || ! -f "$config_dir/dashboard.yaml" || ! -d "$config_dir/assets" ]]; then
      echo "Set RV_WEB_CONFIG_DIR to a directory containing config.yaml, dashboard.yaml, and assets/." >&2
      exit 2
    fi
    docker image inspect "$image" >/dev/null
    if docker container inspect "$container" >/dev/null 2>&1; then
      state="$(docker container inspect --format '{{.State.Status}}' "$container")"
      if [[ "$state" == running ]]; then
        echo "$container is already running"
      else
        docker start "$container"
      fi
    else
      docker run -d \
        --name "$container" \
        --restart unless-stopped \
        -p "$bind:$port:8000" \
        -e RV_WEB_CONFIG=/config/config.yaml \
        -v "$config_dir:/config:ro" \
        --add-host host.docker.internal:host-gateway \
        "$image"
    fi
    ;;
  stop)
    if docker container inspect "$container" >/dev/null 2>&1; then
      state="$(docker container inspect --format '{{.State.Status}}' "$container")"
      if [[ "$state" == running ]]; then
        docker stop "$container"
      else
        echo "$container is already stopped"
      fi
    else
      echo "$container does not exist"
    fi
    ;;
  status)
    if docker container inspect "$container" >/dev/null 2>&1; then
      docker container inspect --format '{{.Name}}: {{.State.Status}}' "$container"
    else
      echo "$container does not exist"
    fi
    ;;
  *)
    echo "Usage: $0 {start|stop|status}" >&2
    exit 2
    ;;
esac