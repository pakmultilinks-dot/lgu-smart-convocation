// Student support centre (Phase 9, §3). One screen: the list of requests
// the signed-in student has opened, plus a composer to open a new one.
// A request never changes a registration on its own — the Examination
// Department reviews it and applies any correction through the official
// record, so this screen only reports status and the latest reply.

import { router } from "expo-router";
import { useCallback, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { getToken } from "../../src/store/studentSession";
import { ApiError } from "../../src/api/client";
import * as supportApi from "../../src/api/supportApi";
import { useFreshServerData } from "../../src/hooks/useFreshServerData";
import { colors, fonts, radius, spacing } from "../../src/theme";
import { convocationLine } from "../../src/utils/convocation";
import {
  AppButton,
  AppHeader,
  EmptyState,
  ErrorState,
  Field,
  ListRow,
  LoadingState,
  Screen,
  SectionCard,
  SectionEyebrow,
  StatusPill,
} from "../../src/ui";

type Step =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; data: supportApi.SupportList; stale: boolean };

const SUBJECT_MAX = 160;
const MESSAGE_MAX = 4000;

/** Per-category guidance (Phase 32, Part C): what belongs in this category,
 *  what the student should include, and the standing caveat that staff
 *  review is institutional — no request changes a record immediately. */
const GUIDE: Record<supportApi.Category, { include: string; evidence: string }> = {
  missing_registration: {
    include: "Your registration number (if you have one), full name, roll number and department as you believe they should appear.",
    evidence: "A photo of your student ID or result card helps staff match the official list.",
  },
  correction: {
    include: "The registration number, the exact field that is wrong (name, roll number or department) and how it should read.",
    evidence: "Attach or describe supporting documents (result card, ID) in your message.",
  },
  cancellation: {
    include: "Your registration number and why the cancellation or reinstatement should be reviewed.",
    evidence: "Any official notice you received about the cancellation.",
  },
  account_claim: {
    include: "The university email you used and what happens when you try to claim your registration.",
    evidence: "Screenshots of the error, if any, described in the message.",
  },
  general: {
    include: "Your question about convocation — dates, venue, passes or procedures.",
    evidence: "No documents needed for a general question.",
  },
};

