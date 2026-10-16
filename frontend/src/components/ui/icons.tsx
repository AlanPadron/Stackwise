import React from 'react';

export interface IconProps {
    /** Square size in px; the glyph inherits `currentColor`. */
    size?: number;
    className?: string;
}

const Svg: React.FC<IconProps & { children: React.ReactNode }> = ({
    size = 18,
    className,
    children,
}) => (
    <svg
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.8}
        strokeLinecap="round"
        strokeLinejoin="round"
        className={className}
        aria-hidden="true"
        focusable="false"
    >
        {children}
    </svg>
);

export const DashboardIcon: React.FC<IconProps> = (props) => (
    <Svg {...props}>
        <rect x="3" y="3" width="7" height="7" rx="1.5" />
        <rect x="14" y="3" width="7" height="7" rx="1.5" />
        <rect x="14" y="14" width="7" height="7" rx="1.5" />
        <rect x="3" y="14" width="7" height="7" rx="1.5" />
    </Svg>
);

export const ProjectsIcon: React.FC<IconProps> = (props) => (
    <Svg {...props}>
        <path d="M12 2 2 7l10 5 10-5-10-5Z" />
        <path d="m2 12 10 5 10-5" />
        <path d="m2 17 10 5 10-5" />
    </Svg>
);

export const SignOutIcon: React.FC<IconProps> = (props) => (
    <Svg {...props}>
        <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
        <path d="m16 17 5-5-5-5" />
        <path d="M21 12H9" />
    </Svg>
);

export const SlidersIcon: React.FC<IconProps> = (props) => (
    <Svg {...props}>
        <path d="M21 4h-7M10 4H3" />
        <path d="M21 12h-9M8 12H3" />
        <path d="M21 20h-5M12 20H3" />
        <path d="M14 2v4M8 10v4M16 18v4" />
    </Svg>
);

/** The findings agent: a head with an antenna and two eyes. */
export const RobotIcon: React.FC<IconProps> = (props) => (
    <Svg {...props}>
        <rect x="4" y="8.5" width="16" height="10.5" rx="2.5" />
        <path d="M12 8.5V5.5" />
        <circle cx="12" cy="4.2" r="1.3" />
        <path d="M9.2 12.8v1.6M14.8 12.8v1.6" />
        <path d="M2 12.5v2.5M22 12.5v2.5" />
    </Svg>
);

export const MoonIcon: React.FC<IconProps> = (props) => (
    <Svg {...props}>
        <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />
    </Svg>
);

/** Opens the navigation drawer; paired with CloseIcon in the same button slot. */
export const MenuIcon: React.FC<IconProps> = (props) => (
    <Svg {...props}>
        <path d="M4 7h16M4 12h16M4 17h16" />
    </Svg>
);

export const CloseIcon: React.FC<IconProps> = (props) => (
    <Svg {...props}>
        <path d="M6 6l12 12M18 6L6 18" />
    </Svg>
);

export const SunIcon: React.FC<IconProps> = (props) => (
    <Svg {...props}>
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </Svg>
);

export const GlobeIcon: React.FC<IconProps> = (props) => (
    <Svg {...props}>
        <circle cx="12" cy="12" r="10" />
        <path d="M2 12h20" />
        <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10Z" />
    </Svg>
);

export const MailIcon: React.FC<IconProps> = (props) => (
    <Svg {...props}>
        <rect x="2" y="4" width="20" height="16" rx="2" />
        <path d="m22 7-10 5L2 7" />
    </Svg>
);

/** Shows the mascot is on; paired with EyeOffIcon on the same button. */
export const EyeIcon: React.FC<IconProps> = (props) => (
    <Svg {...props}>
        <path d="M2 12s3.6-6 10-6 10 6 10 6-3.6 6-10 6-10-6-10-6Z" />
        <circle cx="12" cy="12" r="2.6" />
    </Svg>
);

export const EyeOffIcon: React.FC<IconProps> = (props) => (
    <Svg {...props}>
        <path d="M4 5l16 14" />
        <path d="M9.5 6.4A9.6 9.6 0 0 1 12 6c6.4 0 10 6 10 6a17 17 0 0 1-2.6 3.3M6.4 8.2A17 17 0 0 0 2 12s3.6 6 10 6a9.4 9.4 0 0 0 3.4-.6" />
    </Svg>
);

/** Stands in for the development-only mock provider. */
export const TerminalIcon: React.FC<IconProps> = (props) => (
    <Svg {...props}>
        <rect x="2.5" y="4" width="19" height="16" rx="2" />
        <path d="m7 9.5 3 2.5-3 2.5" />
        <path d="M12.5 15H17" />
    </Svg>
);

/**
 * Provider logos are brand marks, not UI glyphs: they carry their own fills
 * (Google's four brand colours) or follow `currentColor` (GitHub), so they are
 * not drawn with the shared stroked wrapper above.
 */

export const GoogleIcon: React.FC<IconProps> = ({ size = 18, className }) => (
    <svg
        width={size}
        height={size}
        viewBox="0 0 24 24"
        className={className}
        aria-hidden="true"
        focusable="false"
    >
        <path
            fill="#4285F4"
            d="M23.49 12.27c0-.79-.07-1.54-.19-2.27H12v4.51h6.47a5.54 5.54 0 0 1-2.4 3.58v3h3.86c2.26-2.09 3.56-5.17 3.56-8.82Z"
        />
        <path
            fill="#34A853"
            d="M12 24c3.24 0 5.95-1.08 7.93-2.91l-3.86-3c-1.08.72-2.45 1.16-4.07 1.16-3.13 0-5.78-2.11-6.73-4.96H1.29v3.09A11.99 11.99 0 0 0 12 24Z"
        />
        <path
            fill="#FBBC05"
            d="M5.27 14.29a7.2 7.2 0 0 1 0-4.58V6.62H1.29a11.99 11.99 0 0 0 0 10.76l3.98-3.09Z"
        />
        <path
            fill="#EA4335"
            d="M12 4.75c1.77 0 3.35.61 4.6 1.8l3.42-3.42C17.95 1.19 15.24 0 12 0 7.7 0 3.99 2.47 1.29 6.62l3.98 3.09C6.22 6.86 8.87 4.75 12 4.75Z"
        />
    </svg>
);

export const GitHubIcon: React.FC<IconProps> = ({ size = 18, className }) => (
    <svg
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill="currentColor"
        className={className}
        aria-hidden="true"
        focusable="false"
    >
        <path d="M12 .5C5.73.5.5 5.73.5 12a11.5 11.5 0 0 0 7.86 10.92c.58.1.79-.25.79-.55v-1.94c-3.2.7-3.88-1.54-3.88-1.54-.52-1.34-1.28-1.7-1.28-1.7-1.05-.72.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.7 1.26 3.36.96.1-.75.4-1.26.73-1.55-2.55-.29-5.24-1.28-5.24-5.7 0-1.26.45-2.29 1.19-3.1-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.18 1.18a11 11 0 0 1 5.79 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.76.11 3.05.74.81 1.19 1.84 1.19 3.1 0 4.43-2.69 5.4-5.25 5.69.41.36.78 1.06.78 2.14v3.17c0 .3.2.66.8.55A11.5 11.5 0 0 0 23.5 12C23.5 5.73 18.27.5 12 .5Z" />
    </svg>
);
