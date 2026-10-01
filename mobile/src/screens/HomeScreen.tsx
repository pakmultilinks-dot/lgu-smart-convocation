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
import { getSettings } from "../api/settingsApi";
import {
  APP_NAME,
  CONVOCATION_DATE,
  CONVOCATION_YEAR,
  MOTTO,
  UNIVERSITY_NAME,
} from "../config";
import { setAppMode } from "../store/appMode";
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
  onPress: () => void;
}

const FALLBACK_ANNOUNCEMENTS: BroadcastEntry[] = [
  { id: -1, audience: "All students", message: "Convocation rehearsal schedule will be announced here. Keep your student card ready.", sent_by: "Registrar Office", sent_at: "" },
  { id: -2, audience: "All students", message: "Gates open two hours before the ceremony. Use the gate printed on your card.", sent_by: "Admin", sent_at: "" },
];

export function HomeScreen() {
  // Convocation date/year come from the server (set in Admin); the
  // compiled-in config values are only a fallback when offline.
  const [eventDate, setEventDate] = useState(CONVOCATION_DATE);
  const [eventYear, setEventYear] = useState(CONVOCATION_YEAR);
  const countdown = useCountdown(eventDate);
  const [announcements, setAnnouncements] = useState<BroadcastEntry[]>(FALLBACK_ANNOUNCEMENTS);
  const [refreshing, setRefreshing] = useState(false);

  const loadEventDetails = useCallback(async () => {
    try {
      const settings = await getSettings();
      if (settings.convocation_datetime) {
        setEventDate(settings.convocation_datetime);
      }
      if (settings.convocation_year) {
        const parsedYear = Number(settings.convocation_year);
        if (Number.isFinite(parsedYear)) {
          setEventYear(parsedYear);
        }
      }
    } catch {
      // Keep the compiled-in fallback when the backend is unreachable.
    }
  }, []);

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
      void loadEventDetails();
      void loadAnnouncements();
    }, [loadAnnouncements, loadEventDetails]),
  );

  const tap = useCallback((fn: () => void) => {
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    fn();
  }, []);

  const switchToLiveBoard = useCallback(() => {
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    void (async () => {
      await setAppMode("liveboard");
      router.replace("/(liveboard)");
    })();
  }, []);

  const QUICK_ACTIONS: QuickAction[] = [
    { icon: "qr-code", title: "Scan QR", subtitle: "Gate entry scanner", onPress: () => router.push("/(volunteer)/scanner") },
    { icon: "stats-chart", title: "Dashboard", subtitle: "Live gate stats", onPress: () => router.push("/(volunteer)/dashboard") },
    { icon: "people", title: "Guests", subtitle: "Guest passes", onPress: () => router.push("/(volunteer)/guests") },
    { icon: "megaphone", title: "Broadcast", subtitle: "Announcements", onPress: () => router.push("/(volunteer)/broadcast") },
    { icon: "shield-checkmark", title: "Admin", subtitle: "Event settings", onPress: () => router.push("/(volunteer)/admin") },
  ];

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
            <Text style={styles.heroTitle}>Class of {eventYear}</Text>
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

      <Pressable
        onPress={switchToLiveBoard}
        style={({ pressed }) => [styles.liveBoardCard, pressed && styles.pressed]}
        accessibilityRole="button"
        accessibilityLabel="Open the live board"
      >
        <View style={styles.liveBoardIcon}>
          <Ionicons name="tv" size={24} color={colors.white} />
        </View>
        <View style={styles.liveBoardText}>
          <Text style={styles.liveBoardTitle}>Live Board</Text>
          <Text style={styles.liveBoardSubtitle}>
            Watch the convocation live, switches app mode
          </Text>
        </View>
        <Ionicons name="chevron-forward" size={22} color="rgba(255,255,255,0.85)" />
      </Pressable>

      <Text style={styles.sectionTitle}>Quick Actions</Text>
      <View style={styles.actionGrid}>
        {QUICK_ACTIONS.map((action) => (
          <Pressable
            key={action.title}
            onPress={() => tap(action.onPress)}
            style={({ pressed }) => [styles.actionCard, pressed && styles.pressed]}
          >
            <View style={styles.actionIcon}>
              <Ionicons name={action.icon} size={24} color={colors.greenDark} />
            </View>
            <Text style={styles.actionTitle}>{action.title}</Text>
            <Text style={styles.actionSubtitle}>{action.subtitle}</Text>
          </Pressable>
        ))}
      </View>

      <View style={styles.sectionHeader}>
        <Text style={styles.sectionTitleInline}>Latest Announcements</Text>
        <Pressable onPress={() => tap(() => router.push("/(volunteer)/broadcast"))}>
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
        <Ionicons name="school" size={26} color={colors.gold} />
        <Text style={styles.mottoText}>&ldquo;{MOTTO}&rdquo;</Text>
      </View>

      <View style={styles.bottomPad} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  actionCard: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderRadius: radius.md,
    borderWidth: 1,
    elevation: 1,
    flex: 1,
    margin: spacing.xs,
    minWidth: "44%",
    padding: spacing.md,
    shadowColor: colors.greenDark,
    shadowOffset: { height: 1, width: 0 },
    shadowOpacity: 0.06,
    shadowRadius: 4,
  },
  actionGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    paddingHorizontal: spacing.sm,
  },
  actionIcon: {
    alignItems: "center",
    backgroundColor: colors.tint,
    borderRadius: radius.md,
    height: 48,
    justifyContent: "center",
    marginBottom: spacing.sm,
    width: 48,
  },
  actionSubtitle: {
    color: colors.muted,
    fontSize: fontSize.caption,
    marginTop: 2,
  },
  actionTitle: {
    color: colors.text,
    fontSize: fontSize.body,
    fontWeight: fontWeight.semibold,
  },
  announceAudience: {
    color: colors.green,
    flex: 1,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.semibold,
    marginLeft: spacing.xs,
  },
  announceCard: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderRadius: radius.md,
    borderWidth: 1,
    elevation: 1,
    marginRight: spacing.sm,
    padding: spacing.md,
    shadowColor: colors.greenDark,
    shadowOffset: { height: 1, width: 0 },
    shadowOpacity: 0.06,
    shadowRadius: 4,
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
    borderBottomLeftRadius: radius.md,
    borderBottomRightRadius: radius.md,
    height: 380,
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
    fontSize: 36,
    fontWeight: fontWeight.bold,
    marginTop: spacing.xs,
  },
  heroTop: {
    padding: spacing.lg,
    paddingTop: spacing.xl,
  },
  liveBoardCard: {
    alignItems: "center",
    backgroundColor: colors.greenDark,
    borderRadius: radius.md,
    elevation: 2,
    flexDirection: "row",
    gap: spacing.md,
    marginHorizontal: spacing.md,
    marginTop: spacing.md,
    padding: spacing.md,
    shadowColor: colors.greenDark,
    shadowOffset: { height: 2, width: 0 },
    shadowOpacity: 0.2,
    shadowRadius: 6,
  },
  liveBoardIcon: {
    alignItems: "center",
    backgroundColor: "rgba(255,255,255,0.14)",
    borderRadius: radius.md,
    height: 48,
    justifyContent: "center",
    width: 48,
  },
  liveBoardSubtitle: {
    color: "rgba(255,255,255,0.75)",
    fontSize: fontSize.caption,
    marginTop: 2,
  },
  liveBoardText: {
    flex: 1,
  },
  liveBoardTitle: {
    color: colors.white,
    fontSize: fontSize.subheading,
    fontWeight: fontWeight.bold,
  },
  logo: {
    borderRadius: 24,
    height: 48,
    width: 48,
  },
  mottoCard: {
    alignItems: "center",
    backgroundColor: colors.greenDark,
    borderRadius: radius.md,
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
    opacity: 0.88,
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
  sectionTitleInline: {
    color: colors.greenDark,
    fontSize: fontSize.subheading,
    fontWeight: fontWeight.bold,
  },
  seeAll: {
    color: colors.green,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.semibold,
  },
});
