import * as ImagePicker from "expo-image-picker";
import { Ionicons } from "@expo/vector-icons";
import { router } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Image, StyleSheet, Text, View } from "react-native";
import { ApiError } from "../../src/api/client";
import * as studentApi from "../../src/api/studentApi";
import { useFreshServerData } from "../../src/hooks/useFreshServerData";
import { clearToken, getToken } from "../../src/store/studentSession";
import { colors, fonts, radius, spacing } from "../../src/theme";
import {
  AppButton,
  AppHeader,
  ErrorState,
  Field,
  ListRow,
  LoadingState,
  ProgressTrack,
  Screen,
  SectionCard,
  SectionEyebrow,
  StatusPill,
} from "../../src/ui";

type Load =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; me: studentApi.SessionBody; token: string };

/** Profile completion (Phase 5, §3): progress, read-only official
 *  details, phone + photo. The convocation list stays authoritative.
 *  Phase 8: silent focus/resume/≤30s refreshes update the server record
 *  WITHOUT clobbering a half-typed phone number or a running photo
 *  upload — an in-progress edit always wins over a background poll. */
export default function StudentProfile() {
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [phone, setPhone] = useState("");
  const [saving, setSaving] = useState<"phone" | "photo" | null>(null);
  const [stale, setStale] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [photo, setPhoto] = useState<{ uri: string; headers: Record<string, string> } | null>(null);
  const [photoFailed, setPhotoFailed] = useState(false);
  const [phoneDirty, setPhoneDirty] = useState(false); // render-safe dirty flag
  const hasDataRef = useRef(false);
  const savingRef = useRef(false);
  const phoneRef = useRef(""); // last value synced from the server
  const phoneDirtyRef = useRef(false); // the student has unsaved edits

  const reload = useCallback(async (silent = false) => {
    const token = await getToken();
    if (!token) {
      setLoad({ kind: "loading" });
      router.replace("/(student)/welcome");
      return;
    }
    // Never interrupt an upload/save with a background refresh.
    if (silent && savingRef.current) return;
    if (!silent) setLoad({ kind: "loading" });
    try {
      const me = await studentApi.me(token);
      if (!me.registration) {
        router.replace("/(student)/verify");
        return;
      }
      const serverPhone = me.profile.phone ?? "";
      if (!silent || !phoneDirtyRef.current) {
        // Only an untouched field follows the server; an edit in progress
        // is preserved until the student saves it.
        phoneRef.current = serverPhone;
        phoneDirtyRef.current = false;
        setPhoneDirty(false);
        setPhone(serverPhone);
      }
      hasDataRef.current = true;
      setStale(false);
      setLoad({ kind: "ready", me, token });
      // A completed profile stays on this screen (the heading reflects
      // "Profile complete") — the student chooses when to move on via the
      // "Go to home" button below. Silent polls never navigate either.
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        await clearToken();
        router.replace("/(student)/welcome");
        return;
      }
      // Keep the last data on a failed background refresh — a network
      // failure is never rendered as an authoritative rejection.
      if (silent && hasDataRef.current) {
        setStale(true);
        return;
      }
      setLoad({
        kind: "error",
        message:
          e instanceof ApiError
            ? e.message
            : "The profile could not be loaded. Check the connection.",
      });
    }
  }, []);

  // Focus / resume / manual / ≤30s cadence — one shared rule.
  useFreshServerData(() => reload(true));

  // <Image> cannot resolve the relative photo route — resolve it against the
  // backend host. Only the async callback writes state; the render gates on
  // me.profile.photo, so a cached URI is never shown for a missing photo.
  useEffect(() => {
    if (load.kind !== "ready" || !load.me.profile.photo) return;
    let live = true;
    void studentApi.photoSource(load.token)
      .then((s) => {
        if (!live) return;
        setPhoto(s);
        setPhotoFailed(false);
      })
      .catch(() => live && setPhotoFailed(true));
    return () => {
      live = false;
    };
  }, [load]);

  const savePhone = async (ready: Extract<Load, { kind: "ready" }>) => {
    if (saving) return; // one save at a time — no duplicate submits
    const value = phone.trim();
    if (value.length > 32) {
      setError("The phone number must be 32 characters or fewer.");
      return;
    }
    setSaving("phone");
    savingRef.current = true;
    setError(null);
    setNote(null);
    try {
      // Success is reported only from the server's confirmed response.
      const out = await studentApi.updatePhone(ready.token, value);
      phoneRef.current = value;
      phoneDirtyRef.current = false;
      setPhoneDirty(false);
      setLoad({ ...ready, me: { ...ready.me, profile: out.profile, completion: out.completion } });
      setNote("Phone saved.");
    } catch (e) {
      // The typed value stays on screen — the student never retypes it.
      setError(e instanceof ApiError ? e.message : "Could not save the phone number.");
    } finally {
      savingRef.current = false;
      setSaving(null);
    }
  };

  const pickPhoto = async (ready: Extract<Load, { kind: "ready" }>, fromCamera: boolean) => {
    if (saving) return; // one upload at a time — no duplicate submits
    setError(null);
    setNote(null);
    savingRef.current = true;
    try {
      const perm = fromCamera
        ? await ImagePicker.requestCameraPermissionsAsync()
        : await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!perm.granted) {
        setError(
          fromCamera
            ? "Camera access is off — allow it in system settings to take a photo."
            : "Photo access is off — allow it in system settings to choose a photo.",
        );
        return;
      }
      const res = fromCamera
        ? await ImagePicker.launchCameraAsync({ quality: 0.8, base64: true })
        : await ImagePicker.launchImageLibraryAsync({
            mediaTypes: ["images"],
            quality: 0.8,
            base64: true,
          });
      const asset = res.assets?.[0];
      if (res.canceled || !asset?.base64) return;
      setSaving("photo");
      const out = await studentApi.uploadPhoto(ready.token, asset.base64);
      setPreview(asset.uri);
      setPhotoFailed(false);
      setLoad({ ...ready, me: { ...ready.me, profile: out.profile, completion: out.completion } });
      // The server STORES the file; it performs no verification. Say what happened.
      setNote("Photo uploaded.");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not upload the photo.");
    } finally {
      savingRef.current = false;
      setSaving(null);
    }
  };

  // Phase 8: signing out must revoke the server session AND clear the
  // local token — a later session must never silently reuse it. (The old
  // button navigated away without touching the token: a stale credential.)
  const signOut = async () => {
    const token = await getToken();
    try {
      if (token) await studentApi.logout(token);
    } finally {
      await clearToken();
      router.replace("/(student)/welcome");
    }
  };

  if (load.kind === "loading") {
    return (
      <Screen scroll={false}>
        <LoadingState label="Loading your profile..." />
      </Screen>
    );
  }
  if (load.kind === "error") {
    return (
      <Screen scroll={false}>
        <ErrorState
          title="Profile unavailable"
          body={load.message}
          onRetry={() => void reload()}
        />
      </Screen>
    );
  }
  const { me } = load;
  const reg = me.registration!;
  const complete = me.completion.complete;
  // Each incomplete step maps to a REAL action via `run` (a stable key, not a
  // render-time closure — keeps react-hooks/refs happy and rows never dead).
  const steps = [
    { label: "Identity verified", done: me.completion.verified,
      action: "Verify identity", run: "verify" as const },
    { label: "Registration claimed", done: me.completion.claimed,
      action: "Claim registration", run: "verify" as const },
    { label: "Profile photo", done: me.completion.photo,
      action: "Add photo", run: "photo" as const },
  ];
  const runStep = (k: "verify" | "photo") => {
    if (k === "photo") void pickPhoto(load, false);
    else router.push("/(student)/verify");
  };

  return (
    <Screen>
      <AppHeader
        title={complete ? "Profile complete" : "Complete your profile"}
        subtitle={reg.student_name}
        onBack={() => router.back()}
      />
      {stale ? (
        <Text style={styles.stale}>
          Offline — showing your last loaded profile. Retrying automatically.
        </Text>
      ) : null}
      <SectionEyebrow>
        Completion · {me.completion.done} of {me.completion.total}
      </SectionEyebrow>
      <ProgressTrack value={me.completion.done} max={me.completion.total} />
      <View style={styles.steps}>
        {steps.map((s) => (
          <ListRow
            key={s.label}
            title={s.label}
            onPress={s.done ? undefined : () => runStep(s.run)}
            trailing={
              s.done ? (
                <StatusPill size="sm" state="accept" label="Done" />
              ) : (
                // Explicit, pressable control — not a dead "Needed" label.
                <View style={styles.stepAction}>
                  <Text style={styles.stepActionText}>{s.action}</Text>
                  <Ionicons name="chevron-forward" size={16} color={colors.brand} />
                </View>
              )
            }
          />
        ))}
      </View>

      <SectionEyebrow>Official record</SectionEyebrow>
      <SectionCard>
        <ListRow title="Registration number" subtitle={reg.registration_number} />
        <ListRow title="Student name" subtitle={reg.student_name} />
        <ListRow title="Roll number" subtitle={reg.roll_number} />
        <ListRow title="Department" subtitle={reg.department} />
        <ListRow title="Registration status" subtitle={reg.status} />
      </SectionCard>
      <Text style={styles.hint}>
        These come from the official convocation list and cannot be edited here.
        If something is wrong, ask the Examination Department to correct it —
        a request never changes the record on its own.
      </Text>
      <AppButton
        label="Request a correction"
        variant="secondary"
        onPress={() => router.push("/(student)/support")}
        style={styles.correct}
      />

      <SectionEyebrow>Photo</SectionEyebrow>
      <View style={styles.photoRow}>
        {preview || photo ? (
          <Image
            key={preview ?? me.profile.photo_updated_at ?? "photo"}
            source={preview ? { uri: preview } : photo!}
            style={styles.photo}
          />
        ) : (
          <View style={[styles.photo, styles.photoEmpty]} />
        )}
        <View style={styles.photoActions}>
          <AppButton
            label={me.profile.photo ? "Replace photo" : "Add photo"}
            variant="secondary"
            loading={saving === "photo"}
            disabled={saving !== null && saving !== "photo"}
            onPress={() => void pickPhoto(load, false)}
          />
          <AppButton
            label="Take photo"
            variant="ghost"
            loading={saving === "photo"}
            disabled={saving !== null && saving !== "photo"}
            onPress={() => void pickPhoto(load, true)}
          />
        </View>
      </View>
      <Text style={styles.hint}>
        {saving === "photo"
          ? "Uploading your photo…"
          : me.profile.photo
            ? photoFailed
              ? "Photo saved on your account, but it could not be displayed — check the connection."
              : `Photo on file${me.profile.photo_updated_at ? ` · updated ${me.profile.photo_updated_at.slice(0, 10)}` : ""}.`
            : "No photo on file yet — staff need one to identify you at convocation."}
      </Text>

      <SectionEyebrow>Contact</SectionEyebrow>
      <Field
        label="Phone number"
        value={phone}
        onChangeText={(v) => {
          phoneDirtyRef.current = v.trim() !== phoneRef.current;
          setPhoneDirty(phoneDirtyRef.current);
          setPhone(v);
        }}
        keyboardType="phone-pad"
        placeholder="+92 300 0000000"
        hint="Optional — for convocation updates. Up to 32 characters."
        error={phone.trim().length > 32 ? "The phone number must be 32 characters or fewer." : null}
      />
      {note ? <Text style={styles.note}>{note}</Text> : null}
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <AppButton
        label={
          saving === "phone"
            ? "Saving..."
            : phoneDirty
              ? "Save phone number"
              : "Phone number saved"
        }
        loading={saving === "phone"}
        disabled={saving === "photo" || (!phoneDirty && saving !== "phone")}
        onPress={() => void savePhone(load)}
        style={styles.submit}
      />
      {complete ? (
        <AppButton
          label="Go to home"
          variant="secondary"
          onPress={() => router.replace("/(student)/home")}
        />
      ) : null}
      <AppButton
        label="Sign out"
        variant="ghost"
        onPress={() => void signOut()}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  steps: { marginTop: spacing.sm },
  stepAction: { flexDirection: "row", alignItems: "center", gap: 2 },
  stepActionText: {
    color: colors.brand,
    fontFamily: fonts.displayMedium,
    fontSize: 13,
  },
  correct: { marginTop: spacing.sm },
  stale: {
    color: colors.amber,
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    marginBottom: spacing.sm,
  },
  hint: {
    color: colors.muted,
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    marginTop: spacing.xs,
  },
  photoRow: {
    flexDirection: "row",
    gap: spacing.md,
    marginTop: spacing.sm,
    alignItems: "center",
  },
  photo: { width: 88, height: 88, borderRadius: radius.md },
  photoEmpty: { backgroundColor: colors.track },
  photoActions: { flex: 1, gap: spacing.xs },
  submit: { marginTop: spacing.md },
  note: {
    color: colors.valid,
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
