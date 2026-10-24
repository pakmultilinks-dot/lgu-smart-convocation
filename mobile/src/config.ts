// Startup fallbacks ONLY (Phase 35K Part F).
//
// These constants render the landing / mode-picker screens before the first
// /api/config response arrives. Once connected, every operational surface
// (volunteer home, live board, broadcast, admin) consumes the SERVER values
// — convocation_name, university_name, convocation_year, venue and the
// shared limits — so a saved settings change is reflected everywhere
// without touching this file. Do NOT add population or event numbers
// here; the server is the single source of truth (tested by
// scripts/ui-35k-source-test.mjs and data-truth-test.mjs).

export const CONVOCATION_YEAR = 2026;

export const UNIVERSITY_NAME = "Lahore Garrison University";
export const APP_NAME = "LGU Convocation";
export const MOTTO = "Nurturing the Future of Pakistan in an Excellent Environment";

// Official naming, used verbatim everywhere the product names itself:
// full institutional name on landings/about, short form on live surfaces.
export const APP_TITLE_FULL = "Lahore Garrison University Convocation";
export const APP_TITLE_SHORT = "LGU Convocation";

/** Event identifier: "LGU Convocation 2026" (landing fallback). */
export function eventTitle(year: number = CONVOCATION_YEAR): string {
  return `${APP_TITLE_SHORT} ${year}`;
}
