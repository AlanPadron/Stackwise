// Sign-in screen: email + password → JWT, then straight to the dashboard.
import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { getApiErrorMessage } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { useSplash } from '../context/SplashContext';
import { Button, Card, Input } from '../components/ui';

const Login: React.FC = () => {
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const { loginWithCredentials } = useAuth();
    const triggerSplash = useSplash();
    const navigate = useNavigate();

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError('');
        setLoading(true);
        try {
            await loginWithCredentials(email, password);
            triggerSplash();
            navigate('/dashboard');
        } catch (err: unknown) {
            setError(getApiErrorMessage(err, 'Authentication failed'));
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="min-h-screen grid place-items-center p-6 neu-ambient">
            <Card className="w-full max-w-md p-8 md:p-10 neu-enter">
                <header className="flex flex-col items-center text-center mb-8">
                    <span className="neu-mark mb-5">W</span>
                    <h1 className="text-2xl font-bold tracking-tight">Welcome back</h1>
                    <p className="text-sm text-muted mt-1.5">Sign in to your Stackwise account</p>
                </header>

                <form onSubmit={handleSubmit} className="space-y-5" noValidate={false}>
                    <Input
                        label="Email"
                        type="email"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        autoComplete="email"
                        required
                    />
                    <Input
                        label="Password"
                        type="password"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        autoComplete="current-password"
                        required
                    />

                    {error && (
                        <p className="neu-hint neu-hint--error text-center neu-enter-pop" role="alert">
                            {error}
                        </p>
                    )}

                    <Button type="submit" variant="primary" size="lg" block loading={loading}>
                        {loading ? 'Signing in…' : 'Sign In'}
                    </Button>
                </form>

                <p className="mt-6 text-center text-sm text-muted">
                    Don't have an account?{' '}
                    <Link to="/register" className="font-semibold text-accent no-underline hover:underline">
                        Register
                    </Link>
                </p>
            </Card>
        </div>
    );
};

export default Login;
