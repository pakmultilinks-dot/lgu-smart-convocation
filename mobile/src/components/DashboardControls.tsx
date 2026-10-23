import { useCallback, useState } from "react";
import { Text } from "react-native";
import { getSettings, updateSettings, type ConvocationSettings } from "../api/settingsApi";
import { useFocusEffect } from "expo-router";
import { AppButton, ErrorState, LoadingState, SectionCard, SectionEyebrow } from "../ui";
import { colors, fonts } from "../theme";

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
    <Text style={{ fontFamily: fonts.displayMedium, color: colors.ink, marginBottom: 12 }}>
      Student Portal: always enabled. Existing registration and verification requirements still apply.
    </Text>
    {!settings && !error ? <LoadingState label="Loading controls…" /> : null}
    {error ? <ErrorState title="Dashboard controls" body={error} onRetry={() => setRetry((value) => value + 1)} /> : null}
    {settings ? <>
      <AppButton label={`${settings.volunteer_enabled === "true" ? "Disable" : "Enable"} Volunteer Operations`}
        disabled={saving} onPress={() => void toggle("volunteer_enabled")} />
      <AppButton label={`${settings.liveboard_enabled === "true" ? "Disable" : "Enable"} Live Dashboard`}
        variant="secondary" disabled={saving} onPress={() => void toggle("liveboard_enabled")} />
    </> : null}
    {note ? <Text style={{ fontFamily: fonts.displayMedium, color: colors.valid }}>{note}</Text> : null}
  </SectionCard>;
}
