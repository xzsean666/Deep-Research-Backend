#!/bin/bash
# Operator CLI for /admin/api-keys (app/api/routers/admin.py). Run this on
# the deployment host, from the deployment directory (the one containing
# .env), against the locally running `api` container — it talks to
# http://localhost:${API_PORT}, not through any reverse proxy or the
# outbound-facing OUTBOUND_PROXY_URL.
#
# Reads ADMIN_API_SECRET and API_PORT straight out of .env — no separate
# config. Exits with a clear error if ADMIN_API_SECRET is unset/empty,
# matching the server's own fail-closed behavior (app/api/deps.py's
# require_admin: an empty secret disables the admin API entirely).
set -euo pipefail

ENV_FILE="${ENV_FILE:-.env}"

usage() {
    cat >&2 <<'USAGE'
Usage: manage_api_keys.sh <command> [args]

Run from the deployment directory (e.g. /home/apps/deep-research-backend)
so ./.env is found — or set ENV_FILE=/path/to/.env.

Commands:
  list                                        List all API keys
  create <label> [rate_limit=60] [expires_at|never]
                                               Create a key. expires_at is
                                               ISO8601 (2026-12-31T00:00:00Z)
                                               or "never" (default) for
                                               permanent. Prints the raw key
                                               once — it cannot be retrieved
                                               again after this.
  show <id>                                   Show one key's metadata
  disable <id>                                Disable a key without deleting it
  enable <id>                                 Re-enable a disabled key
  delete <id>                                 Permanently delete a key
USAGE
    exit 1
}

if [ ! -f "$ENV_FILE" ]; then
    echo "manage_api_keys.sh: $ENV_FILE not found — run this from the deployment directory, or set ENV_FILE=/path/to/.env" >&2
    exit 1
fi

# tail -1: .env.example ships an empty ADMIN_API_SECRET= placeholder line;
# a deployed .env appends the real value after it, so the last match wins
# (matches how docker compose itself resolves duplicate keys).
ADMIN_SECRET="$(grep -E '^ADMIN_API_SECRET=' "$ENV_FILE" | tail -1 | cut -d= -f2-)"
API_PORT="$(grep -E '^API_PORT=' "$ENV_FILE" | tail -1 | cut -d= -f2-)"
API_PORT="${API_PORT:-8000}"

if [ -z "$ADMIN_SECRET" ]; then
    echo "manage_api_keys.sh: ADMIN_API_SECRET is empty in $ENV_FILE — the admin API is disabled server-side until it's set (see .env.example), then restart the api container" >&2
    exit 1
fi

BASE_URL="http://localhost:${API_PORT}/admin/api-keys"

# Sets RESPONSE_BODY / RESPONSE_CODE. Deliberately not run via $(...) —
# this needs to be able to `exit` the whole script on failure later, which
# a command-substitution subshell couldn't do.
_request() {
    local method="$1" path="$2" data="${3:-}"
    local tmp
    tmp="$(mktemp)"
    if [ -n "$data" ]; then
        RESPONSE_CODE="$(curl -sS -o "$tmp" -w '%{http_code}' -X "$method" \
            -H "Authorization: Bearer ${ADMIN_SECRET}" -H 'Content-Type: application/json' \
            -d "$data" "${BASE_URL}${path}")"
    else
        RESPONSE_CODE="$(curl -sS -o "$tmp" -w '%{http_code}' -X "$method" \
            -H "Authorization: Bearer ${ADMIN_SECRET}" "${BASE_URL}${path}")"
    fi
    RESPONSE_BODY="$(cat "$tmp")"
    rm -f "$tmp"
}

_require_status() {
    local expected="$1"
    if [ "$RESPONSE_CODE" != "$expected" ]; then
        echo "manage_api_keys.sh: request failed (HTTP $RESPONSE_CODE)" >&2
        echo "$RESPONSE_BODY" >&2
        exit 1
    fi
}

_pretty() {
    python3 -m json.tool 2>/dev/null || cat
}

[ $# -ge 1 ] || usage
cmd="$1"
shift

case "$cmd" in
    list)
        _request GET ""
        _require_status 200
        echo "$RESPONSE_BODY" | _pretty
        ;;
    create)
        [ $# -ge 1 ] || usage
        label="$1"
        rate_limit="${2:-60}"
        expires_at="${3:-never}"
        if [ "$expires_at" = "never" ]; then
            expires_json="null"
        else
            expires_json="\"${expires_at}\""
        fi
        label_json="$(python3 -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$label")"
        payload="{\"label\": ${label_json}, \"rate_limit_per_minute\": ${rate_limit}, \"expires_at\": ${expires_json}}"
        _request POST "" "$payload"
        _require_status 201
        echo "$RESPONSE_BODY" | _pretty
        echo
        echo "Raw key (shown once, save it now):"
        echo "$RESPONSE_BODY" | python3 -c "import json, sys; print(json.load(sys.stdin)['raw_key'])"
        ;;
    show)
        [ $# -ge 1 ] || usage
        _request GET "/$1"
        _require_status 200
        echo "$RESPONSE_BODY" | _pretty
        ;;
    disable)
        [ $# -ge 1 ] || usage
        _request PATCH "/$1" '{"status": "disabled"}'
        _require_status 200
        echo "$RESPONSE_BODY" | _pretty
        ;;
    enable)
        [ $# -ge 1 ] || usage
        _request PATCH "/$1" '{"status": "active"}'
        _require_status 200
        echo "$RESPONSE_BODY" | _pretty
        ;;
    delete)
        [ $# -ge 1 ] || usage
        _request DELETE "/$1"
        _require_status 204
        echo "deleted $1"
        ;;
    *)
        usage
        ;;
esac
