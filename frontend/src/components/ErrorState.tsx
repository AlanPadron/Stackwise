/**
 * Shown when a screen could not load its data.
 *
 * The list screens used to log the failure and install an empty result, so a
 * dropped request rendered "No projects found. Start by creating one!" — a claim
 * about the user's data that the app had no basis for. This says what happened
 * and offers the only useful action.
 */
import React from 'react';
import { useI18n } from '../i18n/I18nContext';
import { Button, Well } from './ui';

export const ErrorState: React.FC<{ message: string; onRetry: () => void }> = ({
    message,
    onRetry,
}) => {
    const { t } = useI18n();

    return (
        <Well className="flex flex-col items-start gap-4 p-6" role="alert">
            <p className="text-sm text-ink">{message}</p>
            <Button size="sm" onClick={onRetry}>
                {t('common.retry')}
            </Button>
        </Well>
    );
};

export default ErrorState;
