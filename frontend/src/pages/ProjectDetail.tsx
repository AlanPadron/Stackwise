// frontend/src/pages/ProjectDetail.tsx
import React, { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import apiClient from '../api/client';
import { Project, AnalysisRun, Finding } from '../types';
import { AppSidebar } from '../components/AppSidebar';
import {
    AppShell,
    Badge,
    Button,
    Card,
    Loader,
    Well,
    severityTone,
    statusTone,
} from '../components/ui';

const ProjectDetail: React.FC = () => {
    const { id } = useParams();
    const [project, setProject] = useState<Project | null>(null);
    const [analyses, setAnalyses] = useState<AnalysisRun[]>([]);
    const [selectedRun, setSelectedRun] = useState<AnalysisRun | null>(null);
    const [findings, setFindings] = useState<Finding[]>([]);
    const [uploading, setUploading] = useState(false);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const loadData = async () => {
            try {
                const [projRes, analRes] = await Promise.all([
                    apiClient.get(`/projects/${id}`),
                    apiClient.get(`/projects/${id}/analyses`),
                ]);
                setProject(projRes.data);
                setAnalyses(analRes.data);
            } catch (err) {
                console.error('Error loading project', err);
            } finally {
                setLoading(false);
            }
        };
        loadData();
    }, [id]);

    const handleUpload = async (e: React.FormEvent<HTMLFormElement>) => {
        e.preventDefault();
        const fileInput = (e.target as HTMLFormElement).elements.namedItem('file') as HTMLInputElement;
        if (!fileInput?.files?.[0]) return;

        setUploading(true);
        const formData = new FormData();
        formData.append('file', fileInput.files[0]);

        try {
            await apiClient.post(`/projects/${id}/analyses`, formData, {
                headers: { 'Content-Type': 'multipart/form-data' },
            });
            // Refresh analyses list
            const analRes = await apiClient.get(`/projects/${id}/analyses`);
            setAnalyses(analRes.data);
        } catch (err) {
            alert('Upload failed');
        } finally {
            setUploading(false);
        }
    };

    const loadFindings = async (run: AnalysisRun) => {
        setSelectedRun(run);
        try {
            const res = await apiClient.get(`/analyses/${run.id}/findings`);
            setFindings(res.data);
        } catch (err) {
            console.error('Error loading findings', err);
        }
    };

    if (loading) return <Loader fullPage caption="Loading project…" />;
    if (!project) return <Loader fullPage caption="Project not found" />;

    return (
        <AppShell sidebar={<AppSidebar active="projects" />}>
            <header className="flex flex-wrap items-start justify-between gap-4 mb-8 neu-enter">
                <div className="min-w-0">
                    <h2 className="text-3xl font-bold tracking-tight break-words">{project.name}</h2>
                    <p className="text-sm text-muted mt-1">
                        {project.description || 'No description provided'}
                    </p>
                </div>
                <form onSubmit={handleUpload} className="flex items-center gap-3">
                    <input type="file" name="file" accept=".zip" className="hidden" id="zip-upload" />
                    <label htmlFor="zip-upload" className="neu-btn cursor-pointer">
                        Select ZIP
                    </label>
                    <Button type="submit" variant="primary" loading={uploading}>
                        Run Analysis
                    </Button>
                </form>
            </header>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
                {/* Analysis History */}
                <section className="lg:col-span-1">
                    <h3 className="text-lg font-semibold mb-4">Analysis History</h3>
                    {analyses.length === 0 ? (
                        <Well className="p-6 text-sm text-faint italic">
                            No analyses performed yet.
                        </Well>
                    ) : (
                        <div className="space-y-3 neu-stagger">
                            {analyses.map((run) => (
                                <Card
                                    key={run.id}
                                    interactive
                                    active={selectedRun?.id === run.id}
                                    onClick={() => loadFindings(run)}
                                    className="p-4 neu-enter"
                                >
                                    <div className="flex items-center justify-between gap-3 mb-2">
                                        <Badge tone={statusTone(run.status)}>{run.status}</Badge>
                                        <span className="text-xs text-faint">
                                            {new Date(run.created_at).toLocaleDateString()}
                                        </span>
                                    </div>
                                    <p className="text-sm font-semibold">
                                        Run {run.id.slice(0, 8)}
                                    </p>
                                    {run.summary && (
                                        <p className="text-xs text-muted mt-1">
                                            Findings: {run.summary.total_findings}
                                        </p>
                                    )}
                                </Card>
                            ))}
                        </div>
                    )}
                </section>

                {/* Findings View */}
                <section className="lg:col-span-2">
                    {!selectedRun ? (
                        <Well className="h-full min-h-[16rem] grid place-items-center p-10 text-center rounded-neu">
                            <p className="text-sm text-faint">
                                Select an analysis run from the history to view results
                            </p>
                        </Well>
                    ) : (
                        <div className="space-y-6">
                            <div className="flex flex-wrap items-center justify-between gap-3">
                                <h3 className="text-xl font-bold">
                                    Findings for {selectedRun.id.slice(0, 8)}
                                </h3>
                                <div className="flex flex-wrap gap-2">
                                    {Object.entries(selectedRun.summary?.severity_counts || {}).map(
                                        ([sev, count]) => (
                                            <Badge key={sev} tone={severityTone(sev)}>
                                                {sev}: {count}
                                            </Badge>
                                        )
                                    )}
                                </div>
                            </div>

                            <div className="space-y-4 neu-stagger">
                                {findings.length === 0 ? (
                                    <Card className="p-10 text-center neu-enter">
                                        <p className="text-sm text-muted">
                                            No findings detected! Your code is clean ✨
                                        </p>
                                    </Card>
                                ) : (
                                    findings.map((f) => (
                                        <Card key={f.id} className="p-5 neu-enter">
                                            <div className="flex items-start justify-between gap-3 mb-3">
                                                <div className="flex flex-wrap items-center gap-2">
                                                    <Badge tone={severityTone(f.severity)}>
                                                        {f.severity}
                                                    </Badge>
                                                    <Badge>{f.tool}</Badge>
                                                </div>
                                                <span className="neu-mono text-xs text-faint shrink-0">
                                                    {f.rule_id}
                                                </span>
                                            </div>
                                            <h4 className="font-semibold mb-1">{f.title}</h4>
                                            <p className="text-sm text-muted mb-3">{f.message}</p>
                                            <Well className="flex flex-wrap items-center gap-x-3 gap-y-1 p-3 text-xs text-muted neu-mono">
                                                <span className="text-faint">File</span>
                                                <span className="break-all">{f.file_path}</span>
                                                <span className="text-faint">Line</span>
                                                <span>{f.line_start || 'N/A'}</span>
                                            </Well>
                                        </Card>
                                    ))
                                )}
                            </div>
                        </div>
                    )}
                </section>
            </div>
        </AppShell>
    );
};

export default ProjectDetail;
