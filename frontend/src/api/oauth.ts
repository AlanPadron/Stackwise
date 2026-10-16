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

/** One provider identity attached to the signed-in account (no token, ever). */
export interface LinkedAccount {
    provider: OAuthProvider | string;
    login: string | null;
    email: string | null;
    created_at: string | null;
}

export const fetchProviders = async (): Promise<ProviderAvailability> =>
    (await apiClient.get('/auth/providers')).data;

/** The provider identities this account can sign in with. */
export const fetchLinkedAccounts = async (): Promise<LinkedAccount[]> =>
    (await apiClient.get('/auth/oauth/links')).data;

/**
 * Detach a provider identity. The API refuses (409) when it is the account's
 * only way in, and that refusal is what the caller shows.
 */
export const unlinkProvider = async (provider: OAuthProvider): Promise<void> => {
    await apiClient.delete(`/auth/oauth/links/${provider}`);
};

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
