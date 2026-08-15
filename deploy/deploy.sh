#!/usr/bin/env bash
# Publish the PWA and, with --api, rebuild the container.
#   ./deploy/deploy.sh          web only
#   ./deploy/deploy.sh --api    also rebuild the image and restart the unit
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${DEST:-/var/www/thermo}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

VERSION="$(find "$ROOT/web" -type f -exec sha256sum {} + | sort -k2 | sha256sum | cut -c1-12)"

sudo mkdir -p "$DEST"
sudo chown "$(id -un):$(id -gn)" "$DEST"
rsync -a --delete "$ROOT/web"/ "$DEST"/
# Stamp every reference, not just the service worker.
grep -rl __BUILD_VERSION__ "$DEST" | xargs -r sed -i "s/__BUILD_VERSION__/${VERSION}/g"
sudo restorecon -R "$DEST" 2>/dev/null || true
echo "web deployed ${VERSION} -> ${DEST}"

if [[ "${1:-}" == "--api" ]]; then
  podman build -t localhost/thermo:latest -f "$ROOT/deploy/Containerfile" "$ROOT"
  cp "$ROOT/deploy/quadlet/thermo.container" "$HOME/.config/containers/systemd/"
  systemctl --user daemon-reload
  systemctl --user restart thermo.service
  echo "api rebuilt and restarted"
fi
