import { Ionicons } from "@expo/vector-icons";
import { router } from "expo-router";
import { useEffect, useState } from "react";
import { Modal, Pressable, StyleSheet, Text, View } from "react-native";
import { fetchAppConfig, fetchDashboardAccess, type AppConfig } from "../src/api/client";
import { APP_TITLE_SHORT, UNIVERSITY_NAME, eventTitle } from "../src/config";
import {
  getAppMode,
  needsModeConfirmation,
  setAppMode,
  type AppMode,
} from "../src/store/appMode";
import { colors, fonts, radius, spacing } from "../src/theme";
import { useDashboardAvailability } from "../src/hooks/useDashboardAvailability";
import { AppButton, LguMark, Screen } from "../src/ui";

interface Choice {
  mode: AppMode;
  title: string;
  subtitle: string;
  icon: keyof typeof Ionicons.glyphMap;
}

const CHOICES: Choice[] = [
  {
    mode: "student",
    title: "Student Portal",
    subtitle: "Registration, updates and your personal QR entry pass.",
    icon: "school-outline",
  },
  {
    mode: "volunteer",
    title: "Volunteer Operations",
    subtitle: "Check-in, guest passes and gate operations.",
    icon: "qr-code-outline",
  },
  {
    mode: "liveboard",
    title: "Live Dashboard",
    subtitle: "Live admissions and attendance for event screens.",
    icon: "tv-outline",
  },
];

function targetFor(mode: AppMode): "/(volunteer)/home" | "/(liveboard)" | "/(student)" {
  if (mode === "volunteer") return "/(volunteer)/home";
  return mode === "student" ? "/(student)" : "/(liveboard)";
}

