import { router, useLocalSearchParams } from "expo-router";
import { useState } from "react";
import { StyleSheet, Text } from "react-native";
import { ApiError } from "../../src/api/client";
import * as studentApi from "../../src/api/studentApi";
import { takePendingReturn, peekPendingReturn } from "../../src/store/pendingReturn";
import { colors, fonts, spacing } from "../../src/theme";
import { AppButton, AppHeader, Field, Screen, SectionEyebrow } from "../../src/ui";

/** Step 1 — look up your convocation registration (Phase 5, §1). */
export default function StudentVerify() {
  const { returnTo: rawReturn } = useLocalSearchParams<{ returnTo?: string | string[] }>();
  // Resume the destination a signed-out redirect recorded, if any, so
  // verification → sign-in returns there instead of Home.
    const returnTo = rawReturn ?? peekPendingReturn() ?? undefined;
  const [form, setForm] = useState({
    registration_number: "",
    university_email: "",
    roll_number: "",
    student_name: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [showHelp, setShowHelp] = useState(false);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form) => (v: string) => {
    setForm((f) => ({ ...f, [k]: v }));
    setError(null);
    setShowHelp(false);
  };

  const submit = async () => {
    if (busy) return;
    if (Object.values(form).some(value => !value.trim())) {
      setError("Enter your registration number, university email, roll number and full name.");
      setShowHelp(false);
      return;
    }
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(form.university_email.trim())) {
      setError("Enter a valid university email address.");
      setShowHelp(false);
      return;
    }
    setBusy(true);
    setError(null);
    setShowHelp(false);
        // The destination now travels as an explicit returnTo param below —
        // discard the pending record so it cannot leak into a later flow.
        takePendingReturn();
        try {
      const r = await studentApi.verify({
        registration_number: form.registration_number.trim(),
        university_email: form.university_email.trim(),
        roll_number: form.roll_number.trim(),
        student_name: form.student_name.trim(),
      });
      router.push({
        pathname: "/(student)/code",
        params: {
          challenge_id: r.challenge_id,
          masked_email: r.masked_email,
          account_exists: String(r.account_exists),
          pending: String(r.pending),
          resend_remaining: String(r.resend_remaining),
          ...(returnTo ? { returnTo } : {}),
        },
      });
    } catch (e) {
      setShowHelp(true);
      setError(
        e instanceof ApiError
          ? e.code === "email_unavailable"
            ? "Email delivery is unavailable — no code was sent and no account was created. Contact the Examination Department."
            : e.status === 0
              ? "Could not reach the convocation system. Check your connection — nothing was checked."
              : e.message.replace(/registration_number/g, "Registration number").replace(/university_email/g, "University email").replace(/roll_number/g, "Roll number").replace(/student_name/g, "Student name")
          : "Verification failed. Check the connection and try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen>
      <AppHeader
        title="Verify registration"
        subtitle="Match the convocation list to open your account"
        onBack={() => router.replace("/(student)/welcome")}
      />
      <SectionEyebrow>Your details</SectionEyebrow>
      <Field
        label="Registration number"
        value={form.registration_number}
        onChangeText={set("registration_number")}
        autoCapitalize="characters"
        placeholder="REG-0001"
      />
      <Field
        label="University email"
        value={form.university_email}
        onChangeText={set("university_email")}
        autoCapitalize="none"
        keyboardType="email-address"
        placeholder="you@uni.edu.pk"
      />
      <Field
        label="Roll number"
        value={form.roll_number}
        onChangeText={set("roll_number")}
        autoCapitalize="characters"
        placeholder="090001"
      />
      <Field
        label="Student name"
        value={form.student_name}
        onChangeText={set("student_name")}
        hint="Exactly as printed on the convocation list"
        placeholder="Full name"
      />
      {error ? <Text style={styles.error}>{error}</Text> : null}
      {showHelp ? (
        <>
          <Text style={styles.help}>
            Your entries remain on this form. If the official list does not
            match, a request will not change it automatically; contact the
            Examination Department to confirm the correction.
          </Text>
          <AppButton
            label="Already have an account? Sign in for Help & corrections"
            variant="secondary"
            onPress={() => router.push({
              pathname: "/(student)/login",
                          params: { returnTo: returnTo ?? "/(student)/support" },
            })}
          />
        </>
      ) : null}
      <AppButton
        label={busy ? "Checking..." : "Send verification code"}
        loading={busy}
        onPress={() => void submit()}
        style={styles.submit}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  submit: { marginTop: spacing.md },
  error: {
    color: colors.invalid,
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    marginTop: spacing.xs,
  },
  help: {
    color: colors.muted,
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    lineHeight: 19,
    marginTop: spacing.sm,
  },
});
