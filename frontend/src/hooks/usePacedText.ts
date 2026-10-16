/**
 * Text that appears as it is written, instead of in the chunks it arrives in.
 *
 * A streamed answer arrives in whatever fragments the runtime emits — a hosted
 * model may hand back a whole paragraph in one frame — and rendering that
 * verbatim makes the robot "type" a paragraph in one keystroke. This keeps a
 * growing *prefix* of the truth instead: `push()` appends what arrived, a tick
 * reveals a slice of it, and `flush()` resolves once everything pushed so far is
 * on screen, so a caller can commit the turn after the answer has been written
 * rather than before.
 *
 * The reveal is deliberately not a fixed speed: each tick shows a fraction of
 * what is left, so a long backlog catches up within a few hundred milliseconds
 * while a slow model is followed one fragment at a time. What is rendered is
 * always a prefix of the real text — never re-typed, never invented.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

/** How often the prefix grows. ~40 a second: smooth without being a render loop. */
const TICK_MS = 24;
/** Never fewer than this per tick, or a long tail would crawl. */
const MIN_STEP = 3;
/** Denominator of the catch-up fraction: 6 → the backlog shrinks ~17% a tick. */
const CATCH_UP = 6;

export interface PacedText {
    /** The prefix to render. */
    text: string;
    /** Everything pushed so far. A function, so a terminal branch reads the truth
     * rather than whatever the last render happened to hold. */
    shown(): string;
    push(chunk: string): void;
    /** Resolves when the pushed text is fully on screen. */
    flush(): Promise<void>;
    reset(): void;
}

export const usePacedText = (tickMs: number = TICK_MS): PacedText => {
    const [text, setText] = useState('');
    const target = useRef('');
    const shown = useRef('');
    const timer = useRef<number | null>(null);
    const waiters = useRef<Array<() => void>>([]);

    const settle = useCallback(() => {
        const pending = waiters.current;
        waiters.current = [];
        pending.forEach((resolve) => resolve());
    }, []);

    const stop = useCallback(() => {
        if (timer.current !== null) {
            window.clearInterval(timer.current);
            timer.current = null;
        }
    }, []);

    const step = useCallback(() => {
        const full = target.current;
        if (shown.current.length >= full.length) {
            stop();
            settle();
            return;
        }
        const remaining = full.length - shown.current.length;
        const next = Math.max(MIN_STEP, Math.ceil(remaining / CATCH_UP));
        shown.current = full.slice(0, shown.current.length + next);
        setText(shown.current);
    }, [settle, stop]);

    const run = useCallback(() => {
        if (timer.current === null) timer.current = window.setInterval(step, tickMs);
    }, [step, tickMs]);

    const push = useCallback(
        (chunk: string) => {
            if (chunk === '') return;
            target.current += chunk;
            run();
        },
        [run]
    );

    const flush = useCallback(() => {
        if (shown.current === target.current) return Promise.resolve();
        run();
        return new Promise<void>((resolve) => waiters.current.push(resolve));
    }, [run]);

    // Behind the caller's back, not in it: the caller decides when the room it
    // was rendering into is gone, and every promise it was awaiting dies with it.
    const reset = useCallback(() => {
        stop();
        target.current = '';
        shown.current = '';
        waiters.current = [];
        setText('');
    }, [stop]);

    useEffect(
        () => () => {
            stop();
            settle();
        },
        [settle, stop]
    );

    return { text, shown: () => shown.current, push, flush, reset };
};
