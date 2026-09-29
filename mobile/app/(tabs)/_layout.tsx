import { Ionicons } from "@expo/vector-icons";
import { Tabs } from "expo-router";
import type { ColorValue } from "react-native";
import { colors } from "../../src/theme";

function tabIcon(name: keyof typeof Ionicons.glyphMap) {
  return ({ color, size }: { color: ColorValue; size: number }) => (
    <Ionicons name={name} size={size} color={color as string} />
  );
}

export default function TabLayout() {
  return (
    <Tabs
      screenOptions={{
        headerStyle: { backgroundColor: colors.greenDark },
        headerTintColor: colors.white,
        headerTitleStyle: { fontWeight: "700" },
        tabBarActiveTintColor: colors.white,
        tabBarInactiveTintColor: "rgba(255, 255, 255, 0.6)",
        tabBarStyle: {
          backgroundColor: colors.greenDark,
          borderTopColor: colors.greenDeep,
          borderTopWidth: 1,
        },
      }}
    >
      <Tabs.Screen
        name="home"
        options={{
          tabBarIcon: tabIcon("home"),
          title: "Home",
          headerShown: false,
        }}
      />
      <Tabs.Screen
        name="scanner"
        options={{
          tabBarIcon: tabIcon("qr-code"),
          title: "Scanner",
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
        name="broadcast"
        options={{
          tabBarIcon: tabIcon("megaphone"),
          title: "Broadcast",
        }}
      />
      <Tabs.Screen
        name="settings"
        options={{
          tabBarIcon: tabIcon("settings"),
          title: "Settings",
        }}
      />
    </Tabs>
  );
}