export default function SupportScreen() {
  const [step, setStep] = useState<Step>({ kind: "loading" });
  // Composer state — derive the active hint from the picked category.
  const [category, setCategory] = useState<supportApi.Category>("correction");
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  // The server-confirmed request — shown with its real reference only after
  // the create call succeeds, never optimistically.
  const [sent, setSent] = useState<supportApi.SupportRequest | null>(null);

  const load = useCallback(async (silent = false) => {
    const token = await getToken();
    if (!token) {
      router.replace("/(student)/welcome");
      return;
    }
    if (!silent) setStep({ kind: "loading" });
    try {
      const data = await supportApi.list(token);
      setStep({ kind: "ready", data, stale: false });
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        router.replace("/(student)/welcome");
        return;
      }
      setStep((prev) =>
        prev.kind === "ready"
          ? { ...prev, stale: true }
          : {
              kind: "error",
              message:
                e instanceof ApiError
                  ? e.message
                  : "Your requests could not be loaded. Check the connection.",
            },
      );
    }
  }, []);

  const refresh = useFreshServerData(() => load(true));

  const submit = async () => {
    if (sending) return; // one submit at a time — no duplicate requests
    const token = await getToken();
    if (!token) return router.replace("/(student)/welcome");
    const subjectText = subject.trim();
    const messageText = message.trim();
    if (!subjectText || !messageText) {
      setFormError("Add a short subject and describe what you need.");
      return;
    }
    setSending(true);
    setFormError(null);
    try {
      const res = await supportApi.create(token, {
        category,
        subject: subjectText.slice(0, SUBJECT_MAX),
        message: messageText.slice(0, MESSAGE_MAX),
      });
      setSent(res.request);
      setSubject("");
      setMessage("");
      await load(true);
    } catch (e) {
      setFormError(
        e instanceof ApiError
          ? e.message
          : "Your request could not be sent. Try again.",
      );
    } finally {
      setSending(false);
    }
  };

  if (step.kind === "loading") {
    return (
      <Screen scroll={false}>
        <LoadingState label="Loading your requests..." />
      </Screen>
    );
  }
  if (step.kind === "error") {
    return (
      <Screen scroll={false}>
        <ErrorState
          title="Support unavailable"
          body={step.message}
          onRetry={() => void load()}
        />
      </Screen>
    );
  }

  const { data, stale } = step;

  return (
    <Screen>
      <AppHeader
        eyebrow="Student Support"
        title="Help & corrections"
        subtitle={convocationLine(data.convocation)}
        onBack={() => router.back()}
      />
      <Text style={styles.intro}>
        Report a missing or mismatched registration, ask for a correction, or
        raise a cancellation or account-claim issue. The Examination Department
        reviews every request; a correction is applied to your official record
        by staff, never automatically.
      </Text>
      {stale ? (
        <Text style={styles.stale}>
          Offline — showing your last loaded requests. Retrying automatically.
        </Text>
      ) : null}

      <SectionEyebrow>Open a new request</SectionEyebrow>
      <SectionCard>
        <Text style={styles.label}>What do you need help with?</Text>
        {/* Full-width stacked selector — five categories cannot be legible in
            one horizontal segmented row on a phone. */}
        <View style={styles.catList}>
          {supportApi.CATEGORIES.map((c) => {
            const active = c.value === category;
            return (
              <Pressable
                key={c.value}
                accessibilityRole="radio"
                accessibilityState={{ selected: active }}
                accessibilityLabel={c.label}
                onPress={() => setCategory(c.value)}
                style={[styles.cat, active && styles.catActive]}
              >
                <Text style={[styles.catLabel, active && styles.catLabelActive]}>
                  {c.label}
                </Text>
                <Text style={styles.catHint}>{c.hint}</Text>
              </Pressable>
            );
          })}
        </View>
        <Text style={styles.label}>Include in your message</Text>
        <Text style={styles.guide}>{GUIDE[category].include}</Text>
        <Text style={styles.guide}>{GUIDE[category].evidence}</Text>
        <Text style={styles.guide}>
          The Examination Department reviews every request — a correction is
          applied to your official record by staff, never immediately and never
          automatically.
        </Text>
        <Field
          label="Subject"
          placeholder="One-line summary"
          value={subject}
          onChangeText={(v) => {
            setSent(null); // composing again — the old confirmation no longer applies
            setSubject(v);
          }}
          maxLength={SUBJECT_MAX}
          error={
            subject.trim().length === 0 && formError ? "A subject is required." : null
          }
        />
        <Field
          label="Details"
          placeholder="Describe the issue and what you need"
          value={message}
          onChangeText={(v) => {
            setSent(null);
            setMessage(v);
          }}
          multiline
          numberOfLines={4}
          textAlignVertical="top"
          style={styles.message}
          maxLength={MESSAGE_MAX}
          error={
            message.trim().length === 0 && formError ? "Add some detail." : null
          }
        />
        {formError && subject.trim() && message.trim() ? (
          <Text style={styles.formError}>{formError}</Text>
        ) : null}
        <AppButton
          label={sending ? "Sending..." : "Send request"}
          onPress={() => void submit()}
          loading={sending}
          disabled={sending}
          style={styles.submit}
        />
      </SectionCard>

      {sent ? (
        <SectionCard>
          <Text style={styles.sentTitle}>Request sent · {sent.reference}</Text>
          <Text style={styles.guide}>
            Quote reference {sent.reference} in any follow-up. Status:{" "}
            {sent.status_label}.
          </Text>
          <AppButton
            label="View this request"
            variant="secondary"
            onPress={() => router.push(`/(student)/support-detail?id=${sent.id}`)}
            style={styles.submit}
          />
        </SectionCard>
      ) : null}

      <SectionEyebrow>Your requests · {data.total}</SectionEyebrow>
      {data.requests.length === 0 ? (
        <EmptyState
          icon="chatbubbles-outline"
          title="No requests yet"
          body="Requests you open appear here with their status and any reply from the Examination Department."
        />
      ) : (
        <SectionCard pad={false}>
          {data.requests.map((r) => (
            <ListRow
              key={r.id}
              title={r.subject}
              subtitle={`${r.reference} · ${r.category_label} · updated ${r.updated_at.slice(0, 10)}`}
              trailing={<StatusPill state={supportApi.pillState(r.status)} label={r.status_label} size="sm" />}
              onPress={() => router.push(`/(student)/support-detail?id=${r.id}`)}
            />
          ))}
        </SectionCard>
      )}
      <AppButton
        label="Refresh"
        variant="ghost"
        icon="refresh"
        onPress={() => void refresh()}
        style={styles.refresh}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  intro: {
    color: colors.muted,
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    lineHeight: 19,
    marginBottom: spacing.lg,
  },
  stale: {
    color: colors.amber,
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    marginTop: -spacing.sm,
    marginBottom: spacing.md,
  },
  label: {
    color: colors.ink,
    fontFamily: fonts.displayMedium,
    fontSize: 14,
    marginBottom: spacing.sm,
  },
  catList: { gap: spacing.xs, marginBottom: spacing.md },
  cat: {
    borderWidth: 1,
    borderColor: colors.track,
    borderRadius: radius.md,
    padding: spacing.sm,
  },
  catActive: { borderColor: colors.ink, backgroundColor: colors.track },
  catLabel: {
    color: colors.ink,
    fontFamily: fonts.displayMedium,
    fontSize: 14,
  },
  catLabelActive: { fontFamily: fonts.display },
  catHint: {
    color: colors.muted,
    fontFamily: fonts.displayMedium,
    fontSize: 12,
    marginTop: 2,
  },
  guide: {
    color: colors.muted,
    fontFamily: fonts.displayMedium,
    fontSize: 12,
    lineHeight: 18,
    marginBottom: spacing.xs,
  },
  sentTitle: {
    color: colors.ink,
    fontFamily: fonts.displayMedium,
    fontSize: 15,
    marginBottom: spacing.xs,
  },
  message: { minHeight: 96 },
  formError: {
    color: colors.invalid,
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    marginBottom: spacing.sm,
  },
  submit: { marginTop: spacing.md },
  refresh: { marginTop: spacing.md },
});
