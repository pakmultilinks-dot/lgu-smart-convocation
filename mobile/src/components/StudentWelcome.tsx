import { Ionicons } from "@expo/vector-icons";
import { router } from "expo-router";
import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { setAppMode } from "../store/appMode";
import { colors, fonts } from "../theme";
import { DashboardGrid, DashboardTile } from "./DashboardWidgets";
import { AppButton, LguMark, Screen, SectionEyebrow } from "../ui";

export function StudentWelcome() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const open = async (path: "/(student)/login" | "/(student)/verify") => {
    if (busy) return;
    setBusy(true); setError(null);
    try { await setAppMode("student"); router.push(path); }
    catch { setError("Could not open your account. Please try again."); }
    finally { setBusy(false); }
  };
  return <Screen>
    <View style={styles.brand}>
      <LguMark size={44} />
      <View style={{ flex: 1 }}><Text style={styles.brandName}>LGU Convocation</Text><Text style={styles.caption}>Lahore Garrison University</Text></View>
      <Pressable accessibilityRole="button" accessibilityLabel="Connection settings" onPress={() => router.push("/connect-server")} style={styles.settings}>
        <Ionicons name="settings-outline" size={22} color={colors.ink} />
      </Pressable>
    </View>
    <View style={styles.heading}><Text style={styles.heroTitle}>Convocation dashboard</Text><Text style={styles.body}>Student services and event access</Text></View>
      <AppButton label="Sign in" icon="arrow-forward" disabled={busy} onPress={() => void open("/(student)/login")} />
    <DashboardGrid>
      <DashboardTile title="Registration" detail="Activate or view your record" icon="document-text-outline" onPress={() => void open("/(student)/verify")} />
      <DashboardTile title="Entry pass" detail="Sign in to view your QR" icon="qr-code-outline" onPress={() => void open("/(student)/login")} />
      <DashboardTile title="Event schedule" detail="Published ceremony details" icon="calendar-outline" onPress={() => router.push("/(student)/event")} />
      <DashboardTile title="Updates" detail="Published university notices" icon="megaphone-outline" onPress={() => router.push("/(student)/announcements")} />
    </DashboardGrid>
    <SectionEyebrow>Your account</SectionEyebrow>
    <View style={styles.account}>
      <AppButton label="Create student account" variant="secondary" disabled={busy} onPress={() => void open("/(student)/verify")} />
      <Text style={styles.note}>Only students on the official university registration list can create an account.</Text>
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
      <Pressable accessibilityRole="button" onPress={() => router.push("/(student)/recovery")} style={styles.link}><Text style={styles.linkText}>Forgot your password?</Text></Pressable>
    </View>
    <Pressable accessibilityRole="button" accessibilityLabel="Staff & event access" onPress={() => router.push("/event-tools")} style={styles.staff}>
      <Ionicons name="people-outline" size={20} color={colors.ink} /><Text style={styles.staffText}>Staff & event access</Text><Ionicons name="chevron-forward" size={18} color={colors.muted} />
    </Pressable>
  </Screen>;
}
const styles = StyleSheet.create({
  heading: { gap: 5 },
  brand: { flexDirection: "row", gap: 10, alignItems: "center" },
  brandName: { fontFamily: fonts.display, fontSize: 15, color: colors.ink },
  caption: { fontFamily: fonts.displayMedium, fontSize: 11, color: colors.muted, marginTop: 3 },
  settings: { minWidth: 44, minHeight: 44, justifyContent: "center", alignItems: "center" },
  hero: { backgroundColor: "#14452F", borderRadius: 20, padding: 16, gap: 6 },
  heroIcon: { position: "absolute", top: 16, right: 16, backgroundColor: "#2E5B46", width: 40, height: 40, borderRadius: 12, justifyContent: "center", alignItems: "center" },
  eyebrow: { fontFamily: fonts.displayMedium, fontSize: 11, letterSpacing: 1, color: "#C3D6CA" },
  heroTitle: { fontFamily: fonts.display, fontSize: 24, lineHeight: 30, color: colors.ink },
  heroBody: { fontFamily: fonts.displayMedium, fontSize: 13, lineHeight: 20, color: "#DCE9E1" },
  tags: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  tag: { fontFamily: fonts.displayMedium, fontSize: 11, color: "#FFFFFF", backgroundColor: "#2E5B46", paddingHorizontal: 10, paddingVertical: 6, borderRadius: 8 },
  account: { gap: 10 },
  title: { fontFamily: fonts.display, fontSize: 24, color: colors.ink },
  body: { fontFamily: fonts.displayMedium, fontSize: 13, lineHeight: 20, color: colors.muted },
  note: { fontFamily: fonts.displayMedium, fontSize: 11, lineHeight: 17, color: colors.muted },
  link: { minHeight: 44, alignItems: "center", justifyContent: "center" },
  linkText: { fontFamily: fonts.displayMedium, fontSize: 13, color: "#14452F" },
  staff: { flexDirection: "row", gap: 12, alignItems: "center", borderTopWidth: 1, borderTopColor: colors.track, paddingTop: 16, minHeight: 48 },
  staffText: { fontFamily: fonts.displayMedium, fontSize: 13, color: colors.ink, flex: 1 },
  error: { fontFamily: fonts.displayMedium, fontSize: 13, color: colors.invalid },
});
