import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import { router, useFocusEffect } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import {
  Image,
  ImageBackground,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { Defs, LinearGradient, Rect, Stop, Svg } from "react-native-svg";
import { fetchBroadcasts, type BroadcastEntry } from "../api/client";
import {
  APP_NAME,
  CONVOCATION_DATE,
  CONVOCATION_YEAR,
  MOTTO,
  UNIVERSITY_NAME,
} from "../config";
import { colors, fontSize, fontWeight, radius, spacing } from "../theme";

const HERO_IMAGE = require("../../assets/convocation-hero.jpg");
const LGU_LOGO = require("../../assets/lgu-logo.jpg");

function useCountdown(target: string) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const diff = Math.max(0, new Date(target).getTime() - now);
  const days = Math.floor(diff / 86400000);
  const hours = Math.floor((diff % 86400000) / 3600000);
  const minutes = Math.floor((diff % 3600000) / 60000);
  const seconds = Math.floor((diff % 60000) / 1000);
  return { days, hours, minutes, seconds, passed: diff === 0 };
}

function CountdownCell({ value, label }: { value: number; label: string }) {
  const text = value < 10 ? `0${value}` : String(value);
  return (
    <View style={styles.countCell}>
      <Text style={styles.countValue}>{text}</Text>
      <Text style={styles.countLabel}>{label}</Text>
    </View>
  );
}

interface QuickAction {
  icon: keyof typeof Ionicons.glyphMap;
  title: string;
  subtitle: string;
  route: "/scanner" | "/guests" | "/broadcast" | "/dashboard";
  tint: string;
}

const QUICK_ACTIONS: QuickAction[] = [
  { icon: "qr-code", title: "Scan QR", subtitle: "Gate entry scanner", route: "/scanner", tint: colors.emeraldSoft },
  { icon: "people", title: "Guests", subtitle: "Guest passes", route: "/guests", tint: "#E3ECF5" },
  { icon: "megaphone", title: "Broadcast", subtitle: "Announcements", route: "/broadcast", tint: colors.goldSoft },
  { icon: "stats-chart", title: "Dashboard", subtitle: "Live gate stats", route: "/dashboard", tint: colors.tint },
];

const FALLBACK_ANNOUNCEMENTS: BroadcastEntry[] = [
  { id: -1, audience: "All students", message: "Convocation rehearsal schedule will be announced here. Keep your student card ready.", sent_by: "Registrar Office", sent_at: "" },
  { id: -2, audience: "All students", message: "Gates open two hours before the ceremony. Use the gate printed on your card.", sent_by: "Admin", sent_at: "" },
];

