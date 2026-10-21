/**
 * Institutional type system — Phase 35C (Order #3).
 * Bricolage Grotesque 500/800 (display), DM Mono 400/500 (operational
 * labels/values). Type scale ONLY: 11 / 13 / 15 / 24 / 46 / 64–88.
 *
 * 33-QA (P9): the scale above is the law for every new style. Sanctioned
 * exceptions already in the system, each with a documented reason:
 * - fontSize 13 helper tier (Phase 35H) — hints and operational notes.
 * - fontSize 32 heroGate (Home gate label) — QA-pinned in ui-35m (35M R2
 *   item 1, "~32px compact label").
 * - fontSize 72 heroValue (LiveBoard) — inside the 64–88 hero range;
 *   mandated by 33-QA (I8/I10) so the full board fits 360×800.
 * - fontSize 21 passTitle (GuestPass) — 35M item 2 wrap-balance exception
 *   ("Convocation Guest Pass" balances at 360px; 24 orphaned a word).
 * Scanner mode label (ScannerTopBar) was snapped 28 → 24 in this cycle.
 *
 * 35M R2 (item 14 — font loading architecture): Bricolage ships two
 * registered families — `display` (ExtraBold 800) and `displayMedium`
 * (Medium 500); DM Mono ships `mono` (400) and `monoMedium` (500).
 * The FAMILY encodes the weight, and every style applies it with a
 * direct `fontFamily` — React Native `fontWeight` is never used to
 * synthesize or re-select a custom font (a fontWeight RN cannot map to
 * a loaded face is how Android silently fell back to Roboto before).
 */

export const fonts = {
  /** Bricolage Grotesque ExtraBold — titles, headings, major numbers. */
  display: "BricolageGrotesque_800ExtraBold",
  /** Bricolage Grotesque Medium — body copy, secondary emphasis. */
  displayMedium: "BricolageGrotesque_500Medium",
  /** DM Mono Regular — small operational labels, values, timestamps. */
  mono: "DMMono_400Regular",
  /** DM Mono Medium — compact status, emphasized operational values. */
  monoMedium: "DMMono_500Medium",
} as const;

export const fontSize = {
  label: 11,
  /** 13 — helper/explanatory tier (Phase 35H): hints, operational notes. */
  helper: 13,
  body: 15,
  title: 24,
  gate: 46,
  hero: 64,
  heroLg: 88,
  // Legacy keys (pre-35C) — mapped onto the approved scale.
  metric: 64,
  display: 24,
  heading: 24,
  subheading: 15,
  caption: 11,
  small: 11,
} as const;

export const letterSpacing = {
  tight: -0.4,
  normal: 0,
  caps: 0.8,
} as const;

/** Preset text styles — the single source for the institutional type system. */
export const text = {
  /**
   * 11 mono — small operational labels, timestamps.
   * Letter spacing ≈ 0.02em (Phase 35G audit): DM Mono is already a wide
   * face; heavier tracking made 11px labels hard to read at a glance.
   */
  label: {
    fontFamily: fonts.mono,
    fontSize: fontSize.label,
    letterSpacing: 0.2,
  },
  /** 11 mono medium — emphasized labels, compact status. */
  labelMedium: {
    fontFamily: fonts.monoMedium,
    fontSize: fontSize.label,
    letterSpacing: 0.2,
  },
  /** 13 display medium — helper/explanatory text (Phase 35H): field
      hints, operational notes, readable numeric metadata. */
  helper: {
    fontFamily: fonts.displayMedium,
    fontSize: fontSize.helper,
  },
  /** 15 display medium — body copy, sentences. */
  body: {
    fontFamily: fonts.displayMedium,
    fontSize: fontSize.body,
  },
  /** 15 display bold — names, primary row titles. */
  bodyStrong: {
    fontFamily: fonts.display,
    fontSize: fontSize.body,
    letterSpacing: -0.2,
  },
  /** 24 display bold — section headings, state titles. */
  sectionTitle: {
    fontFamily: fonts.display,
    fontSize: fontSize.title,
    letterSpacing: -0.4,
  },
  /** 46 display bold — gate names (hero-adjacent). */
  gateName: {
    fontFamily: fonts.display,
    fontSize: fontSize.gate,
    letterSpacing: -1.2,
  },
  /** 64 display bold — hero numbers (people inside). */
  hero: {
    fontFamily: fonts.display,
    fontSize: fontSize.hero,
    letterSpacing: -2,
  },
  /** 88 display bold — largest hero numbers on spacious surfaces. */
  heroLg: {
    fontFamily: fonts.display,
    fontSize: fontSize.heroLg,
    letterSpacing: -3,
  },
} as const;

export type TextPreset = keyof typeof text;
