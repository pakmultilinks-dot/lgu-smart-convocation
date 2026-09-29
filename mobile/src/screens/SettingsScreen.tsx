import { Ionicons } from "@expo/vector-icons";
import * as Linking from "expo-linking";
import { useEffect, useState } from "react";
import {
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { ApiError, fetchGates } from "../api/client";
import { PrimaryButton } from "../components/PrimaryButton";
import { SectionCard } from "../components/SectionCard";
import {
  APP_NAME,
  CONVOCATION_YEAR,
  MOTTO,
  UNIVERSITY_NAME,
} from "../config";
import {
  DEFAULT_API_BASE_URL,
  getApiBaseUrl,
  getVolunteerName,
  isValidBaseUrl,
  setApiBaseUrl,
  setVolunteerName,
} from "../store/settings";
import { colors, fontSize, fontWeight, radius, spacing } from "../theme";

export function SettingsScreen() {
  const [baseUrl, setBaseUrl] = useState(DEFAULT_API_BASE_URL);
  const [volunteer, setVolunteer] = useState("");
  const [urlError, setUrlError] = useState<string | null>(null);
  const [savedNote, setSavedNote] = useState<string | null>(null);
  const [health, setHealth] = useState<string | null>(null);
  const [healthOk, setHealthOk] = useState(false);
  const [checking, setChecking] = useState(false);

  useEffect(() => {
    void getApiBaseUrl().then(setBaseUrl);
    void getVolunteerName().then(setVolunteer);
  }, []);

  const saveUrl = async () => {
    if (!isValidBaseUrl(baseUrl)) {
      setUrlError("Enter a valid URL, for example http://10.0.2.2:5000");
      return;
    }
    setUrlError(null);
    await setApiBaseUrl(baseUrl);
    setSavedNote("API base URL saved.");
  };

  const saveVolunteer = async () => {
    await setVolunteerName(volunteer);
    setSavedNote("Volunteer name saved.");
  };

  const testConnection = async () => {
    setChecking(true);
    setHealth(null);
    try {
      const gates = await fetchGates();
      setHealthOk(true);
      setHealth(`Connected. ${gates.length} gate(s) found.`);
    } catch (e) {
      setHealthOk(false);
      setHealth(
        e instanceof ApiError
          ? `Connection failed: ${e.message}`
          : "Connection failed.",
      );
    } finally {
      setChecking(false);
    }
  };

  const openCards = async () => {
    const url = `${await getApiBaseUrl()}/admin/cards`;
    const supported = await Linking.canOpenURL(url);
    if (supported) {
      await Linking.openURL(url);
    }
  };

  return (
    <ScrollView style={styles.root}>
      <SectionCard title="Backend Connection" subtitle="Where this app sends its scans">
        <Text style={styles.label}>API base URL</Text>
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
          <PrimaryButton title="Save URL" onPress={() => void saveUrl()} style={styles.flexButton} />
          <PrimaryButton
            title="Test connection"
            onPress={() => void testConnection()}
            loading={checking}
            variant="outline"
            style={styles.flexButton}
          />
        </View>
        {health && (
          <View style={[styles.healthBox, healthOk ? styles.healthOk : styles.healthBad]}>
            <Ionicons
              name={healthOk ? "checkmark-circle" : "alert-circle"}
              size={18}
              color={healthOk ? colors.green : colors.red}
            />
            <Text style={[styles.healthText, { color: healthOk ? colors.green : colors.red }]}>
              {health}
            </Text>
          </View>
        )}
      </SectionCard>

      <SectionCard title="Volunteer" subtitle="Shown on every scan you make">
        <Text style={styles.label}>Volunteer name</Text>
        <TextInput
          style={styles.input}
          value={volunteer}
          onChangeText={setVolunteer}
          placeholder="Your name as shown on scans"
          placeholderTextColor={colors.muted}
          autoCapitalize="words"
        />
        <View style={styles.buttonRow}>
          <PrimaryButton
            title="Save name"
            onPress={() => void saveVolunteer()}
            style={styles.flexButton}
          />
        </View>
        {savedNote && (
          <View style={styles.savedBox}>
            <Ionicons name="checkmark-circle" size={18} color={colors.green} />
            <Text style={styles.saved}>{savedNote}</Text>
          </View>
        )}
      </SectionCard>

      <SectionCard title="Admin Tools">
        <Pressable
          style={({ pressed }) => [styles.linkRow, pressed && styles.pressed]}
          onPress={() => void openCards()}
        >
          <View style={styles.linkIcon}>
            <Ionicons name="id-card-outline" size={22} color={colors.green} />
          </View>
          <View style={styles.linkText}>
            <Text style={styles.linkTitle}>ID card printing</Text>
            <Text style={styles.linkSub}>Open /admin/cards in the browser</Text>
          </View>
          <Ionicons name="open-outline" size={18} color={colors.muted} />
        </Pressable>
      </SectionCard>

      <SectionCard title="About">
        <View style={styles.aboutHeader}>
          <View style={styles.monogram}>
            <Text style={styles.monogramText}>LGU</Text>
          </View>
          <View style={styles.aboutTitles}>
            <Text style={styles.appName}>
              {APP_NAME} {CONVOCATION_YEAR}
            </Text>
            <Text style={styles.university}>{UNIVERSITY_NAME}</Text>
          </View>
        </View>
        <View style={styles.greenRule} />
        <Text style={styles.motto}>"{MOTTO}"</Text>
        <Text style={styles.aboutBody}>
          Official gate companion for convocation day. Volunteers scan QR-coded
          student cards and guest passes, and the control room watches every
          gate live. Version 1.0.0.
        </Text>
      </SectionCard>

      <View style={styles.bottomPad} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  aboutBody: {
    color: colors.muted,
    fontSize: fontSize.body,
    lineHeight: 21,
    marginTop: spacing.sm,
  },
  aboutHeader: {
    alignItems: "center",
    flexDirection: "row",
    gap: spacing.md,
  },
  aboutTitles: {
    flex: 1,
  },
  appName: {
    color: colors.greenDark,
    fontSize: fontSize.subheading,
    fontWeight: fontWeight.bold,
  },
  bottomPad: {
    height: spacing.xl,
  },
  buttonRow: {
    flexDirection: "row",
    gap: spacing.sm,
    marginTop: spacing.md,
  },
  error: {
    color: colors.red,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.semibold,
    marginTop: spacing.xs,
  },
  flexButton: {
    flex: 1,
  },
  greenRule: {
    backgroundColor: colors.emerald,
    borderRadius: radius.sm,
    height: 3,
    marginTop: spacing.md,
    width: 48,
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
    flex: 1,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.semibold,
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
  linkIcon: {
    alignItems: "center",
    backgroundColor: colors.tint,
    borderRadius: radius.full,
    height: 44,
    justifyContent: "center",
    width: 44,
  },
  linkRow: {
    alignItems: "center",
    flexDirection: "row",
    gap: spacing.md,
    paddingVertical: spacing.sm,
  },
  linkSub: {
    color: colors.muted,
    fontSize: fontSize.caption,
    marginTop: 2,
  },
  linkText: {
    flex: 1,
  },
  linkTitle: {
    color: colors.text,
    fontSize: fontSize.body,
    fontWeight: fontWeight.semibold,
  },
  monogram: {
    alignItems: "center",
    backgroundColor: colors.green,
    borderRadius: radius.lg,
    height: 58,
    justifyContent: "center",
    width: 58,
  },
  monogramText: {
    color: colors.white,
    fontSize: fontSize.subheading,
    fontWeight: fontWeight.bold,
  },
  motto: {
    color: colors.greenDark,
    fontSize: fontSize.body,
    fontStyle: "italic",
    fontWeight: fontWeight.semibold,
    marginTop: spacing.sm,
  },
  pressed: {
    opacity: 0.85,
  },
  root: {
    backgroundColor: colors.background,
    flex: 1,
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
  university: {
    color: colors.muted,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.semibold,
    marginTop: 2,
  },
});
