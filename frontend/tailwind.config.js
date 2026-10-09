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
        surface: 'var(--neu-surface)',
        raised: 'var(--neu-raised)',
        sunken: 'var(--neu-sunken)',
        hairline: 'var(--neu-hairline)',
        ink: 'var(--neu-text)',
        muted: 'var(--neu-text-muted)',
        faint: 'var(--neu-text-faint)',
        accent: 'var(--neu-accent)',
        danger: 'var(--neu-danger)',
        warning: 'var(--neu-warning)',
        success: 'var(--neu-success)',
        info: 'var(--neu-info)',
      },
      borderRadius: {
        'neu-sm': 'var(--neu-radius-sm)',
        neu: 'var(--neu-radius)',
        'neu-lg': 'var(--neu-radius-lg)',
      },
      boxShadow: {
        'neu-sm': 'var(--neu-shadow-out-sm)',
        neu: 'var(--neu-shadow-out)',
        'neu-lg': 'var(--neu-shadow-out-lg)',
        'neu-in-sm': 'var(--neu-shadow-in-sm)',
        'neu-in': 'var(--neu-shadow-in)',
      },
      transitionDuration: {
        'neu-fast': '140ms',
        neu: '220ms',
        'neu-slow': '400ms',
      },
      transitionTimingFunction: {
        neu: 'cubic-bezier(0.32, 0.72, 0, 1)',
        'neu-out': 'cubic-bezier(0.16, 1, 0.3, 1)',
      },
    },
  },
  plugins: [],
};
