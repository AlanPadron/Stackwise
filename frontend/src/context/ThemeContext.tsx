import React, { createContext, useContext, useState, useEffect } from 'react';

type Theme = 'light' | 'dark';

interface ThemeContextType {
    theme: Theme;
    toggleTheme: () => void;
}

const isTheme = (value: unknown): value is Theme => value === 'light' || value === 'dark';

/**
 * How long `sw-theming` stays on <html>. Mirrors the swap transition in
 * `index.css`: while it is set, every surface crossfades at the same rate, so
 * the screen changes theme in one motion instead of in two.
 */
const THEME_SWAP_MS = 260;

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

/** Start the uniform crossfade described by `html.sw-theming` in `index.css`. */
const beginThemeSwap = () => {
    const root = window.document.documentElement;
    root.classList.add('sw-theming');
    window.setTimeout(() => root.classList.remove('sw-theming'), THEME_SWAP_MS);
};

export const ThemeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const [theme, setTheme] = useState<Theme>(() => {
        const stored = localStorage.getItem('theme');
        return isTheme(stored) ? stored : 'light';
    });

    useEffect(() => {
        const root = window.document.documentElement;
        if (theme === 'dark') {
            root.classList.add('dark');
        } else {
            root.classList.remove('dark');
        }
        localStorage.setItem('theme', theme);
    }, [theme]);

    // Keep every open tab in sync: other tabs receive the storage event when this one writes.
    useEffect(() => {
        const onStorage = (e: StorageEvent) => {
            if (e.key === 'theme' && isTheme(e.newValue)) {
                beginThemeSwap();
                setTheme(e.newValue);
            }
        };
        window.addEventListener('storage', onStorage);
        return () => window.removeEventListener('storage', onStorage);
    }, []);

    const toggleTheme = () => {
        beginThemeSwap();
        setTheme(prev => prev === 'light' ? 'dark' : 'light');
    };

    return (
        <ThemeContext.Provider value={{ theme, toggleTheme }}>
            {children}
        </ThemeContext.Provider>
    );
};

export const useTheme = () => {
    const context = useContext(ThemeContext);
    if (!context) throw new Error('useTheme must be used within ThemeProvider');
    return context;
};
