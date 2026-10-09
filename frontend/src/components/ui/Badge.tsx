import React from 'react';
import { cx } from './cx';

export type BadgeTone = 'neutral' | 'accent' | 'danger' | 'warning' | 'success' | 'info';

const TONE_CLASS: Record<BadgeTone, string> = {
    neutral: '',
    accent: 'neu-badge--accent',
    danger: 'neu-badge--danger',
    warning: 'neu-badge--warning',
    success: 'neu-badge--success',
    info: 'neu-badge--info',
};

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
    tone?: BadgeTone;
}

export const Badge: React.FC<BadgeProps> = ({ tone = 'neutral', className, children, ...rest }) => (
    <span className={cx('neu-badge', TONE_CLASS[tone], className)} {...rest}>
        {children}
    </span>
);

/** Central mapping so severity colours change in one place. */
export const severityTone = (severity: string): BadgeTone => {
    switch (severity.toLowerCase()) {
        case 'high':
        case 'critical':
            return 'danger';
        case 'medium':
            return 'warning';
        default:
            return 'success';
    }
};

/** Central mapping for analysis-run statuses. */
export const statusTone = (status: string): BadgeTone => {
    switch (status) {
        case 'completed':
            return 'success';
        case 'failed':
            return 'danger';
        case 'processing':
            return 'accent';
        default:
            return 'neutral';
    }
};
