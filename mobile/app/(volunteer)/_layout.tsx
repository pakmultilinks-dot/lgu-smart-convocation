import { Ionicons } from "@expo/vector-icons";
import { Tabs } from "expo-router";
import type { ColorValue } from "react-native";
import { colors, fontWeight } from "../../src/theme";

function tabIcon(name: keyof typeof Ionicons.glyphMap) {
  function TabBarIcon({ color, size }: { color: ColorValue; size: number }) {
    return <Ionicons name={name} size={size} color={color as string} />;
  }
  return TabBarIcon;
}

export default function VolunteerTabLayout() {
  return (
    <Tabs
      screenOptions={{
        headerStyle: { backgroundColor: colors.greenDark },
        headerTintColor: colors.white,
        headerTitleStyle: { fontWeight: "700" },
        tabBarActiveTintColor: colors.greenDark,
        tabBarInactiveTintColor: colors.muted,
        tabBarLabelStyle: { fontSize: 11, fontWeight: fontWeight.semibold },
        tabBarStyle: {
          backgroundColor: colors.white,
          borderTopColor: colors.border,
          borderTopWidth: 1,
        },
      }}
    >
      <Tabs.Screen
        name="home"
        options={{
          tabBarIcon: tabIcon("home"),
          title: "Home",
        }}
      />
      <Tabs.Screen
        name="scanner"
        options={{
          tabBarIcon: tabIcon("qr-code"),
          title: "Scan",
        }}
      />
      <Tabs.Screen
        name="dashboard"
        options={{
          tabBarIcon: tabIcon("stats-chart"),
          title: "Dashboard",
        }}
      />
      <Tabs.Screen
        name="guests"
        options={{
          tabBarIcon: tabIcon("people"),
          title: "Guests",
        }}
      />
      <Tabs.Screen
        name="settings"
        options={{
          tabBarIcon: tabIcon("settings"),
          title: "Settings",
        }}
      />
      {/* Kept out of the tab bar but still reachable via Home quick
          actions and Settings. href: null hides the tab, the route stays
          registered so router.push("/(volunteer)/broadcast") works. */}
      <Tabs.Screen
        name="broadcast"
        options={{
          href: null,
          title: "Broadcast",
        }}
      />
      <Tabs.Screen
        name="admin"
        options={{
          href: null,
          title: "Admin",
        }}
      />
    </Tabs>
  );
}
