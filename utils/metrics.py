import time
from prometheus_client import Counter, Gauge, Histogram, Summary, CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST
from typing import Dict

# --- MTO INDUSTRIAL METRICS ---

# Registry for isolated metric management
REGISTRY = CollectorRegistry()

# 1. Request Telemetry
REQUEST_COUNT = Counter(
    'mto_requests_total', 
    'Total count of municipal API requests', 
    ['method', 'endpoint', 'status'],
    registry=REGISTRY
)

REQUEST_LATENCY = Histogram(
    'mto_request_latency_seconds', 
    'Latency of municipal API requests in seconds', 
    ['method', 'endpoint'],
    registry=REGISTRY
)

# 2. Database Integrity
DB_QUERY_COUNT = Counter(
    'mto_db_queries_total', 
    'Total count of database queries executed', 
    ['operation'],
    registry=REGISTRY
)

DB_QUERY_LATENCY = Histogram(
    'mto_db_query_latency_seconds', 
    'Latency of database queries in seconds', 
    ['operation'],
    registry=REGISTRY
)

# 3. Synchronization & Conflict Pulse
SYNC_QUEUE_SIZE = Gauge(
    'mto_sync_queue_size', 
    'Current number of pending actions in the offline sync queue',
    registry=REGISTRY
)

SYNC_CONFLICTS_TOTAL = Counter(
    'mto_sync_conflicts_total', 
    'Total count of synchronization conflicts detected (409)',
    registry=REGISTRY
)

# 4. Security & Authentication
AUTH_ATTEMPTS = Counter(
    'mto_auth_attempts_total', 
    'Total count of authentication attempts', 
    ['status'],
    registry=REGISTRY
)

ACTIVE_SESSIONS = Gauge(
    'mto_active_sessions', 
    'Estimated number of active municipal sessions',
    registry=REGISTRY
)

# 5. Resilience & Circuit Breakers
CIRCUIT_STATE = Gauge(
    'mto_circuit_breaker_state', 
    'Current state of system circuit breakers (0=CLOSED, 1=HALF_OPEN, 2=OPEN)',
    ['name'],
    registry=REGISTRY
)

class MetricsManager:
    """
    Centralized high-fidelity metrics manager for the MTO System.
    """
    @staticmethod
    def record_request(method: str, endpoint: str, status: int, duration: float):
        REQUEST_COUNT.labels(method=method, endpoint=endpoint, status=status).inc()
        REQUEST_LATENCY.labels(method=method, endpoint=endpoint).observe(duration)

    @staticmethod
    def record_db_query(operation: str, duration: float):
        DB_QUERY_COUNT.labels(operation=operation).inc()
        DB_QUERY_LATENCY.labels(operation=operation).observe(duration)

    @staticmethod
    def record_auth(status: str):
        AUTH_ATTEMPTS.labels(status=status).inc()

    @staticmethod
    def update_sync_status(queue_size: int):
        SYNC_QUEUE_SIZE.set(queue_size)

    @staticmethod
    def record_sync_conflict():
        SYNC_CONFLICTS_TOTAL.inc()

    @staticmethod
    def record_circuit_state(name: str, state: int):
        CIRCUIT_STATE.labels(name=name).set(state)

    @staticmethod
    def get_latest_metrics():
        return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
