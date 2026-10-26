import { activateKeepAwakeAsync, deactivateKeepAwake } from "expo-keep-awake";
import { router, useFocusEffect } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Pressable, ScrollView, Text, View, useWindowDimensions } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import {
  fetchAppConfig,
  fetchDashboard,
  verifyAdminPin,
  ApiError,
  type AppConfig,
  type DashboardData,
} from "../api/client";
import { clearAppMode } from "../store/appMode";
import { WRONG_PIN } from "../store/adminAccess";
import {
  initialLockState,
  isLocked,
  lockSecondsRemaining,
  registerFailure,
  resetOnSuccess,
  type AdminLockState,
} from "../store/adminLockout";
import { colors, fonts, radius, spacing, text } from "../theme";
import { progressDenominator, safePercentFromPct } from "../utils/progress";
import {
  AppButton,
  AppHeader,
  ErrorState,
  Field,
  OfflineBanner,
  ProgressTrack,
  Screen,
  SectionCard,
  SectionEyebrow,
  StatusPill,
  formatClock,
  formatServerClock,
  freshnessState,
} from "../ui";

/** Default poll cadence (Phase 35F target: roughly 5–10s). Phase 38: the
    server suggests a cadence via poll_interval_ms — every client clamps it
    to [2s, 30s] so a bad config can never flood the backend. */
const REFRESH_MS = 5000;
const clampPollMs = (ms?: number) =>
  Math.min(30000, Math.max(2000, typeof ms === "number" && ms > 0 ? ms : REFRESH_MS));
/** Freshness bands scale with the cadence: stale after three missed
    windows, offline after six. The floors preserve the 35I (L) 15s/30s
    defaults at the 5s cadence — a temporary server failure reads STALE
    first, values stay on screen. */
const staleMsFor = (pollMs: number) => Math.max(15000, pollMs * 3);
const offlineMsFor = (pollMs: number) => Math.max(30000, pollMs * 6);
/** 35I (J): darker bar track for the tinted gate section — plain
    colors.track is nearly invisible on the section background. */
const BOARD_TRACK = "rgba(27, 26, 22, 0.16)";
/** Keep-awake tag — the board stays awake on a projector while presented
    (expo-keep-awake ships inside the installed Expo tree; no new dep). */
const KEEP_AWAKE_TAG = "lgu-liveboard";

/**
 * Live Dashboard — the public event view (spec §25), rebuilt in Phase 35F
 * as a purpose-built live information display. 35I (G) + 35M R3: fixed
 * chrome frame with the board content scrolling vertically inside it —
 * compact at the target 360×800 viewport (footer pinned at the bottom),
 * genuinely scrollable whenever content exceeds the available height.
 * 33-QA (I13): the board-wide tap target is GONE. The Pressable that
 * wrapped the scroll content nested inside the crest's own Pressable
 * (web rendered nested <button>s and errored) and armed the protected
 * exit on any stray tap. ScrollView remains the outermost gesture
 * participant; exit is armed explicitly — crest tap, ~2s crest hold, or
 * the footer Exit control — and the confirmation renders as an overlay
 * that is always visible once armed.
 * Order: LIVE → Students inside
 * (hero on paper) → Male/Female/Guests inside (one compact row) → Gate
 * activity · 15 min (every gate, count beside its bar) → Updated (local
 * 12h time + Synced/Delayed/Offline/Connecting) + the footer Exit
 * control. Exit is explicit (crest tap / ~2s crest hold / footer Exit)
 * and arms deliberate confirmation (spec §25 protected exit); Issue 4 (release
 * blocker): the armed exit reveals a server-verified administrator PIN
 * step — leaving the display is an administrator action, and the
 * verifier + lockout reuse the Phase 35G/35H admin-gate machinery.
 * Counts keep
 * Phase 35A semantics (inside_total = students; guests separate); gate
 * activity keeps the Phase 34B fix (server-side throughput, never lifetime
 * feed).
 */
