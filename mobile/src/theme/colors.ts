/**
 * Institutional palette — Phase 35C (Order #3, visual system).
 * Paper + ink dominate (~70/25). Brand green is logo/splash ONLY. Gold is
 * one thin marker per screen. Valid/invalid are scan semantics only.
 * Legacy (pre-35C) names are mapped onto this system so unrewritten files
 * stay on-palette: green surfaces became ink, mint on-dark text became
 * paper, soft fills became track. New code uses the canonical names.
 */
export const palette = {
  paper: "#F6F1E4",
  ink: "#1B1A16",
  muted: "#5C5642",
  track: "#E3DCC6",
  brand: "#14452F",
  gold: "#C9A227",
  // 33-QA (P8-26): the three semantic tokens are darkened so they pass
  // WCAG 4.5:1 BOTH as normal-size text ON paper AND as grounds FOR
  // paper text — they carry 15px button labels (Entry/Exit active,
  // danger buttons, field errors). The previous values sat at
  // 3.81–4.40:1 — below the line for normal text. Values align with the
  // web palette (--green/--red) so both surfaces share one semantic
  // color story; scan semantics (green/red/amber) are unchanged.
  valid: "#177245", // paper-on-valid 5.02:1 (was #1E8A4C = 3.81:1)
  invalid: "#B3261E", // paper-on-invalid 5.69:1 (was #C93A2E = 4.40:1)
  amber: "#7C5A15", // paper-on-amber 5.51:1 (was #9A6B1A = 4.06:1)
};

export const colors = {
  // Canonical names
  ...palette,
  // Surfaces & structure
  background: palette.paper,
  card: palette.paper,
  white: palette.paper,
  text: palette.ink,
  inputBg: palette.paper,
  border: palette.track,
  tint: palette.track,
  overlay: "rgba(27, 26, 22, 0.55)",
  // Legacy aliases (transitional safety net)
  greenDark: palette.ink,
  greenDeep: palette.ink,
  green: palette.ink,
  emerald: palette.valid,
  emeraldSoft: palette.track,
  mint: palette.paper,
  goldSoft: palette.track,
  amberSoft: palette.paper,
  red: palette.invalid,
  redSoft: palette.track,
};

export type ColorName = keyof typeof colors;
