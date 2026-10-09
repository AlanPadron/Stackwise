// Shapes returned by the API. Keep in sync with the Pydantic models in app/schemas/.
export interface User {
    id: string;
    email: string;
}

export interface Project {
    id: string;
    name: string;
    description: string;
    owner_id: string;
    created_at: string;
    updated_at: string;
}

export interface AnalysisRun {
    id: string;
    project_id: string;
    status: 'pending' | 'processing' | 'completed' | 'failed';
    started_at: string | null;
    finished_at: string | null;
    error_message: string | null;
    summary: {
        total_findings: number;
        severity_counts: {
            high: number;
            medium: number;
            low: number;
        };
    } | null;
    created_at: string;
}

export interface Finding {
    id: string;
    tool: string;
    rule_id: string | null;
    severity: string;
    title: string;
    message: string;
    file_path: string;
    line_start: string | null;
    line_end: string | null;
    created_at: string;
}

export interface DashboardSummary {
    total_projects: number;
    total_analyses: number;
    completed_analyses: number;
    total_findings: number;
    findings_by_severity: {
        high: number;
        medium: number;
        low: number;
    };
    last_analysis_status: string | null;
}