export function LiveBoardScreen() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [online, setOnline] = useState<boolean | null>(null);
  const [lastOkAt, setLastOkAt] = useState(0);
  const [now, setNow] = useState(0);
  const [exitArmed, setExitArmed] = useState(false);
  // Issue 4 (release blocker): the armed exit now reveals a server-verified
  // PIN step — leaving the display is an administrator action, not a viewer
  // tap. The PIN is checked against /api/admin/verify (the same verifier the
  // admin gate uses) and wrong attempts share the adminLockout rules.
  const [exitStep, setExitStep] = useState<"confirm" | "pin">("confirm");
  const [exitPin, setExitPin] = useState("");
  const [exitPinError, setExitPinError] = useState<string | null>(null);
  const [exitVerifying, setExitVerifying] = useState(false);
  const [exitLock, setExitLock] = useState<AdminLockState>(initialLockState);
  const [exitNow, setExitNow] = useState(() => Date.now());
  const exitLocked = isLocked(exitLock, exitNow);
  // Phase 38: server-suggested poll cadence (clamped) — the interval below
  // restarts when it changes; starts at the default until the first payload.
  const [pollMs, setPollMs] = useState(REFRESH_MS);
  // Server configuration (Phase 35K F/J): event subtitle + gate-activity
  // window come from /api/config — the same source as the backend queries.
  const [cfg, setCfg] = useState<AppConfig | null>(null);
  const inflight = useRef(false);
  const exitTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const { width } = useWindowDimensions();
  const wide = width >= 768;
  /** 35M R2 (item 2): bottom system/nav inset for the pinned footer. */
  const insets = useSafeAreaInsets();

  const load = useCallback(async () => {
    // One request at a time — a slow server must never stack calls.
    if (inflight.current) return;
    inflight.current = true;
    try {
      const result = await fetchDashboard();
      setData(result);
      setError(null);
      setOnline(true);
      setLastOkAt(Date.now());
      setPollMs(clampPollMs(result.poll_interval_ms));
    } catch (e) {
      // Last known values stay on screen; only freshness degrades.
      setOnline(false);
      setError(
        e instanceof Error ? e.message : "The live dashboard is unreachable.",
      );
    } finally {
      inflight.current = false;
    }
  }, []);

  // Config loads once per mount — identity metadata does not change live.
  useEffect(() => {
    void (async () => {
      try {
        setCfg(await fetchAppConfig());
      } catch {
        // Offline board: keep the local fallback subtitle; the window
        // label then renders without the number (never a fabricated one).
      }
    })();
  }, []);

  // Lock countdown while the exit PIN gate is locked (same rules as the
  // admin gate: 3 wrong PINs → 30s); ticks once per second.
  useEffect(() => {
    if (!exitLocked) return;
    const timer = setInterval(() => setExitNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [exitLocked]);

  const armExit = useCallback(() => {
    // Arms the protected-exit confirmation (Phase 35H): a crest tap, a
    // ~2s crest hold (kit crestHoldMs), or the footer Exit control —
    // 33-QA (I13) removed the board-wide tap. The confirmation card
    // itself is the deliberate second step.
    setExitArmed(true);
    setExitStep("confirm");
    setExitPin("");
    setExitPinError(null);
    if (exitTimer.current) clearTimeout(exitTimer.current);
    // The prompt self-dismisses — a viewer who did not mean to arm it
    // simply waits; nothing else on the board reacts.
    exitTimer.current = setTimeout(() => setExitArmed(false), 8000);
  }, []);

  const finishExit = useCallback(() => {
    if (exitTimer.current) clearTimeout(exitTimer.current);
    setExitArmed(false);
    setExitStep("confirm");
    setExitPin("");
    setExitPinError(null);
    void clearAppMode();
    router.replace("/mode-picker");
  }, []);

  const requestExitPin = useCallback(() => {
    // The self-dismiss timer only covers the confirm step — once the PIN
    // field is on screen the operator is deliberately working; a clock
    // must not yank the keyboard away mid-entry.
    if (exitTimer.current) {
      clearTimeout(exitTimer.current);
      exitTimer.current = null;
    }
    setExitStep("pin");
    setExitPin("");
    setExitPinError(null);
  }, []);

  const confirmExitWithPin = useCallback(async () => {
    const candidate = exitPin.trim();
    if (!candidate) {
      setExitPinError("Enter the administrator PIN.");
      return;
    }
    if (exitLocked) return;
    setExitVerifying(true);
    setExitPinError(null);
    try {
      const verified = await verifyAdminPin(candidate);
      if (!verified.ok) {
        // Defensive: a 200 with ok:false is still a wrong PIN.
        throw new ApiError(WRONG_PIN, 401);
      }
      setExitLock(resetOnSuccess());
      finishExit();
    } catch (e) {
      // Wrong PIN (backend 401 / ok:false) counts toward the shared
      // admin lockout rules; network failures never reached the verifier
      // and do NOT count.
      if (e instanceof ApiError && (e.status === 401 || e.status === 400)) {
        setExitLock((prev) => registerFailure(prev, Date.now()));
        setExitNow(Date.now());
        setExitPinError(WRONG_PIN);
      } else {
        setExitPinError(
          e instanceof ApiError
            ? e.message
            : "Could not verify the PIN. Check the connection and try again.",
        );
      }
    } finally {
      setExitVerifying(false);
    }
  }, [exitPin, exitLocked, finishExit]);

  // Live loop while the board is in view: keep-awake on, poll at the
  // server-suggested (clamped) cadence, freshness clock every 1s; every
  // timer (and the keep-awake tag) is released on blur/unmount (Phase 35F
  // Part L). The one-at-a-time guard in load() prevents overlap; the
  // interval simply restarts if the cadence changes (Phase 38).
  useFocusEffect(
    useCallback(() => {
      let active = true;
      void activateKeepAwakeAsync(KEEP_AWAKE_TAG).catch(() => {});
      const tick = () => {
        if (!active) return;
        setNow(Date.now());
        void load();
      };
      tick();
      const poll = setInterval(tick, pollMs);
      const clock = setInterval(() => {
        if (active) setNow(Date.now());
      }, 1000);
      return () => {
        active = false;
        clearInterval(poll);
        clearInterval(clock);
        setExitArmed(false);
        setExitStep("confirm");
        if (exitTimer.current) {
          clearTimeout(exitTimer.current);
          exitTimer.current = null;
        }
        try {
          deactivateKeepAwake(KEEP_AWAKE_TAG);
        } catch {
          // Web / unsupported runtimes have nothing to release.
        }
      };
    }, [load, pollMs]),
  );

  // 35I (L): live → stale → offline without a successful refresh, with
  // bands scaled to the current cadence; the last known values stay on
  // screen throughout. (A board that never loaded shows the dedicated
  // unavailable card instead.)
  const state = freshnessState(
    online,
    lastOkAt,
    now,
    staleMsFor(pollMs),
    offlineMsFor(pollMs),
  );
  const stale = state === "stale";
  const offline = state === "offline";
  const expected = data?.expected_attendance ?? 0;
  const inside = data?.inside_total ?? 0;
  // "Students inside" = students currently inside (backend inside_total is
  // male + female students; guests are counted separately — Phase 35A
  // bug 3, semantics preserved; "Guests inside" is its own clear label).
  // 35I (A): the label reads "Students inside" — the section is a student
  // count; the counting model itself is unchanged. Phase 35K (B): the
  // denominator is the admin target ONLY — no roster fallback; unset (0)
  // renders the explicit "Expected attendance not set" state below.
  const denom = progressDenominator(expected);
  // Gate board + recent-window activity = server-side throughput over the
  // configured window (Phase 34B fix: feed[] is lifetime and is never
  // consumed for a "15 min" label). The backend returns EVERY gate
  // with zero counts included, so all 7 gates always render; bar scale =
  // highest count, and 0/invalid max stays empty (safe math, no full bar).
  const windowMinutes = cfg?.gate_activity_window_minutes;
  const windowLabel =
    typeof windowMinutes === "number"
      ? `Gate activity · ${windowMinutes} min`
      : "Gate activity";
  const gateRows = (data?.throughput ?? []).map((t) => ({
    code: t.gate.code,
    name: t.gate.label,
    count: t.count,
  }));
  const maxGate = gateRows.length ? Math.max(...gateRows.map((g) => g.count)) : 0;
  const entries15 = gateRows.reduce((sum, g) => sum + g.count, 0);

  if (error && !data) {
    // First load failed — the poll loop keeps retrying underneath, so the
    // display simply says so. No controls, no technical detail.
    return (
      <Screen>
        <AppHeader
          title="Live attendance"
          subtitle={cfg?.event.name || "Lahore Garrison University Convocation"}
          right={<StatusPill state="connecting" label="Connecting" />}
        />
        <SectionCard>
          <ErrorState
            title="Live dashboard unavailable"
            body="The display is reconnecting to the convocation server."
          />
        </SectionCard>
      </Screen>
    );
  }

  return (
    // 35I (G) + 35M R3: fixed chrome frame (`Screen scroll={false}`); the
    // board CONTENT scrolls vertically inside it — compact at the target
    // viewport (footer pinned via marginTop auto), genuinely scrollable
    // whenever content exceeds the available height. No fixed viewport:
    // the footer stays reachable after every gate row.
    // 33-QA (I13): no board-wide tap target. A Pressable used to wrap
    // the scroll content — on web it nested inside the crest's own
    // Pressable (nested <button> errors) and any stray tap armed the
    // exit prompt. ScrollView stays the outermost gesture participant;
    // the exit is armed explicitly (crest tap / ~2s crest hold / footer
    // Exit) and the confirmation renders as an always-visible overlay.
    <Screen scroll={false}>
      <ScrollView
        style={styles.boardScroll}
        contentContainerStyle={styles.boardScrollContent}
        // 35M item 3: the indicator is the obvious "more content exists"
        // affordance — on device, a compact board must never hide the
        // fact that gates/footers continue below the fold.
        showsVerticalScrollIndicator={true}
      >
        {/* Wide displays (tablets/projectors): one calm centered column —
            never stretched mobile fragments. Portrait phones: no wrapper.
            33-QA (I13): plain View — the board-wide tap Pressable is gone. */}
        <View style={wide ? [styles.board, styles.boardWide] : styles.board}>
        <AppHeader
          title="Live attendance"
          subtitle={cfg?.event.name || "Lahore Garrison University Convocation"}
          crest
          onCrestPress={armExit}
          onCrestLongPress={armExit}
          crestHoldMs={2000}
          right={
            <StatusPill
              state={state}
              label={
                state === "live"
                  ? "Live"
                  : state === "stale"
                    ? "Delayed"
                    : state === "offline"
                      ? "Offline"
                      : "Connecting"
              }
            />
          }
        />

        {offline || stale ? (
          <OfflineBanner
            title={
              offline
                ? `Offline · showing data from ${formatClock(lastOkAt)}`
                : "Updates delayed — showing last known update"
            }
            body="Reconnecting automatically."
            lastSyncedAt={lastOkAt || null}
          />
        ) : null}

        {/* Students inside — the number sits directly on paper: no block,
            no card, no color field (Phase 35F Part D). 35I (I) set the
            scale exception for this one focal number; 35M item 3 took it
            from 112 to 96; 33-QA (I8/I10) takes it to 72 — at 360×800 the
            96px hero pushed gates 6–7 + the Entries tail + the Updated
            footer below the fold with no visible affordance. 72px stays
            clearly dominant while the full board fits. */}
        {/* QA fix cycle 2: landscape/tablet (wide) uses two calm columns
            — hero + demo on the left, the gate board on the right; the
            footer stays pinned below. Portrait phones: bare wrappers,
            unchanged single column. */}
        <View style={wide ? styles.columns : undefined}>
        <View style={wide ? styles.column : undefined}>
        <View style={styles.hero}>
          <SectionEyebrow>Inside now</SectionEyebrow>
          <Text style={styles.heroValue}>{inside.toLocaleString()}</Text>
          <View style={styles.arrivedRow}>
            <Text style={styles.arrivedLabel}>Arrived</Text>
            {denom > 0 ? (
              <Text style={styles.arrivedValue}>
                {safePercentFromPct(data?.arrival_pct ?? 0)}%
                <Text style={styles.arrivedCaption}>
                  {" "}of {denom.toLocaleString()} expected
                </Text>
              </Text>
            ) : (
              <Text style={styles.arrivedCaption}>
                Expected attendance not set
              </Text>
            )}
          </View>
          <View style={styles.heroTrack}>
            <ProgressTrack value={inside} max={denom} />
          </View>
        </View>

        {/* One compact supporting row — no per-metric cards. Guests stay
            outside "People inside" (Phase 35A counting decision). */}
        <SectionCard>
          <View style={styles.demoRow}>
            <View style={styles.demoCell}>
              <Text style={styles.demoLabel}>Male</Text>
              <Text style={styles.demoValue}>
                {(data?.male ?? 0).toLocaleString()}
              </Text>
            </View>
            <View style={styles.demoCell}>
              <Text style={styles.demoLabel}>Female</Text>
              <Text style={styles.demoValue}>
                {(data?.female ?? 0).toLocaleString()}
              </Text>
            </View>
            <View style={styles.demoCell}>
              <Text style={styles.demoLabel}>Guests inside</Text>
              <Text style={styles.demoValue}>
                {(data?.guests_inside ?? 0).toLocaleString()}
              </Text>
            </View>
          </View>
        </SectionCard>

        {/* Convocation (LGU2) admissions — a SEPARATE cumulative ledger of
            entry-only arrivals. Deliberately not merged into "Inside now"
            (occupancy) so a recorded entry is never conflated with who is
            currently admitted to the grounds. */}
        <SectionCard>
          <SectionEyebrow>Convocation admissions</SectionEyebrow>
          <View style={styles.demoRow}>
            <View style={styles.demoCell}>
              <Text style={styles.demoLabel}>Main ceremony</Text>
              <Text style={styles.demoValue}>
                {(data?.ceremony_admitted ?? 0).toLocaleString()}
              </Text>
            </View>
            <View style={styles.demoCell}>
              <Text style={styles.demoLabel}>Rehearsal</Text>
              <Text style={styles.demoValue}>
                {(data?.rehearsal_admitted ?? 0).toLocaleString()}
              </Text>
            </View>
          </View>
        </SectionCard>
        </View>
        <View style={wide ? styles.column : undefined}>

        {/* Gate board — every gate, stable order (backend id order), full
            names never abbreviated, proportional recent-window activity;
            zero renders an empty track. */}
        <SectionCard tone="tint">
          <SectionEyebrow>{windowLabel}</SectionEyebrow>
          {gateRows.length === 0 ? (
            <Text style={styles.muted}>Waiting for the first gate scans.</Text>
          ) : (
            gateRows.map((g) => (
              // 35J (A): one ~40px row — code + full name + count share
              // the top line; the darker 6px bar sits underneath, full
              // width (count no longer floats at the far screen edge).
              <View key={g.code || g.name} style={styles.gateRow}>
                <View style={styles.gateHeadRow}>
                  <Text style={styles.gateCode}>{g.code}</Text>
                  <Text style={styles.gateName}>{g.name}</Text>
                  <Text style={styles.gateCount}>{g.count}</Text>
                </View>
                <ProgressTrack
                  value={g.count}
                  max={maxGate}
                  height={6}
                  trackColor={BOARD_TRACK}
                />
              </View>
            ))
          )}
          <View style={styles.tailRow}>
            <Text style={styles.tailLabel}>Entries</Text>
            <Text style={styles.tailValue}>
              {entries15.toLocaleString()}
              {/* 33-QA (I17): entries are the server's windowed
                  throughput — the caption must carry the window, never a
                  lifetime reading. Falls back to the old phrase only
                  when the server never sent a window. */}
              <Text style={styles.tailCaption}>
                {typeof windowMinutes === "number"
                  ? ` in the last ${windowMinutes} min`
                  : " across all gates"}
              </Text>
            </Text>
          </View>
        </SectionCard>
        </View>
        </View>

        {/* Subordinate footer — pinned at the bottom (35I G): the real
            server timestamp of the last successful refresh in local 12h
            time, plus the freshness verdict (H). 35M R2 (item 2): the
            footer also clears the Android system/nav inset — bottom
            padding mirrors the (volunteer) tab-bar safe-area pattern
            (Math.max(insets.bottom, 6)) so the row never sits under the
            navigation bar on 360×800 / 390×844 / 412×915 devices. */}
        <View
          style={[
            styles.footerRow,
            { paddingBottom: Math.max(insets.bottom, 6) + spacing.md },
          ]}
        >
          <Text style={styles.footerText}>
            {/* 33-QA (P9): stakeholder footer names the timezone. Server
                timestamps are Asia/Karachi wall clock; formatServerClock
                renders them in the viewer's local 12-hour clock — correct
                on every in-country device (the deployment surface). */}
            Updated{" "}
            {formatServerClock(data?.generated_at)
              ? `${formatServerClock(data?.generated_at)} PKT`
              : "—"}
            {" · "}
            {state === "live"
              ? "Synced"
              : state === "stale"
                ? "Delayed"
                : state === "offline"
                  ? "Offline"
                  : "Connecting"}
          </Text>
          {/* 33-QA (I13): explicit exit — crest tap/hold or this control
              arm the protected exit (the board-wide tap is gone). */}
          <Pressable
            onPress={armExit}
            accessibilityRole="button"
            accessibilityLabel="Exit live dashboard"
            hitSlop={8}
            style={styles.footerExit}
          >
            <Text style={styles.footerExitText}>Leave display</Text>
          </Pressable>
        </View>

        </View>
      </ScrollView>
      {/* 33-QA (I13): the armed exit renders as an absolute overlay —
          always visible regardless of scroll position (it used to append
          at the end of the scroll content, often below the fold). The
          board dims behind it; both steps (confirm + PIN) and every
          Issue 4 rule are unchanged — only the placement changed. */}
      {exitArmed ? (
        <View style={styles.exitOverlay}>
          <View style={styles.exitOverlayInner}>
            <View style={styles.dialogCard}>
              {exitStep === "pin" ? (
                <>
                  <Text style={styles.confirmTitle}>Enter admin PIN</Text>
                  <Text style={styles.confirmBody}>
                    Leaving the display requires the administrator PIN.
                  </Text>
                  {exitLocked ? (
                    <Text style={styles.confirmBody}>
                      {`Too many attempts. Try again in ${lockSecondsRemaining(exitLock, exitNow)}s.`}
                    </Text>
                  ) : null}
                  <Field
                    label="Administrator PIN"
                    placeholder="Enter the PIN"
                    value={exitPin}
                    onChangeText={(t) => {
                      setExitPin(t);
                      setExitPinError(null);
                    }}
                    secureTextEntry
                    keyboardType="numeric"
                    autoComplete="off"
                    autoCapitalize="none"
                    error={exitPinError}
                    returnKeyType="done"
                    onSubmitEditing={() => void confirmExitWithPin()}
                  />
                  <View style={styles.confirmActions}>
                    <AppButton
                      label="Cancel"
                      variant="ghost"
                      onPress={() => {
                        setExitStep("confirm");
                        setExitPin("");
                        setExitPinError(null);
                      }}
                      style={styles.confirmBtn}
                    />
                    <AppButton
                      label="Leave display"
                      variant="danger"
                      loading={exitVerifying}
                      disabled={exitLocked}
                      onPress={() => void confirmExitWithPin()}
                      style={styles.confirmBtn}
                    />
                  </View>
                </>
              ) : (
                <>
                  <Text style={styles.confirmTitle}>Leave the display?</Text>
                  <Text style={styles.confirmBody}>
                    The dashboard will return to the mode picker.
                  </Text>
                  <View style={styles.confirmActions}>
                    <AppButton
                      label="Stay"
                      variant="ghost"
                      onPress={() => {
                        if (exitTimer.current) clearTimeout(exitTimer.current);
                        setExitArmed(false);
                      }}
                      style={styles.confirmBtn}
                    />
                    <AppButton
                      label="Leave display"
                      variant="danger"
                      onPress={requestExitPin}
                      style={styles.confirmBtn}
                    />
                  </View>
                </>
              )}
            </View>
          </View>
        </View>
      ) : null}
    </Screen>
  );
}

const styles = {
  board: {
    gap: spacing.md,
    flex: 1,
  },
  // 35M R3: genuine vertical scrolling for the board content — a bounded
  // flex container (never a fixed viewport) with a growing content
  // container: compact layout with the footer pinned via marginTop auto
  // when content fits; scrolls to reach the footer when it does not.
  boardScroll: {
    flex: 1,
  },
  boardScrollContent: {
    flexGrow: 1,
  },
  boardWide: {
    width: "100%" as const,
    maxWidth: 1120,
    alignSelf: "center" as const,
  },
  columns: {
    // QA fix cycle 2 (fit): landscape/tablet — supporting stats and the
    // gate board share the row; each column stacks its own sections.
    flexDirection: "row" as const,
    gap: spacing.lg,
    alignItems: "flex-start" as const,
  },
  column: {
    gap: spacing.md,
    flex: 1,
    minWidth: 0,
  },
  hero: {
    // 35I (G) fit: tight stack — the 96px value leads the board; gaps
    // stay on scale but small so 7 gate rows + footer fit the target
    // viewport (scroll is the fallback when exceeded — 35M R3).
    gap: 2,
  },
  heroValue: {
    ...text.hero,
    // 35I (I) mandated the live-display scale exception; 35M item 3
    // from 112 to 96; 33-QA (I8/I10) took it to 72; QA fix cycle 2 (fit)
    // takes it to 64 — extra headroom so 7 gates + Entries + footer stay
    // above the fold on compact devices; still clearly the focal number.
    fontSize: 64,
    lineHeight: 58,
    letterSpacing: -1.5,
    color: colors.ink,
  },
  arrivedRow: {
    flexDirection: "row" as const,
    alignItems: "baseline" as const,
    gap: spacing.sm,
    marginTop: 2,
  },
  arrivedLabel: {
    // 35I (K): sans 13 helper — not technical mono 11.
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.muted,
  },
  arrivedValue: {
    ...text.sectionTitle,
    color: colors.ink,
  },
  arrivedCaption: {
    ...text.helper,
    color: colors.muted,
  },
  heroTrack: {
    marginTop: 2,
  },
  demoRow: {
    flexDirection: "row" as const,
    gap: spacing.md,
  },
  demoCell: {
    flex: 1,
    // 33-QA (I7): long labels must not inflate the cell past its
    // siblings (Yoga automatic minimum sizing) and clip/shift the row.
    minWidth: 0,
    gap: 2,
  },
  demoLabel: {
    // 35I (K): sans 13 helper.
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.muted,
  },
  demoValue: {
    ...text.sectionTitle,
    color: colors.ink,
  },
  muted: {
    ...text.helper,
    color: colors.muted,
    marginTop: spacing.sm,
  },
  gateRow: {
    // 35J (A): ~40px rows — name line + 6px bar underneath; all gates
    // + the pinned footer fit the target viewport — the board scrolls
    // when exceeded (35M R3). 35M item 3: denser rows so all 7 gates
    // stay practically reachable at the tested Android viewport.
    gap: 3,
    marginTop: 2,
  },
  gateHeadRow: {
    flexDirection: "row" as const,
    alignItems: "baseline" as const,
    gap: spacing.sm,
  },
  gateCode: {
    // 35I (K): sans 13 helper.
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.muted,
    width: 28,
  },
  gateName: {
    fontFamily: fonts.displayMedium,
    fontSize: 15,
    color: colors.ink,
    flex: 1,
    // 33-QA (I7): long gate names wrap/shrink inside the row instead
    // of pushing the count (Yoga automatic minimum sizing).
    minWidth: 0,
  },
  gateCount: {
    // 35J (A): the count shares the name's line, left of the row end —
    // never at the far screen edge beside the bar. 35M R2 (item 14):
    // bold request on the 500 family fell back to Roboto — the count now
    // uses the loaded 800 family directly.
    fontFamily: fonts.display,
    fontSize: 15,
    color: colors.ink,
    minWidth: 32,
    textAlign: "right" as const,
  },
  tailRow: {
    flexDirection: "row" as const,
    alignItems: "baseline" as const,
    gap: spacing.sm,
    // 35M item 3: tighter tail so the last gate + footer stay in reach.
    marginTop: 8,
  },
  tailLabel: {
    // 35I (K): sans 13 helper.
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.muted,
  },
  tailValue: {
    ...text.sectionTitle,
    color: colors.ink,
  },
  tailCaption: {
    ...text.helper,
    color: colors.muted,
  },
  footerRow: {
    // 35I (G): auto top margin pins the footer to the board's bottom edge.
    // 33-QA (I13): row layout — the freshness line shares the footer with
    // the explicit Exit control (no more board-wide tap to arm exit).
    marginTop: "auto" as const,
    paddingTop: spacing.sm,
    paddingBottom: spacing.xs,
    borderTopWidth: 1,
    borderTopColor: colors.track,
    flexDirection: "row" as const,
    alignItems: "center" as const,
    justifyContent: "space-between" as const,
    gap: spacing.sm,
  },
  footerText: {
    ...text.helper,
    color: colors.muted,
    flex: 1,
  },
  footerExit: {
    // Explicit exit affordance (33-QA I13): a compact, high-contrast
    // row target; hitSlop keeps the touch area honest on device.
    minHeight: 44,
    flexDirection: "row" as const,
    alignItems: "center" as const,
    gap: spacing.xs,
    paddingHorizontal: spacing.sm,
  },
  footerExitText: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.ink,
    textDecorationLine: "underline" as const,
  },
  exitOverlay: {
    // 33-QA (I13): absolute overlay over the board — the armed exit is
    // always visible, never appended below the fold of the scroll area.
    position: "absolute" as const,
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    backgroundColor: "rgba(11, 18, 16, 0.6)",
    justifyContent: "center" as const,
    alignItems: "center" as const,
    paddingHorizontal: spacing.screen,
  },
  exitOverlayInner: {
    width: "100%" as const,
    maxWidth: 420,
  },
  dialogCard: {
    // QA fix cycle 2 (dialogs): opaque paper card — never a transparent
    // tint over the dimmed board.
    backgroundColor: colors.paper,
    borderColor: colors.track,
    borderRadius: radius.lg,
    borderWidth: 1,
    padding: spacing.lg,
    gap: spacing.sm,
  },
  confirmTitle: {
    fontFamily: fonts.displayMedium,
    fontSize: 15,
    color: colors.ink,
  },
  confirmBody: {
    ...text.helper,
    color: colors.muted,
  },
  confirmActions: {
    flexDirection: "row" as const,
    gap: spacing.sm,
    marginTop: spacing.xs,
  },
  confirmBtn: {
    flex: 1,
  },
};
