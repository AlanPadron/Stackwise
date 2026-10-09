import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { NavItem, SidebarBrand, SidebarFooter } from './ui';

export type SidebarSection = 'dashboard' | 'projects';

/**
 * The authenticated navigation chrome. Rendered inside <AppShell>'s `sidebar`
 * slot so every screen shares one definition of the nav.
 */
export const AppSidebar: React.FC<{ active?: SidebarSection }> = ({ active }) => {
    const { logout } = useAuth();
    const navigate = useNavigate();

    return (
        <>
            <SidebarBrand name="Stackwise" href="/dashboard" />
            <nav className="mt-4 flex flex-col gap-1.5" aria-label="Main">
                <NavItem href="/dashboard" active={active === 'dashboard'}>
                    Dashboard
                </NavItem>
                <NavItem href="/projects" active={active === 'projects'}>
                    My Projects
                </NavItem>
            </nav>
            <SidebarFooter>
                <NavItem
                    onClick={() => {
                        logout();
                        navigate('/login');
                    }}
                >
                    Sign Out
                </NavItem>
            </SidebarFooter>
        </>
    );
};
