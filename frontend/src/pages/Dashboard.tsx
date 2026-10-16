// Overview screen: user-level counters plus the project table.
import React, { useCallback, useEffect, useState } from 'react';
import apiClient from '../api/client';
import { DashboardSummary, Project } from '../types';
import { useNavigate } from 'react-router-dom';
import { AppSidebar } from '../components/AppSidebar';
import { ErrorState } from '../components/ErrorState';
import { ProjectsTable } from '../components/ProjectsTable';
import { useI18n } from '../i18n/I18nContext';
import { AppShell, Badge, Button, Card, Loader } from '../components/ui';

const Dashboard: React.FC = () => {
    const [summary, setSummary] = useState<DashboardSummary | null>(null);
    const [projects, setProjects] = useState<Project[]>([]);
    const [loading, setLoading] = useState(true);
    const [failed, setFailed] = useState(false);
    const { t } = useI18n();
    const navigate = useNavigate();

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const [summaryRes, projectsRes] = await Promise.all([
                apiClient.get('/dashboard/summary'),
                apiClient.get('/projects'),
            ]);
            setSummary(summaryRes.data);
            setProjects(projectsRes.data);
            setFailed(false);
        } catch (err) {
            // Zeros and an empty table would look like a real, empty account.
            console.error('Failed to fetch dashboard data', err);
            setFailed(true);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        void load();
    }, [load]);

    if (loading) {
        return <Loader fullPage caption={t('dashboard.loading')} />;
    }

    if (failed) {
        return (
            <AppShell sidebar={<AppSidebar active="dashboard" />}>
                <ErrorState message={t('dashboard.loadFailed')} onRetry={() => void load()} />
            </AppShell>
        );
    }

    return (
        <AppShell sidebar={<AppSidebar active="dashboard" />}>
            <header className="flex flex-wrap items-center justify-between gap-4 mb-8 sw-enter">
                <div>
                    <h2 className="text-2xl font-bold tracking-tight">{t('dashboard.title')}</h2>
                    <p className="text-sm text-muted mt-1">{t('dashboard.subtitle')}</p>
                </div>
                <div className="flex flex-wrap items-center gap-3">
                    <Button onClick={() => navigate('/projects/import')}>
                        {t('repos.title')}
                    </Button>
                </div>
            </header>

            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-6 mb-10 sw-stagger">
                <StatCard label={t('dashboard.statProjects')} value={summary?.total_projects || 0} />
                <StatCard label={t('dashboard.statAnalyses')} value={summary?.total_analyses || 0} />
                <StatCard label={t('dashboard.statCompleted')} value={summary?.completed_analyses || 0} />
                <StatCard
                    label={t('dashboard.statFindings')}
                    value={summary?.total_findings || 0}
                    valueClassName={summary?.total_findings ? 'text-danger' : undefined}
                />
            </div>

            <Card className="overflow-hidden sw-enter">
                <div className="flex items-center justify-between gap-3 px-6 py-5">
                    <h3 className="font-semibold">{t('dashboard.myProjects')}</h3>
                    <Badge>{projects.length}</Badge>
                </div>
                <ProjectsTable projects={projects} />
            </Card>
        </AppShell>
    );
};

const StatCard: React.FC<{
    label: string;
    value: number;
    valueClassName?: string;
}> = ({ label, value, valueClassName }) => (
    <Card className="p-6 sw-enter">
        {/* 11px is unreadable on a phone; `sm` keeps the previous optical size. */}
        <p className="text-xs sm:text-[0.6875rem] sm:leading-normal font-bold uppercase tracking-[0.06em] text-faint">
            {label}
        </p>
        <p className={`sw-num text-3xl font-bold mt-2 ${valueClassName ?? ''}`}>{value}</p>
    </Card>
);

export default Dashboard;
