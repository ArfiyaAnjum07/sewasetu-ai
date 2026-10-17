import os
import sys
from datetime import datetime, timedelta
from mcp.server.fastmcp import FastMCP, Context

# Ensure app root is on path
if "/app" not in sys.path:
    sys.path.insert(0, "/app")

from common import db, claims, send_sms, BLOCKS, SLA_DAYS

AUDIENCE = os.getenv("MCP_AUDIENCE", "http://localhost:8102")
mcp = FastMCP("Sewa Setu Block Officer", host="0.0.0.0", port=8102, stateless_http=True)


@mcp.tool()
def pending_queue(
    ctx: Context,
    block: str = None,
    village: str = None,
    urgency_only: bool = False,
    limit: int = 20,
    offset: int = 0
) -> dict:
    """List pending applications awaiting block officer verification.
    
    Args:
        block: Optional block filter ('Sonari', 'Rajapara', 'Dhemaji Pathar', 'Borgaon', 'Namti', 'Khelua').
        village: Optional village name filter.
        urgency_only: If True, only returns cases approaching the 15-day SLA deadline (10+ days pending).
        limit: Max applications to return (1 to 100).
        offset: Pagination offset.
    """
    claims(ctx, AUDIENCE, "officer")
    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    where_clauses = ["status='PENDING'"]
    params = []

    if block:
        b_clean = block.strip()
        matched_block = next((b for b in BLOCKS if b.lower() == b_clean.lower()), b_clean)
        where_clauses.append("block = %s")
        params.append(matched_block)

    if village:
        where_clauses.append("LOWER(village) LIKE LOWER(%s)")
        params.append(f"%{village.strip()}%")

    if urgency_only:
        cutoff = datetime.now() - timedelta(days=10)
        where_clauses.append("submitted_at <= %s")
        params.append(cutoff)

    where_str = " AND ".join(where_clauses)
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM applications WHERE {where_str}", params)
        total_pending = cur.fetchone()[0]

        query = f"""
            SELECT id, application_no, applicant_name, village, block, submitted_at, dob
            FROM applications 
            WHERE {where_str} 
            ORDER BY submitted_at ASC 
            LIMIT %s OFFSET %s
        """
        cur.execute(query, params + [limit, offset])
        rows = cur.fetchall()

        now = datetime.now()
        pending_list = []
        for r in rows:
            sub_at = r[5]
            days_pending = (now - sub_at).days if sub_at else 0
            sla_remaining = max(0, SLA_DAYS - days_pending)
            sla_status = "CRITICAL" if days_pending >= 13 else ("WARNING" if days_pending >= 10 else "NORMAL")

            pending_list.append({
                "id": r[0],
                "application_no": r[1],
                "applicant_name": r[2],
                "village": r[3],
                "block": r[4],
                "submitted_at": str(sub_at) if sub_at else None,
                "days_pending": days_pending,
                "days_until_deemed_approval": sla_remaining,
                "sla_status": sla_status
            })

        return {
            "total_pending_matching": total_pending,
            "returned_count": len(pending_list),
            "limit": limit,
            "offset": offset,
            "pending_applications": pending_list
        }
    finally:
        conn.close()


