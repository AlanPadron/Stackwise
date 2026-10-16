/** App-wide constants that are not part of the visual design system. */

/** Product name; also the accessible name used by the brand mark. */
export const APP_NAME = 'Stackwise';

/**
 * Release tag rendered by the version badge (`components/VersionBadge.tsx`).
 * Keep it in sync with `package.json` and the API's `APP_VERSION` setting — the
 * three are bumped together.
 */
export const APP_VERSION = '1.6.0 alpha';

/**
 * Destination of the "Contact" row in the settings drawer. Replace with the
 * real inbox when it is ready — nothing else in the app needs to change.
 */
export const CONTACT_EMAIL = 'stackwise.contact@gmail.com';

/** Ready-to-use `mailto:` link with a prefilled subject. */
export const CONTACT_MAILTO = `mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent(
    `${APP_NAME} enquiry`
)}`;
