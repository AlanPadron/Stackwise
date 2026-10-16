import React from 'react';
import { cx } from './cx';

export type ButtonVariant = 'primary' | 'neutral' | 'ghost' | 'danger';
export type ButtonSize = 'sm' | 'md' | 'lg' | 'icon';

const VARIANT_CLASS: Record<ButtonVariant, string> = {
    primary: 'sw-btn--primary',
    neutral: '',
    ghost: 'sw-btn--ghost',
    danger: 'sw-btn--danger',
};

const SIZE_CLASS: Record<ButtonSize, string> = {
    sm: 'sw-btn--sm',
    md: '',
    lg: 'sw-btn--lg',
    icon: 'sw-btn--icon',
};

export interface ButtonProps
    extends React.ButtonHTMLAttributes<HTMLButtonElement> {
    /** Visual emphasis. Defaults to `neutral` (raised surface). */
    variant?: ButtonVariant;
    size?: ButtonSize;
    /** Shows a pulse cue and disables interaction. */
    loading?: boolean;
    /** Stretches the button to its container width. */
    block?: boolean;
}

export const Button: React.FC<ButtonProps> = ({
    variant = 'neutral',
    size = 'md',
    loading = false,
    block = false,
    className,
    children,
    disabled,
    type = 'button',
    ...rest
}) => (
    <button
        type={type}
        className={cx(
            'sw-btn',
            VARIANT_CLASS[variant],
            SIZE_CLASS[size],
            block && 'sw-btn--block',
            className
        )}
        disabled={disabled || loading}
        aria-busy={loading || undefined}
        {...rest}
    >
        {loading && <span className="sw-btn__spinner" aria-hidden="true" />}
        {children}
    </button>
);
