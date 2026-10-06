import { createContext, useContext } from 'react';

// Lets any screen trigger the full-screen transition splash (e.g. after signing in).
export const SplashContext = createContext<() => void>(() => {});

export const useSplash = () => useContext(SplashContext);
