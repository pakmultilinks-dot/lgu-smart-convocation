# DESIGN_RESEARCH — Principles extracted (not copied) from actual sources

Per §34: principles extracted from cited sources; no branding copied from Eventbrite/Cvent/others. Sources are established, real publications — cited with what each contributes to THIS product. **Phase 34A re-audit 2026-10-03: all principles re-checked against the shipped Phase 34 code (`f51d0d1`); mapping evidence below is current.**

## 1. NN/g — 10 Usability Heuristics (Nielsen Norman Group, nngroup.com/articles/ten-usability-heuristics)

| Heuristic | Application to LGU Convocation |
|---|---|
| Visibility of system status | Scan result appears ≤100 ms after decode (haptic + text + icon); dashboard shows LIVE/stale/offline + "Updated HH:MM:SS"; Home shows connection state. Every async surface shows its state (§37). |
| Match between system and real world | Gate language = venue language ("Main Gate", "Entry/Exit"), no jargon; "People Inside" not "DB aggregate"; guest = "Guest of <host>". |
| User control and freedom | Exit mode = undo of entry; offline queue = user keeps working when network dies; "Switch back to automatic" on Admin connection. |
| Consistency and uniformity | One status vocabulary (Accepted / Duplicate / Invalid / Exit recorded / Queued offline) across Scanner, Home, Search; one pill system; same tokens everywhere. |
| Error prevention | Duplicate-frame suppression prevents double-scans; exit-before-entry blocked with explanation; gate must be selected (NO GATE SELECTED) instead of silent default. |
| Recognition over recall | Gate + mode always VISIBLE on Scanner (not remembered); last scan result shown on Home; search exists so volunteers never memorize roll numbers. |
| Flexibility and efficiency of use | Test Scan for trained volunteers; search by name OR roll OR QR fragment; offline queue keeps gate moving at full speed. |
| Aesthetic and minimalist design | Home answers 7 volunteer questions and NOTHING else; Live Board = 9 ordered facts; no decorative analytics (§11/§25). |
| Help users recover from errors | Every red result names the person + what happened + what to do next ("already entered at Main Gate, 22:29:12" → verify or use Search); camera failure → Search/manual recovery path. |
| Documentation/help | Concise inline help only where a concept is new (e.g., "Guest passes are single-use"); Admin carries connection guidance. |

## 2. Recognition over recall (Miller, "The Magical Number Seven…" 1956; Norman, The Design of Everyday Things)

Gate identity, entry/exit mode, and last result are DISPLAYED at the moment of action, never held in working memory. Scanner header carries "G1 Main Gate · Entry" persistently. Home repeats the assignment block. Search removes the need to recall roll numbers entirely.

## 3. Feedback loops & status visibility (Norman, Designing for the Real World / action–feedback cycle)

Every action closes a loop visibly: press Scan → camera active; decode → freeze-frame + haptic; server verdict → full-screen result moment (ResultCard pattern, kept); queue → "Queued offline" with count badge; sync flush → per-item outcome list. No silent success. No spinner without a label.

## 4. Visual complexity research (Djajadiningrat et al.; Miniukovich & Sanchéz de Angulo, "Visual Complexity of Graphical User Interfaces", 2015 — empirical finding)

Perceived complexity is driven by **number of distinct visual elements and their irregularity**, not by information density itself. Consequence for this product: Home may carry substantial operational information IF the element count is low and rhythm is regular — large numbered blocks, one accent color, consistent 16/24 spacing. The old UI failed here: many small cards, mixed radii/borders/shadows, random link lists. The rebuild reduces element COUNT per screen to the minimum that answers the screen's purpose.

## 5. Visual aesthetics & the "aesthetic–usability effect" (Kurosu & Kashimura 1995; Tractinsky et al. 2006 — empirically replicated)

