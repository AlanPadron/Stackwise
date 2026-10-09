// frontend/src/pages/Dashboard.tsx
import React, { useEffect, useState } from 'react';
import apiClient from '../api/client';
import { DashboardSummary, Project } from '../types';
import { useNavigate } from 'react-router-dom';
import { AppSidebar } from '../components/AppSidebar';
import { ProjectsTable } from '../components/ProjectsTable';
import { AppShell, Badge, Button, Card, Loader } from '../components/ui';

const Dashboard: React.FC = () => {
    const [summary, setSummary] = useState<DashboardSummary | null>(null);
    const [projects, setProjects] = useState<Project[]>([]);
    const [loading, setLoading] = useState(true);
    const navigate = useNavigate();

    useEffect(() => {
        const fetchData = async () => {
            try {
                const [summaryRes, projectsRes] = await Promise.all([
                    apiClient.get('/dashboard/summary'),
                    apiClient.get('/projects'),
                ]);
                setSummary(summaryRes.data);
                setProjects(projectsRes.data);
            } catch (err) {
                console.error('Failed to fetch dashboard data', err);
            } finally {
                setLoading(false);
            }
        };
        fetchData();
    }, []);

    if (loading) {
        return <Loader fullPage caption="Loading dashboard…" />;
    }

    return (
        <AppShell sidebar={<AppSidebar active="dashboard" />}>
            <header className="flex flex-wrap items-center justify-between gap-4 mb-8 neu-enter">
                <div>
                    <h2 className="text-2xl font-bold tracking-tight">Overview</h2>
                    <p className="text-sm text-muted mt-1">Your analysis activity at a glance</p>
                </div>
                <Button variant="primary" onClick={() => navigate('/projects/new')}>
                    + New Project
                </Button>
            </header>

            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-6 mb-10 neu-stagger">
                <StatCard label="Total Projects" value={summary?.total_projects || 0} />
                <StatCard label="Analyses Run" value={summary?.total_analyses || 0} />
                <StatCard label="Completed" value={summary?.completed_analyses || 0} />
                <StatCard
                    label="Total Findings"
                    value={summary?.total_findings || 0}
                    valueClassName={summary?.total_findings ? 'text-danger' : undefined}
                />
            </div>

            <Card className="overflow-hidden neu-enter">
                <div className="flex items-center justify-between gap-3 px-6 py-5">
                    <h3 className="font-semibold">My Projects</h3>
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
    <Card className="p-6 neu-enter">
        <p className="text-[0.6875rem] font-bold uppercase tracking-[0.06em] text-faint">{label}</p>
        <p className={`text-3xl font-bold mt-2 ${valueClassName ?? ''}`}>{value}</p>
    </Card>
);

export default Dashboard;
