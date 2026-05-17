"""One-shot Strava OAuth: opens browser, captures code on localhost, exchanges for refresh_token.

Run once after creating Strava API app at https://www.strava.com/settings/api.
Fill client_id + client_secret into secrets/strava.json (copy from strava.example.json).

Then:
    python -m src.oauth
"""
from __future__ import annotations

import http.server
import json
import socketserver
import sys
import threading
import urllib.parse
import webbrowser

import requests

from . import config as C

SCOPES = "read,activity:read_all"
PORT = 8723
REDIRECT = f"http://localhost:{PORT}/cb"
AUTH_URL = "https://www.strava.com/oauth/authorize"
TOKEN_URL = "https://www.strava.com/oauth/token"


def main() -> None:
    path = C.SECRETS / "strava.json"
    if not path.exists():
        sys.exit(
            f"No {path} — copy secrets/strava.example.json there and fill in "
            f"client_id + client_secret from "
            f"https://www.strava.com/settings/api"
        )
    creds = json.loads(path.read_text())
    if not creds.get("client_id") or not creds.get("client_secret"):
        sys.exit("client_id + client_secret missing in strava.json")

    received_code = {"v": None}

    class CBHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "code" in q:
                received_code["v"] = q["code"][0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<h1>Authorized.</h1><p>Close this tab.</p>")
            else:
                self.send_response(400)
                self.end_headers()

        def log_message(self, *a):
            pass

    def serve_once():
        socketserver.TCPServer.allow_reuse_address = True
        with socketserver.TCPServer(("localhost", PORT), CBHandler) as httpd:
            while received_code["v"] is None:
                httpd.handle_request()

    t = threading.Thread(target=serve_once, daemon=True)
    t.start()

    params = {
        "client_id": creds["client_id"],
        "redirect_uri": REDIRECT,
        "response_type": "code",
        "approval_prompt": "force",
        "scope": SCOPES,
    }
    url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"
    print(f"Opening browser: {url}")
    webbrowser.open(url)
    t.join(timeout=300)

    if not received_code["v"]:
        sys.exit("No code received within 5 min.")

    print("Code received, exchanging for tokens...")
    r = requests.post(TOKEN_URL, data={
        "client_id": creds["client_id"],
        "client_secret": creds["client_secret"],
        "code": received_code["v"],
        "grant_type": "authorization_code",
    })
    r.raise_for_status()
    tok = r.json()

    creds.update({
        "refresh_token": tok["refresh_token"],
        "access_token": tok["access_token"],
        "expires_at": tok["expires_at"],
        "athlete_id": tok.get("athlete", {}).get("id"),
    })
    path.write_text(json.dumps(creds, indent=2))
    print(f"Saved refresh_token → {path}")
    if creds.get("athlete_id"):
        print(f"Athlete ID: {creds['athlete_id']}")


if __name__ == "__main__":
    main()
