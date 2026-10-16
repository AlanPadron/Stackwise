// Landing point for the OAuth round-trip. The provider sends the browser back
// here with a session token — or an error code — in the URL fragment.
import React, { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { AuthLayout } from '../components/AuthLayout';
import { Loader } from '../components/ui';
import { useAuth } from '../context/AuthContext';
import { useSplash } from '../context/SplashContext';
import { TranslationKey } from '../i18n/dictionary';
import { useI18n } from '../i18n/I18nContext';

/** Fragment error codes → translation keys; the SPA owns the wording. */
const ERROR_KEY: Record<string, TranslationKey> = {
    state: 'oauth.errorState',
    provider: 'oauth.errorProvider',
    link: 'oauth.errorLink',
    pkce: 'oauth.errorPkce',
};

const AuthCallback: React.FC = () => {
    const { loginWithToken } = useAuth();
    const { t } = useI18n();
    const triggerSplash = useSplash();
    const navigate = useNavigate();
    const [errorKey, setErrorKey] = useState<TranslationKey | null>(null);
    // Effects run twice under StrictMode; the fragment may only be consumed once.
    const consumed = useRef(false);

    useEffect(() => {
        if (consumed.current) return;
        consumed.current = true;

        const params = new URLSearchParams(window.location.hash.slice(1));
        // Drop the fragment straight away so the token never lingers in history.
        window.history.replaceState(null, '', window.location.pathname);

        const errorCode = params.get('error');
        if (errorCode) {
            setErrorKey(ERROR_KEY[errorCode] ?? 'oauth.errorProvider');
            return;
        }

        const token = params.get('token');
        if (!token) {
            setErrorKey('oauth.errorProvider');
            return;
        }

        const next = params.get('next');
        const destination = next && next.startsWith('/') ? next : '/dashboard';

        loginWithToken(token)
            .then(() => {
                triggerSplash();
                navigate(destination, { replace: true });
            })
            .catch(() => setErrorKey('oauth.errorProvider'));
    }, [loginWithToken, navigate, triggerSplash]);

    return (
        <AuthLayout>
            {errorKey ? (
                <div className="text-center">
                    <p className="break-words text-sm text-muted" role="alert">
                        {t(errorKey)}
                    </p>
                    <Link
                        to="/login"
                        className="mt-6 inline-block py-3 font-semibold text-accent no-underline hover:underline md:py-0"
                    >
                        {t('oauth.backToLogin')}
                    </Link>
                </div>
            ) : (
                <Loader caption={t('oauth.signingIn')} />
            )}
        </AuthLayout>
    );
};

export default AuthCallback;
