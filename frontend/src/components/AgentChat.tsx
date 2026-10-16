// NIom: the findings agent. A floating button (signed in only), its chat popup,
// and the robot that shows what the agent is actually doing.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { matchPath, useLocation } from 'react-router-dom';
import {
    AgentStatus,
    AgentStreamMeta,
    AgentTurn,
    fetchAgentStatus,
    streamAgentMessage,
} from '../api/agent';
import { useFocusTrap } from '../hooks/useFocusTrap';
import { usePacedText } from '../hooks/usePacedText';
import { useI18n } from '../i18n/I18nContext';
import { Robot, RobotState } from './Robot';
import { Button, Loader, RobotIcon } from './ui';
import { cx } from './ui/cx';

/** A rendered turn; the meta line is client-side, so it is not sent back. */
interface Turn {
    role: 'user' | 'assistant';
    content: string;
    meta?: string;
}

/**
 * Where the turn actually is, as far as the wire reports it.
 *
 * `pending` and `generating` both mean "the model is working" to a screen, but
 * they are different facts: the first is a request that has been sent, the
 * second one whose opening frame has arrived. Both are drawn as THINKING — the
 * difference is kept because it is what tells an operator whether the runtime
 * answered at all.
 */
type Phase = 'idle' | 'pending' | 'generating' | 'streaming';

const PROJECT_ROUTE = '/projects/:id';

/** How long a one-shot pose is held before the robot goes back to work. */
const SENT_MS = 280;
const SUCCESS_MS = 1400;

/** After this long without typing, "attentive" relaxes back to "idle". */
const CALM_MS = 6000;

/**
 * After this long without any interaction while the user reads, the robot falls
 * asleep and says so with drifting "z"s — and any sign of life wakes it.
 */
const SLEEP_MS = 60_000;

/** How long the wake-up pose is held before the resting one takes over. */
const WAKE_MS = 520;

/**
 * Interactions closer together than this do not reschedule anything. A pointer
 * move fires dozens of times a second and only the first one after a quiet
 * second has anything to act on.
 */
const ACTIVITY_MS = 1000;

/**
 * The chat that explains the findings of the analysis in scope. Mounted only for
 * a signed-in user (see `App.tsx`).
 *
 * The conversation is always the interface: when the agent cannot answer it says
 * so *in the chat*, in its own voice, rather than the panel turning into an
 * installer notice. The operator-facing reason stays in `GET /agent/status`.
 *
 * The answer is streamed, so the robot's states come from what the server is
 * really doing: a delta arriving is what turns "thinking" into "typing", and
 * stopping the request is what returns it to rest. The one clock of its own is
 * the nap — after a minute of nothing while the panel is open, it falls asleep,
 * and any interaction wakes it with a pose rather than a jolt.
 */
