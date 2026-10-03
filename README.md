# Stackwise

> Multi-language code analysis platform for software repositories.

Stackwise is a code analysis platform designed to connect with software repositories and provide clear insights into code quality, security, complexity, and other engineering metrics.

This repository contains the **initial project skeleton (v0.1.0)**, establishing the foundation and architecture for the future development of the platform.

---

## Project Status

**Version:** `0.1.0`  
**Status:** Early Development

The current version focuses on establishing the project's core structure and architecture.

Stackwise is actively being developed and its functionality will evolve as the project progresses.

---

## Vision

Stackwise aims to make code analysis more accessible by transforming complex technical information into clear and useful insights for developers and software teams.

The platform is designed to support multiple popular programming languages and provide a unified experience for analyzing software repositories.

### Planned capabilities

- Repository integration
- Multi-language static code analysis
- Code quality metrics
- Security analysis
- Complexity analysis
- Analysis history
- Project tracking
- Unified findings
- Clear and actionable insights
- Web-based dashboard

---

## Architecture

Stackwise is designed around a modular architecture that separates repository integration, API services, static analysis, result processing, and data persistence.

```mermaid
flowchart TB
    U[User]

    subgraph PLATFORM["STACKWISE"]
        direction TB

        FE["Web Application<br/>React + TypeScript"]

        API["API Layer<br/>FastAPI"]

        REPO["Repository Integration<br/>Read-only access"]

        ENGINE["Analysis Engine"]

        subgraph ANALYSIS["Static Analysis"]
            direction LR
            QUALITY["Code Quality"]
            SECURITY["Security"]
            COMPLEXITY["Complexity"]
        end

        PROCESS["Result Processing<br/>Normalization & Metrics"]

        DB[("PostgreSQL<br/>Projects · Analyses · Findings")]

        DASH["Analysis Dashboard"]
    end

    PROVIDER["Git Repository Provider"]

    U --> FE
    FE --> API
    API --> REPO
    REPO <--> PROVIDER

    API --> ENGINE
    ENGINE --> ANALYSIS
    ANALYSIS --> PROCESS
    PROCESS --> DB

    DB --> API
    API --> DASH
    DASH --> FE

    classDef user fill:#18181b,stroke:#71717a,color:#fafafa
    classDef frontend fill:#1e293b,stroke:#64748b,color:#f8fafc
    classDef backend fill:#172554,stroke:#3b82f6,color:#eff6ff
    classDef repository fill:#1f2937,stroke:#6b7280,color:#f9fafb
    classDef analysis fill:#292524,stroke:#78716c,color:#fafaf9
    classDef database fill:#1c1917,stroke:#a8a29e,color:#fafaf9
    classDef dashboard fill:#262626,stroke:#a3a3a3,color:#fafafa

    class U user
    class FE frontend
    class API backend
    class REPO,PROVIDER repository
    class ENGINE,QUALITY,SECURITY,COMPLEXITY,PROCESS analysis
    class DB database
    class DASH dashboard

    style PLATFORM fill:#09090b,stroke:#3f3f46,color:#fafafa
    style ANALYSIS fill:#111113,stroke:#3f3f46,color:#d4d4d8


User
  ↓
Web Application
  ↓
API
  ↓
Repository Integration
  ↓
Analysis Engine
  ↓
Static Analysis
  ↓
Result Processing
  ↓
Database
  ↓
Dashboard
