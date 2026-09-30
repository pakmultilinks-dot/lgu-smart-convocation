import { Ionicons } from "@expo/vector-icons";
import { router } from "expo-router";
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
import { PrimaryButton } from "../components/PrimaryButton";
import { BackendConnectionCard } from "../components/BackendConnectionCard";
import { SectionCard } from "../components/SectionCard";
import {
  APP_NAME,
  CONVOCATION_YEAR,
  MOTTO,
  UNIVERSITY_NAME,
} from "../config";
import { clearAppMode, getAppMode, type AppMode } from "../store/appMode";
import {
  getApiBaseUrl,
  getVolunteerName,
  setVolunteerName,
} from "../store/settings";
import { colors, fontSize, fontWeight, radius, spacing } from "../theme";

function modeLabel(mode: AppMode | null): string {
  if (mode === "volunteer") return "Volunteer";
  if (mode === "liveboard") return "Live Board";
  return "Not set";
}

export function SettingsScreen() {
  const [appMode, setAppMode] = useState<AppMode | null>(null);
  const [volunteer, setVolunteer] = useState("");
  const [savedNote, setSavedNote] = useState<string | null>(null);
  const [linkError, setLinkError] = useState<string | null>(null);

  useEffect(() => {
    void getAppMode().then(setAppMode);
    void getVolunteerName().then(setVolunteer);
  }, []);

  const saveVolunteer = async () => {
    await setVolunteerName(volunteer);
    setSavedNote("Volunteer name saved.");
  };

  const switchMode = async () => {
    await clearAppMode();
    router.replace("/mode-picker");
  };

  const openCards = async () => {
    setLinkError(null);
    const url = `${await getApiBaseUrl()}/admin/cards`;
    const supported = await Linking.canOpenURL(url);
    if (supported) {
      await Linking.openURL(url);
    } else {
      setLinkError(
        "Could not open the link. Check the backend URL above first.",
      );
    }
  };

  return (
    <ScrollView style={styles.root}>
      <SectionCard title="App mode" subtitle="Choose what this app is used for">
        <View style={styles.modeRow}>
          <Ionicons
            name={appMode === "liveboard" ? "tv" : "qr-code"}
            size={22}
            color={colors.green}
          />
          <Text style={styles.modeText}>Current mode: {modeLabel(appMode)}</Text>
        </View>
        <PrimaryButton
          title="Switch mode"
          onPress={() => void switchMode()}
          variant="outline"
          style={styles.topMargin}
        />
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

      <BackendConnectionCard />

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
        {linkError && <Text style={styles.linkError}>{linkError}</Text>}
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
        <Text style={styles.motto}>&ldquo;{MOTTO}&rdquo;</Text>
        <Text style={styles.aboutBody}>
          Official gate companion for convocation day. Volunteers scan QR-coded
          student cards and guest passes, and the control room watches every
          gate live. Version 1.1.0.
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
  linkError: {
    color: colors.red,
    fontSize: fontSize.caption,
    marginTop: spacing.xs,
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
  modeRow: {
    alignItems: "center",
    flexDirection: "row",
    gap: spacing.sm,
  },
  modeText: {
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
  topMargin: {
    marginTop: spacing.md,
  },
  university: {
    color: colors.muted,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.semibold,
    marginTop: 2,
  },
});
