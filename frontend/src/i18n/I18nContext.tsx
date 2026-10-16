// Language state: the active UI language, persisted and applied to <html lang>.
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import {
    dictionary,
    LANGUAGE_LOCALE,
    LANGUAGES,
    Language,
    TranslationKey,
} from './dictionary';

/** Values interpolated into `{placeholder}` slots in a translation. */
export type TranslationParams = Record<string, string | number>;

interface I18nContextValue {
    lang: Language;
    /** BCP-47 tag for locale-aware formatting (dates, numbers). */
    locale: string;
    setLang: (lang: Language) => void;
    /** Resolves a key, interpolating `{name}` slots from `params`. */
    t: (key: TranslationKey, params?: TranslationParams) => string;
}

const STORAGE_KEY = 'stackwise_lang';

const isLanguage = (value: unknown): value is Language =>
    LANGUAGES.includes(value as Language);

const detectInitialLanguage = (): Language => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (isLanguage(stored)) return stored;
    // First visit: follow the browser, defaulting to English.
    return navigator.language?.toLowerCase().startsWith('es') ? 'es' : 'en';
};

const I18nContext = createContext<I18nContextValue | undefined>(undefined);

export const I18nProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const [lang, setLangState] = useState<Language>(detectInitialLanguage);

    useEffect(() => {
        localStorage.setItem(STORAGE_KEY, lang);
        document.documentElement.lang = lang;
    }, [lang]);

    // Keep every open tab in sync when another one changes the language.
    useEffect(() => {
        const onStorage = (e: StorageEvent) => {
            if (e.key === STORAGE_KEY && isLanguage(e.newValue)) setLangState(e.newValue);
        };
        window.addEventListener('storage', onStorage);
        return () => window.removeEventListener('storage', onStorage);
    }, []);

    const t = useCallback(
        (key: TranslationKey, params?: TranslationParams): string => {
            const template: string = dictionary[lang][key] ?? dictionary.en[key] ?? key;
            if (!params) return template;
            return Object.entries(params).reduce(
                (text, [name, value]) => text.split(`{${name}}`).join(String(value)),
                template
            );
        },
        [lang]
    );

    const value = useMemo<I18nContextValue>(
        () => ({ lang, locale: LANGUAGE_LOCALE[lang], setLang: setLangState, t }),
        [lang, t]
    );

    return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
};

export const useI18n = (): I18nContextValue => {
    const context = useContext(I18nContext);
    if (!context) throw new Error('useI18n must be used within I18nProvider');
    return context;
};
