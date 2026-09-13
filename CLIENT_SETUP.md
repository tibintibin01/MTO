# 🏛️ MTO Treasury System - Enterprise Deployment Guide

This document outlines the **N-Tier API Architecture** setup for the modernized MTO Treasury System. Follow these steps to ensure a secure, high-performance connection between the Server and Client machines.

> **Phase 2 security notice:** This older guide is retained for architecture
> background only. Do not copy `.env`, Python, database credentials, or the
> project tree to a client PC. Follow
> [`docs/REMEDIATION_PHASE_2_RUNBOOK.md`](docs/REMEDIATION_PHASE_2_RUNBOOK.md)
> for the approved HTTPS server and desktop package procedure.
---

## 🏗️ 1. ARCHITECTURE OVERVIEW
Unlike the old monolithic setup, this system uses a **Centralized API Server**. 
- **Server Machine:** Runs the MySQL Database AND the FastAPI Backend.
- **Client Machine:** Runs `Treasury.exe` and connects through authenticated HTTPS/REST.
- **Security:** Clients do NOT connect to MySQL directly. All traffic is routed through the API for auditing and rate-limiting.

---

## 🖥️ 2. SERVER MACHINE SETUP (Host)

### **A. Secure Database Preparation** 🛡️🗄️
1. Open XAMPP Control Panel and start **MySQL**.
2. **CRITICAL:** Do NOT use the default `root` account with an empty password. Run the following SQL to create a restricted application user with least-privilege access:
   ```sql
   -- REPLACE 'SecurePass123!' with a strong, unique password
   CREATE USER 'mto_app'@'%' IDENTIFIED BY 'SecurePass123!';
   GRANT SELECT, INSERT, UPDATE ON property_system.* TO 'mto_app'@'%';
   FLUSH PRIVILEGES;
   ```
3. Update the `.env` file with these new credentials (`MTO_DB_USER=mto_app`).

### **B. Start the API Engine**
1. Navigate to the project root.
2. Run the API Server:
   ```powershell
   .\run_server.bat
   ```
3. The API binds its configured LAN interface using authenticated HTTPS on port `8001`.

### **C. Firewall Configuration**
You must allow inbound traffic on the **API Port** (e.g., 8000). Run this as Admin:
```powershell
New-NetFirewallRule -DisplayName "MTO API Server" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow
```

---

## 💻 3. CLIENT MACHINE SETUP (Workstation)

### **A. Environment Configuration**
1. Do not copy the source tree, `.env`, Python environment, or database credentials to a client PC.
2. Deploy the secured `Treasury.exe` package produced by the Phase 2 build procedure.
3. Install only the public LAN CA and endpoint-only `server_config.json` described in the Phase 2 runbook.
4. Point `server_config.json` to the authenticated HTTPS server name:
   ```json
   {
     "server_url": "https://<MTO-SERVER-NAME>:8001",
     "ca_certificate": "certificates/mto-lan-ca.pem",
     "client_version": "2.1.0"
   }
   ```

### **B. Launch the Interface**
Start the modernized UI:
```powershell
.\run_system.bat
```

---

## 📡 4. HEALTH & CONNECTIVITY VERIFICATION

To verify that the Client can see the Server and the Database is healthy, visit the **Orchestration Beacon** in any browser:
```text
python -m scripts.check_api_readiness --timeout-seconds 90
```

**Expected JSON Response:**
```json
{
  "status": "healthy",
  "database": "connected",
  "last_backup": "OK"
}
```

---

## 🛠️ 5. TROUBLESHOOTING
- **Status "Offline" in Footer:** Check if the `run_server.bat` is still active on the host machine.
- **Connection Refused:** Check the Windows Firewall on the **Server** machine.
- **Locale Errors:** Ensure the `locales/` directory (containing `en.json` and `tl.json`) is present on the client PC.
- **Authentication Failed:** Verify the `MTO_API_SECRET_KEY` matches on both Server and Client.

---
 
 ## 🛡️ 6. GOVERNMENT-GRADE SECURITY HARDENING
 
 To achieve a 10/10 Engineering Rating and ensure government compliance, the following protocols are baked into the architecture:
 
- **Cryptographic Credentials:** All user passwords are hashed using **PBKDF2-SHA256** with 200,000 iterations. Plaintext or MD5 storage is strictly forbidden.
- **Session Governance:** The system monitors activity heartbeats. If a terminal is idle for **15 minutes**, the session is automatically terminated to prevent unauthorized physical access.
- **Data at Rest Protection:** Ensure the host machine uses BitLocker or a similar full-disk encryption tool to protect the MySQL data directory from physical drive theft.
- **Audit Non-Repudiation:** Every action (Edit/Delete/Payment) is cryptographically signed in the `audit_logs` table with the User ID and a Server-Side Timestamp.
 
 ---
 *MTO Treasury System | Enterprise Modernization v2.0*