/** Student-first entry point; event tools have independent server controls. */
export default function ModePickerScreen() {
  const [busy, setBusy] = useState<AppMode | null>(null);
  const [cfg, setCfg] = useState<AppConfig | null>(null);
  const [current, setCurrent] = useState<AppMode | null>(null);
  const [pending, setPending] = useState<AppMode | null>(null);
  const [accessError, setAccessError] = useState<string | null>(null);
  const { access, state: connection, refresh } = useDashboardAvailability();

  // 35M items 2 + 20: consume the SERVER convocation configuration for
  // the brand title — eventTitle() stays as the offline fallback.
  useEffect(() => {
    let cancelled = false;
    void fetchAppConfig()
      .then((data) => {
        if (!cancelled) setCfg(data);
      })
      .catch(() => {
        // Best-effort: the fallback title keeps the picker honest offline.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // 33-QA (I21): the device's current mode is loaded so a switch to a
  // DIFFERENT surface is confirmed first — a stray tap on the kiosk
  // never silently turns the live dashboard into a scanning station
  // (or the reverse). Picking the mode already active stays one tap.
  useEffect(() => {
    void getAppMode().then((mode) => setCurrent(mode));
  }, []);

  const commit = async (mode: AppMode) => {
    setBusy(mode);
    try {
      setAccessError(null);
      if (mode !== "student") {
        const next = await fetchDashboardAccess();
        if (next[mode] !== true) {
          setAccessError("This dashboard is currently disabled by the administrator.");
          return;
        }
      }
      await setAppMode(mode);
      router.replace(targetFor(mode));
    } catch (e) {
      setAccessError(e instanceof Error ? e.message : "Could not open dashboard.");
    } finally {
      setBusy(null);
      setPending(null);
    }
  };

  // 33-QA (I21): explicit confirm step before the device role changes —
  // Confirm/Cancel, keyboard- and screen-reader-labelled. Phase 27 (E3):
  // the rule lives in needsModeConfirmation() and fails CLOSED, so this
  // screen (the only writer of the stored mode) can never be walked past
  // by an entry point that arrives with nothing stored. Committing is the
  // only place the mode changes, and it writes before it navigates.
  const pick = (mode: AppMode) => {
    if (busy) return;
    if (needsModeConfirmation(current, mode)) {
      setPending(mode);
      return;
    }
    void commit(mode);
  };

  return (
    <Screen>
      <View style={styles.top}>
        <LguMark size={44} />
        <View style={styles.brandText}>
          <Text style={styles.university}>{cfg?.university || UNIVERSITY_NAME}</Text>
          <Text style={styles.title}>{APP_TITLE_SHORT}</Text>
        </View>
      </View>
      <View style={styles.intro}>
        <Text style={styles.eyebrow}>ONE EVENT. EVERYTHING IN ONE PLACE.</Text>
        <Text style={styles.heading}>Your convocation, simplified.</Text>
        <Text style={styles.description}>Students, volunteers and event teams each have their own workspace.</Text>
        <View style={styles.rule} />
      </View>

      <View style={styles.connectionPanel}>
        <View style={styles.connectionHeading}>
          <Ionicons name={connection === "online" ? "cloud-done-outline" : "cloud-offline-outline"}
            size={18} color={connection === "offline" ? colors.invalid : colors.ink} />
          <Text style={styles.connectionTitle}>{connection === "online" ? "Connected to university server" :
            connection === "checking" ? "Checking university server..." : "Server connection required"}</Text>
        </View>
        {connection === "offline" ? (
          <Text style={styles.connectionNote}>Sign-in and live event tools need a reachable LGU server.</Text>
        ) : null}
        <View style={styles.networkActions}>
          {connection === "offline" ? (
            <Pressable accessibilityRole="button" accessibilityLabel="Retry university server connection"
              style={styles.networkAction} onPress={refresh}>
              <Ionicons name="refresh" size={16} color={colors.ink} />
              <Text style={styles.networkActionText}>Retry</Text>
            </Pressable>
          ) : null}
          <Pressable accessibilityRole="button" accessibilityLabel="Open server connection settings"
            style={styles.networkAction} onPress={() => router.push("/connect-server")}>
            <Ionicons name="settings-outline" size={16} color={colors.ink} />
            <Text style={styles.networkActionText}>{connection === "online" ? "Server settings" : "Connect to server"}</Text>
            <Ionicons name="chevron-forward" size={15} color={colors.ink} />
          </Pressable>
        </View>
      </View>
      <View style={styles.choices}>
        {CHOICES.map((choice) => {
          const active = busy === choice.mode;
          const student = choice.mode === "student";
          const unavailable = !student && access?.[choice.mode] === false;
          const status = student ? "Student access" : connection === "checking" ? "Checking availability" :
            connection === "offline" ? "Connection required" : unavailable ? "Disabled by admin" : "Enabled";
          return (
            <View key={choice.mode}>
              {choice.mode === "volunteer" ? <Text style={styles.sectionLabel}>EVENT OPERATIONS</Text> : null}
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={`${choice.title}. ${status}`}
                accessibilityState={{ disabled: busy !== null || unavailable, busy: active }}
                disabled={busy !== null || unavailable}
                onPress={() => void pick(choice.mode)}
                style={({ pressed }) => [styles.choice, student && styles.studentChoice,
                  pressed && styles.choicePressed, active && styles.choiceBusy]}
              >
                <View style={styles.cardTop}>
                  <Ionicons name={choice.icon} size={24} color={student ? colors.paper : colors.ink} />
                  <Text style={[styles.status, student && styles.onDark]}>{status}</Text>
                </View>
                <Text style={[styles.choiceTitle, student && styles.studentTitle]}>{choice.title}</Text>
                <Text style={[styles.choiceSubtitle, student && styles.onDark]}>
                  {unavailable ? "Available when the administrator enables this dashboard." : choice.subtitle}
                </Text>
                <View style={styles.cardAction}>
                  <Text style={[styles.actionText, student && styles.onDark]}>
                    {active ? "Opening…" : unavailable ? "Currently unavailable" : student ? "Open Student Portal" : "Open dashboard"}
                  </Text>
                  <Ionicons name={unavailable ? "lock-closed-outline" : "arrow-forward"} size={18}
                    color={student ? colors.paper : colors.ink} />
                </View>
              </Pressable>
              
            </View>
          );
        })}
      </View>
      {accessError ? <Text accessibilityRole="alert" style={styles.error}>{accessError}</Text> : null}
      <AppButton label="Administrator access" variant="ghost" onPress={() => router.push("/administration")} />
      <Text style={styles.footer}>{cfg?.event.name || eventTitle()}</Text>
      {/* 33-QA (I21): explicit confirm step before the device role
          changes — Confirm/Cancel, keyboard- and screen-reader-labelled. */}
      {pending ? (
        <Modal
          visible={pending !== null}
          transparent
          animationType="fade"
          onRequestClose={() => setPending(null)}
        >
          <View style={styles.confirmBackdrop}>
            <View style={styles.confirmBar}>
          <Text style={styles.confirmText}>
            Switch this device to{" "}
            {CHOICES.find((c) => c.mode === pending)?.title}?
          </Text>
          <View style={styles.confirmActions}>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Confirm mode switch"
              onPress={() => {
                const next = pending;
                setPending(null);
                void commit(next);
              }}
              style={styles.confirmBtn}
            >
              <Text style={styles.confirmBtnText}>Confirm</Text>
            </Pressable>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Cancel mode switch"
              onPress={() => setPending(null)}
              style={[styles.confirmBtn, styles.confirmCancel]}
            >
              <Text style={[styles.confirmBtnText, styles.confirmCancelText]}>
                Cancel
              </Text>
            </Pressable>
          </View>
            </View>
          </View>
        </Modal>
      ) : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  top: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingTop: spacing.sm },
  brandText: { flex: 1, gap: spacing.xs },
  title: { color: colors.ink, fontFamily: fonts.display, fontSize: 24, letterSpacing: -0.4 },
  university: { color: colors.muted, fontFamily: fonts.displayMedium, fontSize: 13 },
  intro: { marginTop: spacing.lg, marginBottom: spacing.md },
  eyebrow: { color: colors.muted, fontFamily: fonts.displayMedium, fontSize: 11, letterSpacing: 0.8 },
  heading: { color: colors.ink, fontFamily: fonts.display, fontSize: 24, letterSpacing: -0.4, marginTop: spacing.sm },
  description: { color: colors.muted, fontFamily: fonts.displayMedium, fontSize: 13, lineHeight: 20, marginTop: spacing.xs },
  rule: { width: 56, height: 2, backgroundColor: colors.gold, marginTop: spacing.md },
  choices: { gap: spacing.sm },
  sectionLabel: { color: colors.muted, fontFamily: fonts.displayMedium, fontSize: 11, letterSpacing: 0.8, marginTop: spacing.md, marginBottom: spacing.sm },
  choice: { borderColor: colors.track, borderWidth: 1, borderRadius: radius.lg, padding: spacing.md },
  studentChoice: { backgroundColor: colors.ink, borderColor: colors.ink },
  cardTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: spacing.sm, marginBottom: spacing.sm },
  status: { color: colors.muted, fontFamily: fonts.displayMedium, fontSize: 13 },
  onDark: { color: colors.paper },
  choiceTitle: { color: colors.ink, fontFamily: fonts.display, fontSize: 15 },
  studentTitle: { color: colors.paper, fontSize: 24 },
  choiceSubtitle: { color: colors.muted, fontFamily: fonts.displayMedium, fontSize: 13, lineHeight: 20, marginTop: spacing.xs },
  cardAction: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: spacing.md, minHeight: 40, marginTop: spacing.sm },
  actionText: { color: colors.ink, fontFamily: fonts.displayMedium, fontSize: 13, flexShrink: 1 },
  registrationNote: { color: colors.muted, fontFamily: fonts.displayMedium, fontSize: 13, lineHeight: 20, marginTop: spacing.sm, paddingHorizontal: spacing.xs },
  choicePressed: { opacity: 0.8 },
  choiceBusy: { opacity: 0.65 },
  connectionPanel: { borderWidth: 1, borderColor: colors.track, borderRadius: radius.md, padding: spacing.md, gap: spacing.sm, marginBottom: spacing.md },
  connectionTitle: { flexShrink: 1, color: colors.ink, fontFamily: fonts.display, fontSize: 13 },
  networkActions: { flexDirection: "row", alignItems: "center", gap: spacing.md, flexWrap: "wrap" },
  networkAction: { flexDirection: "row", alignItems: "center", gap: spacing.xs, minHeight: 44, paddingRight: spacing.sm },
  networkActionText: { color: colors.ink, fontFamily: fonts.displayMedium, fontSize: 13 },
  connectionHeading: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  connectionNote: { color: colors.muted, fontFamily: fonts.displayMedium, fontSize: 13, lineHeight: 20 },
  error: { color: colors.invalid, fontFamily: fonts.displayMedium, fontSize: 13, lineHeight: 20, marginTop: spacing.md },
  footer: { color: colors.muted, fontFamily: fonts.displayMedium, fontSize: 11, textAlign: "center", marginTop: spacing.md, marginBottom: spacing.md },
  confirmBackdrop: {
    flex: 1,
    justifyContent: "center",
    paddingHorizontal: spacing.screen,
    backgroundColor: colors.overlay,
  },
  confirmBar: {
    backgroundColor: colors.paper,
    borderRadius: radius.md,
    borderColor: colors.track,
    borderWidth: 1,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    gap: spacing.sm,
  },
  confirmText: {
    color: colors.ink,
    fontFamily: fonts.displayMedium,
    fontSize: 14,
  },
  confirmActions: {
    flexDirection: "row",
    gap: spacing.sm,
  },
  confirmBtn: {
    minHeight: 48,
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.ink,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    borderRadius: radius.button,
  },
  confirmCancel: {
    backgroundColor: colors.track,
  },
  confirmBtnText: {
    color: colors.paper,
    fontFamily: fonts.displayMedium,
    fontSize: 13,
  },
  confirmCancelText: {
    color: colors.ink,
  },
});
