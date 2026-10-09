import React, { useId } from 'react';
import { cx } from './cx';

export interface SwitchProps {
    checked: boolean;
    onChange: (next: boolean) => void;
    /** Accessible name; required when no visible label is rendered. */
    label?: string;
    title?: string;
    className?: string;
    /** Content drawn inside the moving thumb. */
    thumbOn?: React.ReactNode;
    thumbOff?: React.ReactNode;
}

/**
 * Tactile toggle: the groove is carved in, the thumb rides on top of it and
 * physically slides between both ends of the track.
 */
export const Switch: React.FC<SwitchProps> = ({
    checked,
    onChange,
    label,
    title,
    className,
    thumbOn,
    thumbOff,
}) => {
    const id = useId();
    return (
        <button
            type="button"
            id={id}
            role="switch"
            aria-checked={checked}
            aria-label={label}
            title={title ?? label}
            onClick={() => onChange(!checked)}
            className={cx('neu-switch', className)}
        >
            <span className="neu-switch__thumb" aria-hidden="true">
                {checked ? thumbOn : thumbOff}
            </span>
        </button>
    );
};
