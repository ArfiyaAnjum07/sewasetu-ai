import os
from mcp.server.fastmcp import FastMCP, Context
from common import db, claims

AUDIENCE = os.getenv("MCP_AUDIENCE", "http://localhost:8101")
mcp = FastMCP("Sewa Setu Citizen", host="0.0.0.0", port=8101, stateless_http=True)

@mcp.tool()
def check_my_application(ctx: Context) -> dict:
    """Show application status for the authenticated citizen only."""
    c = claims(ctx, AUDIENCE, "citizen")
    mobile = c["sub"].split(":", 1)[1]
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT application_no, applicant_name, status, submitted_at, decided_at "
            "FROM applications WHERE mobile=%s ORDER BY id DESC LIMIT 5", (mobile,)
        )
        return {"applications": [
            {"application_no": r[0], "name": r[1], "status": r[2],
             "submitted_at": str(r[3]) if r[3] else None,
             "decided_at": str(r[4]) if r[4] else None}
            for r in cur.fetchall()
        ]}
    finally:
        conn.close()

@mcp.tool()
def explain_eligibility() -> dict:
    """Explain the basic eligibility requirements."""
    return {
        "minimum_age": 60,
        "required": ["personal details", "valid bank account and IFSC", "age proof"],
        "note": "The portal makes the final eligibility decision."
    }

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
