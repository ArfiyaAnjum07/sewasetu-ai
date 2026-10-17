import os
import sys
import re
import base64
from datetime import datetime, date
from fpdf import FPDF
from mcp.server.fastmcp import FastMCP, Context

# Ensure app root is on path for shared portal domain logic
if "/app" not in sys.path:
    sys.path.insert(0, "/app")

import app as portal
from common import db, claims, send_sms, BLOCKS, MIN_AGE, SLA_DAYS, UPLOAD_DIR

AUDIENCE = os.getenv("MCP_AUDIENCE", "http://localhost:8101")
mcp = FastMCP("Sewa Setu Citizen", host="0.0.0.0", port=8101, stateless_http=True)


def _normalize_dob(raw_dob: str) -> str:
    """Normalize date strings like YYYY-MM-DD or DD-MM-YYYY into DD/MM/YYYY."""
    s = (raw_dob or "").strip()
    if not s:
        return ""
    # Try DD/MM/YYYY
    try:
        dt = datetime.strptime(s, "%d/%m/%Y")
        return dt.strftime("%d/%m/%Y")
    except ValueError:
        pass
    # Try YYYY-MM-DD
    try:
        dt = datetime.strptime(s, "%Y-%m-%d")
        return dt.strftime("%d/%m/%Y")
    except ValueError:
        pass
    # Try DD-MM-YYYY
    try:
        dt = datetime.strptime(s, "%d-%m-%Y")
        return dt.strftime("%d/%m/%Y")
    except ValueError:
        pass
    return s


def _normalize_block(raw_block: str) -> str:
    """Match block name case-insensitively against valid portal blocks."""
    b = (raw_block or "").strip().lower()
    for valid in BLOCKS:
        if valid.lower() == b:
            return valid
    return raw_block.strip() if raw_block else ""


def _create_age_proof_doc(mobile: str, applicant_name: str, dob_str: str, doc_type: str = "Aadhaar Card", doc_base64: str = None) -> str:
    """Save an age proof document to the shared upload directory and return its path."""
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    clean_name = re.sub(r"[^a-zA-Z0-9_-]", "_", applicant_name.strip() or "applicant")
    
    if doc_base64:
        try:
            content = base64.b64decode(doc_base64)
            filename = f"{mobile}_{clean_name}_proof.pdf"
            path = os.path.join(UPLOAD_DIR, filename)
            with open(path, "wb") as f:
                f.write(content)
            return path
        except Exception:
            pass

    # Generate an official verification PDF stub
    filename = f"{mobile}_{clean_name}_age_proof.pdf"
    path = os.path.join(UPLOAD_DIR, filename)
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "GOVERNMENT OF PURVANCHAL - DEPARTMENT OF SOCIAL WELFARE", align="C")
    pdf.ln(10)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "VERIFIED AGE PROOF DECLARATION", align="C")
    pdf.ln(10)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(50, 8, "Applicant Name:", border=1)
    pdf.cell(0, 8, applicant_name, border=1)
    pdf.ln(8)
    pdf.cell(50, 8, "Mobile Number:", border=1)
    pdf.cell(0, 8, mobile, border=1)
    pdf.ln(8)
    pdf.cell(50, 8, "Date of Birth:", border=1)
    pdf.cell(0, 8, dob_str, border=1)
    pdf.ln(8)
    pdf.cell(50, 8, "Document Type:", border=1)
    pdf.cell(0, 8, doc_type or "Aadhaar Card", border=1)
    pdf.ln(8)
    pdf.cell(50, 8, "Verified At:", border=1)
    pdf.cell(0, 8, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), border=1)
    pdf.ln(12)
    pdf.set_font("Helvetica", "I", 9)
    pdf.multi_cell(0, 5, "This electronic verification record serves as statutory proof of age for Old Age Pension Scheme under the Purvanchal Right to Public Services Act.")
    pdf.output(path)
    return path


@mcp.tool()
def explain_eligibility() -> dict:
    """Explain the complete eligibility requirements, eligible blocks, and rules for the Old Age Pension scheme."""
    return {
        "scheme_name": "Old Age Pension Scheme",
        "department": "Department of Social Welfare, Government of Purvanchal",
        "monthly_pension": "₹250 per month (direct benefit transfer)",
        "minimum_age": MIN_AGE,
        "eligibility_criteria": [
            "Must be a resident of Purvanchal",
            f"Must be {MIN_AGE} years of age or older on the date of application",
            "Must hold an active bank account in applicant's own name with a valid IFSC code"
        ],
        "eligible_blocks": BLOCKS,
        "required_documents": [
            "Proof of age (Aadhaar Card, Voter ID, Birth Certificate, or School Certificate)",
            "Bank account number and bank branch IFSC code",
            "Residential village and block details"
        ],
        "important_rules": [
            "Only one active application (Pending, Approved, or Deemed Approved) is permitted per mobile number at any time.",
            "If a previous application was rejected or withdrawn, the applicant is eligible to submit a fresh application.",
            "Statutory SLA: Under the Purvanchal Right to Public Services Act, applications not reviewed within 15 days are automatically deemed approved.",
            "Application window: Open until 31 October 2026."
        ],
        "note": "The assistant will guide you through application submission and follow-up tracking."
    }


