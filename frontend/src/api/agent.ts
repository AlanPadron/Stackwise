// The findings agent: whether the server can answer, one turn, and the streamed one.
import apiClient, { messageFromBody } from './client';

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

/** What the server says about the answer *before* it starts writing it. */
export interface AgentStreamMeta {
    backend: string;
    model: string;
    findings_used: number;
    truncated: boolean;
    analysis_run_id: string | null;
}

/**
 * How a streamed turn ended.
 *
 * Returned rather than thrown on purpose: "the user pressed stop" and "the model
 * failed half way through" are expected outcomes of this call, not exceptions,
 * and the caller has to tell them apart to draw the right face.
 */
export type AgentStreamOutcome =
    | { kind: 'done'; reply: string }
    | { kind: 'cancelled'; partial: string }
    | { kind: 'error'; detail: string };

const API_BASE_URL = import.meta.env.VITE_API_URL || '/api/v1';

export const fetchAgentStatus = async (): Promise<AgentStatus> =>
    (await apiClient.get('/agent/status')).data;

/**
 * The question, streamed: `onDelta` is called as the model writes.
 *
 * `fetch` rather than the shared axios client, because reading a body
 * incrementally is exactly what axios does not do in a browser; the bearer token
 * is therefore attached here too. Everything that fails before the first byte
 * (bad request, rate limit, unavailable runtime) still arrives as a status code,
 * so `detail` is the server's own reason.
 */
export const streamAgentMessage = async (
    messages: AgentTurn[],
    scope: { projectId?: string; analysisRunId?: string },
    handlers: {
        onMeta?: (meta: AgentStreamMeta) => void;
        onDelta: (text: string) => void;
        signal?: AbortSignal;
    }
): Promise<AgentStreamOutcome> => {
    const token = localStorage.getItem('token');

    let response: Response;
    try {
        response = await fetch(`${API_BASE_URL}/agent/chat/stream`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                Accept: 'text/event-stream',
                ...(token ? { Authorization: `Bearer ${token}` } : {}),
            },
            body: JSON.stringify({
                messages,
                project_id: scope.projectId ?? null,
                analysis_run_id: scope.analysisRunId ?? null,
            }),
            signal: handlers.signal,
        });
    } catch (error) {
        if (isAbort(error)) return { kind: 'cancelled', partial: '' };
        return { kind: 'error', detail: 'network' };
    }

    if (!response.ok) {
        const detail = await readFailureDetail(response);
        return { kind: 'error', detail };
    }

    const reader = response.body?.getReader();
    if (!reader) return { kind: 'error', detail: 'network' };

    const decoder = new TextDecoder();
    let buffer = '';
    let answer = '';
    let failure: string | null = null;

    try {
        for (;;) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            // Frames are separated by a blank line; the tail is kept for the
            // next read, so a frame split across chunks is not lost.
            const blocks = buffer.split('\n\n');
            buffer = blocks.pop() ?? '';
            for (const block of blocks) {
                const frame = parseFrame(block);
                if (frame === null) continue;
                if (frame.event === 'meta') {
                    const meta = readMeta(frame.data);
                    if (meta) handlers.onMeta?.(meta);
                } else if (frame.event === 'delta') {
                    const text = readText(frame.data);
                    if (text) {
                        answer += text;
                        handlers.onDelta(text);
                    }
                } else if (frame.event === 'error') {
                    failure = readDetail(frame.data);
                } else if (frame.event === 'done') {
                    const whole = readReply(frame.data);
                    if (whole) answer = whole;
                }
            }
        }
    } catch (error) {
        if (isAbort(error)) return { kind: 'cancelled', partial: answer };
        return { kind: 'error', detail: 'network' };
    } finally {
        reader.releaseLock();
    }

    if (failure !== null) return { kind: 'error', detail: failure };
    return { kind: 'done', reply: answer };
};

const isAbort = (error: unknown): boolean =>
    typeof error === 'object' && error !== null && 'name' in error && error.name === 'AbortError';

interface SseFrame {
    event: string;
    data: Record<string, unknown>;
}

/** One SSE block as `{event, data}`, or `null` for a comment or a broken frame. */
const parseFrame = (block: string): SseFrame | null => {
    let event = '';
    let payload = '';
    for (const line of block.split('\n')) {
        if (line.startsWith('event:')) event = line.slice('event:'.length).trim();
        else if (line.startsWith('data:')) payload += line.slice('data:'.length).trim();
    }
    if (!event || !payload) return null;
    try {
        const parsed: unknown = JSON.parse(payload);
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
            return { event, data: { ...parsed } };
        }
    } catch {
        return null;
    }
    return null;
};

/** The opening frame, validated field by field: it arrives over the network. */
const readMeta = (data: Record<string, unknown>): AgentStreamMeta | null => {
    const backend = data.backend;
    const model = data.model;
    if (typeof backend !== 'string' || typeof model !== 'string') return null;
    return {
        backend,
        model,
        findings_used: typeof data.findings_used === 'number' ? data.findings_used : 0,
        truncated: data.truncated === true,
        analysis_run_id: typeof data.analysis_run_id === 'string' ? data.analysis_run_id : null,
    };
};

const readText = (data: Record<string, unknown>): string =>
    typeof data.text === 'string' ? data.text : '';

const readReply = (data: Record<string, unknown>): string =>
    typeof data.reply === 'string' ? data.reply : '';

const readDetail = (data: Record<string, unknown>): string =>
    typeof data.detail === 'string' ? data.detail : '';

/** The server's reason for refusing, from the JSON body it sent instead of a stream. */
const readFailureDetail = async (response: Response): Promise<string> => {
    try {
        return messageFromBody(await response.json(), `HTTP ${response.status}`);
    } catch {
        return `HTTP ${response.status}`;
    }
};
