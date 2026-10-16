import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Project } from '../types';
import { useI18n } from '../i18n/I18nContext';
import { Button } from './ui';

/** Project list shared by the Dashboard and the My Projects screen. */
export const ProjectsTable: React.FC<{
    projects: Project[];
    emptyMessage?: string;
}> = ({ projects, emptyMessage }) => {
    const { t, locale } = useI18n();
    const navigate = useNavigate();

    return (
        // The wrapping Card clips (`overflow-hidden`), so the scroll lives here: the
        // table keeps its columns readable and the container scrolls instead of cutting.
        // The header cells inherit 11px from `.sw-table thead th`; the `[&>thead>tr>th]`
        // variant outranks that component selector, so it can raise them to 12px on
        // phones and put them back at `sm` and up.
        <div className="overflow-x-auto">
            <table
                className="sw-table min-w-[32rem]
                    [&>thead>tr>th]:text-xs
                    sm:[&>thead>tr>th]:text-[0.6875rem] sm:[&>thead>tr>th]:leading-normal"
            >
                <caption className="sr-only">{t('nav.projects')}</caption>
                <thead>
                    <tr>
                        <th scope="col">{t('projects.colName')}</th>
                        <th scope="col">{t('projects.colCreated')}</th>
                        <th scope="col" className="text-right">
                            {t('projects.colAction')}
                        </th>
                    </tr>
                </thead>
                <tbody>
                    {projects.length === 0 ? (
                        <tr>
                            <td colSpan={3} className="py-12 text-left text-faint sm:text-center">
                                {emptyMessage ?? t('projects.empty')}
                            </td>
                        </tr>
                    ) : (
                        projects.map((p) => (
                            <tr key={p.id}>
                                <td className="font-medium text-ink">
                                    <span className="block max-w-[24rem] truncate" title={p.name}>
                                        {p.name}
                                    </span>
                                </td>
                                <td className="whitespace-nowrap">
                                    {new Date(p.created_at).toLocaleDateString(locale)}
                                </td>
                                <td className="text-right">
                                    <Button
                                        size="sm"
                                        variant="ghost"
                                        onClick={() => navigate(`/projects/${p.id}`)}
                                    >
                                        {t('projects.viewDetails')}
                                    </Button>
                                </td>
                            </tr>
                        ))
                    )}
                </tbody>
            </table>
        </div>
    );
};
