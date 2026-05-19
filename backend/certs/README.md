# SSL/TLS Certificate Management

## Current Development State: Self-Signed Certificates
Currently, the system uses self-signed certificates (`cert.pem`, `key.pem`) for local development and testing. This is sufficient for encrypted `localhost` communication between the frontend, desktop client, and backend.

However, in a production environment, self-signed certificates will cause "SSL Warning Fatigue" where users constantly see "Your connection is not private" browser warnings. This trains users to ignore critical security alerts, which is a major vulnerability.

## Production Roadmap: Let's Encrypt / Certbot

For production deployment, you must transition to a trusted Certificate Authority (CA) like Let's Encrypt.

### Migration Steps:

1. **Domain Registration:**
   Ensure your production server has a registered domain name (e.g., `treasury.yourmunicipality.gov.ph`) pointing to its public IP address.

2. **Install Certbot:**
   Install Certbot on your production server.
   ```bash
   # Ubuntu/Debian
   sudo apt update
   sudo apt install certbot
   ```

3. **Generate Certificates:**
   Run Certbot to obtain a trusted certificate. If you are running the FastAPI backend directly on port 443, you can use the standalone mode:
   ```bash
   sudo certbot certonly --standalone -d treasury.yourmunicipality.gov.ph
   ```

4. **Update FastAPI Configuration:**
   Modify your backend startup command or systemd service to point to the new Let's Encrypt certificates instead of the local self-signed ones.
   
   *Let's Encrypt typical path:*
   - `ssl_keyfile`: `/etc/letsencrypt/live/treasury.yourmunicipality.gov.ph/privkey.pem`
   - `ssl_certfile`: `/etc/letsencrypt/live/treasury.yourmunicipality.gov.ph/fullchain.pem`

5. **Reverse Proxy (Recommended):**
   Instead of FastAPI handling SSL directly, it is highly recommended to place NGINX or Caddy in front of the backend. NGINX will handle SSL termination (and auto-renewal with Certbot), and pass plaintext HTTP to FastAPI running on a local port.

### Desktop Client Note
If the desktop client connects to the new production domain, it will automatically trust the Let's Encrypt certificate. You must update `server_config.json` on the desktop clients to point to the new secure `https://` domain.
