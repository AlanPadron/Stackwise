// frontend/src/pages/Dashboard.tsx
import React, { useEffect, useState } from 'react';
import apiClient from '../api/client';
import { DashboardSummary, Project } from '../types';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

const Dashboard: React.FC = () => {
    const [summary, setSummary] = useState<DashboardSummary | null>(null);
    const [projects, setProjects] = useState<Project[]>([]);
    const [loading, setLoading] = useState(true);
    const { logout } = useAuth();
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
        return (
            <div className="flex items-center justify-center min-h-screen bg-slate-50 dark:bg-slate-900">
                <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-indigo-600 dark:border-indigo-400"></div>
            </div>
        );
    }

    return (
        <div className="min-h-screen bg-slate-50 dark:bg-slate-900 flex transition-colors duration-500">
            {/* Sidebar */}
            <aside className="w-64 bg-white dark:bg-slate-800 border-r border-slate-200 dark:border-slate-700 flex flex-col">
                <div className="p-6">
                    <h1 className="text-2xl font-bold text-slate-900 dark:text-white tracking-tight">Stackwise</h1>
                </div>
                <nav className="flex-1 px-4 space-y-1">
                    <a href="/dashboard" className="flex items-center px-4 py-2 text-sm font-medium text-indigo-600 dark:text-indigo-400 bg-indigo-50 dark:bg-slate-700 rounded-sm">
                        Dashboard
                    </a>
                    <a href="/projects" className="flex items-center px-4 py-2 text-sm font-medium text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-sm transition-colors">
                        My Projects
                    </a>
                </nav>
                <div className="p-4 border-t border-slate-200 dark:border-slate-700">
                    <button
                        onClick={() => { logout(); navigate('/login'); }}
                        className="w-full flex items-center px-4 py-2 text-sm font-medium text-slate-600 dark:text-slate-300 hover:bg-red-50 dark:hover:bg-red-900/30 hover:text-red-600 dark:hover:text-red-400 rounded-sm transition-colors"
                    >
                        Sign Out
                    </button>
                </div>
            </aside>

            {/* Main Content */}
            <main className="flex-1 p-8 overflow-y-auto">
                <header className="flex justify-between items-center mb-8">
                    <h2 className="text-2xl font-bold text-slate-900 dark:text-white">Overview</h2>
                    <button
                        onClick={() => navigate('/projects/new')}
                        className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-semibold rounded-sm transition-colors shadow-sm"
                    >
                        + New Project
                    </button>
                </header>

                {/* Stats Grid */}
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-10">
                    <StatCard label="Total Projects" value={summary?.total_projects || 0} />
                    <StatCard label="Analyses Run" value={summary?.total_analyses || 0} />
                    <StatCard label="Completed" value={summary?.completed_analyses || 0} />
                    <StatCard label="Total Findings" value={summary?.total_findings || 0} color="text-red-600 dark:text-red-400" />
                </div>

                {/* Recent Projects */}
                <div className="bg-white dark:bg-slate-800 rounded-md border border-slate-200 dark:border-slate-700 shadow-sm overflow-hidden">
                    <div className="px-6 py-4 border-b border-slate-200 dark:border-slate-700">
                        <h3 className="font-semibold text-slate-800 dark:text-slate-100">My Projects</h3>
                    </div>
                    <table className="w-full text-left text-sm">
                        <thead className="bg-slate-50 dark:bg-slate-900/40 text-slate-500 dark:text-slate-400 font-medium">
                            <tr>
                                <th className="px-6 py-3">Project Name</th>
                                <th className="px-6 py-3">Created</th>
                                <th className="px-6 py-3 text-right">Action</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-100 dark:divide-slate-700">
                            {projects.length === 0 ? (
                                <tr>
                                    <td colSpan={3} className="px-6 py-10 text-center text-slate-400 dark:text-slate-500">
                                        No projects found. Start by creating one!
                                    </td>
                                </tr>
                            ) : (
                                projects.map(p => (
                                    <tr key={p.id} className="hover:bg-slate-50 dark:hover:bg-slate-700/50 transition-colors">
                                        <td className="px-6 py-4 font-medium text-slate-900 dark:text-white">{p.name}</td>
                                        <td className="px-6 py-4 text-slate-500 dark:text-slate-400">{new Date(p.created_at).toLocaleDateString()}</td>
                                        <td className="px-6 py-4 text-right">
                                            <button
                                                onClick={() => navigate(`/projects/${p.id}`)}
                                                className="text-indigo-600 dark:text-indigo-400 hover:text-indigo-800 dark:hover:text-indigo-300 font-medium"
                                            >
                                                View Details
                                            </button>
                                        </td>
                                    </tr>
                                ))
                            )}
                        </tbody>
                    </table>
                </div>
            </main>
        </div>
    );
};

const StatCard = ({ label, value, color = "text-slate-900 dark:text-white" }: { label: string, value: number, color?: string }) => (
    <div className="bg-white dark:bg-slate-800 p-6 rounded-md border border-slate-200 dark:border-slate-700 shadow-sm">
        <p className="text-sm font-medium text-slate-500 dark:text-slate-400 mb-1">{label}</p>
        <p className={`text-3xl font-bold ${color}`}>{value}</p>
    </div>
);

export default Dashboard;
