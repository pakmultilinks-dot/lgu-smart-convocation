import { Ionicons } from "@expo/vector-icons";
import { Tabs } from "expo-router/js-tabs";
import type { BottomTabBarProps } from "expo-router/js-tabs";
import type { ColorValue } from "react-native";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { colors, fonts, radius } from "../../src/theme";

/**
 * Phase 31 Part A: the student shell renders exactly these five
 * destinations (Home, My Registration, Entry Pass, Updates, More).
 * Every other student route is registered but hidden (href: null) and
 * reached from Registration or More. `home` is listed FIRST so the tab
 * router's default backBehavior ('firstRoute') resolves to Home — the
 * entry gate at index.tsx is never a back destination.
 */
const VISIBLE_TABS = ["home", "registration", "pass", "announcements", "more"];

/** Hidden routes render their parent tab as the active destination. */
const PARENT_OF: Record<string, string> = {
  profile: "registration",
  verify: "registration",
  code: "registration",
  recovery: "registration",
  history: "registration",
  event: "more",
  medalists: "more",
  readiness: "more",
  support: "more",
  "support-detail": "more",
  // Auth/entry routes: no tab is active while they are current.
  welcome: "",
  login: "",
  index: "",
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
    // Active tab = filled glyph (ink label + ink underline); inactive = outline.
    return (
      <Ionicons
        name={focused ? name : (`${name}-outline` as keyof typeof Ionicons.glyphMap)}
        size={size}
        color={color as string}
      />
    );
  }
  return TabBarIcon;
}

/** Paper tab bar mirroring the volunteer shell: filtered visible routes,
 *  PARENT_OF active mapping, safe-area bottom padding, a11y semantics. */
function StudentTabBar({ state, descriptors, insets, navigation }: BottomTabBarProps) {
  return (
    <View style={[styles.tabBar, { paddingBottom: Math.max(insets.bottom, 6) }]}>
      {state.routes
        .filter((route) => (VISIBLE_TABS as readonly string[]).includes(route.name))
        .map((route) => {
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
              <Text style={[styles.tabLabel, focused && styles.tabLabelActive]} numberOfLines={1}>
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
 * Student shell (Phase 31): five persistent destinations; secondary
 * screens (profile, event, readiness, history, medalists, support, auth)
 * are hidden and reached from Registration/More with in-screen back.
 * Contract change: readiness-source-test check 2 pinned the old
 * `<Stack screenOptions={{ headerShown: false }} />` literal — updated
 * to the Tabs shell with justification (Phase 31 Part A mandates
 * persistent navigation; the Stack shell had no destinations).
 */
export default function StudentTabLayout() {
  const insets = useSafeAreaInsets();
  return (
    <Tabs
      tabBar={(props) => <StudentTabBar {...props} insets={insets} />}
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.ink,
        tabBarInactiveTintColor: colors.muted,
        tabBarLabelStyle: { fontFamily: fonts.displayMedium, fontSize: 11 },
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
        name="registration"
        options={{
          title: "My Registration",
          tabBarLabel: "Registration",
          tabBarIcon: tabIcon("person"),
        }}
      />
      <Tabs.Screen
        name="pass"
        options={{ title: "Entry Pass", tabBarLabel: "Pass", tabBarIcon: tabIcon("qr-code") }}
      />
      <Tabs.Screen
        name="announcements"
        options={{ title: "Updates", tabBarLabel: "Updates", tabBarIcon: tabIcon("megaphone") }}
      />
      <Tabs.Screen
        name="more"
        options={{
          title: "More",
          tabBarLabel: "More",
          tabBarIcon: tabIcon("ellipsis-horizontal"),
        }}
      />
      {/* Hidden secondary/auth routes — reached from Registration/More or
          the launch gate; each renders its own AppHeader back action. */}
      <Tabs.Screen name="profile" options={{ title: "Profile", href: null, headerShown: false }} />
      <Tabs.Screen name="event" options={{ title: "Event Details", href: null, headerShown: false }} />
      <Tabs.Screen name="history" options={{ title: "History", href: null, headerShown: false }} />
      <Tabs.Screen name="medalists" options={{ title: "Medalists", href: null, headerShown: false }} />
      <Tabs.Screen name="readiness" options={{ title: "Readiness", href: null, headerShown: false }} />
      <Tabs.Screen name="support" options={{ title: "Help", href: null, headerShown: false }} />
      <Tabs.Screen name="support-detail" options={{ title: "Request", href: null, headerShown: false }} />
      <Tabs.Screen name="verify" options={{ title: "Verify", href: null, headerShown: false }} />
      <Tabs.Screen name="code" options={{ title: "Code", href: null, headerShown: false }} />
      <Tabs.Screen name="recovery" options={{ title: "Recovery", href: null, headerShown: false }} />
      <Tabs.Screen name="welcome" options={{ title: "Welcome", href: null, headerShown: false }} />
      <Tabs.Screen name="login" options={{ title: "Sign in", href: null, headerShown: false }} />
      <Tabs.Screen name="index" options={{ title: "Entry", href: null, headerShown: false }} />
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
    // Restrained tint marks the active tab; the ink underline is the
    // clear indicator. Never a heavy fill.
    backgroundColor: "rgba(27,26,22,0.06)",
    borderRadius: radius.sm,
  },
  tabIconWrap: { height: 22, justifyContent: "center" },
  tabLabel: { fontFamily: fonts.displayMedium, fontSize: 11, color: colors.muted },
  tabLabelActive: { fontFamily: fonts.display, color: colors.ink },
  tabUnderline: {
    width: 22,
    height: 2,
    borderRadius: radius.full,
    backgroundColor: "transparent",
  },
  // Gold stays reserved for launch/mode-picker — active tab is ink.
  tabUnderlineActive: { backgroundColor: colors.ink },
});
