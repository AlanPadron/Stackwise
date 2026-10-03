// frontend/src/pages/ProjectDetail.tsx
import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import apiClient from '../api/client';
import { Project, AnalysisRun, Finding } from '../types';

const ProjectDetail: React.FC = () => {
    const { id } = useParams();
    const navigate = useNavigate();
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
            const res = await apiClient.post(`/projects/${id}/analyses`, formData, {
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

    if (loading) return <div className="min-h-screen flex items-center justify-center bg-slate-50">Loading...</div>;
    if (!project) return <div className="min-h-screen flex items-center justify-center bg-slate-50">Project not found</div>;

    return (
        <div className="min-h-screen bg-slate-50 flex">
            <aside className="w-64 bg-white border-r border-slate-200 flex flex-col">
                <div className="p-6">
                    <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Stackwise</h1>
                </div>
                <nav className="flex-1 px-4 space-y-1">
                    <a href="/dashboard" className="flex items-center px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 rounded-sm transition-colors">
                        Dashboard
                    </a>
                </nav>
                <div className="p-4 border-t border-slate-200">
                    <button onClick={() => window.location.href = '/dashboard'} className="w-full text-left px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 rounded-sm transition-colors">
                        Back to Home
                    </button>
                </div>
            </aside>

            <main className="flex-1 p-8 overflow-y-auto">
                <header className="flex justify-between items-center mb-8">
                    <div>
                        <h2 className="text-3xl font-bold text-slate-900">{project.name}</h2>
                        <p className="text-slate-500">{project.description || 'No description provided'}</p>
                    </div>
                    <form onSubmit={handleUpload} className="flex gap-2">
                        <input type="file" name="file" accept=".zip" className="hidden" id="zip-upload" />
                        <label htmlFor="zip-upload" className="cursor-pointer px-4 py-2 bg-white border border-slate-300 text-slate-700 text-sm font-medium rounded-sm hover:bg-slate-50 transition-colors">
                            Select ZIP
                        </label>
                        <button
                            type="submit"
                            disabled={uploading}
                            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-semibold rounded-sm transition-colors disabled:opacity-50"
                        >
                            {uploading ? 'Analyzing...' : 'Run Analysis'}
                        </button>
                    </form>
                </header>

                <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
                    {/* Analysis History */}
                    <div className="lg:col-span-1 space-y-4">
                        <h3 className="text-lg font-semibold text-slate-800 mb-4">Analysis History</h3>
                        {analyses.length === 0 ? (
                            <p className="text-sm text-slate-400 italic">No analyses performed yet.</p>
                        ) : (
                            analyses.map(run => (
                                <div
                                    key={run.id}
                                    onClick={() => loadFindings(run)}
                                    className={`p-4 rounded-sm border cursor-pointer transition-all ${selectedRun?.id === run.id ? 'bg-indigo-50 border-indigo-300 shadow-sm' : 'bg-white border-slate-200 hover:border-indigo-200'}`}
                                >
                                    <div className="flex justify-between items-center mb-2">
                                        <span className={`text-xs font-bold uppercase px-2 py-1 rounded ${
                                            run.status === 'completed' ? 'bg-green-100 text-green-700' :
                                            run.status === 'failed' ? 'bg-red-100 text-red-700' : 'bg-slate-100 text-slate-700'
                                        }`}>
                                            {run.status}
                                        </span>
                                        <span className="text-xs text-slate-400">{new Date(run.created_at).toLocaleDateString()}</span>
                                    </div>
                                    <p className="text-sm font-medium text-slate-700">Run {run.id.slice(0, 8)}</p>
                                    {run.summary && (
                                        <p className="text-xs text-slate-500 mt-1">Findings: {run.summary.total_findings}</p>
                                    )}
                                </div>
                            ))
                        )}
                    </div>

                    {/* Findings View */}
                    <div className="lg:col-span-2">
                        {!selectedRun ? (
                            <div className="h-full flex flex-col items-center justify-center text-center p-10 border-2 border-dashed border-slate-200 rounded-md bg-white">
                                <p className="text-slate-400 mb-2">Select an analysis run from the history to view results</p>
                            </div>
                        ) : (
                            <div className="space-y-6">
                                <div className="flex justify-between items-center">
                                    <h3 className="text-xl font-bold text-slate-900">Findings for {selectedRun.id.slice(0, 8)}</h3>
                                    <div className="flex gap-3">
                                        {Object.entries(selectedRun.summary?.severity_counts || {}).map(([sev, count]) => (
                                            <span key={sev} className="text-xs font-medium px-2 py-1 rounded-full bg-slate-100 text-slate-600 capitalize">
                                                {sev}: {count}
                                            </span>
                                        ))}
                                    </div>
                                </div>

                                <div className="space-y-4">
                                    {findings.length === 0 ? (
                                        <div className="p-10 text-center bg-white rounded-md border border-slate-200">
                                            <p className="text-slate-500">No findings detected! Your code is clean ✨</p>
                                        </div>
                                    ) : (
                                        findings.map(f => (
                                            <div key={f.id} className="bg-white p-5 rounded-md border border-slate-200 shadow-sm hover:border-indigo-200 transition-colors">
                                                <div className="flex justify-between items-start mb-3">
                                                    <div className="flex gap-2 items-center">
                                                        <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-full ${
                                                            f.severity === 'high' ? 'bg-red-100 text-red-700' :
                                                            f.severity === 'medium' ? 'bg-amber-100 text-amber-700' : 'bg-blue-100 text-blue-700'
                                                        }`}>
                                                            {f.severity}
                                                        </span>
                                                        <span className="text-[10px] font-bold uppercase px-2 py-0.5 rounded-full bg-slate-100 text-slate-600">
                                                            {f.tool}
                                                        </span>
                                                    </div>
                                                    <span className="text-xs font-mono text-slate-400">{f.rule_id}</span>
                                                </div>
                                                <h4 className="font-semibold text-slate-900 mb-1">{f.title}</h4>
                                                <p className="text-sm text-slate-600 mb-3">{f.message}</p>
                                                <div className="flex items-center gap-2 text-xs font-mono text-slate-400 bg-slate-50 p-2 rounded-sm border border-slate-100">
                                                    <span className="text-slate-300">File:</span> {f.file_path}
                                                    <span className="text-slate-300 ml-2">Line:</span> {f.line_start || 'N/A'}
                                                </div>
                                            </div>
                                        ))
                                    )}
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            </main>
        </div>
    );
};

export default ProjectDetail;
