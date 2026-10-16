// Session state: the JWT in localStorage, the user it resolves to, login/logout.
import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';
import axios from 'axios';
import apiClient from '../api/client';
import { User } from '../types';

interface AuthContextType {
    user: User | null;
    loginWithCredentials: (email: string, password: string) => Promise<User>;
    /** Adopt a session token minted elsewhere (the OAuth callback). */
    loginWithToken: (token: string) => Promise<User>;
    logout: () => void;
    isLoading: boolean;
    isAuthenticated: boolean;
    /** True when the stored session could not be checked: the API is unreachable. */
    sessionUnreachable: boolean;
    retrySession: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const [user, setUser] = useState<User | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [sessionUnreachable, setSessionUnreachable] = useState(false);

    const initAuth = useCallback(async () => {
        setIsLoading(true);
        const token = localStorage.getItem('token');
        if (token) {
            try {
                const response = await apiClient.get('/auth/me');
                setUser(response.data);
                setSessionUnreachable(false);
            } catch (error) {
                // Only an explicit rejection means the session is over. An
                // outage — offline, a 502 from a proxy, a restarting API — used
                // to delete the token and sign the user out for the whole
                // incident; now the session is kept and the screen offers a retry.
                const status = axios.isAxiosError(error) ? error.response?.status : undefined;
                if (status === 401 || status === 403) {
                    localStorage.removeItem('token');
                    setUser(null);
                    setSessionUnreachable(false);
                } else {
                    setSessionUnreachable(true);
                }
            }
        }
        setIsLoading(false);
    }, []);

    useEffect(() => {
        void initAuth();
    }, [initAuth]);

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
        setSessionUnreachable(false);
    };

    const loginWithToken = async (token: string): Promise<User> => {
        // Persist first: the interceptor reads the token for the /auth/me call.
        localStorage.setItem('token', token);
        try {
            const { data } = await apiClient.get('/auth/me');
            setUser(data);
            return data;
        } catch (error) {
            localStorage.removeItem('token');
            throw error;
        }
    };

    return (
        <AuthContext.Provider
            value={{
                user,
                loginWithCredentials,
                loginWithToken,
                logout,
                isLoading,
                isAuthenticated: !!user,
                sessionUnreachable,
                retrySession: () => void initAuth(),
            }}
        >
            {children}
        </AuthContext.Provider>
    );
};

export const useAuth = () => {
    const context = useContext(AuthContext);
    if (!context) throw new Error('useAuth must be used within AuthProvider');
    return context;
};
