import { Ionicons } from "@expo/vector-icons";
import { router, useFocusEffect } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { Modal, Pressable, StyleSheet, Text, View } from "react-native";
import { fetchAppConfig, fetchDashboardAccess, type AppConfig, type DashboardAccess } from "../src/api/client";
import { UNIVERSITY_NAME, eventTitle } from "../src/config";
import {
  getAppMode,
  needsModeConfirmation,
  setAppMode,
  type AppMode,
} from "../src/store/appMode";
import { colors, fonts, radius, spacing } from "../src/theme";
import { AppButton, LguMark, Screen } from "../src/ui";

interface Choice {
  mode: AppMode;
  title: string;
  subtitle: string;
  icon: keyof typeof Ionicons.glyphMap;
}

const CHOICES: Choice[] = [
  {
    mode: "volunteer",
    title: "Volunteer Operations",
    subtitle: "Scan QR codes at the gates and record entry and exit",
    icon: "qr-code",
  },
  {
    mode: "liveboard",
    title: "Live Dashboard",
    subtitle: "Watch the convocation attendance live, for everyone on campus",
    icon: "tv",
  },
  {
    mode: "student",
    title: "Student Portal",
    subtitle: "Claim your convocation registration and complete your profile",
    icon: "person-circle",
  },
];

function targetFor(mode: AppMode): "/(volunteer)/home" | "/(liveboard)" | "/(student)" {
  if (mode === "volunteer") return "/(volunteer)/home";
  return mode === "student" ? "/(student)" : "/(liveboard)";
}

/**
 * Mode selection — two product surfaces on paper (Phase 35C): seal, title,
 * one thin gold rule, then two launch cards (33-QA P8-29: the bare
 * dashed-divider rows now read as cards).
 * The choice persists on the device (store/appMode). 35M R2 (item 13):
 * the university name is sans, and the footer hint sentence is gone —
 * the two rows are the whole screen.
 */
export default function ModePickerScreen() {
  const [busy, setBusy] = useState<AppMode | null>(null);
  const [cfg, setCfg] = useState<AppConfig | null>(null);
  const [current, setCurrent] = useState<AppMode | null>(null);
  const [pending, setPending] = useState<AppMode | null>(null);
  const [accessError, setAccessError] = useState<string | null>(null);
  const [access, setAccess] = useState<DashboardAccess | null>(null);
  useFocusEffect(useCallback(() => {
    let active = true;
    const refresh = () => void fetchDashboardAccess().then((data) => {
      if (active) setAccess(data);
    }).catch(() => {});
    refresh();
    const timer = setInterval(refresh, 15000);
    return () => { active = false; clearInterval(timer); };
  }, []));

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
        setAccess(next);
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
        <LguMark size={96} />
        {/* 35M item 20: authoritative server event name; the local
            constant is the offline fallback only. */}
        <Text style={styles.title}>{cfg?.event.name || eventTitle()}</Text>
        <View style={styles.rule} />
        {/* 35M item 20 trace+fix: university line now consumes the
            server value (cfg.university) like Home/Guest Pass; the
            constant remains the offline fallback only. */}
        <Text style={styles.university}>{cfg?.university || UNIVERSITY_NAME}</Text>
      </View>

      <View style={styles.choices}>
        {CHOICES.map((choice) => {
          const active = busy === choice.mode;
          const unavailable = choice.mode !== "student" && access?.[choice.mode] === false;
          return (
            <Pressable
              key={choice.mode}
              accessibilityRole="button"
              accessibilityLabel={choice.title}
              accessibilityState={{ disabled: busy !== null || unavailable }}
              disabled={busy !== null || unavailable}
              onPress={() => void pick(choice.mode)}
              style={({ pressed }) => [
                styles.choice,
                pressed && styles.choicePressed,
                active && styles.choiceBusy,
                unavailable && styles.choiceBusy,
              ]}
            >
              <Ionicons name={choice.icon} size={22} color={colors.ink} />
              <View style={styles.choiceText}>
                <Text style={styles.choiceTitle}>{choice.title}</Text>
                <Text style={styles.choiceSubtitle}>{unavailable ? "Currently disabled by the administrator" : choice.subtitle}</Text>
              </View>
              <Ionicons name="chevron-forward" size={18} color={colors.muted} />
            </Pressable>
          );
        })}
      </View>
      {accessError ? <Text style={styles.choiceSubtitle}>{accessError}</Text> : null}
      <AppButton label="Administrator access" variant="ghost" onPress={() => router.push("/administration")} />
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Connect to server"
        onPress={() => router.push("/connect-server")}
        style={styles.serverLink}
      >
        <Ionicons name="cloud-outline" size={19} color={colors.ink} />
        <Text style={styles.serverLinkText}>Connect to server</Text>
        <Ionicons name="chevron-forward" size={17} color={colors.muted} />
      </Pressable>
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
  top: {
    alignItems: "center",
    paddingTop: spacing.xl,
  },
  title: {
    color: colors.ink,
    // 35M R2 (item 14): display family encodes the weight.
    // 35M item 2: slightly smaller so the full configured event name
    // wraps balanced at 360px — never a one-word orphan line.
    fontFamily: fonts.display,
    fontSize: 20,
    letterSpacing: -0.4,
    marginTop: spacing.md,
    textAlign: "center",
  },
  rule: {
    width: 64,
    height: 2,
    backgroundColor: colors.gold,
    marginTop: spacing.md,
    marginBottom: spacing.sm,
  },
  university: {
    // 35M R2 (item 13): sans label — not spaced mono lettering.
    color: colors.muted,
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    textAlign: "center",
  },
  choices: {
    gap: spacing.sm,
    marginTop: spacing.lg,
  },
  serverLink: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    minHeight: 48,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
  },
  serverLinkText: {
    flex: 1,
    color: colors.ink,
    fontFamily: fonts.displayMedium,
    fontSize: 14,
  },
  // 33-QA (P8-29): each launch choice reads as a CARD — track border,
  // quiet paper fill, breathing room — instead of a bare dashed row.
  choice: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    paddingVertical: spacing.lg,
    paddingHorizontal: spacing.md,
    minHeight: 72,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.track,
    backgroundColor: colors.paper,
    marginBottom: spacing.sm,
  },
  choicePressed: {
    opacity: 0.7,
  },
  choiceBusy: {
    opacity: 0.55,
  },
  choiceText: {
    flex: 1,
  },
  choiceTitle: {
    color: colors.ink,
    fontFamily: fonts.display,
    fontSize: 15,
    letterSpacing: -0.2,
  },
  choiceSubtitle: {
    color: colors.muted,
    fontFamily: fonts.displayMedium,
    fontSize: 15,
    marginTop: 2,
    lineHeight: 21,
  },
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
