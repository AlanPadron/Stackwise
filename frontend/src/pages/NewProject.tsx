// frontend/src/pages/NewProject.tsx
import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import apiClient from '../api/client';

const NewProject: React.FC = () => {
    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
    const [loading, setLoading] = useState(false);
    const navigate = useNavigate();

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setLoading(true);
        try {
            const res = await apiClient.post('/projects', { name, description });
            navigate(`/projects/${res.data.id}`);
        } catch (err) {
            alert('Failed to create project');
        } finally {
            setLoading(false);
        }
    };

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
            </aside>
            <main className="flex-1 p-8">
                <div className="max-w-2xl mx-auto">
                    <header className="mb-8">
                        <h2 className="text-3xl font-bold text-slate-900">Create Project</h2>
                        <p className="text-slate-500">Set up a new repository for analysis</p>
                    </header>
                    <div className="bg-white p-8 rounded-md border border-slate-200 shadow-sm">
                        <form onSubmit={handleSubmit} className="space-y-6">
                            <div>
                                <label className="block text-sm font-medium text-slate-700 mb-1">Project Name</label>
                                <input
                                    type="text"
                                    value={name}
                                    onChange={(e) => setName(e.target.value)}
                                    className="w-full px-4 py-2 border border-slate-300 rounded-sm focus:ring-2 focus:ring-indigo-500 outline-none transition-all"
                                    placeholder="e.g. My Awesome Python App"
                                    required
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-slate-700 mb-1">Description (Optional)</label>
                                <textarea
                                    value={description}
                                    onChange={(e) => setDescription(e.target.value)}
                                    className="w-full px-4 py-2 border border-slate-300 rounded-sm focus:ring-2 focus:ring-indigo-500 outline-none transition-all h-32"
                                    placeholder="What is this project about?"
                                />
                            </div>
                            <div className="flex justify-end gap-3">
                                <button
                                    type="button"
                                    onClick={() => navigate('/dashboard')}
                                    className="px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 rounded-sm transition-colors"
                                >
                                    Cancel
                                </button>
                                <button
                                    type="submit"
                                    disabled={loading}
                                    className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-semibold rounded-sm transition-colors disabled:opacity-50"
                                >
                                    {loading ? 'Creating...' : 'Create Project'}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            </main>
        </div>
    );
};

export default NewProject;
