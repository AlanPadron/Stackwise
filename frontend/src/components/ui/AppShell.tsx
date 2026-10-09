import React from 'react';
import { Link } from 'react-router-dom';
import { cx } from './cx';

export interface AppShellProps extends React.HTMLAttributes<HTMLDivElement> {
    /** Rendered inside <aside>; use <Sidebar> for the standard chrome. */
    sidebar: React.ReactNode;
}

/** Two-column page frame shared by every authenticated screen. */
export const AppShell: React.FC<AppShellProps> = ({ sidebar, className, children, ...rest }) => (
    <div className={cx('min-h-screen flex neu-ambient', className)} {...rest}>
        <aside className="w-64 shrink-0 neu-sidebar flex flex-col p-4 gap-2">{sidebar}</aside>
        <main className="flex-1 min-w-0 p-6 md:p-10 neu-scroll overflow-y-auto">{children}</main>
    </div>
);

export interface SidebarBrandProps {
    /** Short glyph shown in the carved mark. */
    mark?: string;
    name: string;
    href?: string;
}

export const SidebarBrand: React.FC<SidebarBrandProps> = ({ mark = 'W', name, href = '/' }) => (
    <Link
        to={href}
        className="flex items-center gap-3 px-2 py-3 rounded-neu-sm no-underline text-ink"
    >
        <span className="neu-mark" aria-hidden="true">
            {mark}
        </span>
        <span className="text-lg font-bold tracking-tight">{name}</span>
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
    const classes = cx('neu-nav-item', active && 'neu-nav-item--active', className);
    const content = (
        <>
            {icon}
            <span>{children}</span>
        </>
    );

    if (href) {
        return (
            <Link to={href} className={classes} aria-current={active ? 'page' : undefined}>
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
        <hr className="neu-divider mb-4" />
        {children}
    </div>
);
