/**
 * Keeps keyboard focus inside an open dialog, and gives it back on close.
 *
 * Written once because the app has three of them — the navigation drawer, the
 * settings panel and the findings chat — and each one had the same two gaps:
 * Tab walked straight out into the page behind the overlay, and closing the
 * panel dropped focus on `<body>`, so the next Tab started from the top of the
 * document instead of the button that opened it.
 *
 * The caller owns the open state; this only reacts to it.
 */
import { RefObject, useEffect, useRef } from 'react';

const FOCUSABLE =
    'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export const focusableWithin = (node: HTMLElement): HTMLElement[] =>
    Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (element) => element.offsetParent !== null || element === document.activeElement
    );

export const useFocusTrap = (
    active: boolean,
    container: RefObject<HTMLElement | null>,
    onEscape?: () => void
): void => {
    // Held in a ref so an inline arrow at the call site does not re-run the
    // effect (and re-grab focus) on every parent render.
    const escape = useRef(onEscape);
    useEffect(() => {
        escape.current = onEscape;
    }, [onEscape]);

    useEffect(() => {
        if (!active) return;
        const node = container.current;
        if (!node) return;

        const previous = document.activeElement as HTMLElement | null;

        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                escape.current?.();
                return;
            }
            if (event.key !== 'Tab') return;

            const items = focusableWithin(node);
            if (items.length === 0) {
                event.preventDefault();
                return;
            }
            const first = items[0];
            const last = items[items.length - 1];
            if (event.shiftKey && document.activeElement === first) {
                event.preventDefault();
                last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first.focus();
            }
        };

        document.addEventListener('keydown', onKeyDown, true);
        // A caller may name the element that deserves the focus (the chat's
        // composer, say) instead of settling for the first control in the DOM.
        (
            node.querySelector<HTMLElement>('[data-autofocus]') ??
            node.querySelector<HTMLElement>(FOCUSABLE) ??
            node
        ).focus();

        return () => {
            document.removeEventListener('keydown', onKeyDown, true);
            previous?.focus();
        };
    }, [active, container]);
};
