// frontend/src/pages/Login.tsx
import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import apiClient from '../api/client';
import { useAuth } from '../context/AuthContext';

const Login: React.FC = () => {
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const { login } = useAuth();
    const navigate = useNavigate();

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError('');
        setLoading(true);
        try {
            // FastAPI OAuth2 uses form data for login
            const formData = new FormData();
            formData.append('username', email);
            formData.append('password', password);

            const response = await apiClient.post('/auth/login', formData);
            const { access_token } = response.data;

            // Fetch user info to complete the login
            const userRes = await apiClient.get('/auth/me');
            login(access_token, userRes.data);

            navigate('/dashboard');
        } catch (err: any) {
            setError(err.response?.data?.detail || 'Authentication failed');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="min-h-screen flex items-center justify-center bg-slate-50 dark:bg-slate-900 p-4 relative overflow-hidden transition-colors duration-500">
            {/* Animated Background Waves to match Register page */}
            <div className="absolute inset-0 z-0 pointer-events-none overflow-hidden">
                <div className="absolute -top-[10%] -left-[10%] w-[60%] h-[60%] bg-indigo-200 dark:bg-indigo-900/20 rounded-full blur-[120px] animate-pulse duration-7000"></div>
                <div className="absolute top-[20%] -right-[10%] w-[50%] h-[50%] bg-blue-200 dark:bg-blue-900/20 rounded-full blur-[120px] animate-pulse duration-5000"></div>
                <div className="absolute -bottom-[10%] left-[20%] w-[50%] h-[50%] bg-purple-200 dark:bg-purple-900/20 rounded-full blur-[120px] animate-pulse duration-6000"></div>
            </div>

            <div className="max-w-md w-full bg-white/80 dark:bg-slate-800/80 backdrop-blur-md rounded-md shadow-2xl border border-slate-200 dark:border-slate-700 p-8 z-10 transition-all duration-500">
                <div className="text-center mb-8">
                    <h1 className="text-3xl font-bold text-slate-900 dark:text-white mb-2 tracking-tight">Welcome back</h1>
                    <p className="text-slate-500 dark:text-slate-400">Sign in to your Stackwise account</p>
                </div>
                <form onSubmit={handleSubmit} className="space-y-6">
                    <div className="group">
                        <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1 transition-colors">Email</label>
                        <input
                            type="email"
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            className="w-full px-4 py-2 border border-slate-300 dark:border-slate-600 rounded-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all bg-transparent dark:text-white"
                            required
                        />
                    </div>
                    <div className="group">
                        <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1 transition-colors">Password</label>
                        <input
                            type="password"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            className="w-full px-4 py-2 border border-slate-300 dark:border-slate-600 rounded-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all bg-transparent dark:text-white"
                            required
                        />
                    </div>
                    {error && <div className="text-red-500 dark:text-red-400 text-sm text-center font-medium animate-bounce">{error}</div>}
                    <button
                        type="submit"
                        disabled={loading}
                        className="w-full py-3 px-4 bg-indigo-600 hover:bg-indigo-700 text-white font-semibold rounded-sm transition-all transform hover:scale-[1.02] active:scale-[0.98] disabled:opacity-50 shadow-lg shadow-indigo-500/30"
                    >
                        {loading ? 'Signing in...' : 'Sign In'}
                    </button>
                </form>
                <div className="mt-6 text-center">
                    <p className="text-sm text-slate-500 dark:text-slate-400">
                        Don't have an account? <a href="/register" className="text-indigo-600 dark:text-indigo-400 hover:underline font-medium transition-colors">Register</a>
                    </p>
                </div>
            </div>
        </div>
    );
};

export default Login;
