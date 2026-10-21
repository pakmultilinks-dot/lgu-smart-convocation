import { Ionicons } from "@expo/vector-icons";
import { router, useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { Text, View } from "react-native";
import {
  getApiBaseUrl,
  getApiBaseUrlMode,
  getVolunteerName,
  probeBackend,
  setVolunteerName,
} from "../store/settings";
import { isValidVolunteerName } from "../scanner/scanResultLogic";
import { getAppMode, type AppMode } from "../store/appMode";
import { queueCount } from "../store/offlineQueue";
import { colors, fonts, spacing } from "../theme";
import {
  AppButton,
  AppHeader,
  Field,
  Screen,
  SectionCard,
  SectionEyebrow,
  StatusPill,
  formatClock,
} from "../ui";

/**
 * Settings — Screen 5 of the institutional system (Phase 35C).
 * Title exactly "Settings" (35I U.2: no event eyebrow — the title alone
 * names the screen). Sections: Volunteer name / Mode / Advanced,
 * separated by dashed divider lines; the broadcast entry moved to More
 * (admin-gated) in Phase 35G. Exactly ONE
 * "Change mode" action (the reset row and all developer terminology are
 * removed); connection wording is operator language only. 35I (U.1):
 * Save name is disabled unless the text actually changed — the baseline
 * is the stored volunteer name itself (no duplicate storage key).
 */
export function SettingsScreen() {
  const [name, setName] = useState("");
  const [nameBaseline, setNameBaseline] = useState("");
  const [mode, setMode] = useState<AppMode | null>(null);
  const [baseUrlMode, setBaseUrlMode] = useState<"auto" | "custom">("auto");
  const [hostHint, setHostHint] = useState("");
  const [queued, setQueued] = useState(0);
  const [saved, setSaved] = useState(false);
  // 33-QA (I16): the Advanced pill reports a REAL probe of the effective
  // server — never "READY" from queue state alone — and every verdict is
  // stamped with the time it was taken.
  const [probe, setProbe] = useState<"idle" | "checking" | "ok" | "down">("idle");
  const [testedAt, setTestedAt] = useState(0);

  useFocusEffect(
    useCallback(() => {
      let cancelled = false;
      void (async () => {
        const [storedName, storedMode, apiMode, url, q] = await Promise.all([
          getVolunteerName(),
          getAppMode(),
          getApiBaseUrlMode(),
          getApiBaseUrl(),
          queueCount(),
        ]);
        if (cancelled) return;
        setName(storedName);
        setNameBaseline(storedName);
        setMode(storedMode);
        setBaseUrlMode(apiMode);
        // Host portion only — a raw address is never shown in the list.
        setHostHint(url ? url.replace(/^https?:\/\//, "").split("/")[0] ?? "" : "");
        setQueued(q);
        // 33-QA (I16): probe the effective server on every focus so the
        // pill is a timestamped truth, not a guess from queue state.
        setProbe("checking");
        const reachable = await probeBackend(url ?? "");
        if (cancelled) return;
        setProbe(reachable ? "ok" : "down");
        setTestedAt(Date.now());
      })();
      return () => {
        cancelled = true;
      };
    }, []),
  );

  // 35I (U.1): save only meaningful — trimmed text must be non-empty and
  // different from the stored baseline; after save the baseline follows.
  // 35L (F): a usable identity is at least 2 letters — invalid names are
  // never stored or saved.
  const trimmedName = name.trim();
  const nameValid = isValidVolunteerName(trimmedName);
  const nameDirty = nameValid && trimmedName !== nameBaseline;

  const saveName = useCallback(() => {
    // Same validity rule as scanning (35L F) — the stamped name must be
    // a real name, never blank/single-char/whitespace.
    if (!nameValid || trimmedName === nameBaseline) return;
    void setVolunteerName(trimmedName);
    setName(trimmedName);
    setNameBaseline(trimmedName);
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
  }, [nameValid, trimmedName, nameBaseline]);

  const switchMode = useCallback(() => {
    // Phase 27 (E3): navigate ONLY — the stored mode is deliberately left
    // intact so the picker can compare against it and confirm a change.
    // Clearing it here (the old behaviour) meant the picker loaded no
    // current mode, its guard passed straight through and the confirm step
    // (33-QA I21) was skipped: one stray tap silently changed the device
    // role. Choosing a surface is navigation, never authorization.
    router.replace("/mode-picker");
  }, []);

  return (
    <Screen>
      <AppHeader
        onBack={() =>
          router.canGoBack() ? router.back() : router.replace("/(volunteer)/more")
        }
        title="Settings"
        subtitle="Device and operator preferences"
      />

      {/* 1 — Volunteer name (QA fix cycle 2: ONE naming — the eyebrow
          carries it; the field is a placeholder-only input, no second
          "Name on scan records" label. */}
      <SectionCard>
        <SectionEyebrow>Volunteer name</SectionEyebrow>
        <Field
          placeholder="e.g. Bilal Ahmad"
          value={name}
          onChangeText={setName}
          autoCapitalize="words"
          returnKeyType="done"
          onEndEditing={saveName}
          hint="Stamped on every scan this device records."
        />
        {/* 35L (F): an explicit note when the typed name can't be used. */}
        {trimmedName !== "" && !isValidVolunteerName(trimmedName) ? (
          <Text style={styles.nameError}>
            Enter a real name of at least 2 letters.
          </Text>
        ) : null}
        {/* QA fix cycle 2: a disabled Save explains itself. */}
        {!nameDirty && isValidVolunteerName(trimmedName) ? (
          <Text style={styles.nameHint}>Change the name to save.</Text>
        ) : null}
        <AppButton
          label={saved ? "Saved" : "Save name"}
          icon={saved ? "checkmark" : "save-outline"}
          variant={saved ? "secondary" : "primary"}
          disabled={!nameDirty}
          onPress={saveName}
        />
      </SectionCard>

      {/* 2 — Mode: exactly one change action */}
      <SectionCard tone="tint">
        <SectionEyebrow>Mode</SectionEyebrow>
        <View style={styles.row}>
          <View style={styles.flex1}>
            <Text style={styles.rowTitle}>
              {mode === "liveboard" ? "Live Dashboard" : "Volunteer Operations"}
            </Text>
            <Text style={styles.rowBody}>
              {mode === "liveboard"
                ? "Public attendance view"
                : "Gate scanning and guest management"}
            </Text>
          </View>
          <StatusPill state="info" label="Active" size="sm" />
        </View>
        <AppButton
          label="Change mode"
          icon="swap-horizontal"
          variant="secondary"
          onPress={switchMode}
        />
      </SectionCard>

      {/* 3 — Advanced: operator language only, quiet queue row */}
      <SectionCard tone="tint">
        <SectionEyebrow>Advanced</SectionEyebrow>
        <View style={styles.row}>
          <View style={styles.flex1}>
            <Text style={styles.rowTitle}>
              {baseUrlMode === "custom" ? "Custom server" : "Automatic"}
            </Text>
            <Text style={styles.rowBody}>
              {baseUrlMode === "custom"
                ? hostHint || "Address not reachable"
                : "Connects to the convocation server"}
            </Text>
            {/* 33-QA (I16): when the verdict was taken, on the row. */}
            {testedAt > 0 ? (
              <Text style={styles.rowBody}>Tested {formatClock(testedAt)}</Text>
            ) : null}
          </View>
          {/* 33-QA (I16) → QA fix cycle 2: the pill is the probe verdict
              — Live/Offline/Checking (sentence case) — never "Ready"
              derived from queue state. The queued count stays visible in
              the queue row below. */}
          <StatusPill
            state={
              probe === "ok"
                ? "live"
                : probe === "down"
                  ? "offline"
                  : "connecting"
            }
            label={
              probe === "ok" ? "Live" : probe === "down" ? "Offline" : "Checking"
            }
            size="sm"
          />
        </View>
        <AppButton
          label="Connection settings"
          icon="settings-outline"
          variant="secondary"
          onPress={() => router.push("/(volunteer)/admin")}
        />
        {/* Quiet queue status — no technical language. 33-QA (I16): an
            offline device never claims "All scans synced" — it says the
            scans are waiting, truthfully, with the count. */}
        <View style={styles.queueRow}>
          <Ionicons
            name={
              queued > 0
                ? "cloud-upload-outline"
                : probe === "down"
                  ? "cloud-offline-outline"
                  : "cloud-done-outline"
            }
            size={16}
            color={queued > 0 || probe === "down" ? colors.amber : colors.muted}
          />
          <Text style={styles.queueText}>
            {queued > 0
              ? `${queued} scan(s) waiting to sync`
              : probe === "down"
                ? "No scans waiting to sync · server unreachable"
                : "All scans synced"}
          </Text>
        </View>
      </SectionCard>
    </Screen>
  );
}

const styles = {
  // 33-QA (I7): text containers beside StatusPills need minWidth:0 —
  // without it, long single-line text inflates the row and can push
  // or clip the pill at narrow widths (Yoga automatic minimum sizing).
  flex1: { flex: 1, minWidth: 0 },
  nameError: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.invalid,
  },
  nameHint: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.muted,
  },
  row: {
    flexDirection: "row" as const,
    alignItems: "center" as const,
    gap: spacing.md,
    paddingVertical: spacing.sm,
  },
  rowTitle: {
    fontFamily: fonts.displayMedium,
    fontSize: 15,
    color: colors.ink,
  },
  rowBody: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.muted,
    marginTop: 2,
    lineHeight: 18,
  },
  queueRow: {
    flexDirection: "row" as const,
    alignItems: "center" as const,
    gap: spacing.sm,
    paddingTop: spacing.sm,
  },
  queueText: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.muted,
    lineHeight: 18,
  },
};
