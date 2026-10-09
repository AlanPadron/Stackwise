import React from 'react';
import { cx } from './cx';

export interface LoaderProps extends React.HTMLAttributes<HTMLDivElement> {
    /** Accessible status text, also used as the visible caption. */
    caption?: string;
    /** Stretches the loader across the viewport — route guards and first paints. */
    fullPage?: boolean;
}

/**
 * The only looping animation in the design system: a low-amplitude breathing
 * indicator. Decorative motion is finite; a pending state has to repeat.
 */
export const Loader: React.FC<LoaderProps> = ({
    caption,
    fullPage = false,
    className,
    ...rest
}) => (
    <div
        className={cx(
            'flex flex-col items-center gap-4',
            fullPage && 'min-h-screen justify-center neu-ambient',
            className
        )}
        role="status"
        aria-live="polite"
        {...rest}
    >
        <span className="neu-loader" aria-hidden="true">
            <span />
            <span />
            <span />
        </span>
        {caption && <span className="text-sm text-muted">{caption}</span>}
    </div>
);
