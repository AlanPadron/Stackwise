import React from 'react';
import { cx } from './cx';

export type CardProps = React.HTMLAttributes<HTMLDivElement>;

/**
 * A surface, and nothing more.
 *
 * Anything clickable inside a card is a `Button` or a real `<button>`: a card
 * that handles `onClick` is a `div` no keyboard can reach, which is how the run
 * history used to work.
 */
export const Card: React.FC<CardProps> = ({ className, children, ...rest }) => (
    <div className={cx('sw-card', className)} {...rest}>
        {children}
    </div>
);

export type WellProps = React.HTMLAttributes<HTMLDivElement>;

/** Inset container for code, metadata lines and empty states. */
export const Well: React.FC<WellProps> = ({ className, children, ...rest }) => (
    <div className={cx('sw-inset', className)} {...rest}>
        {children}
    </div>
);
