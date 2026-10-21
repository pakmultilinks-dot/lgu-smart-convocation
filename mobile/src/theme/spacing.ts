/**
 * Spacing + radius — Phase 35C (Order #3). Restrained radii: 8 chips,
 * 10 buttons/surfaces (radius.button is the mandated primary-button
 * radius), 14 sheets, pill for status dots/labels only.
 */

export const spacing = {
  xs: 4,
  sm: 8,
  md: 16,
  screen: 20,
  lg: 24,
  xl: 32,
  xxl: 48,
} as const;

export const radius = {
  sm: 8,
  md: 10,
  button: 10,
  lg: 14,
  full: 999,
} as const;

/** Thin structural rules — dividers and underlines. */
export const hairline = {
  thin: 1,
  marker: 2,
} as const;
