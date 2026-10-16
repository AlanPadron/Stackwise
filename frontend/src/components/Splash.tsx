// Once-per-session transition screen: entry → hold → dissolve, all finite.
import React, { useState, useEffect } from 'react';
import { BrandMark, Wordmark } from './ui';

/**
 * Full-screen transition splash. Two finite passes: the mark is extruded into
 * place, holds, then the whole layer dissolves away.
 */
const Splash: React.FC<{ onComplete: () => void }> = ({ onComplete }) => {
    const [status, setStatus] = useState<'entry' | 'hold' | 'exit'>('entry');

    useEffect(() => {
        // 1. Entry animation
        const timer1 = setTimeout(() => setStatus('hold'), 800);
        // 2. Hold then start dissolve
        const timer2 = setTimeout(() => setStatus('exit'), 1500);
        // 3. Complete transition
        const timer3 = setTimeout(() => onComplete(), 2500);

        return () => {
            clearTimeout(timer1);
            clearTimeout(timer2);
            clearTimeout(timer3);
        };
    }, [onComplete]);

    return (
        <div
            className={`fixed inset-0 z-50 grid place-items-center sw-ambient bg-[var(--sw-bg)]
                transition-all duration-700 ease-sw
                ${status === 'exit' ? 'opacity-0 blur-xl pointer-events-none' : 'opacity-100 blur-0'}`}
        >
            <div
                className={`flex flex-col items-center gap-6 transition-all duration-700 ease-sw-out
                    ${status === 'entry' ? 'scale-90 opacity-0' : 'scale-100 opacity-100'}`}
            >
                <BrandMark size="xl" />
                <Wordmark className="text-xl" />
            </div>
        </div>
    );
};

export default Splash;
