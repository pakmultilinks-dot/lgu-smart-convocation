import { Ionicons } from "@expo/vector-icons";
import { router } from "expo-router";
import { useState } from "react";
import { Modal, Pressable, StyleSheet, Text, View } from "react-native";
import { fetchDashboardAccess } from "../src/api/client";
import { useDashboardAvailability } from "../src/hooks/useDashboardAvailability";
import { getAppMode, needsModeConfirmation, setAppMode, type AppMode } from "../src/store/appMode";
import { colors, fonts } from "../src/theme";
import { AppButton, AppHeader, Screen } from "../src/ui";

export default function EventTools() {
  const { access, state, refresh } = useDashboardAvailability();
  const [pending, setPending] = useState<AppMode | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const commit = async (mode: AppMode) => {
    if (mode === "student" || busy) return;
    setBusy(true); setPending(null); setError(null);
    try {
      const latest = await fetchDashboardAccess();
      if (!latest[mode]) { refresh(); return; }
      await setAppMode(mode);
      router.replace(mode === "volunteer" ? "/(volunteer)/home" : "/(liveboard)");
    } catch { setError("Event tools are unavailable. Check the service connection and try again."); }
    finally { setBusy(false); }
  };
  const pick = async (mode: AppMode) => {
    try {
      if (needsModeConfirmation(await getAppMode(), mode)) setPending(mode);
      else await commit(mode);
    } catch { setError("Could not open this dashboard. Please try again."); }
  };
  return <Screen>
    <AppHeader title="Staff & event access" subtitle="Tools for authorized event teams." onBack={() => router.canGoBack() ? router.back() : router.replace("/mode-picker")} />
    <View style={styles.group}>
      {([{ mode: "volunteer", title: "Volunteer Operations", detail: "Scan passes and manage gate entry", icon: "scan-outline" },
        { mode: "liveboard", title: "Live Dashboard", detail: "Attendance for venue displays", icon: "tv-outline" }] as const).map((item) => {
        const enabled = state === "online" && access?.[item.mode] === true;
        return <Pressable key={item.mode} accessibilityRole="button" accessibilityLabel={item.title}
          disabled={!enabled || busy} accessibilityState={{ disabled: !enabled || busy }}
          onPress={() => void pick(item.mode)} style={styles.row}>
          <View style={styles.icon}><Ionicons name={item.icon} size={22} color={colors.ink} /></View>
          <View style={{ flex: 1, gap: 4 }}><Text style={styles.title}>{item.title}</Text><Text style={styles.detail}>{item.detail}</Text>
            <Text style={styles.status}>{state === "checking" ? "Checking availability" : state !== "online" ? "Service connection needed" : enabled ? "Available" : "Disabled by administrator"}</Text></View>
          <Ionicons name={enabled ? "chevron-forward" : "lock-closed-outline"} size={18} color={colors.muted} />
        </Pressable>;
      })}
    </View>
    {state === "offline" ? <View style={styles.notice}><Text style={styles.detail}>Connect this device to your university service to use event tools.</Text><AppButton label="Connection settings" variant="secondary" onPress={() => router.push("/connect-server")} /><AppButton label="Retry" variant="ghost" onPress={refresh} /></View> : null}
    {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
    <AppButton label="Administrator access" variant="secondary" icon="shield-checkmark-outline" onPress={() => router.push("/administration")} />
    <Text style={styles.detail}>Student services stay available independently of event tools.</Text>
    <Modal visible={pending !== null} transparent animationType="fade" onRequestClose={() => setPending(null)}>
      <View style={styles.confirmBackdrop}><View style={styles.confirmBar}>
        <Text style={styles.title}>Open {pending === "volunteer" ? "Volunteer Operations" : "Live Dashboard"}?</Text>
        <Text style={styles.detail}>This changes the dashboard used on this device. Your account permissions stay the same.</Text>
        <AppButton label="Confirm mode switch" onPress={() => { if (pending) void commit(pending); }} />
        <AppButton label="Cancel mode switch" variant="ghost" onPress={() => setPending(null)} />
      </View></View>
    </Modal>
  </Screen>;
}
const styles = StyleSheet.create({
  group: { backgroundColor: "#FFFFFF", borderRadius: 16, borderWidth: 1, borderColor: colors.track, overflow: "hidden" },
  row: { padding: 16, minHeight: 100, flexDirection: "row", alignItems: "center", gap: 12, borderBottomWidth: 1, borderBottomColor: colors.track },
  icon: { backgroundColor: "#EDF4EF", borderRadius: 12, width: 44, height: 44, justifyContent: "center", alignItems: "center" },
  title: { fontFamily: fonts.display, fontSize: 15, color: colors.ink },
  detail: { fontFamily: fonts.displayMedium, fontSize: 13, lineHeight: 20, color: colors.muted },
  status: { fontFamily: fonts.displayMedium, fontSize: 11, color: colors.muted },
  notice: { gap: 8 }, error: { fontFamily: fonts.displayMedium, fontSize: 13, color: colors.invalid },
  confirmBackdrop: { flex: 1, backgroundColor: colors.overlay, justifyContent: "center", padding: 24 },
  confirmBar: { backgroundColor: colors.paper, padding: 24, borderRadius: 18, gap: 16 },
});
