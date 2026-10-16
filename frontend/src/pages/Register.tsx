import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import apiClient, { getApiErrorMessage } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { useSplash } from '../context/SplashContext';
import { useI18n } from '../i18n/I18nContext';
import { AuthLayout } from '../components/AuthLayout';
import { OAuthButtons } from '../components/OAuthButtons';
import { Button, Input } from '../components/ui';

const Register: React.FC = () => {
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [confirmPassword, setConfirmPassword] = useState('');
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const { loginWithCredentials } = useAuth();
    const { t } = useI18n();
    const triggerSplash = useSplash();
    const navigate = useNavigate();

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError('');

        if (password !== confirmPassword) {
            setError(t('auth.passwordsDoNotMatch'));
            return;
        }

        setLoading(true);
        try {
            await apiClient.post('/auth/register', { email, password });
            // Sign in automatically so the user lands on the dashboard
            await loginWithCredentials(email, password);
            triggerSplash();
            navigate('/dashboard');
        } catch (err: unknown) {
            setError(getApiErrorMessage(err, t('auth.registerFailed')));
        } finally {
            setLoading(false);
        }
    };

    return (
        <AuthLayout>
            <header className="mb-8">
                <h1 className="text-2xl font-bold tracking-tight">{t('auth.createAccount')}</h1>
                <p className="text-sm text-muted mt-1.5">{t('auth.registerSubtitle')}</p>
            </header>

            <form onSubmit={handleSubmit} className="space-y-5">
                <Input
                    label={t('auth.email')}
                    type="email"
                    inputMode="email"
                    autoComplete="email"
                    autoCapitalize="none"
                    spellCheck={false}
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                />
                <Input
                    label={t('auth.password')}
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    autoComplete="new-password"
                    hint={t('auth.passwordHint')}
                    required
                />
                <Input
                    label={t('auth.confirmPassword')}
                    type="password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    autoComplete="new-password"
                    required
                />

                {error && (
                    <p
                        className="sw-hint sw-hint--error break-words text-center sw-enter-pop"
                        role="alert"
                    >
                        {error}
                    </p>
                )}

                <Button type="submit" variant="primary" size="lg" block loading={loading}>
                    {loading ? t('auth.creating') : t('auth.register')}
                </Button>
            </form>

            <OAuthButtons />

            <p className="mt-6 text-center text-sm text-muted">
                {t('auth.alreadyAccount')}{' '}
                <Link to="/login" className="font-semibold text-accent no-underline hover:underline">
                    {t('auth.login')}
                </Link>
            </p>
        </AuthLayout>
    );
};

export default Register;
