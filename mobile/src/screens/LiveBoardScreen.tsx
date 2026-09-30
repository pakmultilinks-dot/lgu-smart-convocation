import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Animated,
  Image,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { fetchDashboard, type DashboardData } from "../api/client";
import { getSettings, type ConvocationSettings } from "../api/settingsApi";
import { colors, fontSize, fontWeight, radius, spacing } from "../theme";
import { CountUp } from "../components/CountUp";
import { GateBar } from "../components/GateBar";
import { ScanFeedItem } from "../components/ScanFeedItem";
import { ProgressRing } from "../components/ProgressRing";

const LGU_CREST = require("../../assets/lgu-logo.jpg");

const DASHBOARD_POLL_MS = 5000;
const SETTINGS_POLL_MS = 60000;
const COUNTDOWN_TICK_MS = 1000;

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

function parseDatetime(raw: string | undefined | null): Date | null {
  if (!raw || raw.trim().length === 0) {
    return null;
  }
  const parsed = new Date(raw.trim());
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

interface CountdownParts {
  days: number;
  hours: number;
  minutes: number;
  seconds: number;
}

function countdownTo(target: Date, now: Date): CountdownParts {
  const diff = Math.max(0, target.getTime() - now.getTime());
  const totalSeconds = Math.floor(diff / 1000);
  return {
    days: Math.floor(totalSeconds / 86400),
    hours: Math.floor((totalSeconds % 86400) / 3600),
    minutes: Math.floor((totalSeconds % 3600) / 60),
    seconds: totalSeconds % 60,
  };
}

/** Public live board: a TV broadcast style scoreboard for the whole convocation. */
export function LiveBoardScreen() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [settings, setSettings] = useState<ConvocationSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [now, setNow] = useState(() => new Date());

  const [pulse] = useState(() => new Animated.Value(1));

  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, { duration: 800, toValue: 0.25, useNativeDriver: true }),
        Animated.timing(pulse, { duration: 800, toValue: 1, useNativeDriver: true }),
      ]),
    );
    loop.start();
    return () => {
      loop.stop();
    };
  }, [pulse]);

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), COUNTDOWN_TICK_MS);
    return () => clearInterval(timer);
  }, []);

  // Data loaders called from effects (via subscriptions) and event handlers.
  const loadDashboard = useCallback(async () => {
    try {
      const fresh = await fetchDashboard();
      setData(fresh);
      setUpdatedAt(new Date());
      setError(null);
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "Could not load the live board. Please check your connection.",
      );
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  const loadSettings = useCallback(async () => {
    try {
      const fresh = await getSettings();
      setSettings(fresh);
    } catch {
      // Settings are decorative; dashboard data is the core of this screen.
    }
  }, []);

  // Subscribe to live updates. The initial fetch is kicked off through a
  // scheduled callback (same subscription pattern as the poll timers) so the
  // effect body only wires up subscriptions, per react-hooks/set-state-in-effect.
  useEffect(() => {
    const dashTimer = setInterval(() => void loadDashboard(), DASHBOARD_POLL_MS);
    const settingsTimer = setInterval(() => void loadSettings(), SETTINGS_POLL_MS);
    const initialTimer = setTimeout(() => {
      void loadDashboard();
      void loadSettings();
    }, 0);
    return () => {
      clearTimeout(initialTimer);
      clearInterval(dashTimer);
      clearInterval(settingsTimer);
    };
  }, [loadDashboard, loadSettings]);

  const onRefresh = useCallback(() => {
    setRefreshing(true);
    void loadDashboard();
    void loadSettings();
  }, [loadDashboard, loadSettings]);

  const target = parseDatetime(settings?.convocation_datetime);
  const countdown = target ? countdownTo(target, now) : null;

  const maxGateCount = data
    ? data.throughput.reduce((max, g) => Math.max(max, g.count), 0)
    : 0;

  if (loading && !data) {
    return (
      <View style={styles.stateWrap}>
        <ActivityIndicator size="large" color={colors.green} />
        <Text style={styles.stateText}>Loading the live board...</Text>
      </View>
    );
  }

  if (error && !data) {
    return (
      <View style={styles.stateWrap}>
        <Ionicons name="cloud-offline-outline" size={56} color={colors.muted} />
        <Text style={styles.stateTitle}>The live board is offline</Text>
        <Text style={styles.stateText}>{error}</Text>
        <TouchableOpacity
          style={styles.retryButton}
          onPress={() => {
            setLoading(true);
            setError(null);
            void loadDashboard();
          }}
          accessibilityRole="button"
        >
          <Text style={styles.retryText}>Try again</Text>
        </TouchableOpacity>
      </View>
    );
  }

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
    >
      <View style={styles.hero}>
        <View style={styles.heroTop}>
          <Image source={LGU_CREST} style={styles.crest} resizeMode="cover" />
          <View style={styles.liveBadge}>
            <Animated.View style={[styles.liveDot, { opacity: pulse }]} />
            <Text style={styles.liveText}>LIVE</Text>
          </View>
        </View>
        <Text style={styles.convocationName}>
          {settings?.convocation_name || "LGU Smart Convocation"}
        </Text>
        {settings?.venue ? (
          <Text style={styles.venue}>
            <Ionicons name="location-outline" size={15} color={colors.goldSoft} /> {settings.venue}
          </Text>
        ) : null}
        {countdown ? (
          <View style={styles.countdownRow}>
            <CountdownCell value={pad(countdown.days)} label="Days" />
            <CountdownCell value={pad(countdown.hours)} label="Hrs" />
            <CountdownCell value={pad(countdown.minutes)} label="Min" />
            <CountdownCell value={pad(countdown.seconds)} label="Sec" />
          </View>
        ) : (
          <Text style={styles.dateTba}>Date to be announced</Text>
        )}
      </View>

      {data ? (
        <View style={styles.body}>
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Arrivals</Text>
            <View style={styles.counterRow}>
              <View style={styles.counter}>
                <CountUp value={data.inside_total} style={styles.counterNumber} />
                <Text style={styles.counterLabel}>Inside now</Text>
              </View>
              <View style={styles.counterDivider} />
              <View style={styles.counter}>
                <CountUp value={data.expected_total} style={styles.counterNumber} />
                <Text style={styles.counterLabel}>Expected</Text>
              </View>
              <View style={styles.counterDivider} />
              <View style={styles.counter}>
                <View style={styles.pctRow}>
                  <CountUp value={data.arrival_pct} style={styles.counterNumber} />
                  <Text style={styles.pctSymbol}>%</Text>
                </View>
                <Text style={styles.counterLabel}>Arrived</Text>
              </View>
            </View>
            <View style={styles.ringWrap}>
              <ProgressRing
                value={data.arrival_pct}
                label={`${Math.round(data.arrival_pct)}%`}
                sublabel="of expected guests arrived"
              />
            </View>
            <View style={styles.barTrack}>
              <View
                style={[
                  styles.barFill,
                  { width: `${Math.min(100, Math.max(0, data.arrival_pct))}%` },
                ]}
              />
            </View>
          </View>

          <View style={styles.card}>
            <Text style={styles.cardTitle}>Who is inside</Text>
            <View style={styles.splitRow}>
              <SplitCard
                icon="man-outline"
                count={data.male}
                expected={data.expected_male}
                label="Male"
                tint={colors.emeraldSoft}
                iconColor={colors.green}
              />
              <SplitCard
                icon="woman-outline"
                count={data.female}
                expected={data.expected_female}
                label="Female"
                tint={colors.goldSoft}
                iconColor={colors.amber}
              />
            </View>
            <View style={styles.guestCard}>
              <View style={[styles.guestIcon, { backgroundColor: colors.tint }]}>
                <Ionicons name="people-outline" size={22} color={colors.greenDark} />
              </View>
              <View style={styles.guestMain}>
                <CountUp value={data.guests_inside} style={styles.guestNumber} />
                <Text style={styles.guestLabel}>Guests inside</Text>
              </View>
              <Text style={styles.guestExpected}>of {data.expected_guests} expected</Text>
            </View>
          </View>

          <View style={styles.card}>
            <View style={styles.gateHeader}>
              <Text style={styles.cardTitle}>Gate activity</Text>
              {data.busiest_gate ? (
                <View style={styles.busyBadge}>
                  <Ionicons name="flame-outline" size={14} color={colors.amber} />
                  <Text style={styles.busyText}>{data.busiest_gate}</Text>
                </View>
              ) : null}
            </View>
            {data.throughput.length === 0 ? (
              <Text style={styles.emptyText}>No gate activity yet. Scans will appear here live.</Text>
            ) : (
              data.throughput.map((g) => (
                <GateBar key={g.gate.id} label={g.gate.label} count={g.count} maxCount={maxGateCount} />
              ))
            )}
          </View>

          <View style={styles.card}>
            <View style={styles.feedHeader}>
              <Text style={styles.cardTitle}>Live scan feed</Text>
              {updatedAt ? (
                <Text style={styles.updated}>
                  Updated {pad(updatedAt.getHours())}:{pad(updatedAt.getMinutes())}:
                  {pad(updatedAt.getSeconds())}
                </Text>
              ) : null}
            </View>
            {data.feed.length === 0 ? (
              <View style={styles.emptyFeed}>
                <Ionicons name="scan-outline" size={40} color={colors.muted} />
                <Text style={styles.emptyText}>
                  No scans yet. New entries will stream in automatically.
                </Text>
              </View>
            ) : (
              data.feed.map((item) => <ScanFeedItem key={item.id} item={item} />)
            )}
          </View>
        </View>
      ) : null}
    </ScrollView>
  );
}

