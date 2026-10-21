import { router, useLocalSearchParams } from "expo-router";
import { useState } from "react";
import { StyleSheet, Text } from "react-native";
import { ApiError } from "../../src/api/client";
import * as studentApi from "../../src/api/studentApi";
import { colors, fonts, spacing } from "../../src/theme";
import { AppButton, AppHeader, Field, Screen } from "../../src/ui";

/** Email + password sign-in for existing student accounts. */
export default function StudentLogin() {
  const { reset } = useLocalSearchParams<{ reset?: string }>();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const session = await studentApi.login({
        email: email.trim(),
        password,
      });
      router.replace(studentApi.homePath(session));
    } catch (e) {
      setError(
        e instanceof ApiError
          ? e.code === "locked"
            // A locked account unlocks the moment the password is reset —
            // point at that path instead of only "wait X minutes".
            ? `${e.message} Use "Forgot password?" below to reset now and unlock immediately.`
            : e.message
          : "Sign-in failed. Check the connection and try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen>
      <AppHeader
        title="Sign in"
        subtitle="Your student account for the convocation"
        onBack={() => router.back()}
      />
      {reset ? (
        <Text style={styles.note}>
          Password changed. Sign in with your new password.
        </Text>
      ) : null}
      <Field
        label="University email"
        value={email}
        onChangeText={setEmail}
        autoCapitalize="none"
        autoComplete="email"
        keyboardType="email-address"
        placeholder="you@uni.edu.pk"
      />
      <Field
        label="Password"
        value={password}
        onChangeText={setPassword}
        secureTextEntry
        autoComplete="password"
        placeholder="Your password"
      />
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <AppButton
        label={busy ? "Signing in..." : "Sign in"}
        loading={busy}
        onPress={() => void submit()}
        style={styles.submit}
      />
      <AppButton
        label="Forgot password?"
        variant="ghost"
        onPress={() => router.push("/(student)/recovery")}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  submit: { marginTop: spacing.md },
  note: {
    color: colors.valid,
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    marginBottom: spacing.sm,
  },
  error: {
    color: colors.invalid,
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    marginTop: spacing.xs,
  },
});
