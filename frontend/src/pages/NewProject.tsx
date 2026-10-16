// Create-project form; navigates to the new project on success.
import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import apiClient from '../api/client';
import { AppSidebar } from '../components/AppSidebar';
import { useI18n } from '../i18n/I18nContext';
import { AppShell, Button, Card, Input, Textarea } from '../components/ui';

const NewProject: React.FC = () => {
    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
    const [loading, setLoading] = useState(false);
    const { t } = useI18n();
    const navigate = useNavigate();

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setLoading(true);
        try {
            const res = await apiClient.post('/projects', { name, description });
            navigate(`/projects/${res.data.id}`);
        } catch (err) {
            alert(t('newProject.failed'));
        } finally {
            setLoading(false);
        }
    };

    return (
        <AppShell sidebar={<AppSidebar active="projects" />}>
            <div className="max-w-2xl mx-auto sw-enter">
                <header className="mb-8">
                    <h2 className="text-3xl font-bold tracking-tight">{t('newProject.title')}</h2>
                    <p className="text-sm text-muted mt-1">{t('newProject.subtitle')}</p>
                    <Link
                        to="/projects/import"
                        className="mt-3 inline-block text-sm font-semibold text-accent no-underline hover:underline"
                    >
                        {t('newProject.orImport')}
                    </Link>
                </header>

                <Card className="p-6 sm:p-8">
                    <form onSubmit={handleSubmit} className="space-y-6">
                        <Input
                            label={t('newProject.name')}
                            type="text"
                            value={name}
                            onChange={(e) => setName(e.target.value)}
                            placeholder={t('newProject.namePlaceholder')}
                            required
                        />
                        <Textarea
                            label={t('newProject.description')}
                            value={description}
                            onChange={(e) => setDescription(e.target.value)}
                            placeholder={t('newProject.descriptionPlaceholder')}
                        />
                        <div className="flex flex-col gap-3 pt-2 sm:flex-row sm:justify-end">
                            <Button
                                variant="ghost"
                                className="w-full sm:w-auto"
                                onClick={() => navigate('/dashboard')}
                            >
                                {t('newProject.cancel')}
                            </Button>
                            <Button
                                type="submit"
                                variant="primary"
                                className="w-full sm:w-auto"
                                loading={loading}
                            >
                                {loading ? t('newProject.creating') : t('newProject.create')}
                            </Button>
                        </div>
                    </form>
                </Card>
            </div>
        </AppShell>
    );
};

export default NewProject;
