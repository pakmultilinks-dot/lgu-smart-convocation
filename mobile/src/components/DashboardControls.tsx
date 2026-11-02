import { useCallback, useState } from "react";
import { StyleSheet, Text, View } from "react-native";
import { getSettings, updateSettings, type ConvocationSettings } from "../api/settingsApi";
import { useFocusEffect } from "expo-router";
import { AppButton, ErrorState, LoadingState, SectionCard, SectionEyebrow } from "../ui";
import { colors, fonts, spacing } from "../theme";

export function DashboardControls() {
  const [settings, setSettings] = useState<ConvocationSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  useFocusEffect(useCallback(() => {
    if (retry > 0) setError(null);
    let active = true;
    void getSettings().then((next) => {
      if (active) { setSettings(next); setError(null); }
    }).catch((e: unknown) => {
      if (active) setError(e instanceof Error ? e.message : "Cannot load dashboard controls.");
    });
    return () => { active = false; };
  }, [retry]));
  const toggle = async (key: "volunteer_enabled" | "liveboard_enabled") => {
    if (!settings || saving) return;
    setSaving(true); setError(null); setNote(null);
    try {
      const next = await updateSettings({ [key]: settings[key] === "true" ? "false" : "true" });
      setSettings(next);
      setNote("Saved. Open dashboards check every 15 seconds. Student Portal stays available.");
    } catch (e) { setError(e instanceof Error ? e.message : "Could not save dashboard access."); }
    finally { setSaving(false); }
  };
  return <SectionCard>
    <SectionEyebrow>Dashboard availability</SectionEyebrow>
    <Text style={styles.description}>
      Student Portal: always enabled. Existing registration and verification requirements still apply.
    </Text>
    {!settings && !error ? <LoadingState label="Loading controls…" /> : null}
    {error ? <ErrorState title="Dashboard controls" body={error} onRetry={() => setRetry((value) => value + 1)} /> : null}
    {settings ? <View style={styles.roles}>
      {([{ key: "volunteer_enabled", title: "Volunteer Operations", description: "Gate scanning, attendee lookup and attendance." },
        { key: "liveboard_enabled", title: "Live Dashboard", description: "Attendance display for event screens." }] as const).map((role) => {
        const enabled = settings[role.key] === "true";
        return <View key={role.key} style={styles.role}>
          <View style={styles.row}>
            <Text style={styles.title}>{role.title}</Text>
            <Text style={styles.status}>{enabled ? "Enabled" : "Disabled"}</Text>
          </View>
          <Text style={styles.description}>{role.description}</Text>
          <AppButton label={`${enabled ? "Disable" : "Enable"} ${role.title}`}
            variant="secondary" disabled={saving} loading={saving}
            onPress={() => void toggle(role.key)} />
        </View>;
      })}
    </View> : null}
    {note ? <Text accessibilityLiveRegion="polite" style={styles.note}>{note}</Text> : null}
  </SectionCard>;
}

const styles = StyleSheet.create({
  roles: { gap: spacing.lg },
  role: { borderTopWidth: 1, borderTopColor: colors.track, paddingTop: spacing.md, gap: spacing.sm },
  row: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: spacing.sm, flexWrap: "wrap" },
  title: { fontFamily: fonts.display, color: colors.ink, fontSize: 15 },
  status: { fontFamily: fonts.displayMedium, color: colors.muted, fontSize: 13 },
  description: { fontFamily: fonts.displayMedium, color: colors.muted, fontSize: 13, lineHeight: 20, marginBottom: spacing.sm },
  note: { fontFamily: fonts.displayMedium, color: colors.ink, fontSize: 13, lineHeight: 20, marginTop: spacing.md },
});
