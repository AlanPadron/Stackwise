import React from 'react';
import { cx } from './cx';

export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
    /** Adds hover lift and a pressed state on click. */
    interactive?: boolean;
    /** Renders the "carved in" (pressed) look, e.g. for the selected item. */
    active?: boolean;
}

export const Card: React.FC<CardProps> = ({
    interactive = false,
    active = false,
    className,
    children,
    ...rest
}) => (
    <div
        className={cx(
            'neu-card',
            interactive && 'neu-card--interactive',
            active && 'neu-card--active',
            className
        )}
        {...rest}
    >
        {children}
    </div>
);

export type WellProps = React.HTMLAttributes<HTMLDivElement>;

/** Inset container for code, metadata lines and empty states. */
export const Well: React.FC<WellProps> = ({ className, children, ...rest }) => (
    <div className={cx('neu-inset', className)} {...rest}>
        {children}
    </div>
);
