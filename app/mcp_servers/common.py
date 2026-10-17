import os
import psycopg2
import requests
import jwt
from mcp.server.fastmcp import Context

ISSUER = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
PORTAL_INTERNAL_URL = os.getenv("PORTAL_INTERNAL_URL", "http://app:8000").rstrip("/")
JWKS = PORTAL_INTERNAL_URL + "/.well-known/jwks.json"

def db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "db"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "sewasetu"),
        user=os.getenv("DB_USER", "sewasetu"),
        password=os.getenv("DB_PASSWORD", "sewasetu123"),
    )

def claims(ctx: Context, audience: str, role: str):
    headers = ctx.request_context.request.headers
    auth = headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        raise ValueError("A portal-issued bearer token is required.")
    token = auth[7:].strip()
    try:
        keys = requests.get(JWKS, timeout=5).json()
        header = jwt.get_unverified_header(token)
        key_data = next(k for k in keys["keys"] if k.get("kid") == header.get("kid"))
        key = jwt.algorithms.RSAAlgorithm.from_jwk(key_data)
        c = jwt.decode(token, key, algorithms=["RS256"], audience=audience, issuer=ISSUER)
    except Exception:
        raise ValueError("Invalid, expired, or incorrectly scoped portal token.")
    if c.get("role") != role or c.get("scope") != role:
        raise ValueError("This token does not have the required role and scope.")
    expected = "citizen:" if role == "citizen" else "officer:"
    if not str(c.get("sub", "")).startswith(expected):
        raise ValueError("Invalid token subject.")
    return c
