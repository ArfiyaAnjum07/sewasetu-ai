import os
import time
import psycopg2
import requests
import jwt
from mcp.server.fastmcp import FastMCP, Context

ISSUER = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
PORTAL_INTERNAL_URL = os.getenv("PORTAL_INTERNAL_URL", "http://app:8000").rstrip("/")
JWKS_URL = PORTAL_INTERNAL_URL + "/.well-known/jwks.json"
SMS_GATEWAY_URL = os.getenv("SMS_GATEWAY_URL", "http://smsgw:8025").rstrip("/")
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/var/sewasetu/uploads")

BLOCKS = ["Sonari", "Rajapara", "Dhemaji Pathar", "Borgaon", "Namti", "Khelua"]
MIN_AGE = 60
SLA_DAYS = 15

_JWKS_CACHE = {"keys": None, "fetched_at": 0}

def db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "db"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "sewasetu"),
        user=os.getenv("DB_USER", "sewasetu"),
        password=os.getenv("DB_PASSWORD", "sewasetu123"),
    )

def _get_jwks():
    now = time.time()
    if _JWKS_CACHE["keys"] and (now - _JWKS_CACHE["fetched_at"] < 300):
        return _JWKS_CACHE["keys"]
    try:
        keys = requests.get(JWKS_URL, timeout=5).json()
        _JWKS_CACHE["keys"] = keys
        _JWKS_CACHE["fetched_at"] = now
        return keys
    except Exception as e:
        if _JWKS_CACHE["keys"]:
            return _JWKS_CACHE["keys"]
        raise RuntimeError(f"Unable to reach portal JWKS endpoint: {e}")

import contextvars
from types import SimpleNamespace
from starlette.types import ASGIApp, Scope, Receive, Send
import uvicorn
import anyio

CURRENT_REQUEST = contextvars.ContextVar("CURRENT_REQUEST", default=None)

class HeaderCaptureMiddleware:
    """Captures HTTP headers from the ASGI scope so tools can access Authorization bearer tokens."""
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "http":
            headers = {}
            for k, v in scope.get("headers", []):
                try:
                    headers[k.decode("latin1").lower()] = v.decode("latin1")
                except Exception:
                    pass
            CURRENT_REQUEST.set(SimpleNamespace(headers=headers))
        await self.app(scope, receive, send)

def run_mcp_server(mcp_instance: FastMCP, host: str = "0.0.0.0", port: int = 8101):
    """Run FastMCP streamable-http wrapped with HeaderCaptureMiddleware for OAuth 2.1 token validation."""
    starlette_app = mcp_instance.streamable_http_app()
    wrapped_app = HeaderCaptureMiddleware(starlette_app)
    config = uvicorn.Config(
        wrapped_app,
        host=host,
        port=port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    anyio.run(server.serve)

def claims(ctx: Context, audience: str, role: str):
    rc = ctx.request_context
    headers = {}
    req = CURRENT_REQUEST.get()
    if req and hasattr(req, "headers"):
        headers = req.headers
        if not hasattr(rc, "request"):
            rc.request = req
    elif hasattr(rc, "request") and hasattr(rc.request, "headers"):
        headers = rc.request.headers

    auth = headers.get("authorization") or headers.get("Authorization") or ""
    if not auth.startswith("Bearer "):
        raise ValueError("A portal-issued bearer token is required in the Authorization header.")
    token = auth[7:].strip()
    try:
        keys = _get_jwks()
        header = jwt.get_unverified_header(token)
        key_data = next(k for k in keys["keys"] if k.get("kid") == header.get("kid"))
        key = jwt.algorithms.RSAAlgorithm.from_jwk(key_data)
        c = jwt.decode(token, key, algorithms=["RS256"], audience=audience, issuer=ISSUER)
    except Exception:
        # Retry with fresh JWKS once in case key was recently rotated
        try:
            keys = requests.get(JWKS_URL, timeout=5).json()
            _JWKS_CACHE["keys"] = keys
            _JWKS_CACHE["fetched_at"] = time.time()
            header = jwt.get_unverified_header(token)
            key_data = next(k for k in keys["keys"] if k.get("kid") == header.get("kid"))
            key = jwt.algorithms.RSAAlgorithm.from_jwk(key_data)
            c = jwt.decode(token, key, algorithms=["RS256"], audience=audience, issuer=ISSUER)
        except Exception:
            raise ValueError("Invalid, expired, or incorrectly scoped portal token.")

    if c.get("role") != role or c.get("scope") != role:
        raise ValueError(f"This token does not have the required role and scope '{role}'.")
    expected = "citizen:" if role == "citizen" else "officer:"
    if not str(c.get("sub", "")).startswith(expected):
        raise ValueError(f"Invalid token subject. Expected subject to begin with '{expected}'.")
    return c

def send_sms(mobile: str, text: str):
    """Dispatch an SMS notification via the simulated telecom gateway."""
    try:
        requests.post(SMS_GATEWAY_URL + "/api/send", json={"to": mobile, "text": text}, timeout=5)
    except Exception:
        pass

