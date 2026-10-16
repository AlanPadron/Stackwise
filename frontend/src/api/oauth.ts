// OAuth sign-in and the GitHub repository import.
import apiClient from './client';
import { AnalysisRun, GitHubRepositoriesResponse, Project } from '../types';

/** Which providers this server can offer. `mock` is the dev-only stand-in. */
export interface ProviderAvailability {
    google: boolean;
    github: boolean;
    mock: boolean;
}

export type OAuthProvider = keyof ProviderAvailability;

export const fetchProviders = async (): Promise<ProviderAvailability> =>
    (await apiClient.get('/auth/providers')).data;

/**
 * The provider URL to send the browser to. The bearer token, when present,
 * makes the round-trip *link* the provider account to the signed-in user
 * instead of signing in with it.
 */
export const fetchAuthorizeUrl = async (
    provider: OAuthProvider,
    next?: string
): Promise<string> => {
    const { data } = await apiClient.get(`/auth/oauth/${provider}/authorize`, {
        params: next ? { next } : undefined,
    });
    return data.authorization_url;
};

export const fetchRepositories = async (): Promise<GitHubRepositoriesResponse> =>
    (await apiClient.get('/github/repositories')).data;

export interface ImportRepositoryPayload {
    repository: string;
    ref?: string;
    name?: string;
    description?: string;
}

export interface ImportRepositoryResult {
    project: Project;
    run: AnalysisRun;
}

export const importRepository = async (
    payload: ImportRepositoryPayload
): Promise<ImportRepositoryResult> =>
    (await apiClient.post('/projects/from-repo', payload)).data;
