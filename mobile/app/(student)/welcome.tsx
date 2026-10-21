import { router } from "expo-router";
import { StyleSheet, Text, View } from "react-native";
import { UNIVERSITY_NAME, eventTitle } from "../../src/config";
import { colors, fonts, spacing } from "../../src/theme";
import { AppButton, LguMark, Screen } from "../../src/ui";

/** Student Portal welcome: create an account, sign in, or recover access. */
export default function StudentWelcome() {
  return (
    <Screen scroll={false}>
      <View style={styles.top}>
        <LguMark size={96} />
        <Text style={styles.title}>Student Portal</Text>
        <View style={styles.rule} />
        <Text style={styles.event}>{eventTitle()}</Text>
        <Text style={styles.university}>{UNIVERSITY_NAME}</Text>
      </View>
      <View style={styles.actions}>
        <AppButton
          label="Create your account"
          size="lg"
          onPress={() => router.push("/(student)/verify")}
        />
        <AppButton
          label="Sign in"
          variant="secondary"
          onPress={() => router.push("/(student)/login")}
        />
        <AppButton
          label="Forgot password?"
          variant="ghost"
          onPress={() => router.push("/(student)/recovery")}
        />
        <AppButton
          label="Change device mode"
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
    fontSize: 20,
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
});
