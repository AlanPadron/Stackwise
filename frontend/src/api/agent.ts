// The findings agent: whether the server can answer, and one chat turn.
import apiClient from './client';

/** What the server is configured to run, and why it cannot when it cannot. */
export interface AgentStatus {
    available: boolean;
    backend: string;
    model: string;
    reason: string | null;
    max_context_findings: number;
    max_message_chars: number;
}

/** One turn of the conversation; the system prompt is the server's business. */
export interface AgentTurn {
    role: 'user' | 'assistant';
    content: string;
}

export interface AgentReply {
    reply: string;
    backend: string;
    model: string;
    /** How many findings were actually quoted to the model. */
    findings_used: number;
    /** More findings exist than fitted in the context. */
    truncated: boolean;
    analysis_run_id: string | null;
}

export const fetchAgentStatus = async (): Promise<AgentStatus> =>
    (await apiClient.get('/agent/status')).data;

/**
 * Ask the agent about the findings in scope. Without a project or run the server
 * quotes nothing and says so, which is the honest answer for a question asked
 * from a screen that is not about one analysis.
 */
export const sendAgentMessage = async (
    messages: AgentTurn[],
    scope: { projectId?: string; analysisRunId?: string } = {}
): Promise<AgentReply> =>
    (
        await apiClient.post('/agent/chat', {
            messages,
            project_id: scope.projectId ?? null,
            analysis_run_id: scope.analysisRunId ?? null,
        })
    ).data;