Users perceive aesthetically refined interfaces as more usable, but only aesthetics built on **order, harmony, and coherence** survive scrutiny — skeuomorphic decoration and gratuitous effects backfire (Tractinsky's follow-up work). Consequence: premium comes from composition, typographic hierarchy, controlled contrast, meaningful negative space, and brand-consistent color — explicitly NOT from gradients-everywhere, glassmorphism, neon, or bouncing motion (§15). The one gradient allowed in this product (guest pass) is functional — it marks the pass as a distinct object type.

## 6. Material Design 3 (m3.material.io) — operational guidance extracted

- **Color roles, not raw hues**: surfaces, containers, on-colors, and state layers are defined semantically. LGU tokens follow this shape (background/card/on-card/state tints).
- **Elevation as tonal + shadow, low amplitude**: cards read through surface contrast, not borders. (Phase 32 already moved this direction; rebuild keeps borderless tonal cards.)
- **Touch targets ≥48dp**: all primary controls 54–56dp min height (Scan button 56).
- **State layers**: pressed/disabled states are tint-based, not opacity hacks.

## 7. Apple Human Interface Guidelines — operational guidance extracted

- **Content priority over chrome**: large titles carry the screen; chrome recedes.
- **Legibility**: minimum body ~15pt equivalent; labels quiet (muted), values strong (text); numbers get display treatment when they are the point (People Inside).
- **Defer to platform conventions**: system back gestures, safe-area insets, keyboard avoidance — expo-safe-area-context + native behaviors, no custom chrome fighting the OS.

## 8. Event ops products — pattern research only (no branding copied)

- **Eventbrite Organizer**: pattern extracted — organizer home leads with TODAY's event context before anything else (what is running, when, where). Applied: Home leads with Assignment (which gate, entry or exit, event title) before any count.
- **Cvent OnArrival / check-in products**: pattern extracted — check-in tools make the NEXT CHECK-IN the largest element on screen, keep the attendee identity and verdict readable at arm's length, and separate "valid / duplicate / invalid" into unmistakably different moments. Applied: Scanner's result moment is full-contrast, carries icon + title + person + detail, and differs structurally (not just by color) per outcome class; gate throughput products separate ENTRY vs EXIT visually in mode control (segmented, labeled, icon-paired).
- **Both**: pattern extracted — operations screens are DENSE but CALM: strong section headers, no illustration, status always peripheral-visible. Applied to Live Board.

## 9. Expo Camera (SDK 57 docs — docs.expo.dev/versions/v57.0.0/sdk/camera) + INSTALLED typings evidence (verified 2026-10-03)

- `CameraView` + `onBarcodeScanned` with barcode settings `barcodeScannerSettings={{ barcodeTypes: ["qr"] }}`.
- Continuous scanning = keep the callback live; use ref/state debounce (duplicate-frame suppression) instead of toggling the camera.
- `enableTorch`, `zoom` (0–1), barcode `bounds` available for auto-zoom. §21 rule followed: INSTALLED typings in `node_modules/expo-camera` (57.0.5) inspected.
- **Installed CameraView props — used by ScannerScreen**: `facing="back"`, `enableTorch`, `zoom`, `autofocus="off"`, `barcodeScannerSettings`, `onBarcodeScanned`. **Available but NOT used**: `active` (mount/unmount gating), `animateShutter`, `onMountError` (error surface — candidate to add during P-14 split). Auto-zoom bounded 0→ZOOM_MAX 0.45, STEP 0.025, TICK 80ms, FRACTION_COMFORT 0.42, hysteresis via FRAME_DEDUPE 4000ms / QR_LEAVE 1400ms — all constants verified in ScannerScreen today.

## 10. Offline-first mobile patterns (Material offline design guidance; Fielding REST cache semantics)

- Optimistic local persistence first (AsyncStorage queue), network as enhancement.
- Never block the primary action on the network when a local path exists (scanner queues).
- Show honest freshness: "Showing last synchronized data" + when it was last fresh; recovery = Retry that actually re-requests.
- Technical failure detail stays in `__DEV__` logs only — user copy stays human (§27).

## Synthesis → design decisions locked (re-verified against shipped code 2026-10-03; no further questions)

**Status: decisions 1–8 implemented in Phase 34 (`f51d0d1`); residuals tracked as P-18 (navy splash) + P-21 (system font identity, uniform SectionCard rhythm, LguMark 36dp) — targeted polish in Phase 34B, NOT re-litigation.**

1. **Identity**: LGU emerald-forward (#0F5132 family) with restrained gold accents (#B8912A) only for institutional/venue moments (Live Board venue line, guest-pass monogram rules). Background = soft tinted paper (#F6F8F7 family), never pure gray-on-white template feel.
2. **Type**: system font (reliability evidence); deliberate scale — metric 40/32 for operational numbers, 24/20/17 hierarchy, 15 body, 13/11 quiet labels with 1.2 caps tracking for section eyebrows.
3. **Spacing**: 4/8/16/24/32/48 rhythm; radius 8/12/16; elevation soft/raised only; NO decorative borders on cards.
4. **Status system**: every async surface = one of {Loading, Live, Stale, Offline, Empty, Error+Retry} with a shared pill + copy vocabulary; scan outcomes = 5 structural classes (Accepted / Already inside / Invalid / Exit recorded / Queued) with icon + title + text, color as reinforcement only.
5. **Motion**: functional only — result moment fade+rise 160–200 ms, button press scale 0.98, camera freeze-frame; no looping/bouncing/decorative animation.
6. **Imagery**: NO stock/AI photography. Branded abstract treatment = crest + typographic composition on emerald field. convocation-hero.jpg retired (P-04).
7. **Logo**: `lgu-logo.png` 444×444 RGBA (alpha verified) at ≤64dp display sizes; no upscaling claims.
8. **Composition law per screen**: one dominant action or number; supporting facts in ONE regular column rhythm; no card-walls; Home ≠ Dashboard.
