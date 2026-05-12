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

### **A. Database Preparation**
1. Open XAMPP Control Panel and start **MySQL**.
2. Verify the database `property_system` exists and is populated.
3. Ensure `.env` has the correct `MTO_DB_*` credentials.

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
*MTO Treasury System | Enterprise Modernization v2.0*
