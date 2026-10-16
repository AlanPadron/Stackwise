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
      /* Durations and easings are the same custom properties `index.css`
         defines, not copies: a change to the token layer must not leave a
         stale number behind in a utility. */
      transitionDuration: {
        'sw-fast': 'var(--sw-t-fast)',
        'sw-hover': 'var(--sw-t-hover)',
        sw: 'var(--sw-t)',
        'sw-enter': 'var(--sw-t-enter)',
        'sw-slow': 'var(--sw-t-slow)',
      },
      transitionTimingFunction: {
        sw: 'var(--sw-ease)',
        'sw-out': 'var(--sw-ease-out)',
        'sw-inout': 'var(--sw-ease-inout)',
        'sw-spring': 'var(--sw-ease-spring)',
      },
      fontFamily: {
        display: ['Cinzel Decorative', 'IM Fell English', 'Georgia', 'serif'],
      },
      fontSize: {
        '2xs': 'var(--sw-text-2xs)',
        micro: 'var(--sw-text-micro)',
      },
    },
  },
  plugins: [],
};
