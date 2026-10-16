import React, { useEffect, useState } from 'react';
import { getApiErrorMessage } from '../api/client';
import {
    fetchAuthorizeUrl,
    fetchProviders,
    OAuthProvider,
    ProviderAvailability,
} from '../api/oauth';
import { useI18n } from '../i18n/I18nContext';
import { Button, GitHubIcon, GoogleIcon, TerminalIcon } from './ui';

// `mock` is the dev-only provider served by this API; it is listed last and only
// rendered when the server reports it as enabled.
const PROVIDER_ORDER: OAuthProvider[] = ['google', 'github', 'mock'];

const PROVIDER_ICON: Record<OAuthProvider, React.ReactNode> = {
    google: <GoogleIcon size={17} />,
    github: <GitHubIcon size={17} />,
    mock: <TerminalIcon size={17} />,
};

const PROVIDER_LABEL = {
    google: 'oauth.google',
    github: 'oauth.github',
    mock: 'oauth.mock',
} as const;

/** The "or" rule that separates the password form from the provider buttons. */
const Divider: React.FC = () => {
    const { t } = useI18n();
    return (
        <div className="mb-5 flex items-center gap-3" aria-hidden="true">
            <span className="h-px flex-1 bg-[var(--sw-hairline)]" />
            <span className="text-xs uppercase tracking-[0.08em] text-faint">{t('oauth.or')}</span>
            <span className="h-px flex-1 bg-[var(--sw-hairline)]" />
        </div>
    );
};

/**
 * Sign-in through an external provider.
 *
 * Renders nothing at all when the server has no provider configured, so the
 * form never offers an option that cannot work. `next` is the SPA path the
 * browser should land on afterwards (used when connecting GitHub from the
 * import screen).
 */
export const OAuthButtons: React.FC<{ next?: string }> = ({ next }) => {
    const { t } = useI18n();
    const [providers, setProviders] = useState<ProviderAvailability | null>(null);
    const [pending, setPending] = useState<OAuthProvider | null>(null);
    const [error, setError] = useState('');

    useEffect(() => {
        let active = true;
        fetchProviders()
            .then((available) => active && setProviders(available))
            // A failed probe means "cannot offer providers", not a broken form.
            .catch(() => active && setProviders({ google: false, github: false, mock: false }));
        return () => {
            active = false;
        };
    }, []);

    if (!providers) return null;

    const enabled = PROVIDER_ORDER.filter((provider) => providers[provider]);

    if (enabled.length === 0) {
        // A production build stays clean: no dead options for end users. In
        // development the missing configuration is spelled out instead, because
        // silently dropping the feature looks like a bug.
        if (!import.meta.env.DEV) return null;
        return (
            <div className="mt-7">
                <Divider />
                <p className="sw-hint break-words text-center">{t('oauth.notConfigured')}</p>
            </div>
        );
    }

    const start = async (provider: OAuthProvider) => {
        setError('');
        setPending(provider);
        try {
            // A full navigation: the provider takes over from here and comes
            // back to /auth/callback.
            window.location.assign(await fetchAuthorizeUrl(provider, next));
        } catch (err: unknown) {
            setError(getApiErrorMessage(err, t('oauth.failed')));
            setPending(null);
        }
    };

    return (
        <div className="mt-7">
            <Divider />

            <div className="flex flex-col gap-3">
                {enabled.map((provider) => (
                    <Button
                        key={provider}
                        className="w-full min-h-[2.75rem] md:min-h-0"
                        onClick={() => start(provider)}
                        disabled={pending !== null}
                        loading={pending === provider}
                    >
                        {PROVIDER_ICON[provider]}
                        {t('oauth.continueWith', { provider: t(PROVIDER_LABEL[provider]) })}
                    </Button>
                ))}
            </div>

            {error && (
                <p className="sw-hint sw-hint--error mt-4 break-words text-center" role="alert">
                    {error}
                </p>
            )}
        </div>
    );
};
