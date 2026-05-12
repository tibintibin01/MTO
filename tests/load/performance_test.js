import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '30s', target: 50 },  // Ramp-up to 50 users
    { duration: '1m', target: 100 },  // Stay at 100 users (Target)
    { duration: '30s', target: 0 },    // Ramp-down
  ],
  thresholds: {
    http_req_duration: ['p(95)<500'], // 95% of requests must be below 500ms
    http_req_failed: ['rate<0.01'],   // Error rate must be less than 1%
  },
};

const BASE_URL = __ENV.API_URL || 'http://localhost:8001';

export default function () {
  // 1. Search Properties
  const searchRes = http.get(`${BASE_URL}/properties/search?term=test&limit=20`);
  check(searchRes, {
    'search status is 200': (r) => r.status === 200,
    'search latency < 300ms': (r) => r.timings.duration < 300,
  });

  sleep(1);

  // 2. View Assessment Roll
  const rollRes = http.get(`${BASE_URL}/billing/assessment-roll?limit=50`);
  check(rollRes, {
    'assessment roll status is 200': (r) => r.status === 200,
  });

  sleep(2);

  // 3. System Status check (Admin-like)
  const healthRes = http.get(`${BASE_URL}/system/backup/status`);
  check(healthRes, {
    'health check status is 200': (r) => r.status === 200,
  });

  sleep(1);
}
