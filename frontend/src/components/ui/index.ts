/**
 * Barrel for the neumorphic primitives.
 *
 * Every component here is a thin, typed wrapper over the `.neu-*` classes in
 * `src/index.css`, so screens never hand-write shadows or colours.
 */
export { Button } from './Button';
export type { ButtonProps, ButtonSize, ButtonVariant } from './Button';
export { Input, Textarea } from './Input';
export type { InputProps, TextareaProps } from './Input';
export { Card, Well } from './Card';
export type { CardProps, WellProps } from './Card';
export { Badge, severityTone, statusTone } from './Badge';
export type { BadgeProps, BadgeTone } from './Badge';
export { Switch } from './Switch';
export type { SwitchProps } from './Switch';
export { Loader } from './Loader';
export type { LoaderProps } from './Loader';
export { AppShell, SidebarBrand, NavItem, SidebarFooter } from './AppShell';
export type { AppShellProps, NavItemProps, SidebarBrandProps } from './AppShell';
