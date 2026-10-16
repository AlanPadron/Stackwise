/**
 * Tailwind is intentionally thin here: raw design tokens live in
 * `src/index.css` (@layer base) and the reusable looks in `@layer components`.
 * This file only exposes those tokens as utilities for one-off tweaks, so a
 * colour/radius/depth change still happens in a single place.
 */
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        surface: 'var(--sw-surface)',
        raised: 'var(--sw-raised)',
        sunken: 'var(--sw-sunken)',
        hairline: 'var(--sw-hairline)',
        ink: 'var(--sw-text)',
        muted: 'var(--sw-text-muted)',
        faint: 'var(--sw-text-faint)',
        accent: 'var(--sw-accent)',
        danger: 'var(--sw-danger)',
        warning: 'var(--sw-warning)',
        success: 'var(--sw-success)',
        info: 'var(--sw-info)',
      },
      borderRadius: {
        'sw-sm': 'var(--sw-radius-sm)',
        sw: 'var(--sw-radius)',
        'sw-lg': 'var(--sw-radius-lg)',
      },
      boxShadow: {
        'sw-sm': 'var(--sw-shadow-out-sm)',
        sw: 'var(--sw-shadow-out)',
        'sw-lg': 'var(--sw-shadow-out-lg)',
        'sw-in-sm': 'var(--sw-shadow-in-sm)',
        'sw-in': 'var(--sw-shadow-in)',
      },
      transitionDuration: {
        'sw-fast': '140ms',
        sw: '220ms',
        'sw-slow': '400ms',
      },
      transitionTimingFunction: {
        sw: 'cubic-bezier(0.32, 0.72, 0, 1)',
        'sw-out': 'cubic-bezier(0.16, 1, 0.3, 1)',
      },
      fontFamily: {
        display: ['Cinzel Decorative', 'IM Fell English', 'Georgia', 'serif'],
      },
    },
  },
  plugins: [],
};
