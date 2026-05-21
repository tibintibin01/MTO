# -*- coding: utf-8 -*-
"""
MTO Treasury System — Locust Load Test Suite
=============================================

Simulates realistic municipal treasury workloads across three user personas:

  CashierUser   — posts payments, generates receipts, searches properties
  ViewerUser    — reads property data, checks delinquency lists, views ledgers
  AdminUser     — checks system health, views audit logs, triggers analytics

Usage
-----
  # Install: pip install locust
  # Start the backend first, then:
  locust -f tests/load/locustfile.py --host https://localhost:8000

  # Headless CI run (100 users, 2-minute ramp, 5-minute hold):
  locust -f tests/load/locustfile.py --host https://localhost:8000 \\
         --users 100 --spawn-rate 10 --run-time 7m --headless

Environment variables
---------------------
  LOCUST_CASHIER_USER   username for cashier login  (default: cashier_test)
  LOCUST_CASHIER_PASS   password for cashier login  (default: TestP@ssw0rd!)
  LOCUST_ADMIN_USER     username for admin login    (default: admin_test)
  LOCUST_ADMIN_PASS     password for admin login    (default: TestP@ssw0rd!)
  LOCUST_VIEWER_USER    username for viewer login   (default: viewer_test)
  LOCUST_VIEWER_PASS    password for viewer login   (default: TestP@ssw0rd!)

  Set these to real test-account credentials before running against a
  staging environment. Never use production credentials in load tests.

Performance targets (tax season)
---------------------------------
  P95 response time  < 500 ms
  P99 response time  < 1500 ms
  Error rate         < 1%
  Concurrent users   100+
"""

import os
import random
from locust import HttpUser, task, between, events
from locust.exception import StopUser


# ---------------------------------------------------------------------------
# Shared test data — use realistic-looking but non-sensitive values
# ---------------------------------------------------------------------------

SAMPLE_TD_NUMBERS = [
    "06-0012-01379",
    "06-0012-02143",
    "06-0006-00012",
    "06-0012-02564",
    "06-0012-02561",
]

SAMPLE_SEARCH_TERMS = [
    "DELA CRUZ",
    "GARCIA",
    "REYES",
    "SANTOS",
    "POBLACION",
    "NORTH",
    "06-0012",
]

SAMPLE_BARANGAYS = [
    "NORTH POBLACION",
    "SOUTH POBLACION",
    "EAST POBLACION",
]


# ---------------------------------------------------------------------------
# Base user — handles login and shared auth header management
# ---------------------------------------------------------------------------

class AuthenticatedUser(HttpUser):
    abstract = True

    # Subclasses set these
    _username_env: str = ""
    _password_env: str = ""
    _default_user: str = ""
    _default_pass: str = ""

    def on_start(self):
        self.token = None
        self.auth_headers = {"X-Requested-With": "XMLHttpRequest"}
        self._login()

    def _login(self):
        username = os.getenv(self._username_env, self._default_user)
        password = os.getenv(self._password_env, self._default_pass)

        with self.client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
            headers={"X-Requested-With": "XMLHttpRequest"},
            catch_response=True,
            name="[auth] POST /api/auth/login",
        ) as resp:
            if resp.status_code == 200:
                data = resp.json()
                self.token = data.get("access_token")
                self.auth_headers = {
                    "Authorization": f"Bearer {self.token}",
                    "X-Requested-With": "XMLHttpRequest",
                }
                resp.success()
            else:
                resp.failure(
                    f"Login failed for {username}: "
                    f"HTTP {resp.status_code} — {resp.text[:200]}"
                )
                raise StopUser()

    def get(self, path, name=None, **kwargs):
        """Authenticated GET with consistent header injection."""
        return self.client.get(
            path,
            headers=self.auth_headers,
            name=name or path,
            **kwargs,
        )

    def post(self, path, name=None, **kwargs):
        """Authenticated POST with consistent header injection."""
        return self.client.post(
            path,
            headers=self.auth_headers,
            name=name or path,
            **kwargs,
        )


# ---------------------------------------------------------------------------
# Cashier — highest-frequency user, drives the most DB writes
# ---------------------------------------------------------------------------

