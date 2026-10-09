import React, { useId } from 'react';
import { cx } from './cx';

interface FieldShellProps {
    label?: string;
    hint?: string;
    error?: string;
    htmlFor?: string;
}

const FieldShell: React.FC<React.PropsWithChildren<FieldShellProps>> = ({
    label,
    hint,
    error,
    htmlFor,
    children,
}) => (
    <div className="w-full">
        {label && (
            <label className="neu-label" htmlFor={htmlFor}>
                {label}
            </label>
        )}
        {children}
        {error ? (
            <p className="neu-hint neu-hint--error mt-2">{error}</p>
        ) : (
            hint && <p className="neu-hint mt-2">{hint}</p>
        )}
    </div>
);

export interface InputProps
    extends React.InputHTMLAttributes<HTMLInputElement> {
    label?: string;
    hint?: string;
    error?: string;
}

export const Input: React.FC<InputProps> = ({ label, hint, error, className, id, ...rest }) => {
    const autoId = useId();
    const inputId = id ?? (label ? `neu-${autoId}` : undefined);
    return (
        <FieldShell label={label} hint={hint} error={error} htmlFor={inputId}>
            <input
                id={inputId}
                className={cx('neu-input', error && 'neu-input--error', className)}
                aria-invalid={error ? true : undefined}
                {...rest}
            />
        </FieldShell>
    );
};

export interface TextareaProps
    extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
    label?: string;
    hint?: string;
    error?: string;
}

export const Textarea: React.FC<TextareaProps> = ({ label, hint, error, className, id, ...rest }) => {
    const autoId = useId();
    const inputId = id ?? (label ? `neu-${autoId}` : undefined);
    return (
        <FieldShell label={label} hint={hint} error={error} htmlFor={inputId}>
            <textarea
                id={inputId}
                className={cx('neu-input neu-input--textarea', error && 'neu-input--error', className)}
                aria-invalid={error ? true : undefined}
                {...rest}
            />
        </FieldShell>
    );
};
