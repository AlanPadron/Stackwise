import React from 'react';
import { APP_NAME } from '../../config';
import { cx } from './cx';

export type BrandMarkSize = 'md' | 'lg' | 'xl';

const SIZE_CLASS: Record<BrandMarkSize, string> = {
    md: '',
    lg: 'sw-mark--lg',
    xl: 'sw-mark--xl',
};

/**
 * The brand tile: the ornamental, manuscript-style "W" on the accent gradient.
 * This is the only place the glyph is defined, so every appearance of the mark
 * — sidebar, splash, auth panel — stays identical.
 */
export const BrandMark: React.FC<{ size?: BrandMarkSize; className?: string }> = ({
    size = 'md',
    className,
}) => (
    <span className={cx('sw-mark', SIZE_CLASS[size], className)} role="img" aria-label={APP_NAME}>
        W
    </span>
);

/**
 * The wordmark. Keeps the name in the UI font but renders the "w" in the
 * ornamental display face, so the brand W is exaggerated wherever the name
 * appears — not only in the tile.
 */
export const Wordmark: React.FC<{ className?: string }> = ({ className }) => (
    <span className={cx('sw-wordmark', className)}>
        Stack<span className="sw-wordmark__w">w</span>ise
    </span>
);