function CountdownCell({ value, label }: { value: string; label: string }) {
  return (
    <View style={styles.countCell}>
      <Text style={styles.countValue}>{value}</Text>
      <Text style={styles.countLabel}>{label}</Text>
    </View>
  );
}

function SplitCard({
  icon,
  count,
  expected,
  label,
  tint,
  iconColor,
}: {
  icon: keyof typeof Ionicons.glyphMap;
  count: number;
  expected: number;
  label: string;
  tint: string;
  iconColor: string;
}) {
  return (
    <View style={styles.splitCard}>
      <View style={[styles.splitIcon, { backgroundColor: tint }]}>
        <Ionicons name={icon} size={24} color={iconColor} />
      </View>
      <CountUp value={count} style={styles.splitNumber} />
      <Text style={styles.splitLabel}>{label}</Text>
      <Text style={styles.splitExpected}>of {expected} expected</Text>
    </View>
  );
}

const shadow = {
  shadowColor: "#1C2B23",
  shadowOffset: { width: 0, height: 2 },
  shadowOpacity: 0.08,
  shadowRadius: 8,
  elevation: 2,
};

const styles = StyleSheet.create({
  barFill: {
    backgroundColor: colors.emerald,
    borderRadius: radius.full,
    height: "100%",
  },
  barTrack: {
    backgroundColor: colors.tint,
    borderRadius: radius.full,
    height: 14,
    marginTop: spacing.md,
    overflow: "hidden",
  },
  body: {
    gap: spacing.md,
    padding: spacing.md,
  },
  busyBadge: {
    alignItems: "center",
    backgroundColor: colors.amberSoft,
    borderRadius: radius.full,
    flexDirection: "row",
    gap: spacing.xs / 2,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs / 2,
  },
  busyText: {
    color: colors.amber,
    fontSize: fontSize.small,
    fontWeight: fontWeight.semibold,
  },
  card: {
    ...shadow,
    backgroundColor: colors.card,
    borderRadius: radius.lg,
    padding: spacing.md,
  },
  cardTitle: {
    color: colors.text,
    fontSize: fontSize.heading,
    fontWeight: fontWeight.bold,
  },
  content: {
    paddingBottom: spacing.xl,
  },
  convocationName: {
    color: colors.white,
    fontSize: fontSize.display,
    fontWeight: fontWeight.bold,
    marginTop: spacing.sm,
    textAlign: "center",
  },
  countCell: {
    alignItems: "center",
    backgroundColor: "rgba(255, 255, 255, 0.12)",
    borderRadius: radius.md,
    minWidth: 64,
    paddingVertical: spacing.sm,
  },
  countLabel: {
    color: colors.goldSoft,
    fontSize: fontSize.small,
    fontWeight: fontWeight.medium,
    marginTop: 2,
  },
  countValue: {
    color: colors.white,
    fontSize: fontSize.heading,
    fontWeight: fontWeight.bold,
    fontVariant: ["tabular-nums"],
  },
  countdownRow: {
    flexDirection: "row",
    gap: spacing.sm,
    marginTop: spacing.md,
  },
  counter: {
    alignItems: "center",
    flex: 1,
  },
  counterDivider: {
    backgroundColor: colors.border,
    height: 44,
    width: 1,
  },
  counterLabel: {
    color: colors.muted,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.medium,
    marginTop: 2,
  },
  counterNumber: {
    color: colors.greenDark,
    fontSize: fontSize.title,
    fontWeight: fontWeight.bold,
    fontVariant: ["tabular-nums"],
  },
  counterRow: {
    alignItems: "center",
    flexDirection: "row",
    marginTop: spacing.md,
  },
  crest: {
    borderRadius: radius.full,
    height: 76,
    width: 76,
  },
  dateTba: {
    color: colors.goldSoft,
    fontSize: fontSize.body,
    fontWeight: fontWeight.medium,
    marginTop: spacing.md,
  },
  emptyFeed: {
    alignItems: "center",
    gap: spacing.sm,
    paddingVertical: spacing.lg,
  },
  emptyText: {
    color: colors.muted,
    fontSize: fontSize.body,
    textAlign: "center",
  },
  feedHeader: {
    alignItems: "baseline",
    flexDirection: "row",
    justifyContent: "space-between",
    marginBottom: spacing.sm,
  },
  gateHeader: {
    alignItems: "center",
    flexDirection: "row",
    justifyContent: "space-between",
    marginBottom: spacing.sm,
  },
  guestCard: {
    alignItems: "center",
    backgroundColor: colors.tint,
    borderRadius: radius.md,
    flexDirection: "row",
    gap: spacing.md,
    marginTop: spacing.md,
    padding: spacing.md,
  },
  guestExpected: {
    color: colors.muted,
    fontSize: fontSize.caption,
  },
  guestIcon: {
    alignItems: "center",
    borderRadius: radius.full,
    height: 46,
    justifyContent: "center",
    width: 46,
  },
  guestLabel: {
    color: colors.muted,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.medium,
  },
  guestMain: {
    flex: 1,
  },
  guestNumber: {
    color: colors.greenDark,
    fontSize: fontSize.heading,
    fontWeight: fontWeight.bold,
    fontVariant: ["tabular-nums"],
  },
  hero: {
    alignItems: "center",
    backgroundColor: colors.greenDark,
    paddingBottom: spacing.xl,
    paddingHorizontal: spacing.md,
    paddingTop: spacing.xl,
  },
  heroTop: {
    alignItems: "center",
    flexDirection: "row",
    justifyContent: "space-between",
    width: "100%",
  },
  liveBadge: {
    alignItems: "center",
    backgroundColor: "rgba(255, 255, 255, 0.14)",
    borderRadius: radius.full,
    flexDirection: "row",
    gap: spacing.xs,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
  },
  liveDot: {
    backgroundColor: colors.red,
    borderRadius: radius.full,
    height: 10,
    width: 10,
  },
  liveText: {
    color: colors.white,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.bold,
    letterSpacing: 2,
  },
  pctRow: {
    alignItems: "baseline",
    flexDirection: "row",
  },
  pctSymbol: {
    color: colors.greenDark,
    fontSize: fontSize.body,
    fontWeight: fontWeight.bold,
    marginLeft: 1,
  },
  retryButton: {
    backgroundColor: colors.green,
    borderRadius: radius.full,
    marginTop: spacing.md,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
  },
  retryText: {
    color: colors.white,
    fontSize: fontSize.body,
    fontWeight: fontWeight.semibold,
  },
  ringWrap: {
    alignItems: "center",
    marginTop: spacing.lg,
  },
  screen: {
    backgroundColor: colors.background,
    flex: 1,
  },
  splitCard: {
    alignItems: "center",
    backgroundColor: colors.tint,
    borderRadius: radius.md,
    flex: 1,
    padding: spacing.md,
  },
  splitExpected: {
    color: colors.muted,
    fontSize: fontSize.small,
    marginTop: 2,
  },
  splitIcon: {
    alignItems: "center",
    borderRadius: radius.full,
    height: 52,
    justifyContent: "center",
    marginBottom: spacing.sm,
    width: 52,
  },
  splitLabel: {
    color: colors.text,
    fontSize: fontSize.body,
    fontWeight: fontWeight.semibold,
    marginTop: 2,
  },
  splitNumber: {
    color: colors.greenDark,
    fontSize: fontSize.title,
    fontWeight: fontWeight.bold,
    fontVariant: ["tabular-nums"],
  },
  splitRow: {
    flexDirection: "row",
    gap: spacing.md,
    marginTop: spacing.md,
  },
  stateText: {
    color: colors.muted,
    fontSize: fontSize.body,
    marginTop: spacing.sm,
    textAlign: "center",
  },
  stateTitle: {
    color: colors.text,
    fontSize: fontSize.heading,
    fontWeight: fontWeight.bold,
    marginTop: spacing.md,
  },
  stateWrap: {
    alignItems: "center",
    backgroundColor: colors.background,
    flex: 1,
    justifyContent: "center",
    padding: spacing.xl,
  },
  updated: {
    color: colors.muted,
    fontSize: fontSize.small,
    fontVariant: ["tabular-nums"],
  },
  venue: {
    color: colors.goldSoft,
    fontSize: fontSize.body,
    marginTop: spacing.xs,
    textAlign: "center",
  },
});
export default LiveBoardScreen;
