import { Ionicons } from "@expo/vector-icons";
import { Tabs } from "expo-router/js-tabs";
import type { BottomTabBarProps } from "expo-router/js-tabs";
import type { ColorValue } from "react-native";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { colors, fonts, radius } from "../../src/theme";

/**
 * Phase 35G: the tab bar renders ONLY these five destinations. Everything
 * else registered by the router (settings, admin, broadcast) is hidden
 * (href: null) and reached from More — the custom bar previously leaked
 * all seven routes because it mapped state.routes unfiltered.
 */
const VISIBLE_TABS = ["home", "scanner", "search", "guests", "more"];

/**
 * Hidden-route parents (Phase 35H item 21): settings/admin/broadcast are
 * registered under More (href: null) — while one of them is the current
 * route, the More tab must render as the active destination.
 */
const PARENT_OF: Record<string, string> = {
  settings: "more",
  admin: "more",
  broadcast: "more",
};

function tabIcon(name: keyof typeof Ionicons.glyphMap) {
  function TabBarIcon({
    focused,
    color,
    size,
  }: {
    focused: boolean;
    color: ColorValue;
    size: number;
  }) {
    // QA fix cycle 2: the active tab is the FILLED glyph (with the ink
    // label + thin gold underline); inactive tabs use the outline glyph.
    return (
      <Ionicons
        name={
          focused
            ? name
            : (`${name}-outline` as keyof typeof Ionicons.glyphMap)
        }
        size={size}
        color={color as string}
      />
    );
  }
  return TabBarIcon;
}

/**
 * Institutional tab bar (Phase 35C, filtered in 35G): paper bar, ink
 * labels (typography + ink emphasis carry the active state), and exactly
 * ONE thin gold underline under the active tab — the sanctioned gold
 * marker for navigation. state.routes is filtered by VISIBLE_TABS before
 * mapping, so hidden entries never render as tabs; hidden routes map to
 * their parent tab via PARENT_OF so More stays highlighted (item 21).
 */
function InstitutionalTabBar({ state, descriptors, insets, navigation }: BottomTabBarProps) {
  return (
    <View
      style={[
        styles.tabBar,
        { paddingBottom: Math.max(insets.bottom, 6) },
      ]}
    >
      {state.routes
        .filter((route) => (VISIBLE_TABS as readonly string[]).includes(route.name))
        .map((route) => {
        // Hidden routes (settings/admin/broadcast) live under More: when
        // one of them is current, state.index points at the hidden route —
        // More must still show as the active tab (Phase 35H item 21).
        const currentName = state.routes[state.index]?.name ?? "";
        const activeName = PARENT_OF[currentName] ?? currentName;
        const focused = route.name === activeName;
        const options = descriptors[route.key]?.options;
        const label = String(options?.tabBarLabel ?? options?.title ?? route.name);
        const icon = options?.tabBarIcon?.({
          focused,
          color: focused ? colors.ink : colors.muted,
          size: 20,
        });
        return (
          <Pressable
            key={route.key}
            accessibilityRole="button"
            accessibilityState={focused ? { selected: true } : undefined}
            accessibilityLabel={options?.tabBarAccessibilityLabel ?? label}
            onPress={() => {
              const event = navigation.emit({
                type: "tabPress",
                target: route.key,
                canPreventDefault: true,
              });
              if (!focused && !event.defaultPrevented) {
                navigation.navigate(route.name, route.params);
              }
            }}
            style={[styles.tabItem, focused && styles.tabItemActive]}
          >
            <View style={styles.tabIconWrap}>{icon}</View>
            <Text
              style={[styles.tabLabel, focused && styles.tabLabelActive]}
              numberOfLines={1}
            >
              {label}
            </Text>
            <View style={[styles.tabUnderline, focused && styles.tabUnderlineActive]} />
          </Pressable>
        );
        })}
    </View>
  );
}