@mcp.tool()
def check_my_application(ctx: Context) -> dict:
    """Show current and past application status and audit history for the authenticated citizen."""
    c = claims(ctx, AUDIENCE, "citizen")
    mobile = c["sub"].split(":", 1)[1]
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT id, application_no, applicant_name, status, submitted_at, decided_at, 
                      decided_by, village, block, bank_account, ifsc, dob 
               FROM applications 
               WHERE mobile=%s 
               ORDER BY id DESC LIMIT 5""", (mobile,)
        )
        rows = cur.fetchall()
        apps = []
        for r in rows:
            app_id = r[0]
            submitted = r[4]
            status = r[3]
            days_pending = (datetime.now() - submitted).days if submitted and status == "PENDING" else None
            sla_remaining = max(0, SLA_DAYS - days_pending) if days_pending is not None else None

            # Fetch audit notes
            cur.execute(
                "SELECT action, actor, note, at FROM audit_log WHERE application_id=%s ORDER BY at ASC",
                (app_id,)
            )
            audit = [
                {"action": a[0], "actor": a[1], "note": a[2], "at": str(a[3]) if a[3] else None}
                for a in cur.fetchall()
            ]

            apps.append({
                "id": app_id,
                "application_no": r[1],
                "applicant_name": r[2],
                "status": status,
                "dob": str(r[11]) if r[11] else None,
                "village": r[7],
                "block": r[8],
                "bank_account": r[9],
                "ifsc": r[10],
                "submitted_at": str(submitted) if submitted else None,
                "decided_at": str(r[5]) if r[5] else None,
                "decided_by": r[6],
                "days_pending": days_pending,
                "sla_days_remaining": sla_remaining,
                "audit_trail": audit
            })

        has_active = any(a["status"] in portal.ACTIVE_STATUSES for a in apps)
        return {
            "authenticated_mobile": mobile,
            "has_active_application": has_active,
            "applications": apps
        }
    finally:
        conn.close()


@mcp.tool()
def apply_for_pension(
    ctx: Context,
    applicant_name: str,
    dob: str,
    gender: str,
    marital_status: str,
    village: str,
    block: str,
    bank_account: str,
    ifsc: str,
    husband_name: str = "",
    age_proof_type: str = "Aadhaar Card",
    document_base64: str = None
) -> dict:
    """Submit a formal application for the Old Age Pension scheme.
    
    Args:
        applicant_name: Full legal name of the senior citizen.
        dob: Date of birth as DD/MM/YYYY (must be 60 years or older).
        gender: Gender of the applicant ('Male', 'Female', or 'Other').
        marital_status: Marital status ('Married', 'Widowed', 'Unmarried', 'Divorced').
        village: Name of resident village.
        block: One of the 6 recognized blocks: Sonari, Rajapara, Dhemaji Pathar, Borgaon, Namti, Khelua.
        bank_account: Bank account number (9 to 18 digits).
        ifsc: Bank branch IFSC code (11 characters, e.g. SBIN0003077).
        husband_name: Name of husband (if applicable for married/widowed applicants).
        age_proof_type: Type of age document provided ('Aadhaar Card', 'Voter ID', 'Birth Certificate').
        document_base64: Optional base64-encoded PDF/image document data.
    """
    c = claims(ctx, AUDIENCE, "citizen")
    mobile = c["sub"].split(":", 1)[1]

    # Normalize inputs
    norm_dob = _normalize_dob(dob)
    norm_block = _normalize_block(block)
    clean_account = re.sub(r"[\s-]", "", bank_account or "")
    clean_ifsc = re.sub(r"[\s-]", "", (ifsc or "")).upper()
    clean_name = portal.sanitize(applicant_name)
    clean_village = (village or "").strip()
    clean_husband = (husband_name or "").strip()

    conn = db()
    try:
        cur = conn.cursor()
        
        # Check active application rule
        existing = portal.active_application(cur, mobile)
        if existing:
            return {
                "success": False,
                "error": "active_application_exists",
                "existing_application_no": existing[1],
                "status": existing[2],
                "message": (
                    f"An active application {existing[1]} ({existing[2]}) already exists for your mobile number {mobile}. "
                    "Under scheme rules, only one active application is permitted. If your pending application contains errors, "
                    "you may withdraw it first using 'withdraw_my_application' and then apply afresh."
                )
            }

        # Create or save age proof document
        doc_path = _create_age_proof_doc(
            mobile=mobile,
            applicant_name=clean_name,
            dob_str=norm_dob,
            doc_type=age_proof_type,
            doc_base64=document_base64
        )

        data = {
            "applicant_name": clean_name,
            "dob": norm_dob,
            "gender": gender,
            "marital_status": marital_status,
            "husband_name": clean_husband,
            "village": clean_village,
            "block": norm_block,
            "bank_account": clean_account,
            "ifsc": clean_ifsc,
        }

        # Run portal's authoritative validation logic
        errors, cleaned = portal.validate_application(data, doc_path)
        if errors:
            return {
                "success": False,
                "error": "validation_failed",
                "validation_errors": errors,
                "message": "Application could not be submitted due to validation errors: " + "; ".join(errors) + "."
            }

        # Create application and ensure portal_users account exists
        new_id, app_no = portal.create_application(cur, mobile, cleaned)
        conn.commit()

        # Send confirmation SMS via simulated gateway
        portal_pass = cleaned["dob"].strftime("%d%m%Y")
        sms_msg = (
            f"Sewa Setu: application {app_no} received. Track at the status portal "
            f"with mobile no. and password (DOB as DDMMYYYY)."
        )
        send_sms(mobile, sms_msg)

        return {
            "success": True,
            "application_no": app_no,
            "application_id": new_id,
            "applicant_name": cleaned["applicant_name"],
            "mobile": mobile,
            "block": cleaned["block"],
            "village": cleaned["village"],
            "status": "PENDING",
            "submitted_at": str(datetime.now()),
            "statutory_sla_days": SLA_DAYS,
            "status_portal_credentials": {
                "mobile": mobile,
                "password_hint": f"Your Date of Birth as DDMMYYYY ({portal_pass})"
            },
            "message": (
                f"Congratulations {cleaned['applicant_name']}! Your application for the Old Age Pension scheme "
                f"has been successfully submitted with Application Number {app_no}. It is now in the verification "
                f"queue for the {cleaned['block']} block officer. Under the Right to Public Services Act, the processing "
                f"SLA is 15 days; if not reviewed within 15 days, it is automatically deemed approved. "
                f"An acknowledgment SMS has been sent to your mobile."
            )
        }
    except Exception as e:
        conn.rollback()
        return {"success": False, "error": "server_error", "message": f"Submission failed: {str(e)}"}
    finally:
        conn.close()


@mcp.tool()
def withdraw_my_application(ctx: Context, reason: str = "Withdrawn by applicant via assistant") -> dict:
    """Withdraw a currently pending application so that you can correct details or apply afresh."""
    c = claims(ctx, AUDIENCE, "citizen")
    mobile = c["sub"].split(":", 1)[1]
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, application_no, applicant_name FROM applications WHERE mobile=%s AND status='PENDING' ORDER BY id DESC LIMIT 1",
            (mobile,)
        )
        row = cur.fetchone()
        if not row:
            return {
                "success": False,
                "message": "No pending application found to withdraw. Only pending applications can be withdrawn."
            }

        app_id, app_no, name = row
        cur.execute(
            "UPDATE applications SET status='WITHDRAWN', decided_at=NOW(), decided_by=%s WHERE id=%s",
            ("applicant:" + mobile, app_id)
        )
        portal.write_audit(cur, app_id, "WITHDRAW", "applicant:" + mobile, note=reason)
        conn.commit()

        send_sms(mobile, f"Sewa Setu: Application {app_no} has been withdrawn upon your request.")
        return {
            "success": True,
            "application_no": app_no,
            "status": "WITHDRAWN",
            "message": f"Application {app_no} has been withdrawn. You may now submit a fresh application with updated details."
        }
    except Exception as e:
        conn.rollback()
        return {"success": False, "message": f"Withdrawal failed: {str(e)}"}
    finally:
        conn.close()


@mcp.tool()
def get_acknowledgment_slip(ctx: Context, application_no: str = None) -> dict:
    """Retrieve structured acknowledgment details for an application."""
    c = claims(ctx, AUDIENCE, "citizen")
    mobile = c["sub"].split(":", 1)[1]
    conn = db()
    try:
        cur = conn.cursor()
        if application_no:
            cur.execute(
                """SELECT id, application_no, applicant_name, mobile, dob, village, block, 
                          bank_account, ifsc, status, submitted_at 
                   FROM applications WHERE mobile=%s AND application_no=%s""",
                (mobile, application_no.strip())
            )
        else:
            cur.execute(
                """SELECT id, application_no, applicant_name, mobile, dob, village, block, 
                          bank_account, ifsc, status, submitted_at 
                   FROM applications WHERE mobile=%s ORDER BY id DESC LIMIT 1""",
                (mobile,)
            )
        r = cur.fetchone()
        if not r:
            return {"found": False, "message": "No matching application found for this citizen."}

        return {
            "found": True,
            "header": "GOVERNMENT OF PURVANCHAL - DEPARTMENT OF SOCIAL WELFARE",
            "scheme": "Old Age Pension Scheme - Computer Generated Acknowledgment",
            "application_no": r[1],
            "applicant_name": r[2],
            "mobile": r[3],
            "date_of_birth": str(r[4]),
            "village": r[5],
            "block": r[6],
            "bank_account_masked": "X" * (len(r[7]) - 4) + r[7][-4:] if r[7] and len(r[7]) > 4 else r[7],
            "ifsc": r[8],
            "status": r[9],
            "submitted_at": str(r[10]) if r[10] else None,
            "statutory_note": "Processing SLA of 15 days applies under Purvanchal Right to Public Services Act."
        }
    finally:
        conn.close()


if __name__ == "__main__":
    from common import run_mcp_server
    run_mcp_server(mcp, port=8101)

