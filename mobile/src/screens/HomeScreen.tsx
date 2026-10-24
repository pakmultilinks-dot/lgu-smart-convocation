import { Ionicons } from "@expo/vector-icons";
import { router, useFocusEffect } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Pressable, Text, View } from "react-native";
import {
  fetchAppConfig,
  fetchDashboardSummary,
  fetchGates,
  type AppConfig,
  type DashboardData,
  type Gate,
} from "../api/client";
import { CONVOCATION_YEAR, UNIVERSITY_NAME } from "../config";
import { needsScanModeConfirmation } from "../store/appMode";
import {
  getLastScanResult,
  getScanMode,
  getSelectedGate,
  setScanMode as persistScanMode,
  setSelectedGate,
  type OpsScanResult,
  type ScanMode,
} from "../store/ops";
import { queueCount } from "../store/offlineQueue";
import { getApiBaseUrl } from "../store/settings";
import { colors, fonts, radius, spacing } from "../theme";
import {
  AppButton,
  AppHeader,
  MetricBlock,
  OfflineBanner,
  ProgressTrack,
  Screen,
  SectionCard,
  SectionEyebrow,
  SegmentedControl,
  StatusPill,
  formatClock,
} from "../ui";
import { ScannerSheet } from "../scanner/ScannerSheet";

/**
 * Volunteer Home — Screen 1 of the institutional system (Phase 35C).
 * Order: seal + Convocation 2026 + sync pill → assignment row (Main Gate ·
 * Entry + Change) with Entry/Exit → Scan QR Code (35I D: the primary action
 * sits right under the gate row, not below every informational section) →
 * Students inside on paper + demographic line → gate board
 * (all gates, tinted selected row, one ink marker) → last scan + queue.
 * 33-QA (I19): no Find attendee button here — attendee lookup lives on
 * the Search tab in the bottom bar; Home never duplicated it.
 * Gate selection reuses the EXISTING ScannerSheet flow — never navigates
 * to the Scanner to pick a gate. Fetches ONLY the summary (audit P-03).
 */