/**
 * Volunteer shell — the mandated five destinations (Phase 35G): Home,
 * Scan, Search, Guests, More. Settings, Admin and Broadcast are registered
 * but hidden (href: null, headerShown: false) and reached from More; each
 * renders its own light in-screen header with a back action. There is NO
 * dashboard tab here — the Live Dashboard lives in its own mode.
 */
export default function VolunteerTabLayout() {
  const insets = useSafeAreaInsets();
  return (
    <Tabs
      tabBar={(props) => (
        <InstitutionalTabBar {...props} insets={insets} />
      )}
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.ink,
        tabBarInactiveTintColor: colors.muted,
        tabBarLabelStyle: {
          // 35M R2 (item 14): displayMedium (500) family carries the
          // weight — no RN synthesis.
          fontFamily: fonts.displayMedium,
          fontSize: 11,
        },
        tabBarStyle: {
          backgroundColor: colors.paper,
          borderTopColor: colors.track,
          borderTopWidth: 1,
          height: 60 + insets.bottom,
          paddingBottom: insets.bottom,
          paddingTop: 6,
        },
      }}
    >
      <Tabs.Screen
        name="home"
        options={{ title: "Home", tabBarLabel: "Home", tabBarIcon: tabIcon("home") }}
      />
      <Tabs.Screen
        name="scanner"
        options={{ title: "Scan", tabBarLabel: "Scan", tabBarIcon: tabIcon("qr-code") }}
      />
      <Tabs.Screen
        name="search"
        options={{ title: "Search", tabBarIcon: tabIcon("search") }}
      />
      <Tabs.Screen
        name="guests"
        options={{ title: "Guests", tabBarIcon: tabIcon("people") }}
      />
      <Tabs.Screen
        name="more"
        options={{ title: "More", tabBarLabel: "More", tabBarIcon: tabIcon("ellipsis-horizontal") }}
      />
      {/* Hidden from the tab bar (Phase 35G): reached from More, with the
          in-screen light header providing the back action. */}
      <Tabs.Screen
        name="settings"
        options={{ title: "Settings", href: null, headerShown: false }}
      />
      <Tabs.Screen
        name="admin"
        options={{ title: "Admin", href: null, headerShown: false }}
      />
      <Tabs.Screen
        name="broadcast"
        options={{ title: "Announcement", href: null, headerShown: false }}
      />
    </Tabs>
  );
}

const styles = StyleSheet.create({
  tabBar: {
    flexDirection: "row",
    backgroundColor: colors.paper,
    borderTopColor: colors.track,
    borderTopWidth: 1,
    paddingTop: 6,
  },
  tabItem: {
    flex: 1,
    minHeight: 48,
    alignItems: "center",
    justifyContent: "center",
    gap: 2,
  },
  tabItemActive: {
    // QA fix cycle 3 (Issue 20): a restrained tint marks the active tab
    // so the current surface reads at a glance; the clear indicator is
    // still the ink underline below. Never a heavy fill.
    backgroundColor: "rgba(27,26,22,0.06)",
    borderRadius: radius.sm,
  },
  tabIconWrap: {
    height: 22,
    justifyContent: "center",
  },
  tabLabel: {
    fontFamily: fonts.displayMedium,
    fontSize: 11,
    color: colors.muted,
  },
  tabLabelActive: {
    // 35M R2 (item 14): active label uses the display (800) family
    // directly.
    fontFamily: fonts.display,
    color: colors.ink,
  },
  tabUnderline: {
    width: 22,
    height: 2,
    borderRadius: radius.full,
    backgroundColor: "transparent",
  },
  tabUnderlineActive: {
    // 33-QA (P8-31): a gold underline under the active tab appeared on
    // EVERY volunteer screen — reading as a stray yellow marker, not
    // the one-thin-gold-marker the design law reserves for the launch /
    // mode-picker screens. The active tab keeps its clear indicator in
    // ink; gold stays where it belongs.
    backgroundColor: colors.ink,
  },
});
