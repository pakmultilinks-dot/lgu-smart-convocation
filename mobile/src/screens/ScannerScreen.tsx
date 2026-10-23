import {
  type BarcodeScanningResult,
  type CameraViewProps,
  useCameraPermissions,
} from "expo-camera";
import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import * as Linking from "expo-linking";
import { router, useFocusEffect } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Modal,
  Platform,
  StyleSheet,
  Text,
  View,
  useWindowDimensions,
} from "react-native";
import {
  ApiError,
  fetchGates,
  fetchTestRecords,
  loginScanner,
  logoutScanner,
  postScan,
  postSync,
  resetTestScans,
  type Gate,
  type Occasion,
  type ScanMode,
  type ScanResult,
  type TestRecord,
} from "../api/client";
import { CameraScannerView } from "../scanner/CameraScannerView";
import { ScannerBottomBar } from "../scanner/ScannerBottomBar";
import { ScannerResult } from "../scanner/ScannerResult";
import { ScannerSheet } from "../scanner/ScannerSheet";
import { ScannerTestPanel } from "../scanner/ScannerTestPanel";
import { ScannerTopBar } from "../scanner/ScannerTopBar";
import { localTimestamp, RESULT_DISMISS_MS } from "../scanner/scannerConstants";
import { getAdminPin } from "../store/adminAccess";
import {
  getScannerSession,
  clearScannerSession,
  type ScannerSession,
} from "../store/scannerSession";
import {
  classifyScanResult,
  createScanResultController,
  createVolunteerName,
  isValidVolunteerName,
  resolveGateLabel,
  scanGateBlocked,
  scanPayload,
  SCAN_RESULT_MS,
  type ScanResultController,
} from "../scanner/scanResultLogic";
import { useScanDedup } from "../scanner/useScanDedup";
import { useScannerZoom } from "../scanner/useScannerZoom";
import {
  enqueueScan,
  getQueue,
  queueCount,
  reconcileSync,
} from "../store/offlineQueue";
import {
  getScanMode,
  getScanOccasion,
  getSelectedGate,
  setLastScanResult,
  setScanMode,
  setScanOccasion,
  setSelectedGate,
  type OpsScanResult,
  type SelectedGate,
} from "../store/ops";
import { getVolunteerName, setVolunteerName } from "../store/settings";
import { colors, fonts, radius, spacing } from "../theme";
import {
  AppButton,
  AppHeader,
  Field,
  LoadingState,
  OfflineBanner,
  Screen,
  SectionCard,
} from "../ui";

type MountErrorHandler = NonNullable<CameraViewProps["onMountError"]>;

/**
 * Scanner — the dominant operational surface (Phase 35B Order #2).
 * Camera first: gate + Entry/Exit always obvious above it, the camera
 * fills the top of the screen on initial render, and labeled Flash +
 * "Find manually" sit under it (Parts A/B/I). A gate is REQUIRED (35J G8):
 * no auto-selection — the gate-only sheet opens whenever none is chosen,
 * and no scan reaches the backend or offline queue without one. Scan
 * results render as three canonical states (VALID / ALREADY USED /
 * Invalid code) — full-surface tone with the actual gate · 12h time and
 * a large "Scan next" action (35J H/I/J); haptics per outcome. The
 * volunteer name is asked once, persisted through the settings
 * store, and stamped on every scan (Part C). Offline queueing, dedup,
 * auto-zoom and the camera mount-error state are preserved (G/H).
 */
