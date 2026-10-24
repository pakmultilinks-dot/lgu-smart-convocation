import { Ionicons } from "@expo/vector-icons";
import { router } from "expo-router";
import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { setAppMode } from "../store/appMode";
import { colors, fonts } from "../theme";
import { AppButton, LguMark, Screen } from "../ui";

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
    <View style={styles.hero}>
      <View style={styles.heroIcon}><Ionicons name="school-outline" size={30} color="#FFFFFF" /></View>
      <Text style={styles.eyebrow}>STUDENT SERVICES</Text>
      <Text style={styles.heroTitle}>Your moment.{"\n"}Your convocation.</Text>
      <Text style={styles.heroBody}>Your official registration, entry pass and ceremony updates, together.</Text>
      <View style={styles.tags}><Text style={styles.tag}>Registration</Text><Text style={styles.tag}>Entry pass</Text><Text style={styles.tag}>Updates</Text></View>
    </View>
    <View style={styles.account}>
      <Text style={styles.title}>Welcome to your portal</Text>
      <Text style={styles.body}>Sign in to continue, or activate your student account.</Text>
      <AppButton label="Sign in" icon="arrow-forward" disabled={busy} onPress={() => void open("/(student)/login")} />
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
  brand: { flexDirection: "row", gap: 10, alignItems: "center" },
  brandName: { fontFamily: fonts.display, fontSize: 15, color: colors.ink },
  caption: { fontFamily: fonts.displayMedium, fontSize: 11, color: colors.muted, marginTop: 3 },
  settings: { minWidth: 44, minHeight: 44, justifyContent: "center", alignItems: "center" },
  hero: { backgroundColor: "#14452F", borderRadius: 20, padding: 20, gap: 8 },
  heroIcon: { position: "absolute", top: 16, right: 16, backgroundColor: "#2E5B46", width: 40, height: 40, borderRadius: 12, justifyContent: "center", alignItems: "center" },
  eyebrow: { fontFamily: fonts.displayMedium, fontSize: 11, letterSpacing: 1, color: "#C3D6CA" },
  heroTitle: { fontFamily: fonts.display, fontSize: 24, lineHeight: 30, color: "#FFFFFF" },
  heroBody: { fontFamily: fonts.displayMedium, fontSize: 13, lineHeight: 20, color: "#DCE9E1" },
  tags: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  tag: { fontFamily: fonts.displayMedium, fontSize: 11, color: "#FFFFFF", backgroundColor: "#2E5B46", paddingHorizontal: 10, paddingVertical: 6, borderRadius: 8 },
  account: { gap: 12 },
  title: { fontFamily: fonts.display, fontSize: 24, color: colors.ink },
  body: { fontFamily: fonts.displayMedium, fontSize: 13, lineHeight: 20, color: colors.muted },
  note: { fontFamily: fonts.displayMedium, fontSize: 11, lineHeight: 17, color: colors.muted },
  link: { minHeight: 44, alignItems: "center", justifyContent: "center" },
  linkText: { fontFamily: fonts.displayMedium, fontSize: 13, color: "#14452F" },
  staff: { flexDirection: "row", gap: 12, alignItems: "center", borderTopWidth: 1, borderTopColor: colors.track, paddingTop: 16, minHeight: 48 },
  staffText: { fontFamily: fonts.displayMedium, fontSize: 13, color: colors.ink, flex: 1 },
  error: { fontFamily: fonts.displayMedium, fontSize: 13, color: colors.invalid },
});