export function HomeScreen() {
  const [gateId, setGateId] = useState<number | null>(null);
  const [gateLabel, setGateLabel] = useState<string | null>(null);
  const [scanMode, setScanMode] = useState<ScanMode>("entry");
  const [lastScan, setLastScan] = useState<OpsScanResult | null>(null);
  const [queued, setQueued] = useState(0);
  const [summary, setSummary] = useState<DashboardData | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [backendConfigured, setBackendConfigured] = useState<boolean | null>(null);
  const [online, setOnline] = useState<boolean | null>(null);
  const [lastOkAt, setLastOkAt] = useState<number>(0);
  const [gates, setGates] = useState<Gate[]>([]);
  const [gatesError, setGatesError] = useState<string | null>(null);
  const [sheetVisible, setSheetVisible] = useState(false);
  // Server configuration (Phase 35K F/J): event identity + gate-activity
  // window come from /api/config; the src/config.ts values remain as
  // startup fallbacks only (before the first successful load).
  const [cfg, setCfg] = useState<AppConfig | null>(null);

  // State updates only after await — keeps the effect below lint-safe.
  // Phase 38: one request at a time — the mount load and the focus refetch
  // must never stack a second in-flight summary call.
  const inflight = useRef(false);
  const refresh = useCallback(async () => {
    if (inflight.current) return;
    inflight.current = true;
    try {
      setSummary(await fetchDashboardSummary());
      setSummaryError(null);
      setOnline(true);
      setLastOkAt(Date.now());
    } catch (e) {
      setOnline(false);
      // Never present previously loaded live figures as current after failure.
      setSummary(null);
      setSummaryError(
        e instanceof Error ? e.message : "The event summary could not be loaded.",
      );
    } finally {
      inflight.current = false;
    }
  }, []);

  const loadGates = useCallback(async () => {
    try {
      setGates(await fetchGates());
      setGatesError(null);
    } catch (e) {
      setGatesError(e instanceof Error ? e.message : "Gates could not be loaded.");
    }
  }, []);

  useEffect(() => {
    void (async () => {
      await Promise.all([refresh(), loadGates()]);
      try {
        setCfg(await fetchAppConfig());
      } catch {
        // Offline: keep the isolated startup fallbacks — never fabricate.
      }
    })();
  }, [refresh, loadGates]);

  // Assignment, last scan, queue state and the summary refetch every time
  // Home is shown (Phase 38: the summary join keeps the board fresh on
  // return without any polling loop — the inflight guard prevents overlap).
  useFocusEffect(
    useCallback(() => {
      let cancelled = false;
      void refresh();
      void loadGates();
      void getApiBaseUrl().then((url) => {
        if (!cancelled) setBackendConfigured(url.length > 0);
      });
      void (async () => {
        const [gate, mode, last, q] = await Promise.all([
          getSelectedGate(),
          getScanMode(),
          getLastScanResult(),
          queueCount(),
        ]);
        if (cancelled) return;
        setGateId(gate?.id ?? null);
        setGateLabel(gate?.label ?? null);
        setScanMode(mode);
        setLastScan(last);
        setQueued(q);
      })();
      return () => {
        cancelled = true;
      };
    }, [refresh, loadGates]),
  );

  const expected = summary?.expected_attendance ?? 0;
  const inside = summary?.inside_total ?? 0;
  const loaded = summary !== null;
  const throughput = summary?.throughput ?? [];
  const countFor = (label: string) =>
    throughput.find((t) => t.gate.label === label)?.count ?? 0;
  const maxGate = throughput.length
    ? Math.max(...throughput.map((t) => t.count))
    : 0;
  // 35I (B): a red result is invalid — shown in invalid red with a concrete
  // "what · where · when" line (actual gate + actual recorded time).
  const invalidScan =
    lastScan !== null &&
    lastScan.level === "red" &&
    /INVALID|UNKNOWN/i.test(lastScan.title);

  // Gate-activity window (Phase 35K J): the eyebrow label and the
  // accessibility text use the same server value as the backend queries.
  const windowMinutes = cfg?.gate_activity_window_minutes;
  const windowLabel =
    typeof windowMinutes === "number"
      ? `Gate activity · ${windowMinutes} min`
      : "Gate activity";
  const windowA11y =
    typeof windowMinutes === "number"
      ? `entries in the last ${windowMinutes} minutes`
      : "recent entries";

  // Queue copy (Phase 35K M): "All scans synced" is only claimed when the
  // last server call succeeded — offline we say scans are waiting to sync.
  const queueCopy =
    queued > 0
      ? `${queued} scan(s) waiting to sync`
      : online === false
        ? "No scans waiting to sync"
        : "All scans synced";

  const handleSelectGate = useCallback((gate: Gate) => {
    void setSelectedGate({ id: gate.id, label: gate.label });
    setGateId(gate.id);
    setGateLabel(gate.label);
    setSheetVisible(false);
  }, []);

  // Phase 28 (concern 2): a direction change is confirmed by the shared
  // fail-closed rule instead of being committed on the tap. Re-tapping the
  // direction already in use is not a change and confirms nothing. The
  // pending request lives only in state — nothing is written to storage
  // until the operator confirms, and dismissing the prompt leaves the
  // current direction (and its persisted value) untouched.
  const [pendingMode, setPendingMode] = useState<ScanMode | null>(null);

  const handleModeChange = useCallback((mode: ScanMode) => {
    if (!needsScanModeConfirmation(scanMode, mode)) return;
    setPendingMode(mode);
  }, [scanMode]);

  const confirmModeChange = useCallback((mode: ScanMode) => {
    setScanMode(mode);
    setPendingMode(null);
    void persistScanMode(mode);
  }, []);

  const cancelModeChange = useCallback(() => setPendingMode(null), []);

  return (
    <Screen>
      {/* 0 — Institutional header: seal, event, sync state. Not a card.
          35M R2 item 12: the eyebrow renders in sans (displayMedium), not
          DM Mono — Home is the only screen that opts in via eyebrowSans. */}
      <AppHeader
        eyebrow="Volunteer Operations"
        eyebrowSans
        // 35M item 2: 20pt keeps a long configured title balanced.
        titleSize={20}
        title={`Convocation ${cfg?.event.year || CONVOCATION_YEAR}`}
        subtitle={cfg?.university || UNIVERSITY_NAME}
        crest
        right={
          <StatusPill
            state={online === false ? "offline" : online ? "live" : "connecting"}
            label={online === false ? "Offline" : online ? "Live" : "Connecting"}
            size="sm"
          />
        }
      />

      {online === false || queued > 0 ? (
        <OfflineBanner
          lastSyncedAt={lastOkAt || null}
          onRetry={() => void refresh()}
          title={backendConfigured === false ? "Server not connected" : "Server offline"}
          body={
            backendConfigured === false
              ? "Connect to the server to load gates and sign in."
              : queued > 0
                ? "Pending scans stay on this device until you reconnect and sync."
                : "Live attendance and gate data are unavailable."
          }
        />
      ) : null}
      {backendConfigured === false ? (
        <AppButton
          label="Connect to server"
          variant="secondary"
          icon="cloud-outline"
          onPress={() => router.push("/connect-server")}
        />
      ) : null}

      {/* 1 — Assignment + mode (35M R2 item 1): the gate label is a
          compact single-line chip at 32px with the small Change action on
          the same row (no mode suffix — the toggle below carries Entry/
          Exit). The Entry/Exit SegmentedControl sits BELOW the label. */}
      {gateLabel ? (
        <View style={styles.hero}>
          <View style={styles.heroGateRow}>
            <Text style={styles.heroGate} numberOfLines={1} ellipsizeMode="clip">
              {gateLabel}
            </Text>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Change gate or direction"
              onPress={() => setSheetVisible(true)}
              hitSlop={8}
              style={({ pressed }) => [styles.changeAction, pressed && styles.pressed]}
            >
              <Text style={styles.changeActionText}>Change</Text>
            </Pressable>
          </View>
          <SegmentedControl<ScanMode>
            options={[
              { label: "Entry", value: "entry" },
              { label: "Exit", value: "exit" },
            ]}
            value={scanMode}
            onChange={handleModeChange}
            // QA fix cycle 4 (Finding 2): same semantic accents as the
            // scanner top bar — Entry green, Exit amber.
            activeColor={scanMode === "exit" ? colors.amber : colors.valid}
          />
          {/* Phase 28 (concern 2): switching Entry/Exit is confirmed before
              it is applied. Nothing is persisted until the operator confirms
              — the prompt names the direction being entered so a volunteer
              cannot silently flip the device from admitting to releasing
              guests. Cancelling leaves the current direction in place. */}
          {pendingMode !== null ? (
            <View style={styles.confirmBox}>
              <Text style={styles.confirmText}>
                {`Switch to ${pendingMode === "exit" ? "Exit" : "Entry"} mode? This device will record ${
                  pendingMode === "exit" ? "exits" : "entries"
                } until you change it back.`}
              </Text>
              <View style={styles.confirmActions}>
                <AppButton
                  label="Cancel"
                  variant="ghost"
                  onPress={cancelModeChange}
                />
                <AppButton
                  label={`Switch to ${pendingMode === "exit" ? "Exit" : "Entry"}`}
                  onPress={() => {
                    if (pendingMode !== null) confirmModeChange(pendingMode);
                  }}
                />
              </View>
            </View>
          ) : null}
        </View>
      ) : (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Choose your gate"
          onPress={() => setSheetVisible(true)}
          style={({ pressed }) => [styles.chooseRow, pressed && styles.pressed]}
        >
          <Ionicons name="location-outline" size={18} color={colors.muted} />
          <Text style={styles.chooseText}>Choose your gate</Text>
          <Ionicons name="chevron-forward" size={18} color={colors.muted} />
        </Pressable>
      )}

      {/* 1b — The primary action, right under the gate row (35I D): the
          volunteer reaches Scan QR Code without scrolling past sections.
          QA fix cycle 2 (gate source of truth): disabled until a gate is
          chosen — the "Choose your gate" row above is the direction. */}
      <AppButton
        label="Scan QR Code"
        icon="qr-code"
        size="lg"
        disabled={gateId === null}
        onPress={() => router.push("/(volunteer)/scanner")}
      />
      {/* QA fix cycle 4 (Finding 11): a disabled primary action always
          states WHY — never a greyed button with no explanation. */}
      {gateId === null ? (
        <Text style={styles.scanNote}>Choose your gate above to start scanning.</Text>
      ) : null}

      {/* 2 — Students inside, directly on paper. Track empty at zero. */}
      <SectionCard>
        <Text style={styles.heroEyebrow}>Inside now</Text>
        <MetricBlock
          value={loaded ? inside.toLocaleString() : summaryError ? "—" : "..."}
          caption={
            !loaded
              ? "Live attendance is unavailable until the server responds."
              : expected > 0
                ? `${inside.toLocaleString()} of ${expected.toLocaleString()} expected`
                : "Expected attendance not set"
          }
        />
        {loaded ? <ProgressTrack value={inside} max={expected} /> : null}
        {/* Never display a fabricated zero for male/female/guest counts offline. */}
        {loaded ? <View style={styles.demoRow}>
          <Text style={styles.demoItem}>
            Male <Text style={styles.demoValue}>{(summary?.male ?? 0).toLocaleString()}</Text>
          </Text>
          <Text style={styles.demoItem}>
            Female <Text style={styles.demoValue}>{(summary?.female ?? 0).toLocaleString()}</Text>
          </Text>
          <Text style={styles.demoItem}>
            {/* 33-QA (I17): guests_inside is a count of guests INSIDE —
                the label says so (matches the Live Dashboard wording);
                roster guests are a different number entirely. */}
            Guests inside <Text style={styles.demoValue}>{(summary?.guests_inside ?? 0).toLocaleString()}</Text>
          </Text>
        </View> : null}
        {summaryError && backendConfigured !== false ? (
          <Text style={styles.inlineError}>
            Live attendance unavailable. Check the server connection.
          </Text>
        ) : null}
      </SectionCard>

      {/* 3 — Gate board: every gate as a clean row. Selected = subtle
          light tint, readable ink text/count, one thin ink marker. */}
      <SectionCard>
        <SectionEyebrow>{windowLabel}</SectionEyebrow>
        {gates.length === 0 ? (
          <Text style={styles.scanNote}>No gate list available. Connect to the server.</Text>
        ) : null}
        {gates.map((gate) => {
          const selected = gate.id === gateId;
          const count = countFor(gate.label);
          return (
            <Pressable
              key={gate.id}
              accessibilityRole="button"
              accessibilityState={{ selected }}
              accessibilityLabel={`${gate.label}, ${count} ${windowA11y}`}
              onPress={() => handleSelectGate(gate)}
              style={({ pressed }) => [
                styles.gateRow,
                selected && styles.gateRowActive,
                pressed && styles.pressed,
              ]}
            >
              <View style={[styles.gateMarker, selected && styles.gateMarkerActive]} />
              <View style={styles.flex1}>
                <View style={styles.gateHeadRow}>
                  <Text style={styles.gateName} numberOfLines={2}>
                    {gate.label}
                  </Text>
                  <Text style={styles.gateCount}>{count}</Text>
                </View>
                <ProgressTrack value={count} max={maxGate} height={4} />
              </View>
            </Pressable>
          );
        })}
      </SectionCard>

      {/* 4 — Last scan recorded on this device. Invalid (red) scans show
          "Invalid code · Gate · time" — actual values, never fabricated. */}
      {lastScan ? (
        <SectionCard>
          <SectionEyebrow>Last scan</SectionEyebrow>
          <View style={styles.lastRow}>
            <View style={styles.flex1}>
              <Text style={styles.lastTitle}>
                {invalidScan ? "Invalid code" : lastScan.title}
              </Text>
              {invalidScan ? (
                <Text style={styles.lastSub}>
                  {`${lastScan.gate ?? gateLabel ?? "Gate"} · ${formatClock(lastScan.at)}`}
                </Text>
              ) : (
                <>
                  {lastScan.name ? (
                    <Text style={styles.lastName}>{lastScan.name}</Text>
                  ) : null}
                  {lastScan.sub ? (
                    <Text style={styles.lastSub}>{lastScan.sub}</Text>
                  ) : null}
                </>
              )}
            </View>
            <StatusPill
              state={
                lastScan.level === "green"
                  ? "accept"
                  : lastScan.level === "amber"
                    ? "queued"
                    : "invalid"
              }
              label={formatClock(lastScan.at)}
              size="sm"
            />
          </View>
        </SectionCard>
      ) : null}

      {/* 6 — Queue depth only (35G: admin/broadcast entries moved to More).
          33-QA (I19): the Home "Find attendee" button is gone — attendee
          lookup lives on the Search tab in the bottom bar; Home never
          duplicated it. */}
      <SectionCard tone="tint">
        <View style={styles.statusRow}>
          <Ionicons
            name={queued > 0 ? "cloud-upload-outline" : "cloud-done-outline"}
            size={18}
            color={queued > 0 ? colors.amber : colors.ink}
          />
          <Text style={styles.statusText}>{queueCopy}</Text>
        </View>
      </SectionCard>

      {/* Existing gate-selection flow (the scanner's sheet) — Home never
          navigates to the Scanner just to choose a gate. The sheet's
          controls are the gate only (35I Q: direction lives in the
          scanner top bar / home toggle). */}
      <ScannerSheet
        visible={sheetVisible}
        gates={gates}
        gatesError={gatesError}
        gateId={gateId}
        onSelectGate={handleSelectGate}
        onClose={() => setSheetVisible(false)}
      />
    </Screen>
  );
}