export function HomeScreen() {
  const countdown = useCountdown(CONVOCATION_DATE);
  const [announcements, setAnnouncements] = useState<BroadcastEntry[]>(FALLBACK_ANNOUNCEMENTS);
  const [refreshing, setRefreshing] = useState(false);

  const loadAnnouncements = useCallback(async () => {
    try {
      const log = await fetchBroadcasts();
      if (log.length > 0) {
        setAnnouncements(log.slice(0, 5));
      }
    } catch {
      // Keep the fallback highlights when the backend is unreachable.
    } finally {
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      void loadAnnouncements();
    }, [loadAnnouncements]),
  );

  const go = useCallback((route: QuickAction["route"]) => {
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    router.push(route);
  }, []);

  return (
    <ScrollView
      style={styles.root}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={() => {
            setRefreshing(true);
            void loadAnnouncements();
          }}
          colors={[colors.green]}
        />
      }
    >
      <View style={styles.hero}>
        <ImageBackground source={HERO_IMAGE} style={styles.heroImage} resizeMode="cover">
          <Svg style={StyleSheet.absoluteFill} width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none">
            <Defs>
              <LinearGradient id="heroFade" x1="0" y1="0" x2="0" y2="1">
                <Stop offset="0" stopColor={colors.greenDark} stopOpacity="0.15" />
                <Stop offset="0.55" stopColor={colors.greenDark} stopOpacity="0.35" />
                <Stop offset="1" stopColor={colors.greenDark} stopOpacity="0.92" />
              </LinearGradient>
            </Defs>
            <Rect x="0" y="0" width="100" height="100" fill="url(#heroFade)" />
          </Svg>
          <View style={styles.heroTop}>
            <View style={styles.brandRow}>
              <Image source={LGU_LOGO} style={styles.logo} />
              <View>
                <Text style={styles.brandName}>{UNIVERSITY_NAME}</Text>
                <Text style={styles.brandSub}>{APP_NAME}</Text>
              </View>
            </View>
          </View>
          <View style={styles.heroBottom}>
            <Text style={styles.heroKicker}>CONVOCATION</Text>
            <Text style={styles.heroTitle}>Class of {CONVOCATION_YEAR}</Text>
            {countdown.passed ? (
              <Text style={styles.dayHere}>The big day is here. Congratulations, graduates.</Text>
            ) : (
              <View style={styles.countRow}>
                <CountdownCell value={countdown.days} label="Days" />
                <CountdownCell value={countdown.hours} label="Hours" />
                <CountdownCell value={countdown.minutes} label="Mins" />
                <CountdownCell value={countdown.seconds} label="Secs" />
              </View>
            )}
          </View>
        </ImageBackground>
      </View>

      <Text style={styles.sectionTitle}>Quick Actions</Text>
      <View style={styles.actionGrid}>
        {QUICK_ACTIONS.map((action) => (
          <Pressable
            key={action.route}
            onPress={() => go(action.route)}
            style={({ pressed }) => [styles.actionCard, pressed && styles.pressed]}
          >
            <View style={[styles.actionIcon, { backgroundColor: action.tint }]}>
              <Ionicons name={action.icon} size={26} color={colors.greenDark} />
            </View>
            <Text style={styles.actionTitle}>{action.title}</Text>
            <Text style={styles.actionSubtitle}>{action.subtitle}</Text>
          </Pressable>
        ))}
      </View>

      <View style={styles.sectionHeader}>
        <Text style={styles.sectionTitle}>Latest Announcements</Text>
        <Pressable onPress={() => router.push("/broadcast")}>
          <Text style={styles.seeAll}>View all</Text>
        </Pressable>
      </View>
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.announceRow}
      >
        {announcements.map((item) => (
          <View key={item.id} style={styles.announceCard}>
            <View style={styles.announceTop}>
              <Ionicons name="megaphone" size={16} color={colors.green} />
              <Text style={styles.announceAudience} numberOfLines={1}>
                {item.audience}
              </Text>
            </View>
            <Text style={styles.announceMessage} numberOfLines={4}>
              {item.message}
            </Text>
            <Text style={styles.announceMeta} numberOfLines={1}>
              {item.sent_by}
              {item.sent_at ? ` \u00B7 ${item.sent_at}` : ""}
            </Text>
          </View>
        ))}
      </ScrollView>

      <View style={styles.mottoCard}>
        <Ionicons name="school" size={28} color={colors.gold} />
        <Text style={styles.mottoText}>"{MOTTO}"</Text>
      </View>

      <View style={styles.bottomPad} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  actionCard: {
    backgroundColor: colors.card,
    borderRadius: radius.lg,
    elevation: 3,
    flex: 1,
    margin: spacing.xs,
    minWidth: "44%",
    padding: spacing.md,
    shadowColor: colors.greenDark,
    shadowOffset: { height: 2, width: 0 },
    shadowOpacity: 0.1,
    shadowRadius: 8,
  },
  actionGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    paddingHorizontal: spacing.sm,
  },
  actionIcon: {
    alignItems: "center",
    borderRadius: radius.lg,
    height: 52,
    justifyContent: "center",
    marginBottom: spacing.sm,
    width: 52,
  },
  actionSubtitle: {
    color: colors.muted,
    fontSize: fontSize.caption,
    marginTop: 2,
  },
  actionTitle: {
    color: colors.text,
    fontSize: fontSize.body,
    fontWeight: fontWeight.bold,
  },
  announceAudience: {
    color: colors.green,
    flex: 1,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.bold,
    marginLeft: spacing.xs,
  },
  announceCard: {
    backgroundColor: colors.card,
    borderLeftColor: colors.emerald,
    borderLeftWidth: 4,
    borderRadius: radius.lg,
    elevation: 2,
    marginRight: spacing.sm,
    padding: spacing.md,
    shadowColor: colors.greenDark,
    shadowOffset: { height: 1, width: 0 },
    shadowOpacity: 0.08,
    shadowRadius: 6,
    width: 250,
  },
  announceMessage: {
    color: colors.text,
    fontSize: fontSize.body,
    lineHeight: 21,
    marginTop: spacing.xs,
  },
  announceMeta: {
    color: colors.muted,
    fontSize: fontSize.caption,
    marginTop: spacing.sm,
  },
  announceRow: {
    paddingHorizontal: spacing.md,
  },
  announceTop: {
    alignItems: "center",
    flexDirection: "row",
  },
  bottomPad: {
    height: spacing.xl,
  },
  brandName: {
    color: colors.white,
    fontSize: fontSize.body,
    fontWeight: fontWeight.bold,
  },
  brandRow: {
    alignItems: "center",
    flexDirection: "row",
    gap: spacing.sm,
  },
  brandSub: {
    color: "rgba(255,255,255,0.85)",
    fontSize: fontSize.caption,
  },
  countCell: {
    alignItems: "center",
    backgroundColor: "rgba(255,255,255,0.16)",
    borderRadius: radius.md,
    marginRight: spacing.sm,
    minWidth: 64,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.sm,
  },
  countLabel: {
    color: "rgba(255,255,255,0.85)",
    fontSize: fontSize.small,
    fontWeight: fontWeight.semibold,
    marginTop: 2,
    textTransform: "uppercase",
  },
  countRow: {
    flexDirection: "row",
    marginTop: spacing.md,
  },
  countValue: {
    color: colors.white,
    fontSize: fontSize.title,
    fontWeight: fontWeight.bold,
  },
  dayHere: {
    color: colors.goldSoft,
    fontSize: fontSize.body,
    fontWeight: fontWeight.semibold,
    marginTop: spacing.md,
  },
  hero: {
    borderBottomLeftRadius: radius.lg,
    borderBottomRightRadius: radius.lg,
    height: 420,
    overflow: "hidden",
  },
  heroBottom: {
    padding: spacing.lg,
  },
  heroImage: {
    flex: 1,
    justifyContent: "space-between",
  },
  heroKicker: {
    color: colors.gold,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.bold,
    letterSpacing: 3,
  },
  heroTitle: {
    color: colors.white,
    fontSize: 40,
    fontWeight: fontWeight.bold,
    marginTop: spacing.xs,
  },
  heroTop: {
    padding: spacing.lg,
    paddingTop: spacing.xl,
  },
  logo: {
    borderRadius: 24,
    height: 48,
    width: 48,
  },
  mottoCard: {
    alignItems: "center",
    backgroundColor: colors.greenDark,
    borderRadius: radius.lg,
    marginHorizontal: spacing.md,
    marginTop: spacing.lg,
    padding: spacing.lg,
  },
  mottoText: {
    color: colors.white,
    fontSize: fontSize.body,
    fontStyle: "italic",
    marginTop: spacing.sm,
    textAlign: "center",
  },
  pressed: {
    opacity: 0.85,
    transform: [{ scale: 0.97 }],
  },
  root: {
    backgroundColor: colors.background,
    flex: 1,
  },
  sectionHeader: {
    alignItems: "center",
    flexDirection: "row",
    justifyContent: "space-between",
    marginBottom: spacing.sm,
    marginTop: spacing.lg,
    paddingHorizontal: spacing.md,
  },
  sectionTitle: {
    color: colors.greenDark,
    fontSize: fontSize.subheading,
    fontWeight: fontWeight.bold,
    marginBottom: spacing.sm,
    marginTop: spacing.lg,
    paddingHorizontal: spacing.md,
  },
  seeAll: {
    color: colors.green,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.bold,
  },
});
