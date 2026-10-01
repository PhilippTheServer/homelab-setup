#!/usr/bin/env bash
# Check the deployed daily stack (daily 2.0, role daily2) end to end.
#
# Run from a machine on the LAN or VPN (resolving through Pi-hole) with a signed SSH
# cert: the containers are healthy, the schema is at the image's migration, the backend
# and its gym-bro sync work, the app answers on daily's LAN host and refuses the API
# without a token, and the public MCP host serves only /mcp and its protected-resource
# metadata. It also checks the switch-over from v1: v1's containers are gone but its
# data volume is kept, v2 signs in with v1's Keycloak clients, and the daily2.* hosts
# and clients are gone. Public DNS is checked against 1.1.1.1: ddclient can only update
# a record that exists at Namecheap, and it cannot delete one, so a leftover daily2-mcp
# record is reported as BLOCKED (a manual Namecheap step), not FAIL. Exits 1 on any
# unexpected result, 2 if the only problem is a blocked manual step.
#
#   scripts/check-daily2.sh
set -uo pipefail

SSH=(ssh -p 1461 -i ~/.ssh/hcvault -o CertificateFile=~/.ssh/hcvault-cert.pub
  -o IdentitiesOnly=yes -o BatchMode=yes -o LogLevel=ERROR
  philipp@minipc.home.example.com)
MINIPC=192.168.178.20
APP=https://daily.home.example.com
MCP_HOST=daily-mcp.example.com
MCP=https://$MCP_HOST
RETIRED_HOSTS=(daily2.home.example.com daily2-mcp.example.com)
ISSUER=https://auth.example.com/realms/homelab
failed=0
blocked=0

expect() {
  if [[ $3 == "$2" ]]; then
    echo "ok   $1"
  else
    echo "FAIL $1: expected '$2', got '$3'"
    failed=1
  fi
}
# ssh joins its arguments into one remote shell command; quote each one for that shell.
remote() { "${SSH[@]}" "$(printf '%q ' "$@")" 2>/dev/null; }
status() { curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$@"; }
sql() { remote docker exec daily2-db psql -U daily2 -d daily2 -tAc "$1"; }
# Keycloak answers an authorization request for an unknown client with "Client not
# found", and for a known one with an error about the (deliberately bogus) redirect URI.
kc_client() {
  curl -s --max-time 10 "$ISSUER/protocol/openid-connect/auth?client_id=$1&response_type=code&scope=openid&redirect_uri=https%3A%2F%2Fexample.invalid%2F" |
    grep -q 'Client not found' && echo absent || echo present
}

for c in daily2-frontend daily2-backend daily2-db; do
  expect "$c healthy" healthy "$(remote docker inspect -f '{{.State.Health.Status}}' "$c")"
done
expect "schema at revision 0001" 0001 "$(sql 'select version_num from alembic_version')"
expect "backend /health ok" ok "$(remote docker exec daily2-backend python -c \
  "import json, urllib.request; print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4))['status'])")"
expect "gym-bro sync succeeded, no error" "t|" \
  "$(sql "select last_success_at is not null, coalesce(last_error, '') from sync_state where source = 'gym-bro'")"

expect "daily v1 containers are gone" "" \
  "$(remote docker ps -aq --filter name='^daily-(frontend|backend|db)$')"
expect "daily v1 data volume is kept" daily_db \
  "$(remote docker volume inspect -f '{{.Name}}' daily_db)"
expect "backend takes app tokens from daily-app" daily-app \
  "$(remote docker exec daily2-backend printenv APP_CLIENT_ID)"
expect "backend takes MCP tokens from daily-mcp" daily-mcp \
  "$(remote docker exec daily2-backend printenv MCP_CLIENT_ID)"

expect "app serves the SPA" 200 "$(status "$APP/")"
expect "app health endpoint" 200 "$(status "$APP/healthz")"
expect "runtime config names daily-app" daily-app \
  "$(curl -s --max-time 10 "$APP/assets/runtime-config.json" | jq -r '.clientId // empty' 2>/dev/null)"
expect "app serves the homepage tile icon" 200 "$(status "$APP/icons/icon-192x192.png")"
expect "app proxies /health to the backend" ok \
  "$(curl -s --max-time 10 "$APP/health" | jq -r '.status // empty' 2>/dev/null)"
expect "API refuses a request without a token" 401 "$(status "$APP/api/v2/schemas")"
mcp_on_app=$(curl -s --max-time 10 -X POST -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' -d '{}' -w '\n%{http_code}' "$APP/mcp")
code=${mcp_on_app##*$'\n'}
reach=$([[ $code == 401 ]] && jq -e . <<<"${mcp_on_app%$'\n'*}" >/dev/null 2>&1 && echo backend-401 || echo not-backend-401)
[[ $code == 000 ]] && reach=no-response
expect "app does not proxy /mcp to the backend" not-backend-401 "$reach"

meta=$(curl -s --max-time 10 "$MCP/.well-known/oauth-protected-resource/mcp")
expect "MCP metadata: resource" "$MCP/mcp" "$(jq -r '.resource // empty' <<<"$meta" 2>/dev/null)"
expect "MCP metadata: scopes" '["openid"]' "$(jq -c '.scopes_supported // empty' <<<"$meta" 2>/dev/null)"
expect "MCP metadata: authorization server" "$ISSUER" \
  "$(jq -r '.authorization_servers[0] // empty | sub("/$"; "")' <<<"$meta" 2>/dev/null)"
expect "MCP refuses a request without a token" 401 "$(status -X POST \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{}' "$MCP/mcp")"
expect "public host does not route the REST API" 404 "$(status "$MCP/api/v2/schemas")"
expect "public host does not route /health" 404 "$(status "$MCP/health")"

for client in daily-app daily-mcp; do
  expect "Keycloak client $client exists" present "$(kc_client "$client")"
done
for client in daily2-app daily2-mcp; do
  expect "retired Keycloak client $client is gone" absent "$(kc_client "$client")"
done
for host in "${RETIRED_HOSTS[@]}"; do
  expect "Pi-hole does not point $host at the Mini PC" "" \
    "$(dig +short "@$MINIPC" "$host" A | grep -Fx "$MINIPC")"
  # /mcp: the only path the old MCP router matched, and an SPA route on the old app host.
  expect "Traefik routes nothing on $host" 404 \
    "$(status -k --resolve "$host:443:$MINIPC" "https://$host/mcp")"
done

if [[ -n $(dig +short "$MCP_HOST" @1.1.1.1) ]]; then
  echo "ok   public DNS record $MCP_HOST exists"
else
  echo "FAIL public DNS record $MCP_HOST missing: claude.ai cannot reach the MCP endpoint"
  failed=1
fi
if [[ -z $(dig +short daily2-mcp.example.com @1.1.1.1) ]]; then
  echo "ok   public DNS record daily2-mcp is gone"
else
  echo "BLOCKED public DNS record daily2-mcp still exists: delete the Namecheap host record"
  blocked=1
fi

((failed)) && exit 1
((blocked)) && exit 2
exit 0
