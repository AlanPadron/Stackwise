/**
 * The install/connection surface of the PWA: one slim banner at the top of the
 * viewport.
 *
 * Two states, and both are honest about what Stackwise can do:
 *
 * * **offline** — the shell still opens (it is cached), but every screen that
 *   needs data says so, and the banner offers the only useful action: try again.
 *   It deliberately does *not* pretend analyses can run without the backend.
 * * **update waiting** — a new service worker was found and is left waiting
 *   (`registerType: 'prompt'` in `vite.config.ts`). Reloading is the user's
 *   call, so an analysis being watched or a half-filled form is never discarded
 *   underneath them.
 *
 * Nothing is shown when the worker finishes precaching: "ready to work offline"
 * would be a promise this product cannot keep.
 */
import React, { useEffect, useState } from 'react';
import { useRegisterSW } from 'virtual:pwa-register/react';
import { useI18n } from '../i18n/I18nContext';
import { Button } from './ui';
import { cx } from './ui/cx';

/** `navigator.onLine`, kept current by the two events that change it. */
const useOnline = (): boolean => {
    const [online, setOnline] = useState(() => navigator.onLine);

    useEffect(() => {
        const goOnline = () => setOnline(true);
        const goOffline = () => setOnline(false);
        window.addEventListener('online', goOnline);
        window.addEventListener('offline', goOffline);
        return () => {
            window.removeEventListener('online', goOnline);
            window.removeEventListener('offline', goOffline);
        };
    }, []);

    return online;
};

export const PwaStatus: React.FC = () => {
    const { t } = useI18n();
    const online = useOnline();
    const {
        needRefresh: [needRefresh, setNeedRefresh],
        updateServiceWorker,
    } = useRegisterSW();

    const offline = !online;
    const updateWaiting = online && needRefresh;
    if (!offline && !updateWaiting) return null;

    return (
        <div
            className="fixed inset-x-0 top-0 z-40 flex justify-center px-4 pointer-events-none
                pt-[max(0.75rem,env(safe-area-inset-top))]"
            role="status"
            aria-live="polite"
        >
            <div className="sw-card sw-enter pointer-events-auto flex w-full max-w-2xl items-center gap-3 px-4 py-3">
                <span
                    className={cx(
                        'h-2 w-2 shrink-0 rounded-full',
                        offline ? 'bg-[var(--sw-warning)]' : 'bg-[var(--sw-accent)]'
                    )}
                    aria-hidden="true"
                />
                <p className="min-w-0 flex-1 text-sm text-ink">
                    {offline ? t('pwa.offline') : t('pwa.updateReady')}
                </p>

                {offline ? (
                    <Button size="sm" variant="ghost" onClick={() => window.location.reload()}>
                        {t('common.retry')}
                    </Button>
                ) : (
                    <>
                        <Button size="sm" variant="ghost" onClick={() => setNeedRefresh(false)}>
                            {t('pwa.later')}
                        </Button>
                        <Button size="sm" variant="primary" onClick={() => updateServiceWorker(true)}>
                            {t('pwa.update')}
                        </Button>
                    </>
                )}
            </div>
        </div>
    );
};

export default PwaStatus;
