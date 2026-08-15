#!/usr/bin/env bash
# Invites and devices for Termometru. Talks to the tailnet-only listener,
# which is what authorises admin -- there is no password; reaching that
# listener is the credential. Will not work from off the tailnet.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ -f "$ROOT/.admin.env" ]] && { set -a; . "$ROOT/.admin.env"; set +a; }
API="${API:-${ADMIN_API:-}}"
: "${API:?set ADMIN_API in .admin.env, e.g. http://<tailnet-address>/thermo}"

j() { python3 -m json.tool 2>/dev/null || cat; }
get() { curl -fsS --max-time 15 "$API$1"; }
post() { curl -fsS --max-time 15 -X POST "$API$1" -H 'Content-Type: application/json' -d "${2:-{\}}"; }

usage() {
  cat <<'USAGE'
usage: ./admin.sh <command>

  invite [label]     create an invite (prints link and code)
  invites            list invites, with codes for the ones still usable
  unvite <id>        revoke an unused invite
  devices            list registered devices
  revoke <id>        lock a device out
  unrevoke <id>      let it back in
  forget <id>        delete a device
  poll               run a collection cycle now

Each invite registers one device. A second phone needs a second invite.
USAGE
}

case "${1:-}" in
  invite)
    post /api/admin/invites "{\"label\":\"${2:-}\"}" \
      | python3 "$ROOT/bin/fmt_invite.py" ;;
  invites)  get /api/admin/invites | j ;;
  unvite)   post "/api/admin/invites/${2:?id}/revoke" | j ;;
  devices)  get /api/admin/devices | j ;;
  revoke)   post "/api/admin/devices/${2:?id}/revoke" '{"revoked":true}' | j ;;
  unrevoke) post "/api/admin/devices/${2:?id}/revoke" '{"revoked":false}' | j ;;
  forget)   curl -fsS --max-time 15 -X DELETE "$API/api/admin/devices/${2:?id}" | j ;;
  poll)     post /api/admin/poll | j ;;
  *) usage; exit 1 ;;
esac
