import { router, usePathname } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { StyleSheet, Text, View } from "react-native";
import {
  getApiBaseUrl,
  isValidBaseUrl,
  probeBackend,
  setApiBaseUrl,
} from "../src/store/settings";
import { getAppMode } from "../src/store/appMode";
import { getToken } from "../src/store/studentSession";
import { colors, fonts, spacing } from "../src/theme";
import { AppButton, AppHeader, Field, Screen, SectionCard } from "../src/ui";

/**
 * First-run network setup. This screen deliberately has no admin PIN gate:
 * choosing an HTTPS server address is not an administrator permission.
 * Admin, scanning and student APIs remain authenticated by the backend.
 */
export default function ConnectServerScreen() {
  const pathname = usePathname();
  const pathRef = useRef(pathname);
    useEffect(() => {
      pathRef.current = pathname;
    }, [pathname]);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  useEffect(() => {
    let active = true;
    void getApiBaseUrl().then((existing) => {
      if (active && existing) setUrl(existing);
    });
    return () => {
      active = false;
    };
  }, []);

  // Role-aware back: this root utility screen is reachable from every role —
  // return to the caller's own role home, never a generic Home shared across
  // roles, and never strand the user on the launch screen.
  const handleBack = async () => {
    try {
      const mode = await getAppMode();
      const path = pathRef.current;
      if (/admin|administration|liveboard/i.test(path)) {
        router.replace("/administration");
        return;
      }
      if (mode === "student") {
        router.replace((await getToken()) ? "/(student)/more" : "/(student)/welcome");
        return;
      }
      if (mode === "liveboard") {
        router.replace("/(liveboard)");
        return;
      }
      if (mode === "volunteer") {
        router.replace("/(volunteer)/more");
        return;
      }
    } catch {
      // fall through to the mode picker below
    }
    router.replace("/mode-picker");
  };

  const save = async () => {
    if (busy) return;
    const next = url.trim().replace(/\/+$/, "");
    if (!isValidBaseUrl(next)) {
      setError("Enter a full server address, such as https://demo.example.org");
      return;
    }
    // Signed standalone APK builds do not allow cleartext Android traffic.
    // Plain HTTP remains usable only while running a local Expo development app.
    if (!__DEV__ && !next.toLowerCase().startsWith("https://")) {
      setError("For an installed APK, use an HTTPS server address.");
      return;
    }
    setBusy(true);
    setError(null);
    setSuccess(false);
    try {
      if (!(await probeBackend(next))) {
        setError(
          "The LGU server did not respond correctly. Check the link and internet connection.",
        );
        return;
      }
      await setApiBaseUrl(next);
      setSuccess(true);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Could not save the connection. Try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen>
      <AppHeader
        eyebrow="Getting started"
        title="Connect to server"
        subtitle="Connect once before signing in as a student, volunteer, or admin."
                onBack={() => void handleBack()}
      />
      <SectionCard>
        <Text style={styles.helper}>
          Enter the address of your LGU server. Do not enter your email,
          student password, or admin PIN here.
        </Text>
        <Field
          label="Server address"
          value={url}
          onChangeText={(value) => {
            setUrl(value);
            setSuccess(false);
            setError(null);
          }}
          placeholder="https://your-demo-server.example"
          keyboardType="url"
          autoCapitalize="none"
          autoCorrect={false}
          returnKeyType="done"
          onSubmitEditing={() => void save()}
          error={error}
        />
        <View style={styles.actions}>
          <AppButton
            label={busy ? "Checking server..." : "Test and save connection"}
            icon="cloud-done-outline"
            loading={busy}
            disabled={busy}
            onPress={() => void save()}
          />
          {success ? (
            <>
              <Text style={styles.success}>
                Connected to LGU Convocation. You can now sign in.
              </Text>
              <AppButton
                label="Continue"
                variant="secondary"
                              onPress={() => void handleBack()}
              />
            </>
          ) : null}
        </View>
      </SectionCard>
      <Text style={styles.note}>
        The installed APK cannot sign in without a reachable server.
        Use a test-only server first; never enter real student records in a demo.
      </Text>
    </Screen>
  );
}

const styles = StyleSheet.create({
  helper: {
    color: colors.muted,
    fontFamily: fonts.displayMedium,
    fontSize: 14,
    lineHeight: 21,
    marginBottom: spacing.md,
  },
  actions: { gap: spacing.sm, marginTop: spacing.md },
  success: {
    color: colors.valid,
    fontFamily: fonts.displayMedium,
    fontSize: 14,
    lineHeight: 21,
  },
  note: {
    color: colors.muted,
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    lineHeight: 20,
    marginTop: spacing.md,
  },
});
