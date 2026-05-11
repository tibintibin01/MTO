# MTO Treasury System Architecture

This document provides a high-level overview of the system components and their interactions.

## Component Overview

The system follows a modern **Client-Server Architecture** designed for security, scalability, and data integrity.

```mermaid
graph TD
    subgraph "Desktop Client (CustomTkinter)"
        UI[User Interface]
        AC[API Clients]
        TH[Theme Manager]
    end

    subgraph "Backend API (FastAPI / HTTPS)"
        API[FastAPI Server]
        Auth[JWT Auth & RBAC]
        RL[Rate Limiter]
        Services[Service Layer]
    end

    subgraph "Data & Storage"
        DB[(SQLite / SQLModel)]
        Logs[Rotating Audit Logs]
    end

    subgraph "Disaster Recovery"
        BS[Backup Service]
        Local[(Local Backup)]
        USB[(USB Mirror)]
        CS[SHA256 Checksums]
    end

    %% Interactions
    UI <--> AC
    AC -- HTTPS / JWT --> API
    API <--> Auth
    Auth <--> Services
    Services <--> DB
    API <--> RL
    Services --> Logs
    BS <--> DB
    BS --> Local
    BS --> USB
    Local --> CS
    USB --> CS
```

## Key Architectural Decisions

1.  **N-Tier Layered Design:** The code is separated into UI, API Clients, Service Layer, and Data Access (DB Manager). This prevents "God Objects" and makes maintenance easier.
2.  **Security-First Backend:** The server enforces HTTPS, CORS, and Rate Limiting at the infrastructure level.
3.  **Stateless RBAC:** Roles and permissions are embedded in JWT tokens, reducing database load and improving response times.
4.  **Hybrid Disaster Recovery:** Backups are automated across multiple locations (Local, USB) with cryptographic verification (SHA256).
5.  **Thread-Safe UI:** The desktop interface utilizes an asynchronous messaging system (`self.after()`) to prevent crashes during background data fetching.
