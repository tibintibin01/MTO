# TECHNICAL BRIEF
## Request for GovCloud Hosting and Domain Configuration
### Municipality of Dipaculao, Aurora — Municipal Treasury Office

---

**Date:** May 2026  
**Prepared by:** Municipal Treasury Office, Dipaculao, Aurora  
**Submitted to:** Department of Information and Communications Technology (DICT), Region III

---

## 1. PROJECT OVERVIEW

The Municipal Treasury Office of Dipaculao, Aurora has developed a **Real Property Tax (RPT) Inquiry Portal** — a web-based system that allows taxpayers to view their property assessment, payment history, and account status online.

This initiative supports the national government's thrust toward **digital governance**, **transparency**, and **citizen-centered public service** under the eGovPH program.

---

## 2. SYSTEM DESCRIPTION

| Item | Details |
|---|---|
| **System Name** | Dipaculao Real Property Tax Inquiry Portal |
| **System Type** | Public-facing web application |
| **Primary Users** | Taxpayers of Dipaculao, Aurora (general public) |
| **Secondary Users** | Municipal Treasury Office staff (admin portal) |
| **Purpose** | Allow taxpayers to check property assessment, payment history, and account status using their Tax Declaration Number (TDN) |

---

## 3. TECHNICAL SPECIFICATIONS

| Component | Technology |
|---|---|
| **Frontend** | Next.js 14 (React) — static site generation + server-side rendering |
| **Backend API** | FastAPI (Python 3.11) — RESTful API |
| **Database** | MariaDB 10.6 — hosted on municipal server |
| **Authentication** | JWT (JSON Web Tokens) with refresh token rotation |
| **Web Server** | Nginx (reverse proxy) |
| **SSL/TLS** | Let's Encrypt (HTTPS) |

**Hosting Architecture:**
- The **public portal** (frontend + API) will be hosted on DICT GovCloud
- The **database** remains on the municipal server (on-premises) for data sovereignty
- The portal connects to the municipal database via secure encrypted connection

---

## 4. REQUESTED DOMAIN

**Requested subdomain:** `treasury.dipaculao-aurora.gov.ph`

The parent domain `dipaculao-aurora.gov.ph` is already registered to the Municipality of Dipaculao.

---

## 5. RESOURCE REQUIREMENTS

| Resource | Estimated Requirement |
|---|---|
| **vCPU** | 2 cores |
| **RAM** | 2 GB |
| **Storage** | 20 GB SSD |
| **Bandwidth** | 100 GB/month (estimated) |
| **Expected daily traffic** | 50–200 requests/day |
| **Peak usage** | January–March (RPT payment season) |

---

## 6. DATA PRIVACY AND SECURITY

This system handles personal data of taxpayers and is fully compliant with:

- **Republic Act No. 10173** — Data Privacy Act of 2012
- **Republic Act No. 7160** — Local Government Code (RPT provisions)
- **COA Circular No. 2009-006** — Government financial records retention

**Security measures implemented:**

| Measure | Implementation |
|---|---|
| Data masking | Owner names and PIN numbers are partially masked in public view |
| Rate limiting | 10 requests/minute per IP address |
| HTTPS | All traffic encrypted via TLS 1.2/1.3 |
| Authentication | JWT with 1-hour expiry + refresh token rotation |
| Audit trail | All staff actions logged with timestamp and IP address |
| Input validation | Server-side validation on all inputs |
| SQL injection protection | ORM-based queries (SQLAlchemy), no raw SQL |

**Data exposed publicly (read-only):**
- Property TD Number (searched by user)
- First 3 characters of owner name (masked)
- Barangay location
- Assessed value
- Payment years and amounts
- Account status (Updated / Delinquent / Pending)

**Data NOT exposed publicly:**
- Full owner name
- Complete PIN number
- Personal contact information
- Staff credentials

---

## 7. BACKUP AND DISASTER RECOVERY

| Item | Details |
|---|---|
| **Backup frequency** | Daily automated backup |
| **Backup type** | Hybrid — local storage + USB mirror + cloud storage |
| **Retention** | 7 days local, 14 days USB, 30 days cloud |
| **Recovery time objective** | Less than 4 hours |
| **Recovery point objective** | Less than 24 hours |
| **Financial records retention** | 10 years minimum (COA compliance) |

---

## 8. COMPLIANCE AND LEGAL BASIS

| Requirement | Compliance |
|---|---|
| RA 10173 (Data Privacy Act) | ✅ Data minimization, masking, audit logs |
| RA 7160 (Local Government Code) | ✅ RPT computation follows LGC provisions |
| RA 9485 / RA 11032 (Anti-Red Tape) | ✅ Online service reduces physical visits |
| DICT MC 2022-002 (Data Retention) | ✅ Retention policies configured |
| COA financial records | ✅ 10-year retention enforced |

---

## 9. EXPECTED BENEFITS

1. **Taxpayer convenience** — citizens can check their RPT status anytime without visiting the office
2. **Reduced foot traffic** — fewer inquiries at the counter, staff can focus on collections
3. **Transparency** — public access to property assessment data builds trust
4. **Digital governance** — aligns with eGovPH and Bagong Pilipinas digital transformation agenda
5. **Reduced delinquency** — taxpayers aware of their balance are more likely to pay

---

## 10. CONTACT INFORMATION

**Municipal Treasurer**  
Municipal Treasury Office  
Doña Aurora St., North Poblacion  
Dipaculao, Aurora 3203

**Municipal Mayor**  
Office of the Mayor  
Municipal Hall, Dipaculao, Aurora 3203

---

*This technical brief is submitted in support of the Municipality of Dipaculao's request for GovCloud hosting services under the DICT eGovPH program.*

---