export function ScannerScreen() {
  const [permission, requestPermission] = useCameraPermissions();
  const { height: windowH } = useWindowDimensions();

  const [gates, setGates] = useState<Gate[]>([]);
  const [gatesError, setGatesError] = useState<string | null>(null);
  // Scanner Fix Round 1 (item 2): flips true after the first successful
  // fetch — the gate chip must show "Choose a gate" (not "Loading
  // gates...") from that moment whenever no gate is selected.
  const [gatesLoaded, setGatesLoaded] = useState(false);
  const [gateId, setGateId] = useState<number | null>(null);
  const [mode, setMode] = useState<ScanMode>("entry");
  // Phase 29: which occasion of the annual cycle this scanner records.
  // Default (and replay default for old queued rows) is the main
  // convocation; rehearsal check-ins are an explicit, confirmed choice.
  const [occasion, setOccasion] = useState<Occasion>("ceremony");
  const [sheetVisible, setSheetVisible] = useState(false);
  const [namePromptVisible, setNamePromptVisible] = useState(false);
  const [nameDraft, setNameDraft] = useState("");
  const [nameError, setNameError] = useState<string | null>(null);
  // Phase 14: a scanner must sign in with a per-account username + PIN
  // before any scan is sent. The server derives the volunteer identity and
  // the permitted gate(s) from the session — never from device input.
  const [session, setSession] = useState<ScannerSession | null>(null);
  const [sessionLoaded, setSessionLoaded] = useState(false);
  const [loginVisible, setLoginVisible] = useState(false);
  const [loginUser, setLoginUser] = useState("");
  const [loginPin, setLoginPin] = useState("");
  const [loginError, setLoginError] = useState<string | null>(null);
  const [loginBusy, setLoginBusy] = useState(false);
  const [torch, setTorch] = useState(false);
  const [cameraFailed, setCameraFailed] = useState(false);
  const [cameraKey, setCameraKey] = useState(0);
  // Issue 6 (Release blocker): distinct camera states — "starting" runs
  // from mount until the first frame (onCameraReady); it resets whenever
  // the camera remounts (retry bumps cameraKey). REQUIRED and DENIED
  // permission states are decided above this — the branch on
  // !permission.granted renders distinct copy + recovery per state.
  const [cameraReady, setCameraReady] = useState(false);
  const [result, setResult] = useState<ScanResult | null>(null);
  const [online, setOnline] = useState<boolean | null>(null);
  const [offline, setOffline] = useState(false);
  const [queued, setQueued] = useState(0);
  const [syncing, setSyncing] = useState(false);
  const [lastSyncAt, setLastSyncAt] = useState<number | null>(null);
  const [testRecords, setTestRecords] = useState<TestRecord[]>([]);
  const [testLoading, setTestLoading] = useState(false);
  const [testResetLoading, setTestResetLoading] = useState(false);
  // Issue 1 (Release blocker): the test panel requires __DEV__ AND an
  // explicit admin unlock on this device — release builds never render it
  // regardless, and the production server independently 404s the test
  // endpoints. Reset additionally requires a confirmation step.
  const [adminUnlocked, setAdminUnlocked] = useState(false);
  const [resetConfirmVisible, setResetConfirmVisible] = useState(false);
  // Issue 3 (Release blocker): Entry/Exit switch requires an explicit
  // confirmation — "Switch mode? Scanning will stop on this device." —
  // so the volunteer never flips direction by accident.
  const [modeSwitchPending, setModeSwitchPending] = useState<ScanMode | null>(null);
  // Phase 29: occasion switch gets the same explicit confirmation.
  const [occasionSwitchPending, setOccasionSwitchPending] =
    useState<Occasion | null>(null);

  const savedGateRef = useRef<SelectedGate | null>(null);

  // Issue 1: check whether this device has an unlocked admin PIN — the
  // explicit condition beyond __DEV__ for showing test tooling.
  useEffect(() => {
    let alive = true;
    void getAdminPin().then((pin) => {
      if (alive) setAdminUnlocked(pin !== null);
    });
    return () => {
      alive = false;
    };
  }, []);

  // Request camera permission on first Scanner open (Phase 35H item 14):
  // useCameraPermissions leaves `permission` null until it is read or
  // requested — ask once, guarded against double-request while resolving.
  const requestedPermissionRef = useRef(false);
  useEffect(() => {
    if (!permission && !requestedPermissionRef.current) {
      requestedPermissionRef.current = true;
      void requestPermission();
    }
  }, [permission, requestPermission]);

  // Race-safe result timeline: ~1.2s for scan results, 4s for sync/test
  // notices; timers are cancelled on a newer result and on unmount
  // (no stale result overwriting a newer scan — Part E).
  const controllerRef = useRef<ScanResultController | null>(null);
  if (controllerRef.current === null) {
    controllerRef.current = createScanResultController(
      (r) => setResult(r),
      () => setResult(null),
    );
  }
  useEffect(() => () => controllerRef.current?.dispose(), []);

  // Volunteer name: asked once, persisted via the settings store (Part C).
  const volunteerRef = useRef(
    createVolunteerName({ load: getVolunteerName, save: setVolunteerName }),
  );

  // Scanner engines: auto-zoom follow + in-frame duplicate suppression.
  const { zoom, trackBounds, onCameraLayout } = useScannerZoom();
  const { claim, release } = useScanDedup();

  const refreshQueueCount = useCallback(async () => {
    const n = await queueCount();
    setQueued(n);
  }, []);

  const loadGates = useCallback(async () => {
    try {
      const list = await fetchGates();
      setGates(list);
      setGatesLoaded(true);
      setGatesError(null);
      setOnline(true);
      // Restore the saved gate if it still exists on the server.
      // 35J (G8): with NO valid stored gate the scanner stays gateless —
      // it never silently defaults to the first gate, and the existing
      // gate-only sheet opens so the volunteer picks one explicitly.
      const saved = savedGateRef.current ?? (await getSelectedGate());
      if (saved && list.some((g) => g.id === saved.id)) {
        savedGateRef.current = saved;
        setGateId(saved.id);
      } else if (list.length > 0) {
        setSheetVisible(true);
      }
    } catch (e) {
      // Phase 38 (MOB-003): an HTTP answer (even a 500) proves the backend
      // is reachable — only a transport failure (status 0) reads offline.
      if (e instanceof ApiError && e.status === 0) setOnline(false);
      setGatesError(
        e instanceof Error ? e.message : "Gates could not be loaded.",
      );
    }
  }, []);

  const loadTestRecords = useCallback(async () => {
    // Issue 1 (Release blocker): the deterministic test panel requires
    // __DEV__ AND an explicit admin unlock on this device. In release
    // builds __DEV__ is false — the fetch never runs. On dev builds
    // without an unlocked admin PIN the panel stays hidden. The server
    // also independently 404s /api/test-records on a production DB.
    if (!__DEV__ || !adminUnlocked) {
      setTestRecords([]);
      return;
    }
    try {
      const records = await fetchTestRecords();
      setTestRecords(records);
    } catch {
      setTestRecords([]);
    }
  }, [adminUnlocked]);

  // Load stored scanner session + volunteer + mode, then gates/queue.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const [sess, , savedMode, savedOccasion] = await Promise.all([
        getScannerSession(),
        volunteerRef.current.load(),
        getScanMode(),
        getScanOccasion(),
      ]);
      if (cancelled) return;
      setSession(sess);
      setSessionLoaded(true);
      // Show one onboarding prompt at a time: login first, name only after auth.
      setLoginVisible(!sess);
      setNamePromptVisible(!!sess && volunteerRef.current.needsSetup);
      setMode(savedMode);
      setOccasion(savedOccasion);
      await loadGates();
      await loadTestRecords();
      await refreshQueueCount();
    })();
    return () => {
      cancelled = true;
    };
  }, [loadGates, loadTestRecords, refreshQueueCount]);

  useFocusEffect(
    useCallback(() => {
      void refreshQueueCount();
      // The stored name may have been set or cleared in Settings meanwhile,
      // and a session revoked elsewhere must re-lock this device.
      void (async () => {
        const [sess] = await Promise.all([
          getScannerSession(),
          volunteerRef.current.load(),
        ]);
        setSession(sess);
        setSessionLoaded(true);
        setLoginVisible(!sess);
        setNamePromptVisible(!!sess && volunteerRef.current.needsSetup);
      })();
    }, [refreshQueueCount]),
  );

  const persistOpsResult = useCallback((r: ScanResult) => {
    const record: OpsScanResult = {
      at: Date.now(),
      level: r.level,
      name: r.name ?? null,
      sub: r.sub ?? null,
      time: r.time ?? null,
      title: r.title,
    };
    void setLastScanResult(record);
  }, []);

  // Scan-path results auto-return in ~1.2s (Part E); invalid / already-used
  // outcomes hold the full-surface state for the 4s notice window (35J H/J:
  // the operator must read "Do not admit. Use Find attendee." and reach the
  // "Scan next" button); sync/test notices keep the 4s window as well.
  const showScanResult = useCallback((r: ScanResult) => {
    const kind = classifyScanResult(r).kind;
    controllerRef.current?.show(
      r,
      kind === "invalid" || kind === "already-used"
        ? RESULT_DISMISS_MS
        : SCAN_RESULT_MS,
    );
  }, []);

  const showResult = useCallback((r: ScanResult) => {
    controllerRef.current?.show(r, RESULT_DISMISS_MS);
  }, []);

  const dismissResult = useCallback(() => {
    controllerRef.current?.clear();
  }, []);

  // 35L (E): real notification haptics per outcome (success / warning /
  // error) with a graceful no-op on platforms that don't support them —
  // a missing haptic engine must never break a scan.
  const haptic = useCallback(
    async (cue: "success" | "warning" | "error") => {
      if (Platform.OS === "web") return;
      try {
        await Haptics.notificationAsync(
          cue === "success"
            ? Haptics.NotificationFeedbackType.Success
            : cue === "warning"
              ? Haptics.NotificationFeedbackType.Warning
              : Haptics.NotificationFeedbackType.Error,
        );
      } catch {
        // No haptic engine — scanning continues unaffected.
      }
    },
    [],
  );

  // A session revoked or expired server-side clears on the next 401 so the
  // device re-locks instead of showing stale scan results.
  const handleAuthFailure = useCallback(async (e: unknown) => {
    if (e instanceof ApiError && e.status === 401) {
      await clearScannerSession();
      setSession(null);
      setLoginVisible(true);
    }
  }, []);

  // Phase 38 (MOB-002): ONE queue path shared by offline mode and a network
  // failure mid-scan — the payload is identical either way, so replay
  // produces the same server verdict it would have produced live.
  const queueScan = useCallback(
    async (stamped: ReturnType<typeof scanPayload>) => {
      const { duplicate } = await enqueueScan({
        ...stamped,
        scanned_at: localTimestamp(),
      });
      await refreshQueueCount();
      await haptic("warning");
      const queuedResult: ScanResult = {
        detail: duplicate
          ? "This scan is already queued on this device."
          : "Saved on this device. Press Sync now when back online.",
        gate: gates.find((g) => g.id === gateId)?.label,
        level: "amber",
        status: "ok",
        title: duplicate ? "ALREADY QUEUED" : "SCAN QUEUED",
      };
      showScanResult(queuedResult);
      persistOpsResult(queuedResult);
    },
    [gates, gateId, haptic, persistOpsResult, refreshQueueCount, showScanResult],
  );

  const handleBarcode = useCallback(
    async (scan: BarcodeScanningResult) => {
      // Track QR bounds on every callback so auto-zoom follows the code.
      trackBounds(scan);
      // In-frame duplicate suppression (spec §22, 35K Part P) — one scan
      // at a time; the cooldown key is payload + mode + gate + occasion so
      // an Entry→Exit sequence, or a Rehearsal→Main-convocation sequence
      // for the same pass, is never suppressed.
      if (!scan.data || !claim(scan.data, mode, gateId, occasion)) {
        return;
      }
      const payload = scan.data;
      let stamped: ReturnType<typeof scanPayload> | null = null;
      try {
        // 35L (F): no scan is ever stamped under an unusable identity —
        // while the stored name is missing/invalid the setup prompt owns
        // the screen and this read is dropped.
        // Authentication always precedes volunteer-name setup. Never open
        // two native modals on top of each other.
        if (!session) {
          setNamePromptVisible(false);
          setLoginVisible(true);
          return;
        }
        if (volunteerRef.current.needsSetup) {
          setNamePromptVisible(true);
          return;
        }
        // 35J (G8): a scan never leaves the device without a gate — no
        // backend POST, no offline queue. The gate-only sheet opens so
        // the volunteer picks a gate, then scanning resumes.
        if (scanGateBlocked(gateId)) {
          setSheetVisible(true);
          showScanResult({
            detail: "Choose a gate before scanning.",
            level: "red",
            status: "error",
            title: "NO GATE SELECTED",
          });
          return;
        }
        // Every scan is stamped with the persisted volunteer name and the
        // confirmed occasion (Phase 29).
        stamped = scanPayload({
          volunteerName: volunteerRef.current.current,
          gateId,
          mode,
          payload,
          occasion,
        });
        if (offline) {
          await queueScan(stamped);
          return;
        }
        const response = await postScan(stamped);
        setOnline(true);
        // 35I (C): invalid/unknown results carry the ACTUAL gate and scan
        // time from this device's context — never fabricated values.
        if (
          (response.title === "INVALID CODE" || response.title === "UNKNOWN CODE") &&
          response.gate == null
        ) {
          response.gate = gates.find((g) => g.id === gateId)?.label;
          response.time = localTimestamp();
        }
        // VALID → positive haptic; ALREADY USED / INVALID → error haptic.
        const cue = classifyScanResult(response).haptic;
        await haptic(cue);
        showScanResult(response);
        persistOpsResult(response);
      } catch (e) {
        // Phase 14: a revoked/expired session re-locks the device first.
        await handleAuthFailure(e);
        // Phase 38 (MOB-003): offline is a NETWORK fact — status 0 means the
        // request never reached the backend (networkError in client.ts).
        // Busy (retryable) and any HTTP answer (401/403/500/...) all mean
        // the server responded, so the device stays online (Phase 23 §2).
        const network = e instanceof ApiError && e.status === 0;
        const retryable = e instanceof ApiError && e.retryable === true;
        if (network) {
          setOnline(false);
          // Phase 38 (MOB-002): a network failure queues the scan for
          // replay on Sync instead of silently dropping the verdict.
          if (stamped) {
            await queueScan(stamped);
            return;
          }
        }
        await haptic(retryable ? "warning" : "error");
        // A retryable answer carries the backend's own amber body, so the
        // volunteer reads "TEMPORARILY BUSY" with retry guidance instead of
        // a red SCAN FAILED they would read as a broken scan.
        const failedResult: ScanResult =
          e instanceof ApiError && e.result !== undefined
            ? e.result
            : {
                detail:
                  e instanceof ApiError
                    ? e.message
                    : "The scan could not be verified. Try again.",
                level: "red",
                status: "error",
                title: "SCAN FAILED",
              };
        showScanResult(failedResult);
        persistOpsResult(failedResult);
      } finally {
        release();
      }
    },
    [
      claim,
      gates,
      gateId,
      handleAuthFailure,
      haptic,
      mode,
      occasion,
      offline,
      persistOpsResult,
      queueScan,
      release,
      session,
      showScanResult,
      trackBounds,
    ],
  );

  const handleSync = useCallback(async () => {
    const items = await getQueue();
    if (items.length === 0) {
      return;
    }
    setSyncing(true);
    try {
      const response = await postSync(items);
      setOnline(true);
      const { remaining, accepted, rejected } = await reconcileSync(
        response.results,
      );
      setQueued(remaining.length);
      setLastSyncAt(Date.now());
      await haptic("success");
      const lines = [`${accepted} scan(s) counted.`];
      if (rejected.length > 0) {
        lines.push(
          `${rejected.length} did NOT count: ` +
            rejected.map((r) => r.title).join(", ") +
            ".",
        );
      }
      if (remaining.length > 0) {
        lines.push(`${remaining.length} still queued, will retry.`);
      }
      showResult({
        detail: lines.join(" "),
        level: rejected.length > 0 ? "amber" : "green",
        status: "ok",
        title: "SYNC COMPLETE",
      });
    } catch (e) {
      // Phase 14: a revoked/expired session re-locks the device too.
      await handleAuthFailure(e);
      // Phase 38 (MOB-003): only a network failure (status 0) is offline —
      // an HTTP answer (busy/500/401) means the server is reachable.
      if (e instanceof ApiError && e.status === 0) setOnline(false);
      showResult({
        detail:
          e instanceof ApiError
            ? e.message
            : "Sync failed. The queue is kept on this device.",
        level: "red",
        status: "error",
        title: "SYNC FAILED",
      });
    } finally {
      setSyncing(false);
    }
  }, [handleAuthFailure, haptic, showResult]);

  /** TEST FUNCTIONALITY — deterministic backend records through the real
      /api/scan path (same handleBarcode as the camera). */
  const handleTestScan = useCallback(
    async (record: TestRecord) => {
      if (testLoading) return;
      setTestLoading(true);
      try {
        await handleBarcode({ data: record.payload } as BarcodeScanningResult);
      } finally {
        setTestLoading(false);
      }
    },
    [handleBarcode, testLoading],
  );

  // Issue 1 (Release blocker): reset is destructive — it never executes
  // on a single tap. The button opens a confirmation modal; the actual
  // reset only runs after explicit confirmation, and the server
  // independently requires the admin PIN + rejects on a production DB.
  const requestTestReset = useCallback(() => {
    if (testResetLoading) return;
    setResetConfirmVisible(true);
  }, [testResetLoading]);

  const handleTestReset = useCallback(async () => {
    if (testResetLoading) return;
    setResetConfirmVisible(false);
    setTestResetLoading(true);
    try {
      const removed = await resetTestScans();
      await refreshQueueCount();
      await haptic("success");
      showResult({
        detail:
          removed > 0
            ? `${removed} test scan(s) cleared. Run a Test Scan again to record a fresh entry.`
            : "No test scans to clear. Run a Test Scan first.",
        level: "green",
        status: "ok",
        title: "TEST SCANS RESET",
      });
    } catch (e) {
      showResult({
        detail:
          e instanceof ApiError
            ? e.message
            : "Could not reset test scans. Try again.",
        level: "red",
        status: "error",
        title: "RESET FAILED",
      });
    } finally {
      setTestResetLoading(false);
    }
  }, [haptic, refreshQueueCount, showResult, testResetLoading]);

  // First-use volunteer name: stored once on this device, never asked
  // again while it stays stored (Part C).
  const saveName = useCallback(async () => {
    // 35L (F): the identity stamped on every scan must be at least
    // two letters — empty/1-char/whitespace values are rejected.
    if (!isValidVolunteerName(nameDraft)) {
      setNameError("Enter a real name of at least 2 letters.");
      return;
    }
    try {
      await volunteerRef.current.ensure(nameDraft);
      setNameDraft("");
      setNameError(null);
      setNamePromptVisible(false);
      await haptic("success");
    } catch {
      setNameError("Could not save on this device. Try again.");
    }
  }, [haptic, nameDraft]);

  // Phase 14: sign in with a per-account username + PIN. The server returns
  // a short-lived session token held only on this device; it also decides the
  // volunteer name and permitted gates, so nothing here trusts local input
  // for identity or authorization.
  const submitLogin = useCallback(async () => {
    if (loginBusy) return;
    if (!loginUser.trim() || !loginPin) {
      setLoginError("Enter your username and PIN.");
      return;
    }
    setLoginBusy(true);
    setLoginError(null);
    try {
      const sess = await loginScanner(loginUser.trim(), loginPin);
      // Account display name comes from the authenticated backend. Avoid a
      // second name pop-up when this is already a valid volunteer name.
      if (volunteerRef.current.needsSetup) {
        await volunteerRef.current.ensure(sess.displayName);
      }
      setSession(sess);
      setLoginVisible(false);
      setNamePromptVisible(volunteerRef.current.needsSetup);
      setLoginUser("");
      setLoginPin("");
      await haptic("success");
    } catch (e) {
      // 429 (rate limit) and 401 (bad credentials) both land here with a
      // sanitized server message; network errors use the client fallback.
      setLoginError(
        e instanceof ApiError ? e.message : "Could not sign in. Try again.",
      );
    } finally {
      setLoginBusy(false);
    }
  }, [haptic, loginBusy, loginPin, loginUser]);

  const signOut = useCallback(async () => {
    await logoutScanner();
    setSession(null);
    setNamePromptVisible(false);
    setLoginVisible(true);
  }, []);

  // Camera mount failures surface a user-safe state; details stay dev-only.
  const handleMountError = useCallback<MountErrorHandler>((event) => {
    if (__DEV__) console.log("[scanner] camera mount error:", event.message);
    setCameraFailed(true);
  }, []);

  const handleTryCamera = useCallback(() => {
    setCameraFailed(false);
    // Issue 6: a retry remounts the camera — the starting state begins again.
    setCameraReady(false);
    setCameraKey((k) => k + 1);
  }, []);

  // Issue 6: the native preview reports its first frame — STARTING ends.
  const handleCameraReady = useCallback(() => setCameraReady(true), []);

  const handleCameraBack = useCallback(() => {
    if (router.canGoBack()) {
      router.back();
    } else {
      router.replace("/(volunteer)/home");
    }
  }, []);

  const handleSelectGate = useCallback((gate: Gate) => {
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
    setGateId(gate.id);
    const selected = { id: gate.id, label: gate.label };
    savedGateRef.current = selected;
    void setSelectedGate(selected);
  }, []);

  // Issue 3 (Release blocker): the Entry/Exit switch never applies
  // silently — tapping the other mode opens a confirmation modal.
  const requestModeChange = useCallback(
    (next: ScanMode) => {
      if (next === mode) return;
      setModeSwitchPending(next);
    },
    [mode],
  );

  const confirmModeChange = useCallback(() => {
    const next = modeSwitchPending;
    setModeSwitchPending(null);
    if (!next || next === mode) return;
    // Local ops-state only (persisted for convenience) — never mutates
    // backend state; the next scan carries the mode in its payload.
    setMode(next);
    void setScanMode(next);
  }, [mode, modeSwitchPending]);

  // Phase 29: the occasion switch follows the same discipline as the mode
  // switch — rehearsal check-ins and main-ceremony admission are distinct
  // records, so the volunteer confirms before the scanner changes which
  // one it records. Local ops-state only; every scan carries the occasion.
  const requestOccasionChange = useCallback(
    (next: Occasion) => {
      if (next === occasion) return;
      setOccasionSwitchPending(next);
    },
    [occasion],
  );

  const confirmOccasionChange = useCallback(() => {
    const next = occasionSwitchPending;
    setOccasionSwitchPending(null);
    if (!next || next === occasion) return;
    setOccasion(next);
    void setScanOccasion(next);
  }, [occasion, occasionSwitchPending]);

  // Scanner Fix Round 1 (item 2): resolved by a pure helper — once gates
  // have loaded the chip can never read "Loading gates..."; with no
  // selection it shows "Choose a gate" (the gate sheet's own words).
  const gateLabel = resolveGateLabel(gates, gateId, gatesError, gatesLoaded);
  // 35L (C1): torch capability is only claimed where the platform can
  // provide it — web has no torch and the control says so honestly.
  const torchSupported = Platform.OS !== "web";
  // 35L (D): scan outcomes resolve as FULL-SCREEN states over the whole
  // screen; operational notices (queue/sync/setup) keep the compact
  // card inside the camera area.
  const resultKind = result ? classifyScanResult(result).kind : null;
  const fullScreenResult =
    result && resultKind !== null && resultKind !== "other" ? result : null;
  // 35M targeted fix (item 7): the camera keeps a large share of the
  // window, but the old fixed 0.62 share pushed the Flash + Find manually
  // controls below the fold on device — worse with the offline banner or
  // the gate notice stacked above the camera. The chrome budget reserves
  // room for the top bar + bottom bar + banners at every window height, so
  // the controls stay visible without blind scrolling; the Test panel
  // below the bar stays reachable by scroll.
  const cameraHeight = Math.max(
    260,
    Math.min(Math.round(windowH * 0.58), windowH - 330),
  );

  if (!permission) {
    return (
      <Screen scroll={false}>
        <LoadingState label="Checking camera permission..." />
      </Screen>
    );
  }

  if (!permission.granted) {
    // Issue 6 (Release blocker): REQUIRED and DENIED are distinct states
    // with distinct copy — never one generic card. 35L (C2): the recovery
    // path is never a dead screen — re-ask while the OS still allows it,
    // otherwise send the operator to system settings, and "Find manually"
    // keeps gate work moving without the camera. One title, NO icon.
    const canAsk = permission.canAskAgain;
    return (
      <Screen>
        <AppHeader title="Scanner" />
        <SectionCard>
          <Text style={styles.permissionTitle}>
            {canAsk ? "Camera access needed" : "Camera permission is off"}
          </Text>
          <Text style={styles.permissionBody}>
            {canAsk
              ? "Grant camera access to scan QR codes at your gate."
              : "Enable the camera for this app in system settings, then come back to the scanner."}
          </Text>
          {canAsk ? (
            <AppButton
              label="Grant camera permission"
              icon="camera-outline"
              onPress={() => void requestPermission()}
            />
          ) : (
            <AppButton
              label="Open settings"
              icon="settings-outline"
              onPress={() => {
                // Best-effort: some platforms reject — the manual path
                // below stays available either way.
                void Linking.openSettings().catch(() => {});
              }}
            />
          )}
          <AppButton
            label="Find manually"
            icon="search"
            variant="secondary"
            onPress={() => router.push("/(volunteer)/search")}
          />
        </SectionCard>
      </Screen>
    );
  }

  return (
    // 33-QA (I14): bounded camera frame — the main scanner column no
    // longer scrolls; the camera grows into its slot (flex:1 with the
    // 35M chrome-budget formula as the minHeight floor) so the viewfinder
    // owns the space between the top bar and the bottom bar at every
    // height, and Flash + Find manually are guaranteed visible without
    // any scroll. (Dev-only test panel may clip on very short windows.)
    <Screen scroll={false}>
      <View style={styles.scannerBody}>
      {/* Top area: gate + Entry/Exit + connection. Own zone — never
          overlaps the camera (Part A). */}
      <ScannerTopBar
        gateLabel={gateLabel}
        mode={mode}
        occasion={occasion}
        online={online}
        onModeChange={requestModeChange}
        onOccasionChange={requestOccasionChange}
        onOpenSheet={() => setSheetVisible(true)}
      />

      {/* Issue 3 (Release blocker): mode-switch confirmation — the
          volunteer explicitly confirms before the direction changes. */}
      <Modal
        visible={modeSwitchPending !== null}
        transparent
        animationType="fade"
        onRequestClose={() => setModeSwitchPending(null)}
      >
        <View style={styles.promptBackdrop}>
          <View style={styles.promptCard}>
            <Text style={styles.promptTitle}>
              {`Switch to ${modeSwitchPending === "exit" ? "Exit" : "Entry"}?`}
            </Text>
            <Text style={styles.promptBody}>
              Scans will be recorded as{" "}
              {modeSwitchPending === "exit" ? "exits" : "entries"}.
            </Text>
            <View style={styles.resetActions}>
              <AppButton
                label="Cancel"
                variant="secondary"
                onPress={() => setModeSwitchPending(null)}
              />
              <AppButton
                label="Switch"
                variant="primary"
                onPress={confirmModeChange}
              />
            </View>
          </View>
        </View>
      </Modal>

      {/* Phase 29: occasion-switch confirmation — a rehearsal check-in and
          a main-ceremony admission are distinct records, so the volunteer
          confirms before the scanner changes which one it records. */}
      <Modal
        visible={occasionSwitchPending !== null}
        transparent
        animationType="fade"
        onRequestClose={() => setOccasionSwitchPending(null)}
      >
        <View style={styles.promptBackdrop}>
          <View style={styles.promptCard}>
            <Text style={styles.promptTitle}>
              {`Switch to ${occasionSwitchPending === "rehearsal" ? "Rehearsal" : "Main convocation"}?`}
            </Text>
            <Text style={styles.promptBody}>
              Scans will be recorded as{" "}
              {occasionSwitchPending === "rehearsal"
                ? "rehearsal check-ins"
                : "main convocation admissions"}
              .
            </Text>
            <View style={styles.resetActions}>
              <AppButton
                label="Cancel"
                variant="secondary"
                onPress={() => setOccasionSwitchPending(null)}
              />
              <AppButton
                label="Switch"
                variant="primary"
                onPress={confirmOccasionChange}
              />
            </View>
          </View>
        </View>
      </Modal>

      {online === false || queued > 0 ? (
        <OfflineBanner
          title={
            queued > 0
              ? `${online === false ? "Offline" : "Waiting to sync"}. ${queued} scan${queued === 1 ? "" : "s"} waiting.`
              : online === false
                ? "Offline"
                : "Waiting to sync"
          }
          lastSyncedAt={lastSyncAt}
          onRetry={() => void loadGates()}
        />
      ) : null}

      {/* Issue 2 (Release blocker): the camera is refused until a gate is
          chosen — no viewfinder, no scan, no ambiguity. The gate sheet
          opens automatically so the volunteer picks one explicitly. */}
      {gateId === null ? (
        <View style={[styles.cameraArea, { minHeight: cameraHeight }]}>
          <View style={styles.gateRequired}>
            <Ionicons name="location-outline" size={48} color={colors.muted} />
            <Text style={styles.gateRequiredTitle}>Choose a gate</Text>
            <Text style={styles.gateRequiredBody}>
              The scanner needs a gate before it can read QR codes. Select
              the gate you are staffing, then scanning starts.
            </Text>
            <AppButton
              label="Choose a gate"
              icon="location-outline"
              onPress={() => setSheetVisible(true)}
            />
          </View>
        </View>
      ) : (
        <View style={[styles.cameraArea, { minHeight: cameraHeight }]}>
          <CameraScannerView
            cameraKey={cameraKey}
            zoom={zoom}
            torch={torch}
            torchSupported={torchSupported}
            paused={sheetVisible}
            onBarcodeScanned={handleBarcode}
            onCameraLayout={onCameraLayout}
            onMountError={handleMountError}
            failed={cameraFailed}
            onTryAgain={handleTryCamera}
            onBack={handleCameraBack}
            onFindManual={() => router.push("/(volunteer)/search")}
            ready={cameraReady}
            onCameraReady={handleCameraReady}
            mode={mode}
            result={fullScreenResult ? null : result}
            onDismissResult={dismissResult}
          />
        </View>
      )}

      {/* Flash (labeled) + Find manually + offline queue — under camera. */}
      <ScannerBottomBar
        torch={torch}
        torchSupported={torchSupported}
        onTorchToggle={() => setTorch((t) => !t)}
        onFindManual={() => router.push("/(volunteer)/search")}
        online={online}
        offline={offline}
        onOfflineChange={setOffline}
        queued={queued}
        syncing={syncing}
        onSync={() => void handleSync()}
        gatesError={gatesError}
        onRetryGates={loadGates}
      />

      {/* Test scan — real backend records through the same code path.
          Issue 1 (Release blocker): renders only in __DEV__ AND when
          this device has an unlocked admin PIN. Release builds never
          render it (the server additionally 404s the test endpoints
          when the configured database is the production file). */}
      {__DEV__ && adminUnlocked ? (
        <ScannerTestPanel
          records={testRecords}
          testLoading={testLoading}
          testResetLoading={testResetLoading}
          onTestScan={(record) => void handleTestScan(record)}
          onTestReset={requestTestReset}
        />
      ) : null}

      {/* Issue 1 (Release blocker): reset-test confirmation — destructive
          actions never execute on a single tap. */}
      <Modal
        visible={resetConfirmVisible}
        transparent
        animationType="fade"
        onRequestClose={() => setResetConfirmVisible(false)}
      >
        <View style={styles.promptBackdrop}>
          <View style={styles.promptCard}>
            <Text style={styles.promptTitle}>Reset test scans?</Text>
            <Text style={styles.promptBody}>
              This clears the test scan records on the server so you can run
              fresh test scans. Real guest and student data is not affected.
            </Text>
            <View style={styles.resetActions}>
              <AppButton
                label="Cancel"
                variant="secondary"
                onPress={() => setResetConfirmVisible(false)}
              />
              <AppButton
                label="Reset test scans"
                variant="danger"
                loading={testResetLoading}
                onPress={() => void handleTestReset()}
              />
            </View>
          </View>
        </View>
      </Modal>

      {/* Gate sheet — gate selection only (35I Q: direction lives in the
          top bar SegmentedControl, the ONE authoritative control). */}
      <ScannerSheet
        visible={sheetVisible}
        gates={gates}
        gatesError={gatesError}
        gateId={gateId}
        onSelectGate={handleSelectGate}
        onClose={() => setSheetVisible(false)}
      />

      {/* Scanner sign-in (Phase 14): required before any scan is sent.
          The server decides the volunteer identity and permitted gates. */}
      <Modal
        visible={sessionLoaded && loginVisible}
        transparent
        animationType="fade"
        onRequestClose={() => {
          setLoginVisible(false);
          router.replace("/(volunteer)/home");
        }}
      >
        <View style={styles.promptBackdrop}>
          <View style={styles.promptCard}>
            <Text style={styles.promptTitle}>Sign in to scan</Text>
            <Text style={styles.promptBody}>
              Use the scanner username and PIN issued by the administrator for
              your gate. Scanning is locked until you sign in.
            </Text>
            <Field
              label="Username"
              placeholder="e.g. gateA-ana"
              value={loginUser}
              onChangeText={(t) => {
                setLoginUser(t);
                setLoginError(null);
              }}
              autoCapitalize="none"
              autoCorrect={false}
              returnKeyType="next"
            />
            <Field
              label="PIN"
              placeholder="Your scanner PIN"
              value={loginPin}
              onChangeText={(t) => {
                setLoginPin(t);
                setLoginError(null);
              }}
              secureTextEntry
              autoCapitalize="none"
              autoCorrect={false}
              returnKeyType="done"
            />
            {loginError ? <Text style={styles.promptError}>{loginError}</Text> : null}
            <AppButton
              label="Connect to demo server"
              icon="cloud-outline"
              variant="secondary"
              onPress={() => {
                setLoginVisible(false);
                router.push("/connect-server");
              }}
            />
            <AppButton
              label={loginBusy ? "Signing in…" : "Sign in"}
              icon="log-in"
              onPress={() => void submitLogin()}
              disabled={loginBusy}
            />
            <AppButton
              label="Back to home"
              variant="ghost"
              onPress={() => {
                setLoginVisible(false);
                router.replace("/(volunteer)/home");
              }}
            />
            {session ? (
              <AppButton
                label="Sign out"
                variant="secondary"
                onPress={() => void signOut()}
              />
            ) : null}
          </View>
        </View>
      </Modal>

      {/* Volunteer name — first use only; stored on this device. */}
      <Modal
        visible={namePromptVisible && session !== null && !loginVisible}
        transparent
        animationType="fade"
        onRequestClose={() => setNamePromptVisible(false)}
      >
        <View style={styles.promptBackdrop}>
          <View style={styles.promptCard}>
            <Text style={styles.promptTitle}>Volunteer name</Text>
            <Text style={styles.promptBody}>
              Every scan at this gate is stamped with your name. It is stored
              once on this device — you will not be asked again.
            </Text>
            <Field
              label="Your name"
              placeholder="e.g. Bilal Ahmad"
              value={nameDraft}
              onChangeText={(t) => {
                setNameDraft(t);
                setNameError(null);
              }}
              autoCapitalize="words"
              returnKeyType="done"
            />
            {nameError ? <Text style={styles.promptError}>{nameError}</Text> : null}
            <AppButton
              label="Save name"
              icon="checkmark"
              onPress={() => void saveName()}
            />
            <AppButton
              label="Not now"
              variant="secondary"
              onPress={() => setNamePromptVisible(false)}
            />
          </View>
        </View>
      </Modal>

      {/* 35L (D): valid / guest / already-used / invalid resolve into a
          full-screen state over the whole screen — the operator cannot
          miss the verdict. Timing preserved (SCAN_RESULT_MS / 4s). */}
      {fullScreenResult ? (
        <View style={styles.fullResultLayer} pointerEvents="box-none">
          <ScannerResult
            result={fullScreenResult}
            mode={mode}
            onDismiss={dismissResult}
          />
        </View>
      ) : null}
      </View>
    </Screen>
  );
}

