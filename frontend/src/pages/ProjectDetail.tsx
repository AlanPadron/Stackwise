// One project: ZIP upload, analysis history, and the findings of the selected run.
import React, { useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import apiClient from '../api/client';
import { Project, AnalysisRun, Finding } from '../types';
import { AppSidebar } from '../components/AppSidebar';
import { useI18n } from '../i18n/I18nContext';
import { cx } from '../components/ui/cx';
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
    const fileInputRef = useRef<HTMLInputElement>(null);
    const { t, locale } = useI18n();

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
            alert(t('project.uploadFailed'));
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

    if (loading) return <Loader fullPage caption={t('project.loading')} />;
    if (!project) return <Loader fullPage caption={t('project.notFound')} />;

    return (
        <AppShell sidebar={<AppSidebar active="projects" />}>
            <header className="flex flex-wrap items-start justify-between gap-4 mb-8 sw-enter">
                <div className="min-w-0">
                    <h2 className="text-3xl font-bold tracking-tight break-words">{project.name}</h2>
                    <p className="text-sm text-muted mt-1">
                        {project.description || t('project.noDescription')}
                    </p>
                </div>
                <form onSubmit={handleUpload} className="flex flex-wrap items-center gap-3">
                    <input
                        ref={fileInputRef}
                        type="file"
                        name="file"
                        accept=".zip"
                        className="hidden"
                        tabIndex={-1}
                        aria-hidden="true"
                    />
                    <Button onClick={() => fileInputRef.current?.click()}>
                        {t('project.selectZip')}
                    </Button>
                    <Button type="submit" variant="primary" loading={uploading}>
                        {t('project.runAnalysis')}
                    </Button>
                </form>
            </header>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
                {/* Analysis History */}
                <section className="min-w-0 lg:col-span-1">
                    <h3 className="text-lg font-semibold mb-4">{t('project.history')}</h3>
                    {analyses.length === 0 ? (
                        <Well className="p-6 text-sm text-faint italic">
                            {t('project.noAnalyses')}
                        </Well>
                    ) : (
                        <div className="space-y-3 sw-stagger">
                            {analyses.map((run) => (
                                // A real button, not a clickable card: picking a
                                // run is an action, and a `div` with `onClick`
                                // cannot be reached or triggered by keyboard.
                                <button
                                    key={run.id}
                                    type="button"
                                    onClick={() => loadFindings(run)}
                                    aria-pressed={selectedRun?.id === run.id}
                                    className={cx(
                                        'sw-card sw-card--interactive sw-enter w-full p-4 text-left',
                                        selectedRun?.id === run.id && 'sw-card--active'
                                    )}
                                >
                                    <div className="flex flex-wrap items-center justify-between gap-3 mb-2">
                                        <div className="flex flex-wrap items-center gap-2">
                                            <Badge tone={statusTone(run.status)}>{run.status}</Badge>
                                            <Badge tone={run.source_type === 'github' ? 'accent' : 'neutral'}>
                                                {run.source_type === 'github'
                                                    ? t('project.sourceGitHub')
                                                    : t('project.sourceZip')}
                                            </Badge>
                                        </div>
                                        <span className="text-xs text-faint">
                                            {new Date(run.created_at).toLocaleDateString(locale)}
                                        </span>
                                    </div>
                                    <p className="text-sm font-semibold">
                                        {t('project.run')} {run.id.slice(0, 8)}
                                    </p>
                                    {run.summary && (
                                        <p className="text-xs text-muted mt-1">
                                            {t('project.findingsCount', {
                                                count: run.summary.total_findings,
                                            })}
                                        </p>
                                    )}
                                </button>
                            ))}
                        </div>
                    )}
                </section>

                {/* Findings View */}
                <section className="min-w-0 lg:col-span-2">
                    {!selectedRun ? (
                        <Well className="h-full min-h-[12rem] max-h-[70dvh] lg:max-h-none grid place-items-center p-10 text-center rounded-sw">
                            <p className="text-sm text-faint">{t('project.selectRun')}</p>
                        </Well>
                    ) : (
                        <div className="space-y-6">
                            <div className="flex flex-wrap items-center justify-between gap-3">
                                <h3 className="text-xl font-bold">
                                    {t('project.findingsFor', { id: selectedRun.id.slice(0, 8) })}
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

                            <div className="sw-stagger space-y-4 overflow-x-auto lg:overflow-x-visible">
                                {findings.length === 0 ? (
                                    <Card className="p-10 text-center sw-enter">
                                        <p className="text-sm text-muted">
                                            {t('project.noFindings')}
                                        </p>
                                    </Card>
                                ) : (
                                    findings.map((f) => (
                                        <Card key={f.id} className="p-5 sw-enter">
                                            <div className="flex items-start justify-between gap-3 mb-3">
                                                <div className="flex flex-wrap items-center gap-2">
                                                    <Badge tone={severityTone(f.severity)}>
                                                        {f.severity}
                                                    </Badge>
                                                    <Badge>{f.tool}</Badge>
                                                </div>
                                                <span className="sw-mono text-xs text-faint shrink-0">
                                                    {f.rule_id}
                                                </span>
                                            </div>
                                            <h4 className="font-semibold mb-1">{f.title}</h4>
                                            <p className="text-sm text-muted mb-3">{f.message}</p>
                                            <Well className="flex flex-wrap items-center gap-x-3 gap-y-1 p-3 text-xs text-muted sw-mono">
                                                <span className="text-faint">{t('project.file')}</span>
                                                <span className="break-all">{f.file_path}</span>
                                                <span className="text-faint">{t('project.line')}</span>
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
