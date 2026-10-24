import { router } from "expo-router";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { UNIVERSITY_NAME, eventTitle } from "../../src/config";
import { colors, fonts, spacing } from "../../src/theme";
import { AppButton, LguMark, Screen } from "../../src/ui";

/** Student Portal welcome: create an account, sign in, or recover access. */
export default function StudentWelcome() {
  return (
    <Screen>
      <View style={styles.top}>
        <LguMark size={64} />
        <Text style={styles.title}>Welcome to your student portal</Text>
        <View style={styles.rule} />
        <Text style={styles.event}>{eventTitle()}</Text>
        <Text style={styles.university}>{UNIVERSITY_NAME}</Text>
      </View>
      <View style={styles.actions}>
        <Text style={styles.intro}>Sign in to track your registration, view your entry pass and read event updates.</Text>
        <AppButton
          label="Sign in"
          size="lg"
          onPress={() => router.push("/(student)/login")}
        />
        <AppButton
          label="Create your account"
          variant="secondary"
          onPress={() => router.push("/(student)/verify")}
        />
        <Text style={styles.note}>Account creation requires a matching official university registration and email verification.</Text>
        <View style={styles.links}>
          <Pressable accessibilityRole="button" onPress={() => router.push("/connect-server")} style={styles.link}>
            <Text style={styles.linkText}>Server settings</Text>
          </Pressable>
          <Pressable accessibilityRole="button" onPress={() => router.push("/(student)/recovery")} style={styles.link}>
            <Text style={styles.linkText}>Forgot password?</Text>
          </Pressable>
          <Pressable accessibilityRole="button" onPress={() => router.replace("/mode-picker")} style={styles.link}>
            <Text style={styles.linkText}>Change workspace</Text>
          </Pressable>
        </View>
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  top: { alignItems: "center", paddingTop: spacing.sm },
  title: {
    color: colors.ink,
    fontFamily: fonts.display,
    fontSize: 24,
    letterSpacing: -0.4,
    marginTop: spacing.md,
    textAlign: "center",
  },
  rule: {
    backgroundColor: colors.gold,
    height: 1,
    marginTop: spacing.sm,
    width: 56,
  },
  event: {
    color: colors.ink,
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    marginTop: spacing.sm,
    textAlign: "center",
  },
  university: {
    color: colors.muted,
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    marginTop: spacing.xs,
    textAlign: "center",
  },
  actions: { gap: spacing.sm, marginTop: spacing.lg },
  links: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", justifyContent: "center", gap: spacing.sm, marginTop: spacing.md },
  link: { minHeight: 44, justifyContent: "center", paddingHorizontal: spacing.sm },
  linkText: { color: colors.ink, fontFamily: fonts.displayMedium, fontSize: 13, textDecorationLine: "underline" },
  intro: { color: colors.ink, fontFamily: fonts.displayMedium, fontSize: 15, lineHeight: 23, marginBottom: spacing.md },
  note: { color: colors.muted, fontFamily: fonts.displayMedium, fontSize: 13, lineHeight: 20, marginBottom: spacing.sm },
});
