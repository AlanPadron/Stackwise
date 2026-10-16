import React from 'react';
import { APP_VERSION } from '../config';
import { cx } from './ui/cx';

/**
 * The release mark. Bottom-left on every screen: inside the sidebar footer when
 * the app is authenticated, fixed to the viewport on the auth screens, so a
 * user always knows which build they are looking at.
 */
export const VersionBadge: React.FC<{ className?: string }> = ({ className }) => (
    <p
        className={cx('sw-mono select-none text-micro tracking-wide text-faint', className)}
        title={`Stackwise ${APP_VERSION}`}
    >
        {APP_VERSION}
    </p>
);