@mcp.tool()
def get_application_details(ctx: Context, application_id: int = None, application_no: str = None) -> dict:
    """Retrieve complete application details, bank information, age proof status, and full audit trail for an officer review.
    
    Args:
        application_id: The numeric ID of the application.
        application_no: Or the alphanumeric application number (e.g. SSP26...).
    """
    claims(ctx, AUDIENCE, "officer")
    if not application_id and not application_no:
        raise ValueError("Either application_id or application_no must be provided.")

    conn = db()
    try:
        cur = conn.cursor()
        if application_id:
            cur.execute(
                """SELECT id, application_no, applicant_name, mobile, dob, gender, marital_status,
                          husband_name, village, block, bank_account, ifsc, doc_path, status,
                          submitted_at, decided_at, decided_by
                   FROM applications WHERE id=%s""", (application_id,)
            )
        else:
            cur.execute(
                """SELECT id, application_no, applicant_name, mobile, dob, gender, marital_status,
                          husband_name, village, block, bank_account, ifsc, doc_path, status,
                          submitted_at, decided_at, decided_by
                   FROM applications WHERE application_no=%s""", (application_no.strip(),)
            )

        row = cur.fetchone()
        if not row:
            return {"found": False, "message": "Application not found."}

        app_id = row[0]
        dob = row[4]
        sub_at = row[14]
        now = datetime.now()
        age = None
        if dob:
            age = (now.date().year - dob.year) - ((now.date().month, now.date().day) < (dob.month, dob.day))

        doc_path = row[12]
        doc_exists = bool(doc_path and os.path.exists(doc_path))
        doc_size = os.path.getsize(doc_path) if doc_exists else None

        days_pending = (now - sub_at).days if sub_at and row[13] == "PENDING" else None
        sla_remaining = max(0, SLA_DAYS - days_pending) if days_pending is not None else None

        # Fetch audit history
        cur.execute(
            "SELECT action, actor, note, at FROM audit_log WHERE application_id=%s ORDER BY at ASC",
            (app_id,)
        )
        audit_trail = [
            {"action": a[0], "actor": a[1], "note": a[2], "at": str(a[3]) if a[3] else None}
            for a in cur.fetchall()
        ]

        return {
            "found": True,
            "id": app_id,
            "application_no": row[1],
            "applicant_name": row[2],
            "mobile": row[3],
            "dob": str(dob) if dob else None,
            "calculated_age": age,
            "is_age_eligible": (age >= 60) if age is not None else False,
            "gender": row[5],
            "marital_status": row[6],
            "husband_name": row[7],
            "village": row[8],
            "block": row[9],
            "bank_account": row[10],
            "ifsc": row[11],
            "document": {
                "doc_path": doc_path,
                "file_exists": doc_exists,
                "file_size_bytes": doc_size
            },
            "status": row[13],
            "submitted_at": str(sub_at) if sub_at else None,
            "decided_at": str(row[15]) if row[15] else None,
            "decided_by": row[16],
            "days_pending": days_pending,
            "days_until_deemed_approval": sla_remaining,
            "audit_trail": audit_trail
        }
    finally:
        conn.close()


