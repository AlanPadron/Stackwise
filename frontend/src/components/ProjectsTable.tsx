import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Project } from '../types';
import { Button } from './ui';

/** Project list shared by the Dashboard and the My Projects screen. */
export const ProjectsTable: React.FC<{
    projects: Project[];
    emptyMessage?: string;
}> = ({ projects, emptyMessage = 'No projects found. Start by creating one!' }) => {
    const navigate = useNavigate();

    return (
        <table className="neu-table">
            <thead>
                <tr>
                    <th>Project Name</th>
                    <th>Created</th>
                    <th className="text-right">Action</th>
                </tr>
            </thead>
            <tbody>
                {projects.length === 0 ? (
                    <tr>
                        <td colSpan={3} className="py-12 text-center text-faint">
                            {emptyMessage}
                        </td>
                    </tr>
                ) : (
                    projects.map((p) => (
                        <tr key={p.id}>
                            <td className="font-medium text-ink">{p.name}</td>
                            <td>{new Date(p.created_at).toLocaleDateString()}</td>
                            <td className="text-right">
                                <Button
                                    size="sm"
                                    variant="ghost"
                                    onClick={() => navigate(`/projects/${p.id}`)}
                                >
                                    View Details
                                </Button>
                            </td>
                        </tr>
                    ))
                )}
            </tbody>
        </table>
    );
};
