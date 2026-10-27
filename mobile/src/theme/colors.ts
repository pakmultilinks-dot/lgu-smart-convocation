/** University green, white surfaces and cool neutral backgrounds. */
export const palette = {
  paper: "#F5F7F8",
  ink: "#173C2B",
  muted: "#5F6F66",
  track: "#DDE5E0",
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
  card: "#FFFFFF",
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
