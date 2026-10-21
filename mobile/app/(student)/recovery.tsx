import { router } from "expo-router";
import { useState } from "react";
import { StyleSheet, Text } from "react-native";
import { ApiError } from "../../src/api/client";
import * as studentApi from "../../src/api/studentApi";
import { clearToken } from "../../src/store/studentSession";
import { colors, fonts, spacing } from "../../src/theme";
import { AppButton, AppHeader, Field, Screen } from "../../src/ui";

/** Password recovery (Phase 5, §2): request a code, set a new password.
 *  The request step NEVER reveals whether the email has an account. */
export default function StudentRecovery() {
  const [step, setStep] = useState<"email" | "code">("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const act = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(
        e instanceof ApiError
          ? e.code === "email_unavailable"
            ? "Email delivery is unavailable — no message was sent. Contact the Examination Department."
            : e.status === 0
              ? "Could not reach the convocation system. Check your connection and try again."
              : e.message
          : "Request failed. Check the connection and try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  const requestCode = () =>
    act(async () => {
      const r = await studentApi.requestRecovery(email.trim());
      setNote(r.message);
      setStep("code");
    });

  const finish = () =>
    act(async () => {
      await studentApi.completeRecovery({
        email: email.trim(),
        code: code.trim(),
        password,
      });
      // Password changed → the old session (if any) is dead. Sign out.
      await clearToken();
      router.replace({ pathname: "/(student)/login", params: { reset: "1" } });
    });

  return (
    <Screen>
      <AppHeader
        title="Reset password"
        subtitle="We will email a code to your university address"
        onBack={() => (step === "code" ? setStep("email") : router.back())}
      />
      <Field
        label="University email"
        value={email}
        onChangeText={setEmail}
        autoCapitalize="none"
        keyboardType="email-address"
        placeholder="you@uni.edu.pk"
        editable={step === "email"}
      />
      {step === "code" ? (
        <>
          <Field
            label="Recovery code"
            value={code}
            onChangeText={setCode}
            keyboardType="number-pad"
            maxLength={6}
            placeholder="6-digit code"
          />
          <Field
            label="New password"
            value={password}
            onChangeText={setPassword}
            secureTextEntry
            hint="At least 12 characters"
            placeholder="New password"
          />
        </>
      ) : null}
      {note ? <Text style={styles.note}>{note}</Text> : null}
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <AppButton
        label={step === "email" ? "Send recovery code" : "Set new password"}
        loading={busy}
        onPress={() => void (step === "email" ? requestCode() : finish())}
        style={styles.submit}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  submit: { marginTop: spacing.md },
  note: {
    color: colors.muted,
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    marginTop: spacing.xs,
  },
  error: {
    color: colors.invalid,
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    marginTop: spacing.xs,
  },
});
