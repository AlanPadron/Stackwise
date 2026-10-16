import React, { useCallback, useEffect, useState } from 'react';
import { getApiErrorMessage } from '../api/client';
import {
    fetchAuthorizeUrl,
    fetchLinkedAccounts,
    fetchProviders,
    LinkedAccount,
    OAuthProvider,
    ProviderAvailability,
    unlinkProvider,
} from '../api/oauth';
import { useAuth } from '../context/AuthContext';
import { useI18n } from '../i18n/I18nContext';
import { Button, GitHubIcon, GoogleIcon, TerminalIcon } from './ui';

// `mock` is the dev-only provider served by this API; it is listed last and only
// offered when the server reports it as enabled, which is also the only way to
// exercise connect/disconnect before real credentials exist.
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

/**
 * "Sign-in methods": the provider identities attached to this account.
 *
 * A row exists for every provider this server can offer *or* that is already
 * linked — a link left over from a provider that was later unconfigured still
 * has to be removable, otherwise the only way to cut it were the database.
 *
 * Connecting is a full navigation (the provider takes over from here and comes
 * back to `/auth/callback`), so it reuses the same endpoint the sign-in form
 * does; disconnecting stays in place and re-reads the list.
 */
export const LinkedAccounts: React.FC = () => {
    const { isAuthenticated } = useAuth();
    const { t } = useI18n();
    const [providers, setProviders] = useState<ProviderAvailability | null>(null);
    const [linked, setLinked] = useState<LinkedAccount[] | null>(null);
    const [pending, setPending] = useState<OAuthProvider | null>(null);
    const [error, setError] = useState('');

    const loadLinked = useCallback(async () => {
        setLinked(await fetchLinkedAccounts());
    }, []);

    useEffect(() => {
        if (!isAuthenticated) return;
        let active = true;
        Promise.all([fetchProviders(), fetchLinkedAccounts()])
            .then(([available, accounts]) => {
                if (!active) return;
                setProviders(available);
                setLinked(accounts);
            })
            // A failed probe means "nothing to manage here", not a broken drawer.
            .catch(() => active && setProviders({ google: false, github: false, mock: false }));
        return () => {
            active = false;
        };
    }, [isAuthenticated]);

    if (!isAuthenticated || !providers || !linked) return null;

    const byProvider: Record<string, LinkedAccount | undefined> = Object.fromEntries(
        linked.map((account) => [account.provider, account])
    );
    const shown = PROVIDER_ORDER.filter(
        (provider) => providers[provider] || byProvider[provider] !== undefined
    );
    if (shown.length === 0) return null;

    const connect = async (provider: OAuthProvider) => {
        setError('');
        setPending(provider);
        try {
            // Land back on the dashboard, where the connection is visible.
            window.location.assign(await fetchAuthorizeUrl(provider, '/dashboard'));
        } catch (err: unknown) {
            setError(getApiErrorMessage(err, t('oauth.failed')));
            setPending(null);
        }
    };

    const disconnect = async (provider: OAuthProvider) => {
        setError('');
        setPending(provider);
        try {
            await unlinkProvider(provider);
            await loadLinked();
        } catch (err: unknown) {
            // The 409 (last way in) belongs on screen: it explains why the
            // button did nothing.
            setError(getApiErrorMessage(err, t('settings.disconnectFailed')));
        } finally {
            setPending(null);
        }
    };

    return (
        <div>
            <hr className="sw-divider my-1" />
            <p className="px-3 pb-2 pt-3 text-xs font-bold uppercase tracking-[0.08em] text-faint sm:text-[0.6875rem]">
                {t('settings.connections')}
            </p>

            {shown.map((provider) => {
                const account = byProvider[provider];
                const identity = account?.login || account?.email || '';
                return (
                    <div key={provider} className="flex items-center gap-3 px-3 py-2.5">
                        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-sw-sm bg-[var(--sw-accent-soft)] text-accent">
                            {PROVIDER_ICON[provider]}
                        </span>
                        <span className="min-w-0 flex-1">
                            <span className="block truncate text-sm font-semibold text-ink">
                                {t(PROVIDER_LABEL[provider])}
                            </span>
                            <span className="block truncate text-xs text-faint">
                                {account
                                    ? t('settings.connectedAs', { account: identity })
                                    : t('settings.notConnected')}
                            </span>
                        </span>
                        {account ? (
                            <Button
                                size="sm"
                                variant="ghost"
                                disabled={pending !== null}
                                loading={pending === provider}
                                onClick={() => disconnect(provider)}
                            >
                                {pending === provider
                                    ? t('settings.disconnecting')
                                    : t('settings.disconnect')}
                            </Button>
                        ) : (
                            <Button
                                size="sm"
                                disabled={pending !== null}
                                loading={pending === provider}
                                onClick={() => connect(provider)}
                            >
                                {t('settings.connect')}
                            </Button>
                        )}
                    </div>
                );
            })}

            {error && (
                <p className="sw-hint sw-hint--error break-words px-3 pb-2" role="alert">
                    {error}
                </p>
            )}
        </div>
    );
};
