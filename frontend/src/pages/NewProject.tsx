// Create-project form; navigates to the new project on success.
import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import apiClient from '../api/client';
import { AppSidebar } from '../components/AppSidebar';
import { AppShell, Button, Card, Input, Textarea } from '../components/ui';

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
        <AppShell sidebar={<AppSidebar active="projects" />}>
            <div className="max-w-2xl mx-auto neu-enter">
                <header className="mb-8">
                    <h2 className="text-3xl font-bold tracking-tight">Create Project</h2>
                    <p className="text-sm text-muted mt-1">Set up a new repository for analysis</p>
                </header>

                <Card className="p-8">
                    <form onSubmit={handleSubmit} className="space-y-6">
                        <Input
                            label="Project Name"
                            type="text"
                            value={name}
                            onChange={(e) => setName(e.target.value)}
                            placeholder="e.g. My Awesome Python App"
                            required
                        />
                        <Textarea
                            label="Description (Optional)"
                            value={description}
                            onChange={(e) => setDescription(e.target.value)}
                            placeholder="What is this project about?"
                        />
                        <div className="flex justify-end gap-3 pt-2">
                            <Button variant="ghost" onClick={() => navigate('/dashboard')}>
                                Cancel
                            </Button>
                            <Button type="submit" variant="primary" loading={loading}>
                                {loading ? 'Creating…' : 'Create Project'}
                            </Button>
                        </div>
                    </form>
                </Card>
            </div>
        </AppShell>
    );
};

export default NewProject;
