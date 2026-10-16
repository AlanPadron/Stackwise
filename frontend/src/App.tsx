import React, { useState } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import { ThemeProvider } from './context/ThemeContext';
import { I18nProvider, useI18n } from './i18n/I18nContext';
import { SplashContext } from './context/SplashContext';
import Splash from './components/Splash';
import { AgentChat } from './components/AgentChat';
import { ErrorState } from './components/ErrorState';
import { PwaStatus } from './components/PwaStatus';
import { SettingsMenu } from './components/SettingsMenu';
import { Loader } from './components/ui';
import Login from './pages/Login';
import Register from './pages/Register';
import AuthCallback from './pages/AuthCallback';
import Dashboard from './pages/Dashboard';
import Projects from './pages/Projects';
import ProjectDetail from './pages/ProjectDetail';
import NewProject from './pages/NewProject';
import ImportRepo from './pages/ImportRepo';

const ProtectedRoute = ({ children }: { children: React.ReactNode }) => {
    const { isAuthenticated, isLoading, sessionUnreachable, retrySession } = useAuth();
    const { t } = useI18n();
    if (isLoading) return <Loader fullPage caption={t('auth.restoring')} />;
    // A stored session that could not be checked is not a signed-out user: show
    // the failure and let them try again instead of bouncing them to the form.
    if (sessionUnreachable) {
        return <ErrorState message={t('auth.sessionUnreachable')} onRetry={retrySession} />;
    }
    if (!isAuthenticated) return <Navigate to="/login" replace />;
    return <>{children}</>;
};

const SPLASH_SESSION_KEY = 'stackwise_splash_shown';

const AppContent: React.FC = () => {
    const { isAuthenticated } = useAuth();
    // The transition screen is shown only when the session starts or the user signs in,
    // not on every reload/navigation within the same session.
    const [showSplash, setShowSplash] = useState(
        () => sessionStorage.getItem(SPLASH_SESSION_KEY) !== '1'
    );

    const finishSplash = () => {
        sessionStorage.setItem(SPLASH_SESSION_KEY, '1');
        setShowSplash(false);
    };

    return (
        <SplashContext.Provider value={() => setShowSplash(true)}>
            <PwaStatus />
            <SettingsMenu />
            {/* The findings agent is an account feature: no session, no button. */}
            {isAuthenticated && <AgentChat />}
            <Routes>
                <Route path="/login" element={<Login />} />
                <Route path="/register" element={<Register />} />
                {/* Where the OAuth providers send the browser back. */}
                <Route path="/auth/callback" element={<AuthCallback />} />
                <Route path="/dashboard" element={<ProtectedRoute><Dashboard /></ProtectedRoute>} />
                <Route path="/projects" element={<ProtectedRoute><Projects /></ProtectedRoute>} />
                <Route path="/projects/new" element={<ProtectedRoute><NewProject /></ProtectedRoute>} />
                <Route path="/projects/import" element={<ProtectedRoute><ImportRepo /></ProtectedRoute>} />
                <Route path="/projects/:id" element={<ProtectedRoute><ProjectDetail /></ProtectedRoute>} />
                <Route path="/" element={<Navigate to="/dashboard" replace />} />
                {/* Unknown URLs must never render an empty shell. */}
                <Route path="*" element={<Navigate to="/dashboard" replace />} />
            </Routes>
            {showSplash && <Splash onComplete={finishSplash} />}
        </SplashContext.Provider>
    );
};

const App: React.FC = () => {
    return (
        <BrowserRouter>
            <ThemeProvider>
                <I18nProvider>
                    <AuthProvider>
                        <AppContent />
                    </AuthProvider>
                </I18nProvider>
            </ThemeProvider>
        </BrowserRouter>
    );
};

export default App;