const styles = {
  cameraArea: {
    // 33-QA (I14): the camera fills its slot in the bounded column
    // (flex: 1); the 35M chrome-budget formula stays the minHeight
    // floor so the bottom bar is never pushed off-screen.
    flex: 1,
    borderRadius: radius.md,
    overflow: "hidden" as const,
  },
  scannerBody: {
    // 33-QA (I14): one tight column — top bar → camera → bottom bar;
    // the camera grows into the leftover height.
    flex: 1,
    gap: spacing.sm,
  },
  // Issue 2: gate-required state replaces the camera until a gate is set.
  gateRequired: {
    flex: 1,
    alignItems: "center" as const,
    justifyContent: "center" as const,
    gap: spacing.md,
    paddingHorizontal: spacing.lg,
    backgroundColor: colors.track,
    borderRadius: radius.md,
  },
  gateRequiredTitle: {
    fontFamily: fonts.display,
    fontSize: 24,
    letterSpacing: -0.4,
    color: colors.ink,
  },
  gateRequiredBody: {
    fontFamily: fonts.displayMedium,
    fontSize: 15,
    color: colors.muted,
    lineHeight: 21,
    textAlign: "center" as const,
  },
  fullResultLayer: {
    ...StyleSheet.absoluteFill,
    // Above camera + bars; the name prompt Modal stays above everything.
    zIndex: 10,
  },
  permissionTitle: {
    fontFamily: fonts.display,
    fontSize: 24,
    letterSpacing: -0.4,
    color: colors.ink,
  },
  permissionBody: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.muted,
    lineHeight: 18,
  },
  promptBackdrop: {
    flex: 1,
    backgroundColor: colors.overlay,
    justifyContent: "center" as const,
    padding: spacing.screen,
  },
  promptCard: {
    backgroundColor: colors.paper,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.track,
    padding: spacing.lg,
    gap: spacing.sm,
  },
  promptTitle: {
    fontFamily: fonts.display,
    fontSize: 24,
    letterSpacing: -0.4,
    color: colors.ink,
  },
  promptBody: {
    fontFamily: fonts.displayMedium,
    fontSize: 15,
    color: colors.muted,
    lineHeight: 21,
  },
  promptError: {
    // 35M item 18: the validation sentence is normal label text — sans,
    // not DM Mono (mono is reserved for status chips + gate identifiers).
    fontFamily: fonts.displayMedium,
    fontSize: 11,
    color: colors.invalid,
  },
  resetActions: {
    flexDirection: "row" as const,
    gap: spacing.sm,
    marginTop: spacing.sm,
  },
};
