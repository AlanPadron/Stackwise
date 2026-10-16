// Once-per-session transition screen: entry → hold → dissolve, all finite.
import React, { useState, useEffect } from 'react';
import { BrandMark, Wordmark } from './ui';

/**
 * Full-screen transition splash. Two finite passes: the mark is extruded into
 * place, holds, then the whole layer dissolves away.
 *
 * The dissolve animates opacity only. It used to sweep `blur(24px)` across a
 * full-screen layer, which re-rasterises the entire viewport on every frame of
 * the exit — the one place in the app where the animation, not the theme, was
 * the cost. Fading the same layer reads the same and costs a compositor pass.
 */
const HOLD_MS = 900;
const DISSOLVE_MS = 1250;
const DONE_MS = 1650;

const Splash: React.FC<{ onComplete: () => void }> = ({ onComplete }) => {
    const [status, setStatus] = useState<'entry' | 'hold' | 'exit'>('entry');

    useEffect(() => {
        // 1. Entry animation
        const timer1 = setTimeout(() => setStatus('hold'), 340);
        // 2. Hold then start dissolve
        const timer2 = setTimeout(() => setStatus('exit'), DISSOLVE_MS);
        // 3. Complete transition
        const timer3 = setTimeout(() => onComplete(), DONE_MS);

        return () => {
            clearTimeout(timer1);
            clearTimeout(timer2);
            clearTimeout(timer3);
        };
    }, [onComplete]);

    return (
        <div
            className={`fixed inset-0 z-50 grid place-items-center sw-ambient bg-[var(--sw-bg)]
                transition-opacity duration-sw-slow ease-sw
                ${status === 'exit' ? 'opacity-0 pointer-events-none' : 'opacity-100'}`}
        >
            <div
                className={`flex flex-col items-center gap-6 transition-[opacity,transform] duration-sw-enter ease-sw-out
                    ${status === 'entry' ? 'scale-95 opacity-0' : 'scale-100 opacity-100'}`}
            >
                <BrandMark size="xl" />
                <Wordmark className="text-xl" />
            </div>
        </div>
    );
};

export default Splash;
