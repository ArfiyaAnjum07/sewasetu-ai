# Loom Video Script: Sewa Setu AI Assistant (3 Minutes)

**Target Duration:** Exactly 3 minutes (180 seconds)  
**Format:** Face & Screen recording  
**Screen Setup:** Have `http://localhost:8000/eval-dashboard` open in Chrome, with the terminal or code editor on the side.

---

## Breakdown & Timings

### 0:00 – 0:30 (30s) &middot; Introduction & The Mission
* **Face on Camera + Screen showing Sewa Setu Portal:**
  > *"Hello Director. Last month in Sonari block, a 70-year-old woman tried to apply for her ₹250 monthly pension through an AI assistant, and the system failed her. It gave outdated information and had no way to talk to our portal.*  
  > *Today, I'm presenting the complete solution: two production-grade Model Context Protocol (MCP) servers built over streamable HTTP, connecting any AI assistant directly to Sewa Setu as the authoritative system of record."*

---

### 0:30 – 1:15 (45s) &middot; Architecture & The Two MCP Servers
* **Screen showing Architecture Banner & Terminal/Code:**
  > *"To ensure safety and public trust, we made three foundational design decisions:*  
  > *First, strict dual-surface separation. A citizen's assistant on port 8101 only sees citizen tools—like checking eligibility, submitting an application, tracking status, or withdrawing. The block officer's assistant runs on a completely separate endpoint on port 8102, handling queue triage, case verification, and decision approvals. A citizen's assistant cannot even see officer tools, preventing prompt injection or privilege escalation.*  
  > *Second, zero policy drift: both MCP servers directly invoke the portal's single source of truth validation engine (`validate_application` and `create_application`). What the counter accepts, the assistant accepts; what the paper form rejects, the assistant rejects.*  
  > *Third, full OAuth 2.1 compliance with RS256 JWT tokens. The citizen's mobile number is cryptographically bound to the token subject, completely preventing identity spoofing on shared village kiosks."*

---

### 1:15 – 2:15 (60s) &middot; The Personas & Empirical Evals (Live Demo)
* **Screen showing `/eval-dashboard` & clicking "Run Evals Live":**
  > *"Rather than guessing, we sat at the counter in our heads and invented six real citizens of Purvanchal. Let's run the evaluation suite live right now.*  
  > *(Click 'Run Evals Live' & show the 100% pass toast in ~600ms)*  
  > *Notice our pass rate is 100%, with 20 out of 20 database invariants verified.*  
  > *Here is Phuleshwari Devi, a 74-year-old widow from Namti village in Sonari block, applying via a CSC kiosk with her grandson. The assistant validates her eligibility, uploads her verified age proof, creates application SSP26517319 in the database, sets up her status portal account, and dispatches an SMS acknowledgment.*  
  > *Next, Bhaben Gogoi from Borgaon, whose earlier application was rejected. Our eval verifies that his old record is preserved while his fresh application is accepted.*  
  > *For Ramesh Chandra Das, age 58, our boundary eval confirms that underage applicants are strictly prevented from entering the database.*  
  > *And in Monowara Begum's lifecycle, the citizen assistant submits the application, and then the officer assistant inspects the queue and records an official approval with audit logging and SMS delivery."*

---

### 2:15 – 2:45 (30s) &middot; What We Learned & Fixed
* **Screen scrolling to "What Evals Found & What We Changed":**
  > *"Our evals caught critical real-world failure modes before production:*  
  > *First, small LLMs frequently defaulted to ISO dates (YYYY-MM-DD) instead of the portal's DD/MM/YYYY. We built defensive normalization in the MCP layer so valid senior citizens aren't rejected over formatting.*  
  > *Second, we diagnosed and resolved an ASGI header detachment in FastMCP by engineering a custom header capture middleware, ensuring reliable bearer token validation.*  
  > *Third, we added voluntary application withdrawal so citizens with typos in bank accounts aren't permanently locked out."*

---

### 2:45 – 3:00 (15s) &middot; Conclusion & Future Improvement
* **Face on Camera + Screen showing Design Note:**
  > *"With more time, we would build on-device document OCR to catch blurry Aadhaar uploads before they reach the officer queue.*  
  > *The portal URL, MCP endpoints, evaluation dashboard, and full Git repository are ready for your review. Thank you!"*
