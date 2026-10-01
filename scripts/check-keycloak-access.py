"""Check who may sign in to which client in the homelab realm.

Creates two throwaway users, one with the realm role `admin` and one without, and runs a
real browser sign-in (authorization code + PKCE) against every client that has a
redirect URI. Each user signs in fresh with a password, and again on top of an existing
SSO session, the path a gate placed only after the password form would miss. Expected:
the admin gets in everywhere, the other user only into keycloak_open_clients
(ansible/roles/keycloak/defaults/main.yml). The users are deleted afterwards, also on
failure. Exits 1 on any unexpected result.

    KEYCLOAK_ADMIN_USER=$(vault kv get -field=keycloak_admin_user secret/ansible) \\
    KEYCLOAK_ADMIN_PASSWORD=$(vault kv get -field=keycloak_admin_password secret/ansible) \\
    python3 scripts/check-keycloak-access.py
"""

import base64
import hashlib
import http.cookiejar
import json
import os
import re
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

KEYCLOAK = os.environ.get("KEYCLOAK_URL", "https://auth.example.com")
REALM = "homelab"
DEFAULTS = (
    Path(__file__).resolve().parents[1] / "ansible/roles/keycloak/defaults/main.yml"
)
# Clients a browser never signs in to: no redirect URIs, or no authorization code flow.
SKIP = {"admin-cli", "broker", "realm-management"}


def open_clients() -> set[str]:
    """The keycloak_open_clients list from the role defaults, the single source of intent."""
    lines = DEFAULTS.read_text().splitlines()
    start = lines.index("keycloak_open_clients:") + 1
    names = set()
    for line in lines[start:]:
        match = re.match(r"^\s+-\s+([\w-]+)", line)
        if not match:
            break
        names.add(match.group(1))
    return names


