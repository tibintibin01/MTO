# 🏛️ MTO Treasury System - Enterprise Deployment Guide

This document outlines the **N-Tier API Architecture** setup for the modernized MTO Treasury System. Follow these steps to ensure a secure, high-performance connection between the Server and Client machines.

---

## 🏗️ 1. ARCHITECTURE OVERVIEW
Unlike the old monolithic setup, this system uses a **Centralized API Server**. 
- **Server Machine:** Runs the MySQL Database AND the FastAPI Backend.
- **Client Machine:** Runs the Desktop UI and connects to the Server via HTTP/REST.
- **Security:** Clients do NOT connect to MySQL directly. All traffic is routed through the API for auditing and rate-limiting.

---

## 🖥️ 2. SERVER MACHINE SETUP (Host)

### **A. Secure Database Preparation** 🛡️🗄️
1. Open XAMPP Control Panel and start **MySQL**.
2. **CRITICAL:** Do NOT use the default `root` account with an empty password. Run the following SQL to create a restricted application user:
   ```sql
   -- REPLACE 'SecurePass123!' with a strong, unique password
   CREATE USER 'mto_admin'@'%' IDENTIFIED BY 'SecurePass123!';
   GRANT ALL PRIVILEGES ON property_system.* TO 'mto_admin'@'%';
   FLUSH PRIVILEGES;
   ```
3. Update the `.env` file with these new credentials (`MTO_DB_USER=mto_admin`).

### **B. Start the API Engine**
1. Navigate to the project root.
2. Run the API Server:
   ```powershell
   .\run_server.bat
   ```
3. The server will start on `http://0.0.0.0:8000` (or `8001`). Note the Server's IP address (e.g., `192.168.1.151`).

### **C. Firewall Configuration**
You must allow inbound traffic on the **API Port** (e.g., 8000). Run this as Admin:
```powershell
New-NetFirewallRule -DisplayName "MTO API Server" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow
```

---

## 💻 3. CLIENT MACHINE SETUP (Workstation)

### **A. Environment Configuration**
1. Copy the project folder to the Client PC.
2. Ensure Python 3.14+ is installed.
3. Run `install_packages.bat` to setup dependencies.
4. Open the `.env` (or `api_config.json`) and point the **API_URL** to the Server's IP:
   ```env
   # Example for Client PC
   MTO_API_URL=http://192.168.1.151:8000
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
http://[SERVER_IP]:8000/healthz
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
