// Session state: the JWT in localStorage, the user it resolves to, login/logout.
import React, { createContext, useContext, useState, useEffect } from 'react';
import apiClient from '../api/client';
import { User } from '../types';

interface AuthContextType {
    user: User | null;
    loginWithCredentials: (email: string, password: string) => Promise<User>;
    logout: () => void;
    isLoading: boolean;
    isAuthenticated: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const [user, setUser] = useState<User | null>(null);
    const [isLoading, setIsLoading] = useState(true);

    useEffect(() => {
        const initAuth = async () => {
            const token = localStorage.getItem('token');
            if (token) {
                try {
                    const response = await apiClient.get('/auth/me');
                    setUser(response.data);
                } catch (e) {
                    localStorage.removeItem('token');
                }
            }
            setIsLoading(false);
        };
        initAuth();
    }, []);

    const loginWithCredentials = async (email: string, password: string): Promise<User> => {
        // FastAPI OAuth2 login expects form data (username = email)
        const formData = new FormData();
        formData.append('username', email);
        formData.append('password', password);

        const { data } = await apiClient.post('/auth/login', formData, {
            headers: { 'Content-Type': 'multipart/form-data' },
        });

        // Persist the token before any authenticated request so interceptors can attach it
        localStorage.setItem('token', data.access_token);
        const meRes = await apiClient.get('/auth/me');
        setUser(meRes.data);
        return meRes.data;
    };

    const logout = () => {
        localStorage.removeItem('token');
        setUser(null);
    };

    return (
        <AuthContext.Provider value={{ user, loginWithCredentials, logout, isLoading, isAuthenticated: !!user }}>
            {children}
        </AuthContext.Provider>
    );
};

export const useAuth = () => {
    const context = useContext(AuthContext);
    if (!context) throw new Error('useAuth must be used within AuthProvider');
    return context;
};