def api(method: str, path: str, token: str, body: dict | None = None):
    request = urllib.request.Request(
        f"{KEYCLOAK}/admin/realms/{REALM}{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = response.read()
        location = response.headers.get("Location", "")
    return json.loads(payload) if payload else location


def admin_token() -> str:
    form = urllib.parse.urlencode(
        {
            "client_id": "admin-cli",
            "grant_type": "password",
            "username": os.environ["KEYCLOAK_ADMIN_USER"],
            "password": os.environ["KEYCLOAK_ADMIN_PASSWORD"],
        }
    ).encode()
    url = f"{KEYCLOAK}/realms/master/protocol/openid-connect/token"
    with urllib.request.urlopen(url, data=form, timeout=20) as response:
        return json.load(response)["access_token"]


def create_user(token: str, username: str, password: str, admin: bool) -> str:
    location = api(
        "POST",
        "/users",
        token,
        {
            "username": username,
            "enabled": True,
            "email": f"{username}@example.invalid",
            "emailVerified": True,
            "firstName": "Access",
            "lastName": "Check",
            "credentials": [
                {"type": "password", "value": password, "temporary": False}
            ],
        },
    )
    user_id = location.rsplit("/", 1)[1]
    if admin:
        role = api("GET", "/roles/admin", token)
        api("POST", f"/users/{user_id}/role-mappings/realm", token, [role])
    return user_id


class LoginForm(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.action: str | None = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form" and attrs.get("id") == "kc-form-login":
            self.action = attrs.get("action")


class StopAtApp(urllib.request.HTTPRedirectHandler):
    """Follow redirects within Keycloak; stop at the redirect back to the client.

    The client's redirect URI can itself be a Keycloak URL (the account console), so the
    stop is the URI the sign-in asked for, not merely leaving Keycloak.
    """

    target = ""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if newurl.startswith(self.target) or not newurl.startswith(KEYCLOAK):
            raise ReachedApp(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class ReachedApp(Exception):
    def __init__(self, url: str) -> None:
        super().__init__(url)
        self.url = url


def redirect_uri(client: dict) -> str:
    uri = client["redirectUris"][0].replace("*", "access-check")
    return KEYCLOAK + uri if uri.startswith("/") else uri


def sign_in(opener, client: dict, username: str, password: str) -> str:
    """Return 'allowed', 'denied' or a description of anything else."""
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    query = urllib.parse.urlencode(
        {
            "client_id": client["clientId"],
            "redirect_uri": redirect_uri(client),
            "response_type": "code",
            "scope": "openid",
            "state": secrets.token_urlsafe(16),
            "code_challenge": challenge.rstrip(b"=").decode(),
            "code_challenge_method": "S256",
        }
    )
    auth = f"{KEYCLOAK}/realms/{REALM}/protocol/openid-connect/auth?{query}"
    opener.stop.target = redirect_uri(client)

    def outcome(request) -> tuple[str, str]:
        try:
            with opener.open(request, timeout=20) as response:
                return "page", response.read().decode(errors="replace")
        except ReachedApp as reached:
            back = reached.url.startswith(opener.stop.target) and "code=" in reached.url
            return ("allowed" if back else f"redirected to {reached.url[:60]}"), ""
        except urllib.error.HTTPError as error:
            return "page", error.read().decode(errors="replace")

    kind, html = outcome(auth)
    if kind == "page":
        form = LoginForm()
        form.feed(html)
        if form.action:
            data = urllib.parse.urlencode({"username": username, "password": password})
            kind, html = outcome(
                urllib.request.Request(form.action, data=data.encode())
            )
    if kind != "page":
        return kind
    if "access denied" in html.lower():
        return "denied"
    title = re.search(r"<title>(.*?)</title>", html, re.DOTALL)
    feedback = re.search(r'id="input-error"[^>]*>\s*(.*?)\s*<', html, re.DOTALL)
    detail = f" ({feedback.group(1).strip()})" if feedback else ""
    return (
        f"unexpected page: {title.group(1).strip() if title else html[:80]!r}{detail}"
    )


def new_opener():
    stop = StopAtApp()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), stop
    )
    opener.stop = stop
    return opener


def main() -> int:
    token = admin_token()
    open_names = open_clients()
    clients = [
        c
        for c in api("GET", "/clients?max=200", token)
        if c["clientId"] not in SKIP
        and c.get("standardFlowEnabled")
        and c.get("redirectUris")
    ]
    users = {
        "admin": (
            f"access-check-admin-{secrets.token_hex(3)}",
            secrets.token_urlsafe(24),
        ),
        "member": (
            f"access-check-member-{secrets.token_hex(3)}",
            secrets.token_urlsafe(24),
        ),
    }
    ids = {}
    failures = 0
    try:
        for kind, (username, password) in users.items():
            ids[kind] = create_user(token, username, password, admin=kind == "admin")

        print(f"open clients: {sorted(open_names)}")
        print(f"{'client':24} {'user':7} {'path':6} {'expected':8} result")
        for kind, (username, password) in users.items():
            # One SSO session per user, opened on an open client, reused for every other.
            sso = new_opener()
            first = next(c for c in clients if c["clientId"] == "gym-bro")
            sign_in(sso, first, username, password)
            for client in sorted(clients, key=lambda c: c["clientId"]):
                expected = (
                    "allowed"
                    if kind == "admin" or client["clientId"] in open_names
                    else "denied"
                )
                for path, opener in (("fresh", new_opener()), ("sso", sso)):
                    # Keycloak counts "Access denied" as a failed login, and two failures
                    # within a second lock the account for a minute. This checks the gate,
                    # not brute-force protection, so start each attempt from zero.
                    api(
                        "DELETE",
                        f"/attack-detection/brute-force/users/{ids[kind]}",
                        admin_token(),
                    )
                    result = sign_in(opener, client, username, password)
                    ok = result == expected
                    failures += not ok
                    mark = "ok" if ok else "FAIL"
                    print(
                        f"{client['clientId']:24} {kind:7} {path:6} {expected:8} {result}  {mark}"
                    )
    finally:
        token = admin_token()
        for user_id in ids.values():
            api("DELETE", f"/users/{user_id}", token)
        print(f"deleted {len(ids)} temporary users")

    print(f"{failures} unexpected result(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
