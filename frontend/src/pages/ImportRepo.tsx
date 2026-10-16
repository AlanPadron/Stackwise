// Import a GitHub repository and analyze it in one step.
import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getApiErrorMessage } from '../api/client';
import { fetchAuthorizeUrl, fetchRepositories, importRepository } from '../api/oauth';
import { AppSidebar } from '../components/AppSidebar';
import { useI18n } from '../i18n/I18nContext';
import { AppShell, Badge, Button, Card, GitHubIcon, Input, Loader } from '../components/ui';
import { GitHubRepositoriesResponse, GitHubRepository } from '../types';

const ImportRepo: React.FC = () => {
    const { t, locale } = useI18n();
    const navigate = useNavigate();
    const [state, setState] = useState<GitHubRepositoriesResponse | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [filter, setFilter] = useState('');
    const [connecting, setConnecting] = useState(false);
    const [importing, setImporting] = useState<string | null>(null);

    useEffect(() => {
        fetchRepositories()
            .then(setState)
            .catch((err: unknown) => setError(getApiErrorMessage(err, t('repos.failed'))))
            .finally(() => setLoading(false));
    }, [t]);

    const repositories = useMemo(() => {
        const all = state?.repositories ?? [];
        const needle = filter.trim().toLowerCase();
        if (!needle) return all;
        return all.filter(
            (repo) =>
                repo.full_name.toLowerCase().includes(needle) ||
                (repo.language ?? '').toLowerCase().includes(needle)
        );
    }, [state, filter]);

    const connect = async () => {
        setError('');
        setConnecting(true);
        try {
            // Back to this screen once GitHub has granted access.
            window.location.assign(await fetchAuthorizeUrl('github', '/projects/import'));
        } catch (err: unknown) {
            setError(getApiErrorMessage(err, t('repos.failed')));
            setConnecting(false);
        }
    };

    const importOne = async (repo: GitHubRepository) => {
        setError('');
        setImporting(repo.full_name);
        try {
            const { project } = await importRepository({ repository: repo.full_name });
            navigate(`/projects/${project.id}`);
        } catch (err: unknown) {
            setError(getApiErrorMessage(err, t('repos.importFailed')));
            setImporting(null);
        }
    };

    if (loading) return <Loader fullPage caption={t('repos.loading')} />;

    return (
        <AppShell sidebar={<AppSidebar active="import" />}>
            <header className="mb-8 sw-enter">
                <h2 className="text-2xl font-bold tracking-tight">{t('repos.title')}</h2>
                <p className="text-sm text-muted mt-1">{t('repos.subtitle')}</p>
            </header>

            {error && (
                <p className="sw-hint sw-hint--error mb-6" role="alert">
                    {error}
                </p>
            )}

            {state && !state.connected ? (
                <Card className="max-w-2xl p-8 sw-enter">
                    <span className="grid h-12 w-12 place-items-center rounded-sw-sm bg-[var(--sw-accent-soft)] text-accent">
                        <GitHubIcon size={24} />
                    </span>
                    <h3 className="mt-5 text-lg font-semibold">{t('repos.connectTitle')}</h3>
                    <p className="mt-2 text-sm text-muted">{t('repos.connectBody')}</p>
                    <Button
                        variant="primary"
                        className="mt-6"
                        loading={connecting}
                        onClick={connect}
                    >
                        {t('repos.connect')}
                    </Button>
                    <p className="mt-4 text-xs text-faint">{t('repos.scopeNote')}</p>
                </Card>
            ) : (
                <Card className="overflow-hidden sw-enter">
                    <div className="flex flex-wrap items-center justify-between gap-3 px-6 py-5">
                        <h3 className="font-semibold">
                            {t('repos.connectedAs', { login: state?.login ?? '' })}
                        </h3>
                        <Badge>{t('repos.count', { count: repositories.length })}</Badge>
                    </div>

                    <div className="px-6 pb-4">
                        <Input
                            label={t('repos.search')}
                            type="search"
                            value={filter}
                            onChange={(event) => setFilter(event.target.value)}
                        />
                    </div>

                    <ul className="sw-scroll max-h-[min(28rem,60dvh)] overflow-y-auto border-t border-[var(--sw-hairline)]">
                        {repositories.length === 0 ? (
                            <li className="px-6 py-12 text-center text-sm text-faint">
                                {t('repos.empty')}
                            </li>
                        ) : (
                            repositories.map((repo) => (
                                <li
                                    key={repo.full_name}
                                    className="flex flex-wrap items-center gap-4 border-b border-[var(--sw-hairline)] px-6 py-4 last:border-b-0"
                                >
                                    <div className="min-w-0 flex-1">
                                        <p className="truncate font-medium text-ink">{repo.name}</p>
                                        <p className="truncate text-xs text-faint">
                                            {repo.owner}
                                            {repo.description ? ` · ${repo.description}` : ''}
                                        </p>
                                        <div className="mt-2 flex flex-wrap items-center gap-2">
                                            <Badge tone={repo.private ? 'warning' : 'neutral'}>
                                                {repo.private
                                                    ? t('repos.private')
                                                    : t('repos.public')}
                                            </Badge>
                                            {repo.language && <Badge>{repo.language}</Badge>}
                                            {repo.updated_at && (
                                                <span className="text-xs text-faint">
                                                    {t('repos.updated', {
                                                        date: new Date(
                                                            repo.updated_at
                                                        ).toLocaleDateString(locale),
                                                    })}
                                                </span>
                                            )}
                                        </div>
                                    </div>
                                    <Button
                                        variant="primary"
                                        size="sm"
                                        loading={importing === repo.full_name}
                                        disabled={importing !== null}
                                        onClick={() => importOne(repo)}
                                    >
                                        {importing === repo.full_name
                                            ? t('repos.importing')
                                            : t('repos.import')}
                                    </Button>
                                </li>
                            ))
                        )}
                    </ul>
                </Card>
            )}
        </AppShell>
    );
};

export default ImportRepo;
