import { Ionicons } from "@expo/vector-icons";
import { router, useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { Modal, Pressable, ScrollView, Text, View } from "react-native";
import { getSettings, updateSettings } from "../api/settingsApi";
import { DashboardControls } from "../components/DashboardControls";
import { getQueue } from "../store/offlineQueue";
import {
  getApiBaseUrl,
  getApiBaseUrlMode,
  isValidBaseUrl,
  resetToAutomaticBackend,
  setApiBaseUrl,
} from "../store/settings";
import { colors, fonts, radius, spacing } from "../theme";
import {
  AppButton,
  AppHeader,
  ErrorState,
  Field,
  LoadingState,
  Screen,
  SectionCard,
  SectionEyebrow,
  StatusPill,
  formatClock,
} from "../ui";

type ProbeState = "idle" | "probing" | "ok" | "fail";

/** Direct health probe against a custom address (the config surface only —
    technical values never appear in operator-facing list UI). */
async function probe(url: string): Promise<boolean> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 5000);
  try {
    const res = await fetch(`${url.replace(/\/$/, "")}/api/health`, {
      signal: controller.signal,
    });
    const body = (await res.json()) as { ok?: boolean; app?: string };
    return res.ok && body.ok === true && body.app === "LGU Smart Convocation";
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * 33-QA (I16): every connection verdict carries WHEN it was taken. A
 * "Connected" note without a timestamp reads as current truth forever —
 * the note now leads with the local clock time of the probe itself.
 */
function probeNoteFor(reachable: boolean): string {
  return `${formatClock(Date.now())} — ${
    reachable
      ? "Connection successful. Server is reachable."
      : "Could not reach the server. Confirm the address and that the server is running on the same network."
  }`;
}

/** "2500" -> "2,500" for idle display; empty/invalid pass through. */
function formatNumberDisplay(value: string | null | undefined): string {
  const digits = (value ?? "").replace(/[^0-9]/g, "");
  if (!digits) return "";
  const n = Number(digits);
  if (!Number.isFinite(n)) return value ?? "";
  return n.toLocaleString("en-US");
}

interface DateTimeParts {
  y: number;
  m: number;
  d: number;
  hh: number;
  mm: number;
}

const MONTHS_SHORT = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];
const MONTHS_LONG = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

/** "2026-12-12T09:00:00+05:00" -> structured parts (stored form stays ISO). */
function parseIsoLocal(value: string | null | undefined): DateTimeParts | null {
  if (!value) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(value);
  if (!m) return null;
  return { y: Number(m[1]), m: Number(m[2]), d: Number(m[3]), hh: Number(m[4]), mm: Number(m[5]) };
}

