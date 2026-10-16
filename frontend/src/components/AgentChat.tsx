// NIom: the findings agent. A floating button (signed in only) and its chat popup.
import React, { useEffect, useRef, useState } from 'react';
import { matchPath, useLocation } from 'react-router-dom';
import { AgentStatus, AgentTurn, fetchAgentStatus, sendAgentMessage } from '../api/agent';
import { useFocusTrap } from '../hooks/useFocusTrap';
import { useI18n } from '../i18n/I18nContext';
import { Button, Loader, RobotIcon } from './ui';
import { cx } from './ui/cx';

/** A rendered turn; the meta line is client-side, so it is not sent back. */
interface Turn {
    role: 'user' | 'assistant';
    content: string;
    meta?: string;
}

const PROJECT_ROUTE = '/projects/:id';

/**
 * The chat that explains the findings of the analysis in scope. Mounted only for
 * a signed-in user (see `App.tsx`).
 *
 * The conversation is always the interface: when the agent cannot answer it says
 * so *in the chat*, in its own voice, rather than the panel turning into an
 * installer notice. The operator-facing reason stays in `GET /agent/status`.
 */
export const AgentChat: React.FC = () => {
    const { t } = useI18n();
    const location = useLocation();
    const [open, setOpen] = useState(false);
    const [status, setStatus] = useState<AgentStatus | null>(null);
    const [statusFailed, setStatusFailed] = useState(false);
    const [turns, setTurns] = useState<Turn[]>([]);
    const [draft, setDraft] = useState('');
    const [sending, setSending] = useState(false);
    const containerRef = useRef<HTMLDivElement>(null);
    const panel = useRef<HTMLDivElement | null>(null);
    const listRef = useRef<HTMLDivElement>(null);
    // The agent speaks up about a broken runtime once per session, not on every
    // open/close of the panel.
    const greeted = useRef(false);

    // The analysis the conversation is grounded in: whatever project the user is
    // looking at. The server decides which run that means (the latest finished one).
    const projectId = matchPath(PROJECT_ROUTE, location.pathname)?.params.id;
    const canAnswer = status !== null && status.available;

    useEffect(() => {
        if (!open || status !== null || statusFailed) return;
        let cancelled = false;
        fetchAgentStatus()
            .then((next) => {
                if (!cancelled) setStatus(next);
            })
            .catch(() => {
                if (!cancelled) setStatusFailed(true);
            });
        return () => {
            cancelled = true;
        };
    }, [open, status, statusFailed]);

    // A runtime that cannot answer gets one line from the agent itself, so the
    // user is not left typing into a chat that will never reply.
    useEffect(() => {
        if (!open || greeted.current) return;
        if (status === null && !statusFailed) return;
        greeted.current = true;
        if (!statusFailed && status?.available) return;

        const notice = statusFailed ? t('agent.error') : t('agent.unavailable');
        setTurns((previous) =>
            previous.length > 0 ? previous : [{ role: 'assistant', content: notice }]
        );
    }, [open, status, statusFailed, t]);

    // Dismiss on outside click, exactly like the settings drawer.
    useEffect(() => {
        if (!open) return;
        const onPointerDown = (event: PointerEvent) => {
            if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
        };
        document.addEventListener('pointerdown', onPointerDown);
        return () => {
            document.removeEventListener('pointerdown', onPointerDown);
        };
    }, [open]);

    // Tab stays inside the open panel and Escape closes it, handing the focus
    // back to the button that opened it. The composer takes the focus first.
    useFocusTrap(open, panel, () => setOpen(false));

    useEffect(() => {
        listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
    }, [turns, sending]);

    const send = async () => {
        const content = draft.trim();
        if (!content || sending) return;

        const history: Turn[] = [...turns, { role: 'user', content }];
        setTurns(history);
        setDraft('');
        setSending(true);
        try {
            const payload: AgentTurn[] = history.map((turn) => ({
                role: turn.role,
                content: turn.content,
            }));
            const reply = await sendAgentMessage(payload, { projectId });
            setTurns([
                ...history,
                {
                    role: 'assistant',
                    content: reply.reply,
                    meta: [
                        t('agent.findingsUsed', { count: reply.findings_used }),
                        reply.truncated ? t('agent.truncated') : '',
                    ]
                        .filter(Boolean)
                        .join(' · '),
                },
            ]);
        } catch {
            // The server's own wording for a failure is written for operators; the
            // chat answers in the agent's voice instead.
            setTurns([...history, { role: 'assistant', content: t('agent.error') }]);
        } finally {
            setSending(false);
        }
    };

    return (
        <div
            ref={containerRef}
            // 5.25rem = the settings cluster is 48px tall sitting at bottom-6, so
            // the two stacks keep the same 12px rhythm instead of overlapping.
            // The safe-area term keeps that rhythm on a phone with a home
            // indicator, where the settings cluster sits higher.
            className="fixed bottom-[calc(5.25rem+env(safe-area-inset-bottom))] right-[max(1.5rem,env(safe-area-inset-right))] z-40 flex flex-col items-end gap-3"
        >
            {open && (
                <div
                    ref={panel}
                    role="dialog"
                    aria-modal="true"
                    aria-label={t('agent.title')}
                    tabIndex={-1}
                    className="sw-popover sw-enter-pop flex w-[min(26rem,calc(100vw-3rem))] flex-col"
                >
                    <header className="flex items-start gap-3 border-b border-[var(--sw-hairline)] px-4 py-3">
                        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-sw-sm bg-[var(--sw-accent-soft)] text-accent">
                            <RobotIcon size={17} />
                        </span>
                        <span className="min-w-0 flex-1">
                            <span className="block text-sm font-semibold text-ink">
                                {t('agent.title')}
                            </span>
                            <span className="block truncate text-xs text-faint">
                                {canAnswer && status
                                    ? t('agent.model', { model: status.model })
                                    : t('agent.subtitle')}
                            </span>
                        </span>
                        <Button
                            size="icon"
                            variant="ghost"
                            onClick={() => setOpen(false)}
                            aria-label={t('agent.close')}
                            title={t('agent.close')}
                        >
                            ×
                        </Button>
                    </header>

                    <p className="px-4 pt-3 text-xs text-faint">
                        {projectId ? t('agent.scopeProject') : t('agent.scopeNone')}
                    </p>

                    <div
                        ref={listRef}
                        className="sw-scroll flex max-h-[min(22rem,55dvh)] min-h-[min(9rem,25dvh)] flex-col gap-3 overflow-y-auto px-4 py-3"
                    >
                        {turns.length === 0 && <p className="sw-hint">{t('agent.empty')}</p>}
                        {turns.map((turn, index) => (
                            <div
                                key={index}
                                className={cx(
                                    'flex flex-col',
                                    turn.role === 'user' ? 'items-end' : 'items-start'
                                )}
                            >
                                <span className="text-xs font-bold uppercase tracking-[0.08em] text-faint sm:text-[0.625rem]">
                                    {turn.role === 'user' ? t('agent.you') : t('agent.name')}
                                </span>
                                <p
                                    className={cx(
                                        'mt-1 max-w-[90%] whitespace-pre-wrap rounded-sw px-3 py-2 text-sm text-ink',
                                        turn.role === 'user'
                                            ? 'bg-[var(--sw-accent-soft)]'
                                            : 'bg-[var(--sw-sunken)]'
                                    )}
                                >
                                    {turn.content}
                                </p>
                                {turn.meta && (
                                    <span className="mt-1 text-xs text-faint sm:text-[0.6875rem]">
                                        {turn.meta}
                                    </span>
                                )}
                            </div>
                        ))}
                        {sending && (
                            <div className="py-2">
                                <Loader caption={t('agent.thinking')} />
                            </div>
                        )}
                    </div>

                    <div className="flex items-end gap-2 border-t border-[var(--sw-hairline)] p-3">
                        <textarea
                            rows={2}
                            data-autofocus
                            value={draft}
                            disabled={sending}
                            maxLength={status?.max_message_chars}
                            placeholder={t('agent.placeholder')}
                            aria-label={t('agent.placeholder')}
                            onChange={(event) => setDraft(event.target.value)}
                            onKeyDown={(event) => {
                                if (event.key === 'Enter' && !event.shiftKey) {
                                    event.preventDefault();
                                    void send();
                                }
                            }}
                            className="sw-input sw-input--textarea flex-1"
                        />
                        <Button
                            variant="primary"
                            loading={sending}
                            disabled={!draft.trim()}
                            onClick={() => void send()}
                        >
                            {t('agent.send')}
                        </Button>
                    </div>
                </div>
            )}

            <button
                type="button"
                onClick={() => setOpen((value) => !value)}
                className="sw-fab"
                aria-expanded={open}
                aria-haspopup="dialog"
                aria-label={t('agent.open')}
                title={t('agent.open')}
            >
                <RobotIcon size={20} />
            </button>
        </div>
    );
};
