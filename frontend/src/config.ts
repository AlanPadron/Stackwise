/** App-wide constants that are not part of the visual design system. */

/** Product name; also the accessible name used by the brand mark. */
export const APP_NAME = 'Stackwise';

/**
 * Release tag rendered by the version badge (`components/VersionBadge.tsx`).
 * Keep it in sync with `package.json` and the API's `APP_VERSION` setting — the
 * three are bumped together.
 */
export const APP_VERSION = '1.8.0-alpha';

/**
 * Destination of the "Contact" row in the settings drawer. Replace with the
 * real inbox when it is ready — nothing else in the app needs to change.
 */
export const CONTACT_EMAIL = 'stackwise.contact@gmail.com';

/** Ready-to-use `mailto:` link with a prefilled subject. */
export const CONTACT_MAILTO = `mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent(
    `${APP_NAME} enquiry`
)}`;

/**
 * The one password rule the sign-up form checks before it sends anything.
 *
 * The server owns the policy (`app/core/security.py::password_problem`) and is
 * what actually refuses a weak password — including the blocklist of common
 * ones, which is not worth mirroring here. This mirror exists so the form can
 * answer immediately instead of after a round-trip; the two are kept in step on
 * purpose, like the release tag above.
 */
export const PASSWORD_MIN_LENGTH = 10;

/** Whether the typed password satisfies the mirrored rule. */
export const isPasswordAcceptable = (password: string): boolean =>
    password.length >= PASSWORD_MIN_LENGTH &&
    /[A-Za-z]/.test(password) &&
    /[0-9]/.test(password);
