import { Ionicons } from "@expo/vector-icons";
import { router } from "expo-router";
import { useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { setAppMode, type AppMode } from "../src/store/appMode";
import { colors, fontSize, fontWeight, radius, spacing } from "../src/theme";

interface CardOption {
  mode: AppMode;
  title: string;
  subtitle: string;
  icon: keyof typeof Ionicons.glyphMap;
}

const OPTIONS: CardOption[] = [
  {
    mode: "volunteer",
    title: "I am a Volunteer",
    subtitle: "Scan QR codes at the gates",
    icon: "qr-code",
  },
  {
    mode: "liveboard",
    title: "Live Board",
    subtitle: "Watch the convocation live, for everyone",
    icon: "tv",
  },
];

function targetFor(mode: AppMode): "/(volunteer)/scanner" | "/(liveboard)" {
  return mode === "volunteer" ? "/(volunteer)/scanner" : "/(liveboard)";
}

export default function ModePickerScreen() {
  const [busy, setBusy] = useState<AppMode | null>(null);

  const pick = async (mode: AppMode) => {
    if (busy) return;
    setBusy(mode);
    try {
      await setAppMode(mode);
      router.replace(targetFor(mode));
    } finally {
      setBusy(null);
    }
  };

  return (
    <View style={styles.root}>
      <View style={styles.header}>
        <View style={styles.monogram}>
          <Text style={styles.monogramText}>LGU</Text>
        </View>
        <Text style={styles.title}>Welcome to LGU Smart Convocation</Text>
        <Text style={styles.subtitle}>How are you using this app today?</Text>
      </View>

      <View style={styles.cards}>
        {OPTIONS.map((option) => (
          <Pressable
            key={option.mode}
            style={({ pressed }) => [
              styles.card,
              pressed && styles.cardPressed,
            ]}
            onPress={() => void pick(option.mode)}
            disabled={busy !== null}
            accessibilityRole="button"
            accessibilityLabel={option.title}
          >
            <View style={styles.cardIcon}>
              <Ionicons name={option.icon} size={34} color={colors.green} />
            </View>
            <View style={styles.cardText}>
              <Text style={styles.cardTitle}>{option.title}</Text>
              <Text style={styles.cardSubtitle}>{option.subtitle}</Text>
            </View>
            <View style={styles.cardAction}>
              {busy === option.mode ? (
                <ActivityIndicator color={colors.green} />
              ) : (
                <Ionicons
                  name="chevron-forward"
                  size={24}
                  color={colors.green}
                />
              )}
            </View>
          </Pressable>
        ))}
      </View>

      <Text style={styles.hint}>
        You can change this later from the app settings.
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    alignItems: "center",
    backgroundColor: colors.card,
    borderRadius: radius.lg,
    elevation: 3,
    flexDirection: "row",
    gap: spacing.md,
    padding: spacing.lg,
    shadowColor: colors.greenDark,
    shadowOffset: { height: 2, width: 0 },
    shadowOpacity: 0.12,
    shadowRadius: 10,
  },
  cardAction: {
    alignItems: "center",
    justifyContent: "center",
    width: 28,
  },
  cardIcon: {
    alignItems: "center",
    backgroundColor: colors.tint,
    borderRadius: radius.full,
    height: 64,
    justifyContent: "center",
    width: 64,
  },
  cardPressed: {
    opacity: 0.85,
    transform: [{ scale: 0.98 }],
  },
  cardSubtitle: {
    color: colors.muted,
    fontSize: fontSize.body,
    marginTop: 4,
  },
  cardText: {
    flex: 1,
  },
  cardTitle: {
    color: colors.greenDark,
    fontSize: fontSize.subheading,
    fontWeight: fontWeight.bold,
  },
  cards: {
    gap: spacing.md,
    paddingHorizontal: spacing.lg,
  },
  header: {
    alignItems: "center",
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.xl * 2,
  },
  hint: {
    color: colors.muted,
    fontSize: fontSize.caption,
    marginTop: spacing.xl,
    textAlign: "center",
  },
  monogram: {
    alignItems: "center",
    backgroundColor: colors.green,
    borderRadius: radius.lg,
    height: 72,
    justifyContent: "center",
    marginBottom: spacing.md,
    width: 72,
  },
  monogramText: {
    color: colors.white,
    fontSize: fontSize.title,
    fontWeight: fontWeight.bold,
  },
  root: {
    backgroundColor: colors.background,
    flex: 1,
  },
  subtitle: {
    color: colors.muted,
    fontSize: fontSize.body,
    marginBottom: spacing.xl,
    marginTop: spacing.xs,
    textAlign: "center",
  },
  title: {
    color: colors.greenDark,
    fontSize: fontSize.title,
    fontWeight: fontWeight.bold,
    textAlign: "center",
  },
});