function buildIso(p: DateTimeParts): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${p.y}-${pad(p.m)}-${pad(p.d)}T${pad(p.hh)}:${pad(p.mm)}:00+05:00`;
}

function formatDayLabel(p: DateTimeParts): string {
  return `${p.d} ${MONTHS_SHORT[p.m - 1]} ${p.y}`;
}

function formatTimeLabel(p: DateTimeParts): string {
  const h12 = p.hh % 12 === 0 ? 12 : p.hh % 12;
  return `${h12}:${String(p.mm).padStart(2, "0")} ${p.hh < 12 ? "AM" : "PM"}`;
}

/** "2026-12-12T09:00:00+05:00" -> "12 Dec 2026, 9:00 AM" (falls back raw). */
function formatFullLabel(value: string | null | undefined): string {
  if (!value) return "";
  const p = parseIsoLocal(value);
  if (!p) return value;
  return `${formatDayLabel(p)}, ${formatTimeLabel(p)}`;
}

/** Percentage width for one of seven equal day columns (typed literal). */
const DAY_CELL_WIDTH = `${100 / 7}%` as `${number}%`;

/** Sunday-first day grid; 0 = padding cell. */
function calendarGrid(year: number, month: number): number[] {
  const firstWeekday = new Date(Date.UTC(year, month - 1, 1)).getUTCDay();
  const daysInMonth = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const cells: number[] = Array.from({ length: firstWeekday }, () => 0);
  for (let d = 1; d <= daysInMonth; d += 1) cells.push(d);
  while (cells.length % 7 !== 0) cells.push(0);
  return cells;
}

/**
 * Admin — the ONLY surface where server addresses and convocation
 * configuration live (spec §7 exception). Everything else in the app
 * speaks plain operational language. Sections (35I W.1): two clearly
 * separated surfaces — "Server connection" (address + connectivity) and
 * "Convocation details" (event config + expected attendance) — plus
 * operational quick actions. 35I (W.2): operator copy says "server",
 * never the architecture word "backend". 35I (W.3): the connection pill
 * probes on load, so it always resolves to Connected / Can't reach
 * server — never a stuck CHECKING state. 33-QA (I16): every verdict is
 * stamped with the probe time (see probeNoteFor).
 */
export function AdminScreen() {
  const [mode, setMode] = useState<"auto" | "custom">("auto");
  const [url, setUrl] = useState("");
  const [urlError, setUrlError] = useState<string | null>(null);
  // 33-QA (P8-27): in automatic mode the address field shows the
  // EFFECTIVE server as its placeholder — operators see which server the
  // device is actually using before deciding to pin one.
  const [effectiveUrl, setEffectiveUrl] = useState("");
  const [probeState, setProbeState] = useState<ProbeState>("idle");
  const [probeNote, setProbeNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [settings, setSettings] = useState<Parameters<typeof updateSettings>[0] | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [settingsLoading, setSettingsLoading] = useState(true);
  const [savingSettings, setSavingSettings] = useState(false);
  const [savedNote, setSavedNote] = useState<string | null>(null);
  const [queueDepth, setQueueDepth] = useState(0);
  // Attendance display: raw digits while focused, grouped when idle.
  const [attendanceFocused, setAttendanceFocused] = useState(false);
  // Date/time picker sheet (Phase 35H): structured editors, no free text.
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerParts, setPickerParts] = useState<DateTimeParts | null>(null);
  const [cursor, setCursor] = useState<{ y: number; m: number }>({
    y: 2026,
    m: 12,
  });
  // Baseline snapshot of the last loaded/saved settings — drives the
  // dirty check that disables Save when nothing has changed (35H).
  const [baseline, setBaseline] = useState<string | null>(null);

  const load = useCallback(async () => {
    setSettingsLoading(true);
    try {
      const [storedMode, storedUrl, convocation, queue] = await Promise.all([
        getApiBaseUrlMode(),
        getApiBaseUrl(),
        getSettings(),
        getQueue(),
      ]);
      setMode(storedMode);
      setUrl(storedMode === "custom" ? storedUrl : "");
      setSettings(convocation);
      setBaseline(JSON.stringify(convocation));
      setSettingsError(null);
      setQueueDepth(queue.length);
      // 35I (W.3): probe the EFFECTIVE server address on load so the pill
      // always resolves to a real state — never a stuck "Checking".
      const effective = (await getApiBaseUrl()) ?? storedUrl;
      setEffectiveUrl(effective);
      const reachable = await probe(effective);
      setProbeState(reachable ? "ok" : "fail");
      setProbeNote(probeNoteFor(reachable));
    } catch (e) {
      setSettingsError(
        e instanceof Error
          ? e.message
          : "Admin data could not be loaded. Check the connection and retry.",
      );
    } finally {
      setSettingsLoading(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      void load();
    }, [load]),
  );

  const runProbe = useCallback(
    async (candidate: string) => {
      setProbeState("probing");
      setProbeNote(null);
      const reachable = await probe(candidate);
      if (reachable) {
        setProbeState("ok");
        setProbeNote(probeNoteFor(true));
      } else {
        setProbeState("fail");
        setProbeNote(probeNoteFor(false));
      }
      return reachable;
    },
    [],
  );

  const saveConnection = useCallback(async () => {
    const trimmed = url.trim().replace(/\/$/, "");
    if (!isValidBaseUrl(trimmed)) {
      setUrlError("Enter a full HTTPS address, e.g. https://demo.example.org");
      return;
    }
    setUrlError(null);
    setBusy(true);
    try {
      const reachable = await runProbe(trimmed);
      if (!reachable) return;
      await setApiBaseUrl(trimmed);
      setMode("custom");
    } catch (e) {
      setUrlError(e instanceof Error ? e.message : "Could not save connection.");
    } finally {
      setBusy(false);
    }
  }, [url, runProbe]);

  const applyAutomatic = useCallback(async () => {
    setBusy(true);
    try {
      await resetToAutomaticBackend();
      setMode("auto");
      setUrl("");
      setUrlError(null);
      // 35I (W.3): re-probe the newly effective server so the pill
      // resolves instead of idling at "Checking".
      const effective = await getApiBaseUrl();
      setEffectiveUrl(effective);
      const reachable = await probe(effective);
      setProbeState(reachable ? "ok" : "fail");
      setProbeNote(probeNoteFor(reachable));
    } catch (e) {
      setUrlError(e instanceof Error ? e.message : "Could not reset connection.");
    } finally {
      setBusy(false);
    }
  }, []);

  const settingsDirty =
    baseline !== null &&
    settings !== null &&
    JSON.stringify(settings) !== baseline;

  const saveSettings = useCallback(async () => {
    if (!settings) return;
    const parts = parseIsoLocal(settings.convocation_datetime);
    if (!parts) {
      setSettingsError(
        "Enter a valid date and time — e.g. 12 Dec 2026, 9:00 AM.",
      );
      return;
    }
    const attendance = Number(settings.expected_attendance);
    // 33-QA (I24): realistic cap — values beyond convocation scale are
    // rejected instead of silently accepted.
    if (!Number.isFinite(attendance) || attendance < 0 || attendance > 25000) {
      setSettingsError("Enter an expected attendance between 0 and 25,000.");
      return;
    }
    setSavingSettings(true);
    setSavedNote(null);
    setSettingsError(null);
    try {
      // Year is derived from the chosen date — never a free-text field.
      const next = await updateSettings({
        convocation_name: settings.convocation_name,
        university_name: settings.university_name,
        venue: settings.venue,
        expected_attendance: settings.expected_attendance,
        convocation_year: String(parts.y),
        convocation_datetime: buildIso(parts),
      });
      setSettings(next);
      setBaseline(JSON.stringify(next));
      setSavedNote("Convocation details saved.");
    } catch (e) {
      setSettingsError(
        e instanceof Error ? e.message : "Settings could not be saved.",
      );
    } finally {
      setSavingSettings(false);
      setTimeout(() => setSavedNote(null), 2500);
    }
  }, [settings]);

  const patchSettings = useCallback(
    (patch: Partial<NonNullable<typeof settings>>) => {
      setSettings((prev) => (prev ? { ...prev, ...patch } : prev));
    },
    [],
  );

  const shiftMonth = useCallback((delta: number) => {
    setCursor((prev) => {
      const next = new Date(Date.UTC(prev.y, prev.m - 1 + delta, 1));
      return { y: next.getUTCFullYear(), m: next.getUTCMonth() + 1 };
    });
  }, []);

  const commitPicker = useCallback(() => {
    if (!pickerParts) return;
    patchSettings({ convocation_datetime: buildIso(pickerParts) });
    setPickerOpen(false);
  }, [pickerParts, patchSettings]);

  return (
    // Light in-screen header (Phase 35G: dark native header removed).
    <Screen>
      {/* 35M item 16: the eyebrow "Admin" is a plain sans label —
          the shared eyebrowSans family, not DM Mono. */}
      <AppHeader
        onBack={() =>
          router.canGoBack() ? router.back() : router.replace("/mode-picker")
        }
        eyebrow="Admin"
        eyebrowSans
        title="System configuration"
        subtitle="Dashboard availability, server connection and convocation details"
      />

      <DashboardControls />
      {/* ------------------------------------------------- server connection */}
      <SectionCard>
        <SectionEyebrow>Server connection</SectionEyebrow>
        <View style={styles.connRow}>
          <View style={styles.flex1}>
            <Text style={styles.connTitle}>
              {mode === "custom" ? "Custom address" : "Automatic discovery"}
            </Text>
            <Text style={styles.connBody}>
              {mode === "custom"
                ? "Using a manually saved server address"
                : "Server found automatically on the local network"}
            </Text>
            {/* QA fix cycle 2 (server address): the operator always sees
                WHICH server the device is actually using. QA fix cycle 4
                (Finding 12): automatic mode states "dynamic IP" instead of
                leaking a discovered host; custom shows the saved address. */}
            {effectiveUrl ? (
              <Text style={styles.connBody}>
                {mode === "custom"
                  ? `Using: Custom (${effectiveUrl.replace(/^https?:\/\//, "")})`
                  : "Using: Automatic (dynamic IP)"}
              </Text>
            ) : null}
          </View>
          <StatusPill
            state={
              probeState === "ok"
                ? "live"
                : probeState === "fail"
                  ? "offline"
                  : "connecting"
            }
            label={
              probeState === "ok"
                ? "Connected"
                : probeState === "fail"
                  ? "Can't reach server"
                  : "Checking"
            }
            size="sm"
          />
        </View>

        {/* 33-QA (P8-27): automatic mode shows the effective server in
            the placeholder — the field never hides which server the
            device is using. */}
        <Field
          label="Server address"
          placeholder={
            mode === "custom" || !effectiveUrl
              ? "e.g. http://192.168.1.10:5000"
              : effectiveUrl
          }
          value={url}
          onChangeText={(t) => {
            setUrl(t);
            setUrlError(null);
          }}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
          error={urlError}
          hint="Used when Automatic discovery cannot find the server (e.g. a different subnet)."
        />
        {probeNote ? (
          <Text
            style={[
              styles.probeNote,
              probeState === "ok" ? styles.probeOk : styles.probeFail,
            ]}
          >
            {probeNote}
          </Text>
        ) : null}

        <View style={styles.connButtons}>
          <View style={styles.flex1}>
            <AppButton
              label={busy ? "Working…" : "Save & test"}
              icon="cloud-upload-outline"
              loading={busy}
              onPress={() => void saveConnection()}
            />
          </View>
          <View style={styles.flex1}>
            <AppButton
              label="Use automatic"
              icon="flash-outline"
              variant="secondary"
              disabled={busy || mode === "auto"}
              onPress={() => void applyAutomatic()}
            />
          </View>
        </View>
        {/* QA fix cycle 3 (Issue 12): a disabled action always explains
            itself — never a dead control with no reason. */}
        {mode === "auto" && !busy ? (
          <Text style={styles.btnNote}>Automatic is already active.</Text>
        ) : null}
      </SectionCard>

      {/* ----------------------------------------------- convocation details */}
      {settingsLoading ? (
        <SectionCard>
          <LoadingState label="Loading convocation details…" />
        </SectionCard>
      ) : settingsError && !settings ? (
        <SectionCard>
          <ErrorState title="Settings unavailable" body={settingsError} onRetry={() => void load()} />
        </SectionCard>
      ) : settings ? (
        <SectionCard>
          <SectionEyebrow>Convocation details</SectionEyebrow>
          <Field
            label="Convocation name"
            value={settings.convocation_name}
            onChangeText={(t) => patchSettings({ convocation_name: t })}
          />
          {/* Phase 35K (F): the institution name shown on event screens is
              saved here — event screens read it from /api/config, not from
              a hard-coded constant. */}
          <Field
            label="University name"
            value={settings.university_name}
            onChangeText={(t) => patchSettings({ university_name: t })}
          />
          <View>
            <Text style={styles.dtLabel}>Date and time</Text>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={`Date and time, ${formatFullLabel(settings.convocation_datetime)}`}
              onPress={() => {
                const parts =
                  parseIsoLocal(settings.convocation_datetime) ??
                  { y: 2026, m: 12, d: 12, hh: 9, mm: 0 };
                setPickerParts(parts);
                setCursor({ y: parts.y, m: parts.m });
                setPickerOpen(true);
              }}
              style={styles.dtField}
            >
              <Text style={styles.dtValue}>
                {formatFullLabel(settings.convocation_datetime)}
              </Text>
              <Ionicons name="calendar-outline" size={18} color={colors.muted} />
            </Pressable>
            <Text style={styles.dtHint}>
              All convocation times are Pakistan Standard Time (UTC+5).
            </Text>
          </View>
          <Field
            label="Expected attendance"
            value={
              attendanceFocused
                ? settings.expected_attendance
                : formatNumberDisplay(settings.expected_attendance)
            }
            onChangeText={(t) =>
              patchSettings({ expected_attendance: t.replace(/[^0-9]/g, "") })
            }
            onFocus={() => setAttendanceFocused(true)}
            onBlur={() => setAttendanceFocused(false)}
            keyboardType="number-pad"
            hint="Enter a number up to 25,000"
          />
          <Field
            label="Venue"
            value={settings.venue}
            onChangeText={(t) => patchSettings({ venue: t })}
          />
          {settingsError ? <Text style={styles.formError}>{settingsError}</Text> : null}
          {savedNote ? <Text style={styles.savedNote}>{savedNote}</Text> : null}
          <AppButton
            label={savingSettings ? "Saving…" : "Save details"}
            icon="save-outline"
            loading={savingSettings}
            disabled={!settingsDirty || savingSettings}
            onPress={() => void saveSettings()}
          />
          {/* QA fix cycle 3 (Issue 12): explain the disabled save. */}
          {!settingsDirty && !savingSettings ? (
            <Text style={styles.btnNote}>No changes to save.</Text>
          ) : null}
        </SectionCard>
      ) : null}

      {/* ------------------------------------------------- operational tools */}
      <SectionCard>
        <SectionEyebrow>Operations</SectionEyebrow>
        <View style={styles.opsRow}>
          <View style={styles.flex1}>
            <Text style={styles.connTitle}>Queued offline scans</Text>
            <Text style={styles.connBody}>
              {queueDepth > 0
                ? `${queueDepth} scan(s) waiting on this device — sync from the Scanner.`
                : "Nothing waiting — all scans are synced."}
            </Text>
          </View>
          <View style={styles.opsStatus}>
            <Ionicons
              name={queueDepth > 0 ? "time-outline" : "checkmark-circle"}
              size={20}
              color={queueDepth > 0 ? colors.amber : colors.valid}
            />
            <Text style={styles.opsStatusText}>
              {queueDepth > 0 ? `${queueDepth} waiting` : "All synced"}
            </Text>
          </View>
        </View>
        <AppButton
          label="Open announcements"
          icon="megaphone-outline"
          variant="secondary"
          onPress={() => router.push("/(volunteer)/broadcast")}
        />
      </SectionCard>

      {/* ------------------------------------- date/time picker sheet (35H) */}
      <Modal
        visible={pickerOpen}
        transparent
        animationType="slide"
        onRequestClose={() => setPickerOpen(false)}
      >
        <View style={styles.pickerBackdrop}>
          <View style={styles.pickerCard}>
            <ScrollView
              keyboardShouldPersistTaps="handled"
              showsVerticalScrollIndicator={false}
            >
              <Text style={styles.pickerTitle}>Date and time</Text>
              <Text style={styles.pickerSub}>
                {pickerParts
                  ? `${formatDayLabel(pickerParts)}, ${formatTimeLabel(pickerParts)}`
                  : ""}
              </Text>

              <View style={styles.monthRow}>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="Previous month"
                  onPress={() => shiftMonth(-1)}
                  style={styles.monthBtn}
                >
                  <Ionicons name="chevron-back" size={20} color={colors.ink} />
                </Pressable>
                <Text style={styles.monthLabel}>
                  {MONTHS_LONG[cursor.m - 1]} {cursor.y}
                </Text>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="Next month"
                  onPress={() => shiftMonth(1)}
                  style={styles.monthBtn}
                >
                  <Ionicons name="chevron-forward" size={20} color={colors.ink} />
                </Pressable>
              </View>

              <View style={styles.weekRow}>
                {["S", "M", "T", "W", "T", "F", "S"].map((d, i) => (
                  <Text key={`${d}-${i}`} style={styles.weekday}>
                    {d}
                  </Text>
                ))}
              </View>
              <View style={styles.dayGrid}>
                {calendarGrid(cursor.y, cursor.m).map((day, idx) => {
                  if (day === 0) {
                    return <View key={`pad-${idx}`} style={styles.dayCell} />;
                  }
                  const selected =
                    pickerParts !== null &&
                    pickerParts.y === cursor.y &&
                    pickerParts.m === cursor.m &&
                    pickerParts.d === day;
                  return (
                    <Pressable
                      key={day}
                      accessibilityRole="button"
                      accessibilityState={{ selected }}
                      accessibilityLabel={`${day} ${MONTHS_LONG[cursor.m - 1]} ${cursor.y}`}
                      onPress={() =>
                        setPickerParts((prev) =>
                          prev ? { ...prev, y: cursor.y, m: cursor.m, d: day } : prev,
                        )
                      }
                      style={[styles.dayCell, selected && styles.dayCellActive]}
                    >
                      <Text
                        style={[styles.dayText, selected && styles.dayTextActive]}
                      >
                        {day}
                      </Text>
                    </Pressable>
                  );
                })}
              </View>

              <Text style={styles.pickerLabel}>Hour</Text>
              <View style={styles.chipWrap}>
                {Array.from({ length: 24 }, (_, h) => h).map((h) => {
                  const label = `${h % 12 === 0 ? 12 : h % 12} ${h < 12 ? "AM" : "PM"}`;
                  const active = pickerParts?.hh === h;
                  return (
                    <Pressable
                      key={h}
                      accessibilityRole="button"
                      accessibilityState={{ selected: active }}
                      accessibilityLabel={label}
                      onPress={() =>
                        setPickerParts((prev) => (prev ? { ...prev, hh: h } : prev))
                      }
                      style={[styles.chip, active && styles.chipActive]}
                    >
                      <Text style={[styles.chipText, active && styles.chipTextActive]}>
                        {label}
                      </Text>
                    </Pressable>
                  );
                })}
              </View>

              <Text style={styles.pickerLabel}>Minute</Text>
              <View style={styles.chipWrap}>
                {[0, 15, 30, 45].map((m) => {
                  const label = String(m).padStart(2, "0");
                  const active = pickerParts?.mm === m;
                  return (
                    <Pressable
                      key={m}
                      accessibilityRole="button"
                      accessibilityState={{ selected: active }}
                      accessibilityLabel={`Minute ${label}`}
                      onPress={() =>
                        setPickerParts((prev) => (prev ? { ...prev, mm: m } : prev))
                      }
                      style={[styles.chip, active && styles.chipActive]}
                    >
                      <Text style={[styles.chipText, active && styles.chipTextActive]}>
                        {label}
                      </Text>
                    </Pressable>
                  );
                })}
              </View>
            </ScrollView>
            <AppButton
              label="Set date and time"
              icon="checkmark"
              onPress={commitPicker}
            />
            <AppButton
              label="Cancel"
              variant="secondary"
              onPress={() => setPickerOpen(false)}
            />
          </View>
        </View>
      </Modal>
    </Screen>
  );
}

