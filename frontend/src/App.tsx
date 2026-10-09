import React, { useState } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import { ThemeProvider, useTheme } from './context/ThemeContext';
import { SplashContext } from './context/SplashContext';
import Splash from './components/Splash';
import { Loader, Switch } from './components/ui';
import Login from './pages/Login';
import Register from './pages/Register';
import Dashboard from './pages/Dashboard';
import Projects from './pages/Projects';
import ProjectDetail from './pages/ProjectDetail';
import NewProject from './pages/NewProject';

const ProtectedRoute = ({ children }: { children: React.ReactNode }) => {
    const { isAuthenticated, isLoading } = useAuth();
    if (isLoading) return <Loader fullPage caption="Restoring session…" />;
    if (!isAuthenticated) return <Navigate to="/login" replace />;
    return <>{children}</>;
};

/** Floating tactile switch: the whole theme lives in one control. */
const ThemeToggle: React.FC = () => {
    const { theme, toggleTheme } = useTheme();
    const isDark = theme === 'dark';
    return (
        <div className="fixed bottom-6 right-6 z-40 neu-card rounded-neu-lg pl-4 pr-2 py-2 flex items-center gap-3">
            <span className="text-[0.6875rem] font-bold uppercase tracking-[0.06em] text-faint">
                Theme
            </span>
            <Switch
                checked={isDark}
                onChange={toggleTheme}
                label="Toggle dark mode"
                thumbOn={<span aria-hidden="true">🌙</span>}
                thumbOff={<span aria-hidden="true">☀️</span>}
            />
        </div>
    );
};

const SPLASH_SESSION_KEY = 'stackwise_splash_shown';

const AppContent: React.FC = () => {
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
            <ThemeToggle />
            <Routes>
                <Route path="/login" element={<Login />} />
                <Route path="/register" element={<Register />} />
                <Route path="/dashboard" element={<ProtectedRoute><Dashboard /></ProtectedRoute>} />
                <Route path="/projects" element={<ProtectedRoute><Projects /></ProtectedRoute>} />
                <Route path="/projects/new" element={<ProtectedRoute><NewProject /></ProtectedRoute>} />
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
                <AuthProvider>
                    <AppContent />
                </AuthProvider>
            </ThemeProvider>
        </BrowserRouter>
    );
};

export default App;