class CashierUser(AuthenticatedUser):
    """
    Simulates a cashier at the counter during tax season.
    Cashiers are the primary write path — they search properties, post
    payments, and generate receipts. Weight 50% of simulated users.
    """
    weight = 5
    wait_time = between(1, 3)

    _username_env = "LOCUST_CASHIER_USER"
    _password_env = "LOCUST_CASHIER_PASS"
    _default_user = "cashier_test"
    _default_pass = "TestP@ssw0rd!"

    @task(5)
    def search_property_by_td(self):
        """Most common cashier action — look up a property by TDN."""
        td = random.choice(SAMPLE_TD_NUMBERS)
        with self.get(
            f"/properties?search={td}&limit=10",
            name="[cashier] GET /properties?search=<td>",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Property search failed: {resp.status_code}")

    @task(4)
    def search_property_by_name(self):
        """Search by owner name — common when taxpayer doesn't know their TDN."""
        term = random.choice(SAMPLE_SEARCH_TERMS)
        with self.get(
            f"/properties?search={term}&limit=20",
            name="[cashier] GET /properties?search=<name>",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 404):
                resp.success()
            else:
                resp.failure(f"Name search failed: {resp.status_code}")

    @task(3)
    def view_property_statement(self):
        """View billing statement before posting payment."""
        # Use a low property ID — likely to exist in any seeded DB
        prop_id = random.randint(1, 20)
        with self.get(
            f"/properties/{prop_id}/statement",
            name="[cashier] GET /properties/:id/statement",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 404):
                resp.success()
            else:
                resp.failure(f"Statement fetch failed: {resp.status_code}")

    @task(2)
    def get_next_or_number(self):
        """Cashier fetches the next OR number before printing a receipt."""
        with self.get(
            "/payments/next-or",
            name="[cashier] GET /payments/next-or",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Next OR failed: {resp.status_code}")

    @task(2)
    def view_recent_payments(self):
        """Dashboard widget — recent payments list."""
        with self.get(
            "/payments/recent?limit=8",
            name="[cashier] GET /payments/recent",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Recent payments failed: {resp.status_code}")

    @task(1)
    def view_payment_ledger(self):
        """View full payment ledger for a property."""
        td = random.choice(SAMPLE_TD_NUMBERS)
        with self.get(
            f"/payments/ledger?term={td}",
            name="[cashier] GET /payments/ledger?term=<td>",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 404):
                resp.success()
            else:
                resp.failure(f"Ledger failed: {resp.status_code}")


# ---------------------------------------------------------------------------
# Viewer — read-only reporting user, drives heavy aggregate queries
# ---------------------------------------------------------------------------

class ViewerUser(AuthenticatedUser):
    """
    Simulates a supervisor or assessor running reports.
    Viewers drive the expensive aggregate queries — delinquency lists,
    assessment rolls, barangay breakdowns. Weight 30% of simulated users.
    """
    weight = 3
    wait_time = between(2, 6)

    _username_env = "LOCUST_VIEWER_USER"
    _password_env = "LOCUST_VIEWER_PASS"
    _default_user = "viewer_test"
    _default_pass = "TestP@ssw0rd!"

    @task(4)
    def view_delinquent_accounts(self):
        """
        Delinquency list — GROUP BY + HAVING query, most expensive read.
        This is the query most likely to degrade under load.
        """
        with self.get(
            "/properties/delinquent?limit=50",
            name="[viewer] GET /properties/delinquent",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Delinquent list failed: {resp.status_code}")

    @task(3)
    def view_assessment_roll(self):
        """Assessment roll — cursor-paginated full property list."""
        with self.get(
            "/billing/assessment-roll?limit=100",
            name="[viewer] GET /billing/assessment-roll",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Assessment roll failed: {resp.status_code}")

    @task(3)
    def view_barangay_breakdown(self):
        """Barangay revenue breakdown — aggregate join query."""
        with self.get(
            "/analytics/barangay-breakdown",
            name="[viewer] GET /analytics/barangay-breakdown",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Barangay breakdown failed: {resp.status_code}")

    @task(2)
    def view_collection_trend(self):
        """Monthly collection trend — time-series aggregate."""
        with self.get(
            "/analytics/trends?months=12",
            name="[viewer] GET /analytics/trends",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Trend failed: {resp.status_code}")

    @task(2)
    def view_kpis(self):
        """KPI dashboard — today/month/total aggregates."""
        with self.get(
            "/analytics/kpis",
            name="[viewer] GET /analytics/kpis",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"KPIs failed: {resp.status_code}")

    @task(2)
    def view_receivables_by_barangay(self):
        """Receivables breakdown — used for COA reporting."""
        with self.get(
            "/reports/receivables-by-barangay",
            name="[viewer] GET /reports/receivables-by-barangay",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Receivables report failed: {resp.status_code}")

    @task(1)
    def view_billing_delinquents(self):
        """Billing delinquents — second delinquency endpoint."""
        with self.get(
            "/billing/delinquents?limit=50",
            name="[viewer] GET /billing/delinquents",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Billing delinquents failed: {resp.status_code}")


# ---------------------------------------------------------------------------
# Admin — low-frequency, high-privilege operations
# ---------------------------------------------------------------------------

class AdminUser(AuthenticatedUser):
    """
    Simulates an IT admin or treasurer monitoring the system.
    Low frequency but hits expensive system endpoints.
    Weight 20% of simulated users.
    """
    weight = 2
    wait_time = between(5, 15)

    _username_env = "LOCUST_ADMIN_USER"
    _password_env = "LOCUST_ADMIN_PASS"
    _default_user = "admin_test"
    _default_pass = "TestP@ssw0rd!"

    @task(3)
    def health_check(self):
        """Deep health probe — DB + cache + storage + vault."""
        with self.get(
            "/healthz",
            name="[admin] GET /healthz",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            elif resp.status_code == 503:
                resp.failure("System unhealthy")
            else:
                resp.failure(f"Health check failed: {resp.status_code}")

    @task(2)
    def view_audit_logs(self):
        """Audit log viewer — cursor-paginated."""
        with self.get(
            "/system/audit-logs?limit=50",
            name="[admin] GET /system/audit-logs",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Audit logs failed: {resp.status_code}")

    @task(2)
    def view_audit_stats(self):
        """Audit statistics summary."""
        with self.get(
            "/system/audit-stats",
            name="[admin] GET /system/audit-stats",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Audit stats failed: {resp.status_code}")

    @task(2)
    def view_backup_status(self):
        """Backup health dashboard."""
        with self.get(
            "/system/backup/status",
            name="[admin] GET /system/backup/status",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Backup status failed: {resp.status_code}")

    @task(1)
    def view_system_stats(self):
        """System stats — DB pool, cache, active sessions."""
        with self.get(
            "/system/stats",
            name="[admin] GET /system/stats",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"System stats failed: {resp.status_code}")

    @task(1)
    def global_search(self):
        """Command palette global search."""
        term = random.choice(SAMPLE_SEARCH_TERMS)
        with self.get(
            f"/search/global?q={term}",
            name="[admin] GET /search/global",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Global search failed: {resp.status_code}")


# ---------------------------------------------------------------------------
# Public portal user — unauthenticated citizen lookups
# ---------------------------------------------------------------------------

class PublicPortalUser(HttpUser):
    """
    Simulates citizens using the public web portal to check their property.
    No authentication — hits the rate-limited public endpoints.
    Weight 20% of simulated users (separate from staff users above).
    """
    weight = 2
    wait_time = between(3, 10)

    @task(3)
    def lookup_property(self):
        td = random.choice(SAMPLE_TD_NUMBERS)
        with self.client.get(
            f"/public/property/{td}",
            name="[public] GET /public/property/:td",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 404, 429):
                resp.success()
            else:
                resp.failure(f"Public lookup failed: {resp.status_code}")

    @task(1)
    def lookup_payment_history(self):
        td = random.choice(SAMPLE_TD_NUMBERS)
        with self.client.get(
            f"/public/property/{td}/history",
            name="[public] GET /public/property/:td/history",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 404, 429):
                resp.success()
            else:
                resp.failure(f"Public history failed: {resp.status_code}")


# ---------------------------------------------------------------------------
# Event hooks — print a summary reminder on test start
# ---------------------------------------------------------------------------

@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    print("\n" + "=" * 60)
    print("MTO Treasury Load Test Starting")
    print("=" * 60)
    print("User mix: 50% Cashier | 30% Viewer | 20% Admin+Public")
    print("Targets: P95 < 500ms | Error rate < 1%")
    print("=" * 60 + "\n")
