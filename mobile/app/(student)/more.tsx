import { Ionicons } from "@expo/vector-icons";
import { router } from "expo-router";
import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import * as studentApi from "../../src/api/studentApi";
import { getToken } from "../../src/store/studentSession";
import { colors, fonts } from "../../src/theme";
import { AppHeader, Screen } from "../../src/ui";
import { StudentRouteGate } from "../../src/components/StudentRouteGate";

type Destination = Parameters<typeof router.push>[0];
export default function StudentMore() {
  const [signingOut, setSigningOut] = useState(false);
  const signOut = async () => {
    if (signingOut) return;
    setSigningOut(true);
    try { const token = await getToken(); if (token) await studentApi.logout(token); }
    catch { /* logout clears the local session even if the service is offline */ }
    finally { router.replace("/(student)/welcome"); setSigningOut(false); }
  };
  const row = (title: string, icon: keyof typeof Ionicons.glyphMap, path: Destination) =>
    <Pressable accessibilityRole="button" key={title} onPress={() => router.push(path)} style={styles.row}>
      <View style={styles.icon}><Ionicons name={icon} size={20} color={colors.ink} /></View>
      <Text style={styles.label}>{title}</Text><Ionicons name="chevron-forward" size={17} color={colors.muted} />
    </Pressable>;
  return <StudentRouteGate><Screen>
    <AppHeader title="Account & services" subtitle="Manage your details and prepare for the day." />
    <Text style={styles.section}>YOUR ACCOUNT</Text>
    <View style={styles.group}>
      {row("Profile & contact details", "person-outline", "/(student)/profile")}
      {row("Help & corrections", "help-circle-outline", "/(student)/support")}
    </View>
    <Text style={styles.section}>CONVOCATION</Text>
    <View style={styles.group}>
      {row("Event schedule", "calendar-outline", "/(student)/event")}
      {row("Readiness checklist", "checkbox-outline", "/(student)/readiness")}
      {row("Convocation history", "time-outline", "/(student)/history")}
      {row("Medalists", "medal-outline", "/(student)/medalists")}
    </View>
    <Text style={styles.section}>APP SETTINGS</Text>
    <View style={styles.group}>
      {row("Connection settings", "settings-outline", "/connect-server")}
      {row("Staff & event access", "people-outline", "/event-tools")}
    </View>
    <Pressable accessibilityRole="button" disabled={signingOut} onPress={() => void signOut()} style={styles.signout}>
      <Ionicons name="log-out-outline" size={20} color={colors.invalid} /><Text style={styles.signoutText}>{signingOut ? "Signing out..." : "Sign out"}</Text>
    </Pressable>
  </Screen></StudentRouteGate>;
}
const styles = StyleSheet.create({
  section: { fontFamily: fonts.displayMedium, fontSize: 11, letterSpacing: 0.8, color: colors.muted, marginBottom: -12 },
  group: { backgroundColor: "#FFFFFF", borderRadius: 16, borderWidth: 1, borderColor: colors.track, overflow: "hidden" },
  row: { minHeight: 60, flexDirection: "row", alignItems: "center", gap: 12, paddingHorizontal: 14, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: "#EDF1EE" },
  icon: { backgroundColor: "#EDF4EF", width: 34, height: 34, borderRadius: 10, alignItems: "center", justifyContent: "center" },
  label: { flex: 1, fontFamily: fonts.displayMedium, fontSize: 13, color: colors.ink },
  signout: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, minHeight: 48 },
  signoutText: { fontFamily: fonts.displayMedium, fontSize: 13, color: colors.invalid },
});
