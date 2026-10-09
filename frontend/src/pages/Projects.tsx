// Full project list — the sidebar's "My Projects" destination.
import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import apiClient from '../api/client';
import { Project } from '../types';
import { AppSidebar } from '../components/AppSidebar';
import { ProjectsTable } from '../components/ProjectsTable';
import { AppShell, Badge, Button, Card, Loader } from '../components/ui';

const Projects: React.FC = () => {
    const [projects, setProjects] = useState<Project[]>([]);
    const [loading, setLoading] = useState(true);
    const navigate = useNavigate();

    useEffect(() => {
        const fetchProjects = async () => {
            try {
                const res = await apiClient.get('/projects');
                setProjects(res.data);
            } catch (err) {
                console.error('Failed to fetch projects', err);
            } finally {
                setLoading(false);
            }
        };
        fetchProjects();
    }, []);

    if (loading) return <Loader fullPage caption="Loading projects…" />;

    return (
        <AppShell sidebar={<AppSidebar active="projects" />}>
            <header className="flex flex-wrap items-center justify-between gap-4 mb-8 neu-enter">
                <div>
                    <h2 className="text-2xl font-bold tracking-tight">My Projects</h2>
                    <p className="text-sm text-muted mt-1">
                        Every repository you have set up for analysis
                    </p>
                </div>
                <Button variant="primary" onClick={() => navigate('/projects/new')}>
                    + New Project
                </Button>
            </header>

            <Card className="overflow-hidden neu-enter">
                <div className="flex items-center justify-between gap-3 px-6 py-5">
                    <h3 className="font-semibold">All Projects</h3>
                    <Badge>{projects.length}</Badge>
                </div>
                <ProjectsTable projects={projects} />
            </Card>
        </AppShell>
    );
};

export default Projects;
