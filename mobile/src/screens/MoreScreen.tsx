import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { View } from "react-native";
import { getAdminPin } from "../store/adminAccess";
import { colors } from "../theme";
import {
  AppHeader,
  ListRow,
  Screen,
  SectionCard,
  SectionEyebrow,
} from "../ui";

/**
 * More — the fifth tab (Phase 35G). Holds Settings for everyone; Broadcast
 * and Admin appear here only after the administrator PIN gate has been
 * unlocked on this device (before that, a single "Administrator access"
 * row leads into the gate). The routes themselves stay gated regardless.
 */
export function MoreScreen() {
  const router = useRouter();
  const [isAdmin, setIsAdmin] = useState(false);

  useFocusEffect(
    useCallback(() => {
      let alive = true;
      void getAdminPin().then((pin) => {
        if (alive) setIsAdmin(pin !== null);
      });
      return () => {
        alive = false;
      };
    }, []),
  );

  return (
    <Screen>
      <AppHeader
        title="More"
        subtitle="Settings and administrator tools"
      />

      <SectionCard tone="tint">
        <SectionEyebrow>Device</SectionEyebrow>
        <ListRow
          title="Settings"
          subtitle="Volunteer name, mode and device preferences"
          onPress={() => router.push("/(volunteer)/settings")}
        />
      </SectionCard>

      <SectionCard tone="tint">
        <SectionEyebrow>Administrator</SectionEyebrow>
        {isAdmin ? (
          <>
            <ListRow
              title="Announcements"
              subtitle="Send an announcement"
              onPress={() => router.push("/(volunteer)/broadcast")}
            />
            <View style={styles.divider} />
            <ListRow
              title="Admin"
              subtitle="Backend connection and convocation details"
              onPress={() => router.push("/(volunteer)/admin")}
            />
          </>
        ) : (
          <ListRow
            title="Administrator access"
            subtitle="Enter the administrator PIN to unlock admin tools"
            trailing={
              <View style={styles.lockTrailing}>
                <Ionicons name="lock-closed-outline" size={18} color={colors.muted} />
                <Ionicons name="chevron-forward" size={18} color={colors.muted} />
              </View>
            }
            onPress={() => router.push("/(volunteer)/broadcast")}
          />
        )}
      </SectionCard>
    </Screen>
  );
}

const styles = {
  divider: {
    height: 1,
    backgroundColor: colors.track,
  },
  lockTrailing: {
    flexDirection: "row" as const,
    alignItems: "center" as const,
    gap: 8,
  },
};
