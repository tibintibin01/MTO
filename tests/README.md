# MTO Treasury Performance Testing Lab 🏛️🏋️‍♂️🔥

This directory contains professional load and performance testing suites to ensure the MTO Treasury System can handle high-concurrency municipal operations (Target: 100+ concurrent users).

## 1. Locust (Pythonic Stress Test) 🏛️🦗
Locust is ideal for simulating complex user workflows using Python.

### Installation
```bash
pip install locust
```

### Execution
1. Start the backend server (`uvicorn backend.main:app --port 8001`)
2. Run Locust:
   ```bash
   locust -f tests/load/locustfile.py --host http://localhost:8001
   ```
3. Open `http://localhost:8089` in your browser to start the test and view real-time charts.

---

## 2. k6 (High-Precision Performance) 🏛️🚀⚡
k6 is a high-performance tool written in Go/JS, ideal for CI/CD and latency benchmarking.

### Installation
Download the binary from [k6.io](https://k6.io/docs/getting-started/installation/) or use Chocolatey:
```powershell
choco install k6
```

### Execution
Run the ramp-up test targeting 100 concurrent users:
```bash
k6 run tests/load/performance_test.js
```

### Success Thresholds
- **P95 Latency:** < 500ms (95% of requests must be fast)
- **Error Rate:** < 1% (Minimal failures under load)

---

## Performance Targets 🏛️📊🛡️
- **Concurrency:** 100 Concurrent Users (Simulated)
- **Throughput:** ~20-50 Requests Per Second (RPS)
- **DB Stability:** 50 Connection Pool (No exhaustion)
