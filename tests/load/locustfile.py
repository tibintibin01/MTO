import random
from locust import HttpUser, task, between

class MTOTreasuryUser(HttpUser):
    wait_time = between(1, 5)
    
    def on_start(self):
        """Perform login to get token before running tasks."""
        self.login()

    def login(self):
        # Simulate login to the /token endpoint
        # In a real test, you'd use credentials from an environment variable or CSV
        response = self.client.post("/token", data={
            "username": "admin",
            "password": "password123" # Replace with valid test credentials
        })
        if response.status_code == 200:
            self.token = response.json().get("access_token")
            self.headers = {"Authorization": f"Bearer {self.token}"}
        else:
            self.token = None
            self.headers = {}

    @task(3)
    def search_properties(self):
        """Simulates common property searching."""
        search_terms = ["Poblacion", "Brgy", "Zone", "123", "Owner"]
        term = random.choice(search_terms)
        self.client.get(f"/properties/search?term={term}&limit=50", headers=self.headers)

    @task(2)
    def view_assessment_roll(self):
        """Simulates viewing large lists of properties."""
        self.client.get("/billing/assessment-roll?limit=100", headers=self.headers)

    @task(1)
    def check_backup_status(self):
        """Simulates an admin checking system health."""
        self.client.get("/system/backup/status", headers=self.headers)

    @task(2)
    def get_delinquent_accounts(self):
        """Simulates delinquency reporting (high impact query)."""
        self.client.get("/properties/delinquent?limit=20", headers=self.headers)

    @task(1)
    def get_audit_logs(self):
        """Simulates viewing audit logs."""
        self.client.get("/system/audit-logs?limit=50", headers=self.headers)
