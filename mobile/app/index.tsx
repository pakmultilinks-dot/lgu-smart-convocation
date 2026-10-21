import { Redirect } from "expo-router";
import { useEffect, useState } from "react";
import { StyleSheet, Text, View } from "react-native";
import { fetchAppConfig, type AppConfig } from "../src/api/client";
import { UNIVERSITY_NAME, eventTitle } from "../src/config";
import { getAppMode, setAppMode } from "../src/store/appMode";
import { colors, fonts, spacing } from "../src/theme";
import { LguMark, Screen } from "../src/ui";

type LaunchTarget = "pending" | "picker" | "volunteer" | "student";

/**
 * Launch gate. Institutional brand moment on paper (Phase 35C): the LGU
 * seal sits directly on the surface, title in Bricolage, university name
 * in sans (35M R2 item 13). One deterministic
 * mode-resolution rule (35M R3):
 *   volunteer -> volunteer home
 *   student -> student portal gate (Phase 5)
 *   liveboard (stale/legacy) -> normalized to volunteer -> volunteer home
 *   none/unknown -> mode picker
 * Live Dashboard is an explicit in-session mode (mode picker / Change
 * mode) — never a launch default — so a stale stored "liveboard" value
 * can no longer hijack normal launches.
 */
export default function LaunchScreen() {
  const [target, setTarget] = useState<LaunchTarget>("pending");
  const [cfg, setCfg] = useState<AppConfig | null>(null);

  // 35M items 2 + 20: the brand moment consumes the SERVER convocation
  // configuration when connected — eventTitle() is only the offline
  // fallback for the very first render.
  useEffect(() => {
    let cancelled = false;
    void fetchAppConfig()
      .then((data) => {
        if (!cancelled) setCfg(data);
      })
      .catch(() => {
        // Best-effort: the fallback title keeps the splash honest offline.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const mode = await getAppMode();
      if (cancelled) return;
      if (mode === "liveboard") {
        // 35M R3: stale stored dashboard mode — normalize to the default
        // launch mode and land on Volunteer Home.
        await setAppMode("volunteer");
        setTarget("volunteer");
        return;
      }
      setTarget(
        mode === "volunteer" ? "volunteer" : mode === "student" ? "student" : "picker",
      );
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (target === "pending") {
    return (
      <Screen scroll={false}>
        <View style={styles.center}>
          <LguMark size={104} />
          {/* 35M item 20: authoritative server event name; the local
              constant is the offline fallback only. */}
          <Text style={styles.title}>{cfg?.event.name || eventTitle()}</Text>
          {/* QA fix cycle 3 (Issue 11): the gold divider beneath the launch
              title is removed — it carried no meaning. */}
          <Text style={styles.university}>{cfg?.university || UNIVERSITY_NAME}</Text>
        </View>
      </Screen>
    );
  }
  if (target === "volunteer") return <Redirect href="/(volunteer)/home" />;
  if (target === "student") return <Redirect href="/(student)" />;
  return <Redirect href="/mode-picker" />;
}

const styles = StyleSheet.create({
  center: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
  },
  title: {
    color: colors.ink,
    // 35M R2 (item 14): display family encodes the weight.
    // 35M item 2: slightly smaller so the full configured event name
    // wraps balanced at 360px — never a one-word orphan line.
    fontFamily: fonts.display,
    fontSize: 20,
    letterSpacing: -0.4,
    marginTop: spacing.lg,
    textAlign: "center",
  },
  university: {
    color: colors.muted,
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    marginTop: spacing.sm,
    textAlign: "center",
  },
});
