import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useFocusTrap } from '../../hooks/useFocusTrap';
import { useI18n } from '../../i18n/I18nContext';
import { BrandMark, Wordmark } from './Brand';
import { cx } from './cx';
import { CloseIcon, MenuIcon } from './icons';

export interface AppShellProps extends React.HTMLAttributes<HTMLDivElement> {
    /** Rendered inside <aside>; use <Sidebar> for the standard chrome. */
    sidebar: React.ReactNode;
}

/** The width at which the fixed sidebar gives way to the drawer (Tailwind `md`). */
const DESKTOP = '(min-width: 768px)';

/**
 * Page frame shared by every authenticated screen.
 *
 * From `md` up it is the two-column layout it always was: a fixed 256px sidebar
 * beside the content. Below `md` the sidebar becomes a drawer behind a menu
 * button, because a 256px column on a 360px viewport left ~100px of content —
 * the single worst thing about the app on a phone.
 *
 * The drawer closes on navigation, on Escape and on the backdrop; focus moves
 * into it and returns to the menu button (`useFocusTrap`).
 */
export const AppShell: React.FC<AppShellProps> = ({ sidebar, className, children, ...rest }) => {
    const { t } = useI18n();
    const location = useLocation();
    const [navOpen, setNavOpen] = useState(false);
    const drawer = useRef<HTMLElement | null>(null);

    // Following a link is what closes the drawer: the nav items are ordinary
    // links, so nothing has to be threaded through them.
    useEffect(() => {
        setNavOpen(false);
    }, [location.pathname]);

    // Rotating to landscape or resizing past `md` hides the drawer's container
    // with `md:hidden`; without this the trap would still be holding focus
    // inside an element nobody can see.
    useEffect(() => {
        const media = window.matchMedia(DESKTOP);
        const onChange = (event: MediaQueryListEvent) => {
            if (event.matches) setNavOpen(false);
        };
        media.addEventListener('change', onChange);
        return () => media.removeEventListener('change', onChange);
    }, []);

    const closeNav = useCallback(() => setNavOpen(false), []);
    useFocusTrap(navOpen, drawer, closeNav);

    return (
        <div className={cx('min-h-dvh flex flex-col md:flex-row sw-ambient', className)} {...rest}>
            {/* Skips the navigation on the first Tab, as a keyboard user expects. */}
            <a
                href="#sw-main"
                className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[60]
                    focus:rounded-sw-sm focus:border focus:border-[var(--sw-border)] focus:px-4 focus:py-2
                    focus:text-sm focus:text-ink focus:shadow-sw focus:bg-[var(--sw-raised)]"
            >
                {t('a11y.skipToContent')}
            </a>

            <header
                className="md:hidden sticky top-0 z-30 flex items-center gap-2 sw-sidebar
                    pt-[max(0.5rem,env(safe-area-inset-top))] pb-2
                    pl-[max(0.75rem,env(safe-area-inset-left))] pr-[max(0.75rem,env(safe-area-inset-right))]"
            >
                <button
                    type="button"
                    className="sw-btn sw-btn--icon"
                    aria-label={t('nav.open')}
                    aria-expanded={navOpen}
                    aria-haspopup="dialog"
                    onClick={() => setNavOpen(true)}
                >
                    <MenuIcon />
                </button>
                <SidebarBrand href="/dashboard" />
            </header>

            <aside className="hidden md:flex w-64 shrink-0 sw-sidebar flex-col p-4 gap-2">
                {sidebar}
            </aside>

            <main
                id="sw-main"
                className="flex-1 min-w-0 p-6 md:p-10 sw-scroll overflow-y-auto
                    pl-[max(1.5rem,env(safe-area-inset-left))] pr-[max(1.5rem,env(safe-area-inset-right))]
                    pb-[max(1.5rem,env(safe-area-inset-bottom))] md:pl-10 md:pr-10 md:pb-10"
            >
                {children}
            </main>

            {navOpen && (
                <div
                    className="md:hidden fixed inset-0 z-40"
                    role="dialog"
                    aria-modal="true"
                    aria-label={t('nav.main')}
                >
                    {/* Mouse affordance only: Escape and the visible button are
                        the accessible ways out, so this stays out of the tab
                        order and out of the accessibility tree. */}
                    <button
                        type="button"
                        tabIndex={-1}
                        aria-hidden="true"
                        className="absolute inset-0 h-full w-full bg-black/45"
                        onClick={closeNav}
                    />
                    <aside
                        ref={drawer}
                        tabIndex={-1}
                        className="absolute inset-y-0 left-0 flex w-[min(17rem,86vw)] flex-col gap-2 sw-sidebar
                            sw-scroll overflow-y-auto
                            pt-[max(1rem,env(safe-area-inset-top))] pb-[max(1rem,env(safe-area-inset-bottom))]
                            pl-[max(1rem,env(safe-area-inset-left))] pr-4"
                    >
                        {/* Floats over the brand the sidebar renders, rather than
                            wrapping it: the drawer shows one navigation, not two. */}
                        <button
                            type="button"
                            className="sw-btn sw-btn--icon absolute right-3 top-[max(0.75rem,env(safe-area-inset-top))] z-10"
                            aria-label={t('nav.close')}
                            onClick={closeNav}
                        >
                            <CloseIcon />
                        </button>
                        {sidebar}
                    </aside>
                </div>
            )}
        </div>
    );
};

export interface SidebarBrandProps {
    href?: string;
}

/** The brand lockup: ornamental mark + wordmark, shared by every screen. */
export const SidebarBrand: React.FC<SidebarBrandProps> = ({ href = '/' }) => (
    <Link
        to={href}
        className="flex items-center gap-3 px-2 py-2 rounded-sw-sm no-underline text-ink"
    >
        <BrandMark />
        <Wordmark className="text-lg" />
    </Link>
);

export interface NavItemProps {
    href?: string;
    active?: boolean;
    onClick?: () => void;
    icon?: React.ReactNode;
    children: React.ReactNode;
    className?: string;
}

export const NavItem: React.FC<NavItemProps> = ({
    href,
    active = false,
    onClick,
    icon,
    children,
    className,
}) => {
    const classes = cx('sw-nav-item', active && 'sw-nav-item--active', className);
    const content = (
        <>
            {icon}
            <span>{children}</span>
        </>
    );

    if (href) {
        return (
            <Link
                to={href}
                className={classes}
                aria-current={active ? 'page' : undefined}
                onClick={onClick}
            >
                {content}
            </Link>
        );
    }

    return (
        <button
            type="button"
            onClick={onClick}
            className={classes}
            aria-current={active ? 'page' : undefined}
        >
            {content}
        </button>
    );
};

export type SidebarFooterProps = React.HTMLAttributes<HTMLDivElement>;

export const SidebarFooter: React.FC<SidebarFooterProps> = ({ className, children, ...rest }) => (
    <div className={cx('mt-auto pt-4', className)} {...rest}>
        <hr className="sw-divider mb-4" />
        {children}
    </div>
);
