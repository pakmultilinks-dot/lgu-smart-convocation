import { router } from "expo-router";
import { useState } from "react";
import { StyleSheet, Text } from "react-native";
import { ApiError } from "../../src/api/client";
import * as studentApi from "../../src/api/studentApi";
import { colors, fonts, spacing } from "../../src/theme";
import { AppButton, AppHeader, Field, Screen, SectionEyebrow } from "../../src/ui";

/** Step 1 — look up your convocation registration (Phase 5, §1). */
export default function StudentVerify() {
  const [form, setForm] = useState({
    registration_number: "",
    university_email: "",
    roll_number: "",
    student_name: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form) => (v: string) =>
    setForm((f) => ({ ...f, [k]: v }));

  const submit = async () => {
    setBusy(true);
    setError(null);
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
        },
      });
    } catch (e) {
      setError(
        e instanceof ApiError
          ? e.code === "email_unavailable"
            ? "Email delivery is unavailable — no code was sent and no account was created. Contact the Examination Department."
            : e.status === 0
              ? "Could not reach the convocation system. Check your connection — nothing was checked."
              : e.message
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
        onBack={() => router.back()}
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
});
