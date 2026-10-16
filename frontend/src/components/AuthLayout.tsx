import React from 'react';
import { useI18n } from '../i18n/I18nContext';
import { BrandMark, Card, Wordmark } from './ui';
import { VersionBadge } from './VersionBadge';

/**
 * Frame for the unauthenticated screens: the brand pitch (mark, wordmark and
 * the product description) fills the left column, the credential form the
 * right one. On narrow viewports the pitch collapses to a compact header
 * above the form.
 */
export const AuthLayout: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const { t } = useI18n();

    return (
        <div className="min-h-dvh flex flex-col lg:grid lg:grid-cols-[1.1fr_1fr] sw-ambient">
            <section
                className="sw-brand-panel flex flex-col justify-center gap-8 border-b border-[var(--sw-hairline)]
                    px-6 py-8 lg:border-b-0 lg:border-r lg:px-16 lg:py-16
                    pt-[max(2rem,env(safe-area-inset-top))] pl-[max(1.5rem,env(safe-area-inset-left))] lg:pl-16"
            >
                <div className="flex items-center gap-3 lg:flex-col lg:items-start lg:gap-6">
                    <BrandMark size="lg" className="lg:hidden" />
                    <BrandMark size="xl" className="hidden lg:grid" />
                    <Wordmark className="text-xl sm:text-2xl lg:text-4xl" />
                </div>
                <p className="max-w-md text-sm leading-relaxed text-muted lg:text-base">
                    {t('brand.description')}
                </p>
            </section>

            <section className="flex-1 grid place-items-center p-6 pb-[max(1.5rem,env(safe-area-inset-bottom))] lg:p-14">
                <Card className="w-full max-w-md p-6 sm:p-8 md:p-10 sw-enter">{children}</Card>
            </section>

            {/* No sidebar on these screens, so the release mark floats in the corner. */}
            <VersionBadge className="fixed z-30 left-[max(1rem,env(safe-area-inset-left))] bottom-[max(1rem,env(safe-area-inset-bottom))]" />
        </div>
    );
};
