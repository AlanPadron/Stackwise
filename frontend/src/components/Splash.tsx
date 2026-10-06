// frontend/src/components/Splash.tsx
import React, { useState, useEffect } from 'react';

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
        <div className={`fixed inset-0 z-50 flex items-center justify-center bg-white dark:bg-slate-900 transition-all duration-1000
            ${status === 'exit' ? 'opacity-0 blur-xl pointer-events-none' : 'opacity-100 blur-0'}`}>

            <div className={`transition-all duration-700 transform
                ${status === 'entry' ? 'scale-90 opacity-0 blur-md' : 'scale-100 opacity-100 blur-0'}`}>

                <h1 className="text-8xl font-serif font-bold text-slate-900 dark:text-white tracking-tighter select-none">
                    W
                </h1>
            </div>
        </div>
    );
};

export default Splash;
