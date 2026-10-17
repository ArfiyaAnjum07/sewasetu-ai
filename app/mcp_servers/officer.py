import os
from mcp.server.fastmcp import FastMCP, Context
from common import db, claims

AUDIENCE = os.getenv("MCP_AUDIENCE", "http://localhost:8102")
mcp = FastMCP("Sewa Setu Block Officer", host="0.0.0.0", port=8102, stateless_http=True)

@mcp.tool()
def pending_queue(ctx: Context, limit: int = 20) -> dict:
    """List pending applications for an authenticated officer."""
    claims(ctx, AUDIENCE, "officer")
    limit = max(1, min(limit, 100))
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, application_no, applicant_name, village, block, submitted_at "
            "FROM applications WHERE status='PENDING' ORDER BY submitted_at LIMIT %s",
            (limit,)
        )
        return {"pending": [
            {"id": r[0], "application_no": r[1], "name": r[2],
             "village": r[3], "block": r[4], "submitted_at": str(r[5]) if r[5] else None}
            for r in cur.fetchall()
        ]}
    finally:
        conn.close()

@mcp.tool()
def record_decision(ctx: Context, application_id: int, decision: str, reason: str) -> dict:
    """Record an approve/reject decision on a pending application with an audit entry."""
    c = claims(ctx, AUDIENCE, "officer")
    decision = decision.strip().upper()
    reason = reason.strip()[:500]
    if decision not in ("APPROVED", "REJECTED"):
        raise ValueError("Decision must be APPROVED or REJECTED.")
    if decision == "REJECTED" and not reason:
        raise ValueError("A rejection reason is required.")
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT status FROM applications WHERE id=%s FOR UPDATE", (application_id,))
        row = cur.fetchone()
        if not row:
            raise ValueError("Application not found.")
        if row[0] != "PENDING":
            raise ValueError("Only pending applications can receive a decision.")
        cur.execute(
            "UPDATE applications SET status=%s, decided_at=NOW(), decided_by=%s "
            "WHERE id=%s AND status='PENDING'",
            (decision, c["sub"].split(":", 1)[1], application_id)
        )
        if cur.rowcount != 1:
            raise ValueError("Application changed; reload the queue.")
        cur.execute(
            "INSERT INTO audit_log (application_id, action, actor, note, at) "
            "VALUES (%s, %s, %s, %s, NOW())",
            (application_id, decision, c["sub"], reason)
        )
        conn.commit()
        return {"application_id": application_id, "status": decision, "audit_logged": True}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
