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
    /** Per-project analysis overrides (validated server-side); null when defaults apply. */
    analysis_config: Record<string, unknown> | null;
    created_at: string;
    updated_at: string;
}

/** Canonical severity scale, shared by findings and every aggregate. */
export type Severity = 'critical' | 'high' | 'medium' | 'low' | 'info';

/**
 * Run lifecycle: pending → running → completed | completed_with_errors | failed.
 * `completed_with_errors` means the run finished but at least one analyzer did
 * not (missing, timed out, crashed) — the results it did produce are kept.
 */
export type AnalysisStatus =
    | 'pending'
    | 'running'
    | 'completed'
    | 'completed_with_errors'
    | 'failed'
    | 'cancelled';

export interface AnalysisRun {
    id: string;
    project_id: string;
    status: AnalysisStatus;
    /** Where the archive came from: an uploaded ZIP or an imported repository. */
    source_type: string;
    source_ref: string | null;
    source_hash: string | null;
    engine_version: string | null;
    config_version: string | null;
    config_hash: string | null;
    analysis_config: Record<string, unknown> | null;
    started_at: string | null;
    finished_at: string | null;
    duration_seconds: number | null;
    error_category: string | null;
    error_message: string | null;
    summary: {
        total_findings: number;
        severity_counts: Record<Severity, number>;
        category_counts?: Record<string, number>;
        analyzer_counts?: Record<string, number>;
        files?: { discovered: number; analyzed: number; skipped: number; failed: number };
        analyzers?: { applicable: number; succeeded: number; failed: number };
        duplicates_removed?: number;
        dropped_findings?: number;
        findings_truncated?: boolean;
        /** True when every applicable analyzer produced results. */
        complete?: boolean;
        engine_version?: string;
        config_hash?: string;
    } | null;
    /** Objective measurements; see docs/ANALYSIS_ENGINE.md. Null keys mean "not measured". */
    metrics: Record<string, any> | null;
    /** Heuristic indicators (never a probability of exploitation). */
    risk: Record<string, any> | null;
    tool_versions: Record<string, string | null> | null;
    created_at: string;
}

export interface Finding {
    id: string;
    analysis_run_id: string;
    project_id: string;
    tool: string;
    rule_id: string | null;
    category: string;
    severity: string;
    confidence: string | null;
    title: string;
    message: string;
    file_path: string;
    line_start: number | null;
    line_end: number | null;
    column_start: number | null;
    column_end: number | null;
    fingerprint: string;
    references: Record<string, string> | null;
    finding_metadata: Record<string, unknown> | null;
    created_at: string;
}

export interface GitHubRepository {
    full_name: string;
    name: string;
    owner: string;
    private: boolean;
    description: string | null;
    default_branch: string | null;
    language: string | null;
    updated_at: string | null;
    html_url: string | null;
}

export interface GitHubRepositoriesResponse {
    /** `false` when the user has not linked a GitHub account yet. */
    connected: boolean;
    login: string | null;
    repositories: GitHubRepository[];
}

export interface DashboardSummary {
    total_projects: number;
    total_analyses: number;
    /** Completed plus completed-with-errors runs: both did their work. */
    completed_analyses: number;
    total_findings: number;
    findings_by_severity: Record<Severity, number>;
    last_analysis_status: string | null;
}
