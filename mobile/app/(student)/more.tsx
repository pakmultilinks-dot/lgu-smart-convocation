import { router } from "expo-router";
import { StyleSheet, View } from "react-native";
import * as studentApi from "../../src/api/studentApi";
import { getToken } from "../../src/store/studentSession";
import { colors } from "../../src/theme";
import { AppHeader, ListRow, Screen, SectionCard, SectionEyebrow } from "../../src/ui";

/**
 * More — the fifth student tab (Phase 31 Part A): the full directory of
 * less-frequent destinations (event details, readiness, history,
 * medalists, help) plus session controls, so Home stays a focused
 * dashboard instead of a long button list. No staff-only operations.
 */
export default function StudentMore() {
  const signOut = async () => {
    const token = await getToken();
    if (token) await studentApi.logout(token);
    router.replace("/(student)/welcome");
  };

  const row = (title: string, subtitle: string, path: Parameters<typeof router.push>[0]) => (
    <ListRow title={title} subtitle={subtitle} onPress={() => router.push(path)} />
  );

  return (
    <Screen>
      <AppHeader title="More" subtitle="Event, records and help" eyebrow="Student Portal" />

      <SectionCard tone="tint">
        <SectionEyebrow>Convocation</SectionEyebrow>
        {row("Event details", "Rehearsal and ceremony schedule", "/(student)/event")}
        <View style={styles.divider} />
        {row("Readiness", "What is still needed before the day", "/(student)/readiness")}
        <View style={styles.divider} />
        {row("Convocation history", "Past ceremonies and your record", "/(student)/history")}
        <View style={styles.divider} />
        {row("Medalist board", "Published medalists and photos", "/(student)/medalists")}
      </SectionCard>

      <SectionCard tone="tint">
        <SectionEyebrow>Account</SectionEyebrow>
        {row("Profile", "Photo and contact details", "/(student)/profile")}
        <View style={styles.divider} />
        {row("Help & corrections", "Ask for a registration correction", "/(student)/support")}
      </SectionCard>

      <SectionCard tone="tint">
        <SectionEyebrow>Device</SectionEyebrow>
        <ListRow
          title="Change device mode"
          subtitle="Switch between student, volunteer and scanner"
          onPress={() => router.replace("/mode-picker")}
        />
        <View style={styles.divider} />
        <ListRow title="Sign out" subtitle="End the session on this device" onPress={() => void signOut()} />
      </SectionCard>
    </Screen>
  );
}

const styles = StyleSheet.create({
  divider: { height: 1, backgroundColor: colors.track },
});