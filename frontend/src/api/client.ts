// frontend/src/api/client.ts
import axios from 'axios';

// Use the Vite dev proxy (relative /api/v1) by default; override with VITE_API_URL.
const API_BASE_URL = import.meta.env.VITE_API_URL || '/api/v1';

const apiClient = axios.create({
    baseURL: API_BASE_URL,
    headers: {
        'Content-Type': 'application/json',
    },
});

// Request interceptor to add JWT token
apiClient.interceptors.request.use((config) => {
    const token = localStorage.getItem('token');
    if (token) {
        config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
}, (error) => {
    return Promise.reject(error);
});

// Response interceptor for centralized error handling
apiClient.interceptors.response.use(
    (response) => response,
    (error) => {
        const url: string = error.config?.url || '';
        const isAuthEndpoint = url.includes('/auth/login') || url.includes('/auth/register');
        if (error.response?.status === 401 && !isAuthEndpoint && window.location.pathname !== '/login') {
            localStorage.removeItem('token');
            window.location.href = '/login';
        }
        return Promise.reject(error);
    }
);

export default apiClient;

// Extracts a human-readable message from an API/axios error without `any`.
export const getApiErrorMessage = (error: unknown, fallback: string): string => {
    if (!axios.isAxiosError(error)) return fallback;
    const data: unknown = error.response?.data;
    if (data && typeof data === 'object' && 'detail' in data) {
        const detail: unknown = data.detail;
        if (typeof detail === 'string') return detail;
        if (Array.isArray(detail) && detail.length > 0) {
            const first: unknown = detail[0];
            if (first && typeof first === 'object' && 'msg' in first && typeof first.msg === 'string') {
                return first.msg;
            }
        }
    }
    return fallback;
};
