# API Contract - Stackwise V1

## Base URL: `/api/v1`

### 1. Authentication
- `POST /auth/register`: Create a new account.
  - Request: `{ "email": "user@example.com", "password": "securepassword123" }`
  - Response: `201 Created` with User object.
- `POST /auth/login`: Get JWT token.
  - Request: (Form Data) `username` (email), `password`.
  - Response: `200 OK` with `{ "access_token": "...", "token_type": "bearer" }`.
- `GET /auth/me`: Get current user profile.
  - Header: `Authorization: Bearer <token>`
  - Response: `200 OK` with User object.

### 2. Project Management
- `POST /projects`: Create a project.
  - Request: `{ "name": "My Project", "description": "Analysis of my app" }`
  - Response: `201 Created` with Project object.
- `GET /projects`: List user's projects.
  - Response: `200 OK` with list of Project objects.
- `GET /projects/{id}`: Get project details.
- `PATCH /projects/{id}`: Update name/description.
- `DELETE /projects/{id}`: Remove project.

### 3. Analysis Pipeline
- `POST /projects/{id}/analyses`: Upload ZIP for analysis.
  - Request: Multipart Form Data `file` (ZIP).
  - Response: `202 Accepted` with AnalysisRun object (status: `pending`).
- `GET /analyses/{id}`: Poll analysis status.
  - Response: `200 OK` with AnalysisRun object (status: `pending` | `processing` | `completed` | `failed`).
- `GET /analyses/{id}/findings`: Get detailed results.
  - Response: `200 OK` with list of Finding objects.
- `GET /projects/{id}/analyses`: History of analyses for a project.

### 4. Dashboard
- `GET /dashboard/summary`: High-level stats.
  - Response: `200 OK` with `{ "total_projects": 5, "total_analyses": 10, "completed_analyses": 8, "total_findings": 42, "findings_by_severity": { "high": 2, "medium": 10, "low": 30 }, "last_analysis_status": "completed" }`