const styles = {
  // 33-QA (I7): gate/last-scan text containers beside counts and pills
  // need minWidth:0 — long labels must shrink/wrap, not inflate the row
  // (Yoga automatic minimum sizing).
  flex1: { flex: 1, minWidth: 0 },
  pressed: { opacity: 0.7 },

  heroEyebrow: {
    // 35J (F4): readable sans 13 — not wide DM Mono 11.
    // 35M R2 (item 14): displayMedium (500) family carries the weight.
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.muted,
  },
  hero: {
    // 35M R2 (item 1): column — compact label row on top, Entry/Exit
    // toggle BELOW it. The label never pushes the toggle vertically.
    gap: spacing.sm,
  },
  scanNote: {
    // Finding 11: visible reason under the disabled Scan QR Code action.
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.muted,
    textAlign: "center" as const,
  },
  heroGateRow: {
    // Compact single-line chip: dynamic gate label + small Change action.
    flexDirection: "row" as const,
    alignItems: "center" as const,
    gap: spacing.sm,
  },
  heroGate: {
    // 35M R2 (item 1): ~32px compact label — clip (no ellipsis), no mode
    // suffix (the toggle below carries Entry/Exit). Family encodes the
    // weight directly (display = 800 face); no RN fontWeight synthesis.
    flex: 1,
    minWidth: 0,
    fontFamily: fonts.display,
    fontSize: 32,
    letterSpacing: -0.6,
    color: colors.ink,
  },

  chooseRow: {
    flexDirection: "row" as const,
    alignItems: "center" as const,
    minHeight: 48,
    gap: spacing.sm,
  },
  chooseText: {
    flex: 1,
    fontFamily: fonts.displayMedium,
    fontSize: 15,
    color: colors.ink,
  },
  changeAction: {
    // Inline on the centered label row — no extra margin.
    // 35M item 6: 48px minimum hit area — the label text stays compact.
    flexShrink: 0,
    minHeight: 48,
    justifyContent: "center" as const,
  },
  changeActionText: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.ink,
    textDecorationLine: "underline" as const,
  },

  // Phase 28 (concern 2): the Entry/Exit confirmation prompt. Sits directly
  // under the toggle so the question and the control stay in one place.
  confirmBox: {
    marginTop: spacing.sm,
    gap: spacing.sm,
  },
  confirmText: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.ink,
  },
  confirmActions: {
    flexDirection: "row" as const,
    gap: spacing.sm,
  },

  demoRow: {
    flexDirection: "row" as const,
    flexWrap: "wrap" as const,
    columnGap: spacing.lg,
    rowGap: spacing.xs,
    marginTop: spacing.xs,
  },
  demoItem: {
    // 35J (F4): readable sans 13 — the Male/Female/Guests inside labels
    // are operational text, not codes; DM Mono is reserved for codes/values.
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.muted,
  },
  demoValue: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.ink,
  },

  inlineError: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.invalid,
  },

  gateRow: {
    // 35M R2 (item 11): compact dynamic list — the marker gap drops from
    // md (16px + 3px marker ≈ 19px indent) to sm so all 7 server-provided
    // gates fit naturally; vertical padding tightens one step. Count stays
    // fully dynamic (gates.map, maxGate) — never hard-coded.
    // 35M item 4: symmetric horizontal padding so the selected ink row
    // never clips the right-side count; the marker lives INSIDE the
    // padding zone (absolute) so left/right spacing stays balanced.
    position: "relative" as const,
    flexDirection: "row" as const,
    alignItems: "center" as const,
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
    borderRadius: radius.sm,
  },
  gateRowActive: {
    backgroundColor: colors.track,
  },
  gateMarker: {
    position: "absolute" as const,
    left: spacing.sm,
    top: 10,
    bottom: 10,
    width: 3,
    borderRadius: radius.full,
    backgroundColor: "transparent",
  },
  gateMarkerActive: {
    backgroundColor: colors.ink,
  },
  gateHeadRow: {
    flexDirection: "row" as const,
    alignItems: "baseline" as const,
    gap: spacing.sm,
    marginBottom: 6,
  },
  gateName: {
    flex: 1,
    fontFamily: fonts.displayMedium,
    fontSize: 15,
    color: colors.ink,
  },
  gateCount: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.muted,
  },

  lastRow: {
    flexDirection: "row" as const,
    alignItems: "center" as const,
    gap: spacing.md,
  },
  lastTitle: {
    fontFamily: fonts.display,
    fontSize: 15,
    color: colors.ink,
  },
  lastName: {
    fontFamily: fonts.displayMedium,
    fontSize: 15,
    color: colors.ink,
    marginTop: 2,
  },
  lastSub: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.muted,
    marginTop: 2,
  },

  statusRow: {
    flexDirection: "row" as const,
    alignItems: "center" as const,
    gap: spacing.sm,
  },
  statusText: {
    flex: 1,
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.ink,
  },
};