const styles = {
  // 33-QA (I7): text containers beside StatusPills need minWidth:0 —
  // long server URLs must not inflate the row and clip the pill.
  flex1: { flex: 1, minWidth: 0 },
  connRow: {
    flexDirection: "row" as const,
    alignItems: "center" as const,
    gap: spacing.sm,
    marginBottom: spacing.md,
  },
  connTitle: {
    fontFamily: fonts.display,
    fontSize: 15,
    color: colors.ink,
  },
  connBody: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.muted,
    marginTop: 2,
    lineHeight: 18,
  },
  probeNote: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    marginTop: spacing.sm,
    lineHeight: 18,
  },
  probeOk: {
    color: colors.valid,
  },
  probeFail: {
    color: colors.invalid,
  },
  connButtons: {
    flexDirection: "row" as const,
    gap: spacing.sm,
    marginTop: spacing.md,
  },
  formError: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.invalid,
    marginBottom: spacing.sm,
    lineHeight: 18,
  },
  savedNote: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.valid,
    marginBottom: spacing.sm,
    lineHeight: 18,
  },
  opsRow: {
    flexDirection: "row" as const,
    alignItems: "center" as const,
    gap: spacing.sm,
    marginBottom: spacing.md,
  },
  opsStatus: {
    flexDirection: "row" as const,
    alignItems: "center" as const,
    gap: 4,
  },
  opsStatusText: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.ink,
  },
  dtLabel: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.ink,
    marginBottom: 6,
  },
  dtField: {
    flexDirection: "row" as const,
    alignItems: "center" as const,
    justifyContent: "space-between" as const,
    minHeight: 52,
    borderWidth: 1,
    borderColor: colors.track,
    borderRadius: radius.md,
    backgroundColor: colors.paper,
    paddingHorizontal: spacing.md,
  },
  dtValue: {
    fontFamily: fonts.displayMedium,
    fontSize: 15,
    color: colors.ink,
  },
  dtHint: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.muted,
    marginTop: 6,
    lineHeight: 18,
  },
  btnNote: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.muted,
    marginTop: 6,
    lineHeight: 18,
  },
  pickerBackdrop: {
    flex: 1,
    backgroundColor: colors.overlay,
    justifyContent: "flex-end" as const,
  },
  pickerCard: {
    backgroundColor: colors.paper,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.track,
    padding: spacing.screen,
    paddingBottom: spacing.lg,
    gap: spacing.sm,
    maxHeight: "88%" as const,
  },
  pickerTitle: {
    fontFamily: fonts.display,
    fontSize: 24,
    letterSpacing: -0.4,
    color: colors.ink,
  },
  pickerSub: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.muted,
    lineHeight: 18,
  },
  pickerLabel: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.ink,
    marginTop: spacing.sm,
  },
  monthRow: {
    flexDirection: "row" as const,
    alignItems: "center" as const,
    justifyContent: "space-between" as const,
  },
  monthBtn: {
    padding: 8,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.track,
  },
  monthLabel: {
    fontFamily: fonts.display,
    fontSize: 15,
    color: colors.ink,
  },
  weekRow: {
    flexDirection: "row" as const,
  },
  weekday: {
    // 35M item 18: calendar day letters are normal labels — sans,
    // not DM Mono (mono is reserved for status chips + identifiers).
    flex: 1,
    textAlign: "center" as const,
    fontFamily: fonts.displayMedium,
    fontSize: 11,
    color: colors.muted,
    marginBottom: 4,
  },
  dayGrid: {
    flexDirection: "row" as const,
    flexWrap: "wrap" as const,
  },
  dayCell: {
    width: DAY_CELL_WIDTH,
    aspectRatio: 1,
    alignItems: "center" as const,
    justifyContent: "center" as const,
  },
  dayCellActive: {
    backgroundColor: colors.ink,
    borderRadius: radius.sm,
  },
  dayText: {
    fontFamily: fonts.displayMedium,
    fontSize: 15,
    color: colors.ink,
  },
  dayTextActive: {
    // 35M R2 (item 14): family encodes the weight — display (bold).
    fontFamily: fonts.display,
    color: colors.paper,
  },
  chipWrap: {
    flexDirection: "row" as const,
    flexWrap: "wrap" as const,
    gap: 6,
  },
  chip: {
    flexGrow: 1,
    flexBasis: "30%",
    alignItems: "center" as const,
    justifyContent: "center" as const,
    minHeight: 40,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.track,
    backgroundColor: colors.paper,
  },
  chipActive: {
    backgroundColor: colors.ink,
    borderColor: colors.ink,
  },
  chipText: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.ink,
  },
  chipTextActive: {
    // 35M R2 (item 14): family encodes the weight — display (bold).
    fontFamily: fonts.display,
    color: colors.paper,
  },
};
