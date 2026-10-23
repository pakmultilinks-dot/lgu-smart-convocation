import { router } from "expo-router";
import { StyleSheet, Text, View } from "react-native";
import { UNIVERSITY_NAME, eventTitle } from "../../src/config";
import { colors, fonts, spacing } from "../../src/theme";
import { AppButton, LguMark, Screen } from "../../src/ui";

/** Student Portal welcome: create an account, sign in, or recover access. */
export default function StudentWelcome() {
  return (
    <Screen>
      <View style={styles.top}>
        <LguMark size={96} />
        <Text style={styles.title}>Student Portal</Text>
        <View style={styles.rule} />
        <Text style={styles.event}>{eventTitle()}</Text>
        <Text style={styles.university}>{UNIVERSITY_NAME}</Text>
      </View>
      <View style={styles.actions}>
        <Text style={styles.intro}>Your registration, entry pass and university updates in one place.</Text>
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
        <AppButton
          label="Connect to server"
          variant="ghost"
          onPress={() => router.push("/connect-server")}
        />
        <AppButton
          label="Forgot password?"
          variant="ghost"
          onPress={() => router.push("/(student)/recovery")}
        />
        <AppButton
          label="Choose dashboard"
          variant="ghost"
          onPress={() => router.replace("/mode-picker")}
        />
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  top: { alignItems: "center", paddingTop: spacing.xl },
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
  actions: { gap: spacing.sm, marginTop: spacing.xl },
  intro: { color: colors.ink, fontFamily: fonts.displayMedium, fontSize: 15, lineHeight: 23, marginBottom: spacing.md },
  note: { color: colors.muted, fontFamily: fonts.displayMedium, fontSize: 13, lineHeight: 20, marginBottom: spacing.md },
});
