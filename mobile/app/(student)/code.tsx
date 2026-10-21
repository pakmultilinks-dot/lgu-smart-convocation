import { router, useLocalSearchParams } from "expo-router";
import { useState } from "react";
import { StyleSheet, Text, View } from "react-native";
import { ApiError } from "../../src/api/client";
import * as studentApi from "../../src/api/studentApi";
import { colors, fonts, spacing } from "../../src/theme";
import {
  AppButton,
  AppHeader,
  Field,
  LoadingState,
  Screen,
  StatusPill,
} from "../../src/ui";

/** Step 2 — enter the emailed code; new accounts set a password here. */
export default function StudentCode() {
  const p = useLocalSearchParams<{
    challenge_id: string;
    masked_email: string;
    account_exists: string;
    pending: string;
    resend_remaining: string;
  }>();
  const accountExists = p.account_exists === "true";
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(
    p.pending === "true" ? "A code is waiting for you from a recent request." : null,
  );
  const [remaining, setRemaining] = useState(Number(p.resend_remaining ?? 0));
  const [busy, setBusy] = useState<"submit" | "resend" | null>(null);
  // Success is rendered only after the backend accepted the code — never
  // because a request was merely submitted.
  const [ok, setOk] = useState(false);

  const submit = async () => {
    setBusy("submit");
    setError(null);
    try {
      const session = await studentApi.complete({
        challenge_id: Number(p.challenge_id),
        code: code.trim(),
        ...(accountExists ? {} : { password }),
      });
      setOk(true);
      setTimeout(() => router.replace(studentApi.homePath(session)), 700);
    } catch (e) {
      setError(
        e instanceof ApiError
          ? e.status === 0
            ? "Could not reach the convocation system. Check your connection — the code was not checked."
            : e.message
          : "Verification failed. Check the connection and try again.",
      );
    } finally {
      setBusy(null);
    }
  };

  const resend = async () => {
    setBusy("resend");
    setError(null);
    try {
      const r = await studentApi.resend(Number(p.challenge_id));
      setRemaining(r.resend_remaining);
      setNote(`A new code was sent to ${p.masked_email}.`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not resend the code.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <Screen>
      <AppHeader
        title="Enter code"
        subtitle={`Email verification required — we emailed a 6-digit code to ${p.masked_email}`}
        onBack={() => router.back()}
      />
      <View style={styles.status}>
        <StatusPill
          state={accountExists ? "info" : "queued"}
          label={accountExists ? "Existing account" : "New account"}
        />
      </View>
      <Field
        label="Verification code"
        value={code}
        onChangeText={setCode}
        keyboardType="number-pad"
        maxLength={6}
        placeholder="6-digit code"
      />
      {!accountExists ? (
        <Field
          label="Create a password"
          value={password}
          onChangeText={setPassword}
          secureTextEntry
          hint="At least 12 characters — you will sign in with this"
          placeholder="New password"
        />
      ) : null}
      {note ? <Text style={styles.note}>{note}</Text> : null}
      {error ? <Text style={styles.error}>{error}</Text> : null}
      {ok ? (
        <Text style={styles.ok}>Verification successful — opening your account…</Text>
      ) : busy === "submit" ? (
        <LoadingState
          label={
            accountExists
              ? "Confirming your code..."
              : "Account creation in progress..."
          }
        />
      ) : (
        <AppButton
          label="Confirm and continue"
          onPress={() => void submit()}
          style={styles.submit}
        />
      )}
      <AppButton
        label={
          busy === "resend"
            ? "Resending verification..."
            : remaining > 0
              ? `Resend code (${remaining} left)`
              : "No resends left"
        }
        loading={busy === "resend"}
        variant="secondary"
        disabled={remaining <= 0 || busy !== null || ok}
        onPress={() => void resend()}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  status: { marginBottom: spacing.md },
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
  ok: {
    color: colors.valid,
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    marginTop: spacing.md,
  },
});
