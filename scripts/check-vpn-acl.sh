#!/usr/bin/env bash
# Check what a VPN member outside group:admins can reach.
#
# Creates a throwaway headscale user (a plain member, like a guest account), joins the
# tailnet with it from a throwaway Tailscale container on this machine, accepting the Mini
# PC's home-LAN route, and probes TCP ports through the tailnet. Expected: only the Mini
# PC's LAN address on 443 (Traefik) and 53 (Pi-hole). Container, node and user are removed
# afterwards, also on failure. Exits 1 on any unexpected result.
#
# Then joins a second throwaway node as vpn-check-exit, a member of group:exit-node. Both
# nodes select the Mini PC as exit node (headscale 0.29 offers it to every member); only
# vpn-check-exit may get internet traffic through it, the plain member's is dropped.
#
#   scripts/check-vpn-acl.sh
set -euo pipefail

SSH=(ssh -p 1461 -i ~/.ssh/hcvault -o CertificateFile=~/.ssh/hcvault-cert.pub
  -o IdentitiesOnly=yes -o BatchMode=yes -o LogLevel=ERROR
  philipp@minipc.home.example.com)
LOGIN_SERVER=https://vpn.example.com
MINIPC_LAN=192.168.178.20
MINIPC_TAILNET=100.64.0.1
ROUTER=192.168.178.1
NAME="acl-check-$(openssl rand -hex 3)"
EXIT_USER=vpn-check-exit
EXIT_NAME="$EXIT_USER-$(openssl rand -hex 3)"
user_id=""
exit_user_id=""

hs() { "${SSH[@]}" docker exec headscale headscale "$@"; }

cleanup() {
  docker rm -f "$NAME" "$EXIT_NAME" >/dev/null 2>&1 || true
  local node_id
  node_id=$(hs nodes list -o json |
    jq -r --arg a "$NAME" --arg b "$EXIT_USER" '.[] | select(.user.name == $a or .user.name == $b) | .id')
  for id in $node_id; do hs nodes delete --identifier "$id" --force >/dev/null; done
  for id in $user_id $exit_user_id; do hs users destroy --identifier "$id" --force >/dev/null; done
  echo "removed containers, node(s) and users $NAME $EXIT_USER"
}
trap cleanup EXIT

# join <container> <headscale user id>: starts a userspace Tailscale node as that user and
# waits until the Mini PC's LAN route shows up among its peers.
join() {
  local key routes
  key=$(hs preauthkeys create --user "$2" --expiration 15m -o json | jq -r .key)
  docker run -d --name "$1" \
    -e TS_AUTHKEY="$key" -e TS_HOSTNAME="$1" -e TS_USERSPACE=true \
    -e TS_EXTRA_ARGS="--login-server=$LOGIN_SERVER --accept-routes" \
    tailscale/tailscale:stable >/dev/null
  for _ in $(seq 60); do
    routes=$(docker exec "$1" tailscale status --json 2>/dev/null |
      jq -r '[.Peer[]?.PrimaryRoutes[]?] | join(" ")' 2>/dev/null || true)
    [[ $routes == *"192.168.178.0/24"* ]] && return
    sleep 1
  done
  echo "$1 never saw the 192.168.178.0/24 route"
  exit 1
}

# Whether the Mini PC is offered to a node as exit node.
exit_offered() {
  docker exec "$1" tailscale status --json |
    jq -e --arg ip "$MINIPC_TAILNET" '.Peer[] | select(.TailscaleIPs[0] == $ip) | .ExitNodeOption' >/dev/null
}

user_id=$(hs users create "$NAME" -o json | jq -r .id)
join "$NAME" "$user_id"

# A dropped connection sends nothing back and times out. A reachable service answers the
# junk line or closes the connection, which `tailscale nc` reports as bytes or exit 0.
reachable() { reachable_from "$NAME" "$@"; }
reachable_from() {
  local node=$1 out
  shift
  # PIPESTATUS has to be read inside the substitution, right after its pipeline.
  out=$(printf 'HELLO\r\n\r\n' |
    timeout 6 docker exec -i "$node" tailscale nc "$1" "$2" 2>/dev/null | head -c 64 | wc -c
    echo ":${PIPESTATUS[1]}")
  local bytes=${out%%:*} status=${out##*:}
  [[ ${bytes//[[:space:]]/} -gt 0 || $status -eq 0 ]]
}

failures=0
check() {
  local host=$1 port=$2 what=$3 expected=$4 result
  if reachable "$host" "$port"; then result=reachable; else result=blocked; fi
  local mark=ok
  [[ $result == "$expected" ]] || { mark=FAIL; failures=$((failures + 1)); }
  printf '%-22s %-6s %-28s %-9s %-9s %s\n' "$host" "$port" "$what" "$expected" "$result" "$mark"
}

printf '%-22s %-6s %-28s %-9s %-9s\n' host port service expected result
check "$MINIPC_LAN" 443 "Traefik (gym-bro)" reachable
check "$MINIPC_LAN" 53 "Pi-hole DNS" reachable
check "$MINIPC_LAN" 1461 "Mini PC SSH" blocked
check "$MINIPC_LAN" 80 "Traefik HTTP (redirect)" blocked
check "$ROUTER" 80 "home router" blocked
check "$MINIPC_TAILNET" 1461 "Mini PC SSH via tailnet IP" blocked

expect() {
  local what=$1 expected=$2 result=no mark=ok
  shift 2
  if "$@" >/dev/null 2>&1; then result=yes; fi
  [[ $result == "$expected" ]] || { mark=FAIL; failures=$((failures + 1)); }
  printf '%-58s %-9s %-9s %s\n' "$what" "$expected" "$result" "$mark"
}

echo
exit_user_id=$(hs users create "$EXIT_USER" -o json | jq -r .id)
join "$EXIT_NAME" "$exit_user_id"
printf '%-58s %-9s %-9s\n' "exit node" expected result
expect "member: selects the Mini PC as exit node" yes docker exec "$NAME" tailscale set --exit-node="$MINIPC_TAILNET"
expect "member: reaches 1.1.1.1:443 through it" no reachable_from "$NAME" 1.1.1.1 443
expect "group:exit-node: Mini PC offered as exit node" yes exit_offered "$EXIT_NAME"
expect "group:exit-node: selects it" yes docker exec "$EXIT_NAME" tailscale set --exit-node="$MINIPC_TAILNET"
expect "group:exit-node: reaches 1.1.1.1:443 through it" yes reachable_from "$EXIT_NAME" 1.1.1.1 443
echo "$failures unexpected result(s)"
[[ $failures -eq 0 ]]
