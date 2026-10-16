// Axios instance for the Stackwise API: injects the JWT and centralizes 401 handling.
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

/**
 * The human-readable message of a failed API body (FastAPI's `detail`), or the
 * fallback. Shared with the streamed agent call, which uses `fetch` and so never
 * sees an axios error.
 */
export const messageFromBody = (data: unknown, fallback: string): string => {
    if (data && typeof data === 'object' && 'detail' in data) {
        // `in` narrows the property to `unknown`, so it is read and then checked.
        const detail: unknown = data.detail;
        if (typeof detail === 'string') return detail;
        if (Array.isArray(detail) && detail.length > 0) {
            const first: unknown = detail[0];
            if (first && typeof first === 'object' && 'msg' in first && typeof first.msg === 'string') {
                // Pydantic prefixes a validator's own `ValueError` with this, so
                // a refusal from the password policy reads as the sentence it
                // was written as (`Password is too common`).
                return first.msg.replace(/^Value error, /, '');
            }
        }
    }
    return fallback;
};

// Extracts a human-readable message from an API/axios error without `any`.
export const getApiErrorMessage = (error: unknown, fallback: string): string => {
    if (!axios.isAxiosError(error)) return fallback;
    return messageFromBody(error.response?.data, fallback);
};
