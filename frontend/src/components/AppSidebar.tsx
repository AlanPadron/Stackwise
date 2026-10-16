import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useI18n } from '../i18n/I18nContext';
import {
    DashboardIcon,
    GitHubIcon,
    NavItem,
    ProjectsIcon,
    SidebarBrand,
    SidebarFooter,
    SignOutIcon,
} from './ui';
import { VersionBadge } from './VersionBadge';

export type SidebarSection = 'dashboard' | 'projects' | 'import';

/**
 * The authenticated navigation chrome. Rendered inside <AppShell>'s `sidebar`
 * slot so every screen shares one definition of the nav.
 */
export const AppSidebar: React.FC<{ active?: SidebarSection }> = ({ active }) => {
    const { logout } = useAuth();
    const { t } = useI18n();
    const navigate = useNavigate();

    return (
        <>
            <SidebarBrand href="/dashboard" />
            <nav className="mt-4 flex flex-col gap-1.5" aria-label={t('nav.main')}>
                <NavItem
                    href="/dashboard"
                    active={active === 'dashboard'}
                    icon={<DashboardIcon />}
                >
                    {t('nav.dashboard')}
                </NavItem>
                <NavItem href="/projects" active={active === 'projects'} icon={<ProjectsIcon />}>
                    {t('nav.projects')}
                </NavItem>
                <NavItem href="/projects/import" active={active === 'import'} icon={<GitHubIcon />}>
                    {t('repos.title')}
                </NavItem>
            </nav>
            <SidebarFooter>
                <NavItem
                    icon={<SignOutIcon />}
                    onClick={() => {
                        logout();
                        navigate('/login');
                    }}
                >
                    {t('nav.signOut')}
                </NavItem>
                {/* Bottom-left of the program: the build the user is looking at. */}
                <VersionBadge className="mt-3 px-3" />
            </SidebarFooter>
        </>
    );
};
