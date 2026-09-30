import { Ionicons } from "@expo/vector-icons";
import { useEffect, useState } from "react";
import { StyleSheet, Text, TextInput, View } from "react-native";
import type { Gate } from "../api/client";
import {
  DEFAULT_API_BASE_URL,
  getApiBaseUrl,
  isValidBaseUrl,
  setApiBaseUrl,
} from "../store/settings";
import { colors, fontSize, fontWeight, radius, spacing } from "../theme";
import { PrimaryButton } from "./PrimaryButton";
import { SectionCard } from "./SectionCard";

const CONNECT_TIMEOUT_MS = 10000;

/**
 * Backend Connection editor. Lives in Settings (which never depends on the
 * server) so the API base URL can always be fixed, even on a first-run
 * phone that cannot reach the default address yet.
 */
export function BackendConnectionCard() {
  const [baseUrl, setBaseUrl] = useState(DEFAULT_API_BASE_URL);
  const [urlError, setUrlError] = useState<string | null>(null);
  const [urlSaved, setUrlSaved] = useState(false);
  const [testing, setTesting] = useState(false);
  const [reachable, setReachable] = useState<boolean | null>(null);
  const [reachability, setReachability] = useState<string | null>(null);

  useEffect(() => {
    void getApiBaseUrl().then(setBaseUrl);
  }, []);

  const saveUrl = async () => {
    if (!isValidBaseUrl(baseUrl)) {
      setUrlError("Enter a valid URL, for example http://192.168.1.10:5000");
      return;
    }
    setUrlError(null);
    await setApiBaseUrl(baseUrl);
    setUrlSaved(true);
    setTimeout(() => setUrlSaved(false), 2500);
  };

  const testConnection = async () => {
    setTesting(true);
    setReachability(null);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), CONNECT_TIMEOUT_MS);
    try {
      const response = await fetch(`${baseUrl.trim()}/api/gates`, {
        signal: controller.signal,
      });
      clearTimeout(timer);
      if (!response.ok) {
        setReachable(false);
        setReachability(`Not reachable: server returned ${response.status}.`);
        return;
      }
      const body = (await response.json()) as { gates?: Gate[] };
      const count = Array.isArray(body.gates) ? body.gates.length : 0;
      setReachable(true);
      setReachability(`Reachable. ${count} gate(s) found.`);
    } catch {
      clearTimeout(timer);
      setReachable(false);
      setReachability(
        "Not reachable. Check the URL, and make sure the server is running and the phone shares the same Wi-Fi.",
      );
    } finally {
      setTesting(false);
    }
  };

  return (
    <SectionCard
      title="Backend Connection"
      subtitle="Where this app sends its scans"
    >
      <Text style={styles.label}>API base URL</Text>
      <Text style={styles.hint}>
        On a real phone this must be your laptop's Wi-Fi address, for example
        http://192.168.1.10:5000 (10.0.2.2 works only in the Android emulator).
      </Text>
      <TextInput
        style={styles.input}
        value={baseUrl}
        onChangeText={setBaseUrl}
        placeholder={DEFAULT_API_BASE_URL}
        placeholderTextColor={colors.muted}
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="url"
      />
      {urlError && <Text style={styles.error}>{urlError}</Text>}
      <View style={styles.buttonRow}>
        <PrimaryButton
          title="Save URL"
          onPress={() => void saveUrl()}
          style={styles.flexButton}
        />
        <PrimaryButton
          title="Test connection"
          onPress={() => void testConnection()}
          loading={testing}
          variant="outline"
          style={styles.flexButton}
        />
      </View>
      {urlSaved && (
        <View style={styles.savedBox}>
          <Ionicons name="checkmark-circle" size={18} color={colors.green} />
          <Text style={styles.saved}>API base URL saved.</Text>
        </View>
      )}
      {reachability && (
        <View
          style={[
            styles.healthBox,
            reachable ? styles.healthOk : styles.healthBad,
          ]}
        >
          <Ionicons
            name={reachable ? "checkmark-circle" : "alert-circle"}
            size={18}
            color={reachable ? colors.green : colors.red}
          />
          <Text style={styles.healthText}>{reachability}</Text>
        </View>
      )}
    </SectionCard>
  );
}

const styles = StyleSheet.create({
  buttonRow: {
    flexDirection: "row",
    gap: spacing.sm,
    marginTop: spacing.md,
  },
  error: {
    color: colors.red,
    fontSize: fontSize.caption,
    marginTop: spacing.xs,
  },
  flexButton: {
    flex: 1,
  },
  healthBad: {
    backgroundColor: colors.redSoft,
  },
  healthBox: {
    alignItems: "center",
    borderRadius: radius.md,
    flexDirection: "row",
    gap: spacing.xs,
    marginTop: spacing.sm,
    padding: spacing.sm,
  },
  healthOk: {
    backgroundColor: colors.emeraldSoft,
  },
  healthText: {
    color: colors.text,
    flex: 1,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.semibold,
  },
  hint: {
    color: colors.muted,
    fontSize: fontSize.caption,
    marginTop: spacing.xs,
  },
  input: {
    backgroundColor: colors.inputBg,
    borderColor: colors.border,
    borderRadius: radius.md,
    borderWidth: 1,
    color: colors.text,
    fontSize: fontSize.body,
    marginTop: spacing.xs,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  label: {
    color: colors.greenDark,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.bold,
    marginTop: spacing.sm,
    textTransform: "uppercase",
  },
  saved: {
    color: colors.green,
    flex: 1,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.semibold,
    marginLeft: spacing.xs,
  },
  savedBox: {
    alignItems: "center",
    backgroundColor: colors.emeraldSoft,
    borderRadius: radius.md,
    flexDirection: "row",
    marginTop: spacing.sm,
    padding: spacing.sm,
  },
});