export const AgentChat: React.FC = () => {
    const { t } = useI18n();
    const location = useLocation();
    const [open, setOpen] = useState(false);
    const [status, setStatus] = useState<AgentStatus | null>(null);
    const [statusFailed, setStatusFailed] = useState(false);
    const [turns, setTurns] = useState<Turn[]>([]);
    const [draft, setDraft] = useState('');
    const [phase, setPhase] = useState<Phase>('idle');
    const [mood, setMood] = useState<'sent' | 'success' | 'error' | 'wake' | null>(null);
    const [sleeping, setSleeping] = useState(false);
    // Bumped by every interaction while the panel is open: it is what reschedules
    // the nap below, so the timer itself never has to be juggled by hand.
    const [activity, setActivity] = useState(0);
    const reveal = usePacedText();
    const [calm, setCalm] = useState(true);
    const containerRef = useRef<HTMLDivElement>(null);
    const panel = useRef<HTMLDivElement | null>(null);
    const listRef = useRef<HTMLDivElement>(null);
    const abort = useRef<AbortController | null>(null);
    const timers = useRef<number[]>([]);
    const calmTimer = useRef<number | null>(null);
    // Read by callbacks that outlive a render (the activity throttle, the wake).
    const sleepingRef = useRef(false);
    const lastActivity = useRef(0);
    // The agent speaks up about a broken runtime once per session, not on every
    // open/close of the panel.
    const greeted = useRef(false);

    // The analysis the conversation is grounded in: whatever project the user is
    // looking at. The server decides which run that means (the latest finished one).
    const projectId = matchPath(PROJECT_ROUTE, location.pathname)?.params.id;
    const canAnswer = status !== null && status.available;
    const busy = phase !== 'idle';

    /** A timeout that dies with the component. */
    const later = useCallback((run: () => void, ms: number) => {
        timers.current.push(window.setTimeout(run, ms));
    }, []);

    useEffect(
        () => () => {
            timers.current.forEach(window.clearTimeout);
            if (calmTimer.current !== null) window.clearTimeout(calmTimer.current);
            abort.current?.abort();
        },
        []
    );

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
    }, [turns, reveal.text, phase]);

    /**
     * Any sign of life: the robot pays attention, and if it had nodded off it
     * comes back up instead of simply opening its eyes mid-sentence.
     */
    const noteActivity = useCallback(
        (force = false) => {
            const now = Date.now();
            if (!force && now - lastActivity.current < ACTIVITY_MS) return;
            lastActivity.current = now;
            if (sleepingRef.current) {
                sleepingRef.current = false;
                setSleeping(false);
                setMood('wake');
                later(() => setMood((current) => (current === 'wake' ? null : current)), WAKE_MS);
            }
            setActivity(now);
        },
        [later]
    );

    /**
     * The nap. Armed only while the panel is open and the agent is not working —
     * a closed panel has nothing to animate, and a run in flight is not idle — and
     * re-armed from scratch by every interaction, because the effect's cleanup is
     * the cancellation.
     */
    useEffect(() => {
        if (!open || busy || sleeping) return;
        const timer = window.setTimeout(() => {
            sleepingRef.current = true;
            setSleeping(true);
        }, SLEEP_MS);
        return () => window.clearTimeout(timer);
    }, [open, busy, sleeping, activity]);

    /** Any sign of life from the user: the robot pays attention again. */
    const noteInput = () => {
        setCalm(false);
        noteActivity();
        setMood((current) => (current === 'error' ? null : current));
        // One timer, replaced: keystrokes must not stack up and let an old one
        // relax the robot while the user is still typing.
        if (calmTimer.current !== null) window.clearTimeout(calmTimer.current);
        calmTimer.current = window.setTimeout(() => setCalm(true), CALM_MS);
    };

    const send = async () => {
        const content = draft.trim();
        if (!content || busy) return;

        const history: Turn[] = [...turns, { role: 'user', content }];
        setTurns(history);
        setDraft('');
        reveal.reset();
        setMood('sent');
        setPhase('pending');
        later(() => setMood((current) => (current === 'sent' ? null : current)), SENT_MS);

        const controller = new AbortController();
        abort.current = controller;
        let accumulated = '';
        // Held locally as well as in state: the outcome is read after the awaits,
        // where a captured state value would still be the one from this render.
        let meta: AgentStreamMeta | null = null;

        const outcome = await streamAgentMessage(
            history.map(({ role, content: text }) => ({ role, content: text })),
            { projectId },
            {
                signal: controller.signal,
                onMeta: (next) => {
                    meta = next;
                    setPhase((current) => (current === 'pending' ? 'generating' : current));
                },
                onDelta: (text) => {
                    accumulated += text;
                    reveal.push(text);
                    setPhase('streaming');
                },
            }
        );

        abort.current = null;

        // A finished answer is waited for: the turn is committed once the text has
        // been written to the screen, so the bubble never jumps from a half-written
        // paragraph to the whole one. A cut or failed stream is not waited for —
        // stopping a generation should keep the answer, not the animation.
        if (outcome.kind === 'done') {
            await reveal.flush();
        }
        reveal.reset();
        setPhase('idle');

        /** How the answer was produced, in the transcript's footnote form. */
        const footnote = (reply: AgentStreamMeta | null): string =>
            [
                t('agent.findingsUsed', { count: reply?.findings_used ?? 0 }),
                reply?.truncated ? t('agent.truncated') : '',
            ]
                .filter(Boolean)
                .join(' · ');

        if (outcome.kind === 'done') {
            setTurns([
                ...history,
                { role: 'assistant', content: outcome.reply || accumulated, meta: footnote(meta) },
            ]);
            setMood('success');
            later(() => setMood((current) => (current === 'success' ? null : current)), SUCCESS_MS);
            return;
        }

        if (outcome.kind === 'cancelled') {
            // Nothing failed, so nothing looks wrong: the partial answer stays
            // where it got to — everything the server had already sent, which is
            // more than the screen had got round to revealing — and the robot goes
            // back to resting.
            const partial = outcome.partial || accumulated;
            setTurns([
                ...history,
                partial
                    ? { role: 'assistant', content: partial, meta: t('agent.cancelled') }
                    : { role: 'assistant', content: t('agent.cancelled') },
            ]);
            return;
        }

        // The server's own wording for a failure is written for operators; the
        // chat answers in the agent's voice instead.
        setTurns([
            ...history,
            accumulated
                ? { role: 'assistant', content: accumulated, meta: t('agent.error') }
                : { role: 'assistant', content: t('agent.error') },
        ]);
        setMood('error');
    };

    /**
     * The robot's state, derived from the turn's real phase — never from a timer
     * of its own, except for the two poses at the ends of a turn.
     *
     * Order matters: real text arriving outranks the greeting nod (a fast model
     * must not be hidden behind a 280ms pose), and the nod outranks "thinking"
     * (it is the reaction to *sending*, which happens before there is anything to
     * think about yet).
     */
    const robotState: RobotState =
        mood === 'error'
            ? 'error'
            : mood === 'success'
              ? 'success'
              : phase === 'streaming'
                ? 'typing'
                : mood === 'sent'
                  ? 'user-sent'
                  : phase !== 'idle'
                    ? 'thinking'
                    : mood === 'wake'
                      ? 'wake'
                      : sleeping
                        ? 'sleeping'
                        : draft.trim() !== '' || !calm
                          ? 'attentive'
                          : 'idle';

    /** Opening is the one gesture that always counts, however long it has been. */
    const toggleOpen = () => {
        const next = !open;
        setOpen(next);
        if (next) noteActivity(true);
    };

    return (
        <div
            ref={containerRef}
            // 8.75rem = the settings cluster (48px tall, bottom 5rem) plus its 12px
            // gap, so the two stacks keep the same rhythm instead of overlapping.
            // Both clear the Netlify badge in the bottom-right corner. The
            // safe-area term keeps that rhythm on a phone with a home indicator.
            className="fixed bottom-[calc(8.75rem+env(safe-area-inset-bottom))] right-[max(1.5rem,env(safe-area-inset-right))] z-40 flex flex-col items-end gap-3"
        >
            {open && (
                <div
                    ref={panel}
                    role="dialog"
                    aria-modal="true"
                    aria-label={t('agent.title')}
                    tabIndex={-1}
                    // Reading is interaction: the pointer being over the panel, or
                    // the transcript being scrolled, is what keeps the robot awake.
                    onPointerDown={() => noteActivity()}
                    onPointerMove={() => noteActivity()}
                    className="sw-popover sw-enter-pop flex w-[min(26rem,calc(100vw-3rem))] flex-col"
                >
                    <header className="flex items-start gap-3 border-b border-[var(--sw-hairline)] px-4 py-3">
                        {/* The robot always sits here, so whatever it is doing is
                            visible while the answer is being written. */}
                        <Robot state={robotState} size={40} className="shrink-0 -my-1 -ml-1" />
                        <span className="min-w-0 flex-1">
                            <span className="block text-sm font-semibold text-ink">
                                {t('agent.title')}
                            </span>
                            <span className="block truncate text-xs text-faint">
                                {busy && phase !== 'streaming'
                                    ? t('agent.thinking')
                                    : canAnswer && status
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
                        onScroll={() => noteActivity()}
                        className="sw-scroll flex max-h-[min(22rem,55dvh)] min-h-[min(9rem,25dvh)] flex-col gap-3 overflow-y-auto px-4 py-3"
                    >
                        {turns.length === 0 && <p className="sw-hint">{t('agent.empty')}</p>}
                        {turns.map((turn, index) => (
                            // Turns are append-only and never reordered, so the
                            // index is a stable key: a growing transcript does not
                            // re-mount (or re-animate) the bubbles above it.
                            <div
                                key={index}
                                className={cx(
                                    'flex flex-col',
                                    turn.role === 'user' ? 'items-end' : 'items-start'
                                )}
                            >
                                <span className="text-xs font-bold uppercase tracking-[0.08em] text-faint sm:text-2xs">
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
                                    <span className="mt-1 text-xs text-faint sm:text-micro">
                                        {turn.meta}
                                    </span>
                                )}
                            </div>
                        ))}

                        {reveal.text !== '' && (
                            <div className="flex flex-col items-start">
                                <span className="text-xs font-bold uppercase tracking-[0.08em] text-faint sm:text-2xs">
                                    {t('agent.name')}
                                </span>
                                <p className="mt-1 max-w-[90%] whitespace-pre-wrap rounded-sw bg-[var(--sw-sunken)] px-3 py-2 text-sm text-ink">
                                    {reveal.text}
                                </p>
                                <span
                                    className="mt-1 text-xs text-faint sm:text-micro"
                                    role="status"
                                >
                                    {t('agent.generating')}
                                </span>
                            </div>
                        )}

                        {busy && reveal.text === '' && (
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
                            maxLength={status?.max_message_chars}
                            placeholder={t('agent.placeholder')}
                            aria-label={t('agent.placeholder')}
                            onChange={(event) => {
                                setDraft(event.target.value);
                                noteInput();
                            }}
                            onFocus={noteInput}
                            onKeyDown={(event) => {
                                if (event.key === 'Enter' && !event.shiftKey) {
                                    event.preventDefault();
                                    void send();
                                }
                            }}
                            className="sw-input sw-input--textarea flex-1"
                        />
                        {busy ? (
                            <Button variant="neutral" onClick={() => abort.current?.abort()}>
                                {t('agent.stop')}
                            </Button>
                        ) : (
                            <Button
                                variant="primary"
                                disabled={!draft.trim()}
                                onClick={() => void send()}
                            >
                                {t('agent.send')}
                            </Button>
                        )}
                    </div>
                </div>
            )}

            <button
                type="button"
                onClick={toggleOpen}
                className="sw-fab sw-fab--accent"
                aria-expanded={open}
                aria-haspopup="dialog"
                aria-label={t('agent.open')}
                title={t('agent.open')}
            >
                <RobotIcon size={22} />
            </button>
        </div>
    );
};
