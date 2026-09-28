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
  DEFAULT_API_BASE_URL,
  getApiBaseUrl,
  getVolunteerName,
  isValidBaseUrl,
  setApiBaseUrl,
  setVolunteerName,
} from "../store/settings";
import { colors, fontSize, fontWeight, radius, spacing } from "../theme";

const APP_NAME = "LGU Smart Convocation System";
const UNIVERSITY = "Lahore Garrison University";
const MOTTO = "Nurturing the Future of Pakistan in an Excellent Environment";

export function SettingsScreen() {
  const [baseUrl, setBaseUrl] = useState(DEFAULT_API_BASE_URL);
  const [volunteer, setVolunteer] = useState("");
  const [urlError, setUrlError] = useState<string | null>(null);
  const [savedNote, setSavedNote] = useState<string | null>(null);
  const [health, setHealth] = useState<string | null>(null);
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
      setHealth(`Connected. ${gates.length} gate(s) found.`);
    } catch (e) {
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
      <SectionCard title="Backend Connection">
        <Text style={styles.label}>API base URL</Text>
        <TextInput
          style={styles.input}
          value={baseUrl}
          onChangeText={setBaseUrl}
          placeholder={DEFAULT_API_BASE_URL}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
        />
        {urlError && <Text style={styles.error}>{urlError}</Text>}
        <View style={styles.buttonRow}>
          <PrimaryButton title="Save URL" onPress={() => void saveUrl()} />
          <PrimaryButton
            title="Test connection"
            onPress={() => void testConnection()}
            loading={checking}
            variant="outline"
          />
        </View>
        {health && <Text style={styles.health}>{health}</Text>}
      </SectionCard>

      <SectionCard title="Volunteer">
        <Text style={styles.label}>Volunteer name</Text>
        <TextInput
          style={styles.input}
          value={volunteer}
          onChangeText={setVolunteer}
          placeholder="Your name as shown on scans"
          autoCapitalize="words"
        />
        <View style={styles.buttonRow}>
          <PrimaryButton
            title="Save name"
            onPress={() => void saveVolunteer()}
          />
        </View>
        {savedNote && <Text style={styles.saved}>{savedNote}</Text>}
      </SectionCard>

      <SectionCard title="Admin Tools">
        <Pressable style={styles.linkRow} onPress={() => void openCards()}>
          <Ionicons name="id-card-outline" size={22} color={colors.navy} />
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
            <Text style={styles.appName}>{APP_NAME}</Text>
            <Text style={styles.university}>{UNIVERSITY}</Text>
          </View>
        </View>
        <View style={styles.goldRule} />
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
    color: colors.navy,
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
  goldRule: {
    backgroundColor: colors.gold,
    borderRadius: radius.sm,
    height: 3,
    marginTop: spacing.md,
    width: 48,
  },
  health: {
    color: colors.navy,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.semibold,
    marginTop: spacing.sm,
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
    color: colors.navy,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.bold,
    marginTop: spacing.sm,
    textTransform: "uppercase",
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
    backgroundColor: colors.navy,
    borderRadius: radius.md,
    height: 56,
    justifyContent: "center",
    width: 56,
  },
  monogramText: {
    color: colors.gold,
    fontSize: fontSize.subheading,
    fontWeight: fontWeight.bold,
  },
  motto: {
    color: colors.navy,
    fontSize: fontSize.body,
    fontStyle: "italic",
    fontWeight: fontWeight.semibold,
    marginTop: spacing.sm,
  },
  root: {
    backgroundColor: colors.background,
    flex: 1,
  },
  saved: {
    color: colors.green,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.semibold,
    marginTop: spacing.sm,
  },
  university: {
    color: colors.muted,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.semibold,
    marginTop: 2,
  },
});