@mcp.tool()
def record_decision(ctx: Context, application_id: int, decision: str, reason: str) -> dict:
    """Record an official approval or rejection decision on a pending application with audit logging and citizen SMS notification.
    
    Args:
        application_id: The ID of the pending application.
        decision: Must be 'APPROVED' or 'REJECTED'.
        reason: Justification/note for the decision (mandatory for REJECTED, recorded against officer name in audit log).
    """
    c = claims(ctx, AUDIENCE, "officer")
    officer_sub = c["sub"]
    officer_name = officer_sub.split(":", 1)[1] if ":" in officer_sub else officer_sub

    decision = decision.strip().upper()
    reason = reason.strip()[:500]

    if decision not in ("APPROVED", "REJECTED"):
        raise ValueError("Decision must be either 'APPROVED' or 'REJECTED'.")
    if decision == "REJECTED" and not reason:
        raise ValueError("A specific rejection reason is mandatory when rejecting an application.")

    conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT status, application_no, applicant_name, mobile FROM applications WHERE id=%s FOR UPDATE",
            (application_id,)
        )
        row = cur.fetchone()
        if not row:
            raise ValueError("Application not found.")
        current_status, app_no, applicant_name, mobile = row

        if current_status != "PENDING":
            raise ValueError(f"Application is in '{current_status}' state; only PENDING applications can receive an officer decision.")

        # Update application status
        cur.execute(
            """UPDATE applications 
               SET status=%s, decided_at=NOW(), decided_by=%s 
               WHERE id=%s AND status='PENDING'""",
            (decision, officer_name, application_id)
        )
        if cur.rowcount != 1:
            raise ValueError("Application state changed concurrently; please reload the queue.")

        # Write audit log entry
        cur.execute(
            """INSERT INTO audit_log (application_id, action, actor, note, at)
               VALUES (%s, %s, %s, %s, NOW())""",
            (application_id, decision, officer_sub, reason or f"Decision {decision} by {officer_name}")
        )
        conn.commit()

        # Send official SMS notification to citizen
        if decision == "APPROVED":
            sms_text = f"Sewa Setu: Application {app_no} has been APPROVED by the Block Officer. Pension disbursement will begin shortly."
        else:
            sms_text = f"Sewa Setu: Application {app_no} was not approved. Reason: {reason}. You may re-apply after addressing this issue."
        send_sms(mobile, sms_text)

        return {
            "success": True,
            "application_id": application_id,
            "application_no": app_no,
            "applicant_name": applicant_name,
            "status": decision,
            "decided_by": officer_name,
            "decided_at": str(datetime.now()),
            "audit_logged": True,
            "sms_notification_sent": True,
            "message": f"Application {app_no} for {applicant_name} has been {decision}. Audit trail recorded and citizen notified via SMS."
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@mcp.tool()
def get_block_statistics(ctx: Context, block: str = None) -> dict:
    """Retrieve live statistics for the pension scheme, including pending queue sizes and SLA alerts."""
    claims(ctx, AUDIENCE, "officer")
    conn = db()
    try:
        cur = conn.cursor()
        where_clause = ""
        params = []
        if block:
            b_clean = block.strip()
            matched_block = next((b for b in BLOCKS if b.lower() == b_clean.lower()), b_clean)
            where_clause = "WHERE block = %s"
            params = [matched_block]

        cur.execute(
            f"""SELECT status, COUNT(*) 
                FROM applications 
                {where_clause} 
                GROUP BY status""",
            params
        )
        status_counts = {r[0]: r[1] for r in cur.fetchall()}

        # SLA alerts: pending for 10 or more days
        sla_query = f"""
            SELECT COUNT(*) FROM applications 
            WHERE status='PENDING' 
              AND submitted_at <= NOW() - INTERVAL '10 days'
              {'AND block=%s' if block else ''}
        """
        cur.execute(sla_query, params)
        approaching_sla = cur.fetchone()[0]

        # Breakdown by block
        cur.execute(
            """SELECT block, status, COUNT(*) 
               FROM applications 
               GROUP BY block, status 
               ORDER BY block"""
        )
        block_breakdown = {}
        for b, st, cnt in cur.fetchall():
            if b not in block_breakdown:
                block_breakdown[b] = {}
            block_breakdown[b][st] = cnt

        return {
            "filter_block": block,
            "total_applications": sum(status_counts.values()),
            "status_counts": {
                "PENDING": status_counts.get("PENDING", 0),
                "APPROVED": status_counts.get("APPROVED", 0),
                "REJECTED": status_counts.get("REJECTED", 0),
                "DEEMED_APPROVED": status_counts.get("DEEMED_APPROVED", 0),
                "WITHDRAWN": status_counts.get("WITHDRAWN", 0)
            },
            "sla_alert_count_10days_plus": approaching_sla,
            "block_breakdown": block_breakdown,
            "statutory_sla_days": SLA_DAYS
        }
    finally:
        conn.close()


@mcp.tool()
def search_applications(ctx: Context, query: str, block: str = None, status: str = None, limit: int = 20) -> dict:
    """Search applications across any status by applicant name, mobile number, or application number."""
    claims(ctx, AUDIENCE, "officer")
    q = (query or "").strip()
    limit = max(1, min(limit, 50))
    if not q:
        raise ValueError("A search query string is required.")

    where_clauses = ["(LOWER(applicant_name) LIKE LOWER(%s) OR mobile = %s OR application_no = %s)"]
    params = [f"%{q}%", q, q]

    if block:
        b_clean = block.strip()
        matched_block = next((b for b in BLOCKS if b.lower() == b_clean.lower()), b_clean)
        where_clauses.append("block = %s")
        params.append(matched_block)

    if status:
        where_clauses.append("status = %s")
        params.append(status.strip().upper())

    where_str = " AND ".join(where_clauses)
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            f"""SELECT id, application_no, applicant_name, mobile, village, block, status, submitted_at, decided_at, decided_by 
               FROM applications 
               WHERE {where_str} 
               ORDER BY id DESC LIMIT %s""",
            params + [limit]
        )
        rows = cur.fetchall()
        return {
            "query": q,
            "count": len(rows),
            "results": [
                {
                    "id": r[0],
                    "application_no": r[1],
                    "applicant_name": r[2],
                    "mobile": r[3],
                    "village": r[4],
                    "block": r[5],
                    "status": r[6],
                    "submitted_at": str(r[7]) if r[7] else None,
                    "decided_at": str(r[8]) if r[8] else None,
                    "decided_by": r[9]
                }
                for r in rows
            ]
        }
    finally:
        conn.close()


if __name__ == "__main__":
    from common import run_mcp_server
    run_mcp_server(mcp, port=8102)

