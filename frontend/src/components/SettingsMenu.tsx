import React, { useEffect, useRef } from 'react';
import { CONTACT_EMAIL, CONTACT_MAILTO } from '../config';
import { useTheme } from '../context/ThemeContext';
import { useFocusTrap } from '../hooks/useFocusTrap';
import { LANGUAGE_LABEL, LANGUAGE_SHORT, LANGUAGES } from '../i18n/dictionary';
import { useI18n } from '../i18n/I18nContext';
import { LinkedAccounts } from './LinkedAccounts';
import { GlobeIcon, MailIcon, MoonIcon, SlidersIcon, SunIcon, Switch } from './ui';
import { cx } from './ui/cx';

interface RowProps {
    icon: React.ReactNode;
    label: string;
    hint?: string;
    trailing?: React.ReactNode;
}

/** One settings line: leading glyph, label/hint, and the control on the right. */
const Row: React.FC<RowProps> = ({ icon, label, hint, trailing }) => (
    <div className="flex items-center gap-3 px-3 py-2.5">
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-sw-sm bg-[var(--sw-accent-soft)] text-accent">
            {icon}
        </span>
        <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-semibold text-ink">{label}</span>
            {hint && <span className="block truncate text-xs text-faint">{hint}</span>}
        </span>
        {trailing}
    </div>
);

interface SettingsMenuProps {
    /** Owned by the app shell so the NIom cluster can step aside while open. */
    open: boolean;
    onOpenChange: (open: boolean) => void;
}

/**
 * Single floating control for the three global preferences — appearance,
 * language and contact — so the chrome stays out of the way of the content.
 */
export const SettingsMenu: React.FC<SettingsMenuProps> = ({ open, onOpenChange }) => {
    const { theme, toggleTheme } = useTheme();
    const { lang, setLang, t } = useI18n();
    const containerRef = useRef<HTMLDivElement>(null);
    const panel = useRef<HTMLDivElement | null>(null);

    // Dismiss on outside click while the drawer is open.
    useEffect(() => {
        if (!open) return;
        const onPointerDown = (event: PointerEvent) => {
            if (!containerRef.current?.contains(event.target as Node)) onOpenChange(false);
        };
        document.addEventListener('pointerdown', onPointerDown);
        return () => {
            document.removeEventListener('pointerdown', onPointerDown);
        };
    }, [open, onOpenChange]);

    // Tab stays inside the open panel and Escape closes it, handing the focus
    // back to the button that opened it.
    useFocusTrap(open, panel, () => onOpenChange(false));

    return (
        <div
            ref={containerRef}
            className="fixed bottom-[calc(5rem+env(safe-area-inset-bottom))] right-[max(1.5rem,env(safe-area-inset-right))] z-40 flex flex-col items-end gap-3"
        >
            {open && (
                <div
                    ref={panel}
                    role="dialog"
                    aria-modal="true"
                    aria-label={t('settings.title')}
                    tabIndex={-1}
                    className="sw-popover w-[min(20rem,calc(100vw-2rem))] p-2 sw-enter-pop sm:w-80"
                >
                    <p className="px-3 pb-2 pt-3 text-xs font-bold uppercase tracking-[0.08em] text-faint sm:text-micro">
                        {t('settings.title')}
                    </p>

                    <Row
                        icon={<MoonIcon size={17} />}
                        label={t('settings.theme')}
                        hint={t('settings.themeHint')}
                        trailing={
                            <Switch
                                checked={theme === 'dark'}
                                onChange={toggleTheme}
                                label={t('settings.theme')}
                                thumbOn={<MoonIcon size={12} />}
                                thumbOff={<SunIcon size={12} />}
                            />
                        }
                    />

                    <Row
                        icon={<GlobeIcon size={17} />}
                        label={t('settings.language')}
                        trailing={
                            <div
                                className="sw-seg"
                                role="group"
                                aria-label={t('settings.language')}
                            >
                                {LANGUAGES.map((code) => (
                                    <button
                                        key={code}
                                        type="button"
                                        lang={code}
                                        title={LANGUAGE_LABEL[code]}
                                        aria-label={LANGUAGE_LABEL[code]}
                                        onClick={() => setLang(code)}
                                        aria-pressed={lang === code}
                                        className={cx(
                                            'sw-seg__btn',
                                            lang === code && 'sw-seg__btn--active'
                                        )}
                                    >
                                        {LANGUAGE_SHORT[code]}
                                    </button>
                                ))}
                            </div>
                        }
                    />

                    <LinkedAccounts />

                    <a
                        href={CONTACT_MAILTO}
                        className="flex items-center gap-3 rounded-sw-sm px-3 py-2.5 no-underline transition-colors hover:bg-[var(--sw-sunken)] focus-visible:outline-none focus-visible:bg-[var(--sw-sunken)]"
                    >
                        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-sw-sm bg-[var(--sw-accent-soft)] text-accent">
                            <MailIcon size={17} />
                        </span>
                        <span className="min-w-0 flex-1">
                            <span className="block truncate text-sm font-semibold text-ink">
                                {t('settings.contact')}
                            </span>
                            <span className="block truncate text-xs text-faint">
                                {CONTACT_EMAIL}
                            </span>
                        </span>
                        <span className="text-faint" aria-hidden="true">
                            ↗
                        </span>
                    </a>
                </div>
            )}

            <button
                type="button"
                onClick={() => onOpenChange(!open)}
                className="sw-fab"
                aria-expanded={open}
                aria-haspopup="dialog"
                aria-label={t('settings.open')}
                title={t('settings.open')}
            >
                <SlidersIcon size={20} />
            </button>
        </div>
    );
};
