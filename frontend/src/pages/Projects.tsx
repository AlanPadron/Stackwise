// Full project list — the sidebar's "My Projects" destination.
import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import apiClient from '../api/client';
import { Project } from '../types';
import { AppSidebar } from '../components/AppSidebar';
import { ErrorState } from '../components/ErrorState';
import { ProjectsTable } from '../components/ProjectsTable';
import { useI18n } from '../i18n/I18nContext';
import { AppShell, Badge, Button, Card, Loader } from '../components/ui';

const Projects: React.FC = () => {
    const [projects, setProjects] = useState<Project[]>([]);
    const [loading, setLoading] = useState(true);
    const [failed, setFailed] = useState(false);
    const { t } = useI18n();
    const navigate = useNavigate();

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const res = await apiClient.get('/projects');
            setProjects(res.data);
            setFailed(false);
        } catch (err) {
            // A failed read is not an empty list: saying "you have no projects"
            // here would be a claim about the user's data that we cannot make.
            console.error('Failed to fetch projects', err);
            setFailed(true);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        void load();
    }, [load]);

    if (loading) return <Loader fullPage caption={t('projects.loading')} />;

    return (
        <AppShell sidebar={<AppSidebar active="projects" />}>
            <header className="flex flex-wrap items-center justify-between gap-4 mb-8 sw-enter">
                <div>
                    <h2 className="text-2xl font-bold tracking-tight">{t('projects.title')}</h2>
                    <p className="text-sm text-muted mt-1">{t('projects.subtitle')}</p>
                </div>
                <div className="flex flex-wrap items-center gap-3">
                    <Button onClick={() => navigate('/projects/import')}>
                        {t('repos.title')}
                    </Button>
                </div>
            </header>

            {failed ? (
                <ErrorState message={t('projects.loadFailed')} onRetry={() => void load()} />
            ) : (
                <Card className="overflow-hidden sw-enter">
                    <div className="flex items-center justify-between gap-3 px-6 py-5">
                        <h3 className="font-semibold">{t('projects.allProjects')}</h3>
                        <Badge>{projects.length}</Badge>
                    </div>
                    <ProjectsTable projects={projects} />
                </Card>
            )}
        </AppShell>
    );
};

export default Projects;
