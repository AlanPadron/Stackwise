import React, { useState } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import { ThemeProvider, useTheme } from './context/ThemeContext';
import Splash from './components/Splash';
import Login from './pages/Login';
import Register from './pages/Register';
import Dashboard from './pages/Dashboard';
import ProjectDetail from './pages/ProjectDetail';
import NewProject from './pages/NewProject';

const ProtectedRoute = ({ children }: { children: React.ReactNode }) => {
    const { isAuthenticated, isLoading } = useAuth();
    if (isLoading) return <div className="min-h-screen flex items-center justify-center bg-slate-50 dark:bg-slate-900">Loading...</div>;
    if (!isAuthenticated) return <Navigate to="/login" replace />;
    return <>{children}</>;
};

const ThemeToggle: React.FC = () => {
    const { theme, toggleTheme } = useTheme();
    return (
        <button
            onClick={toggleTheme}
            className="fixed bottom-6 right-6 p-3 rounded-full bg-white dark:bg-slate-800 shadow-lg border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:scale-110 transition-all z-50"
            title="Toggle Theme"
        >
            {theme === 'light' ? '🌙' : '☀️'}
        </button>
    );
};

const AppContent: React.FC = () => {
    const [showSplash, setShowSplash] = useState(true);

    if (showSplash) {
        return <Splash onComplete={() => setShowSplash(false)} />;
    }

    return (
        <>
            <ThemeToggle />
            <Routes>
                <Route path="/login" element={<Login />} />
                <Route path="/register" element={<Register />} />
                <Route path="/dashboard" element={<ProtectedRoute><Dashboard /></ProtectedRoute>} />
                <Route path="/projects/new" element={<ProtectedRoute><NewProject /></ProtectedRoute>} />
                <Route path="/projects/:id" element={<ProtectedRoute><ProjectDetail /></ProtectedRoute>} />
                <Route path="/" element={<Navigate to="/dashboard" replace />} />
            </Routes>
        </>
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
