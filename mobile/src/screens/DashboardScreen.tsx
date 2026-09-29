import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";
import { useCallback, useRef, useState } from "react";
import {
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { Defs, LinearGradient, Rect, Stop, Svg } from "react-native-svg";
import {
  ApiError,
  fetchDashboard,
  type DashboardData,
} from "../api/client";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { CountUp } from "../components/CountUp";
import { GateBar } from "../components/GateBar";
import { KpiCard } from "../components/KpiCard";
import { ScanFeedItem } from "../components/ScanFeedItem";
import { SectionCard } from "../components/SectionCard";
import { CONVOCATION_YEAR } from "../config";
import { colors, fontSize, fontWeight, radius, spacing } from "../theme";

const REFRESH_MS = 5000;

function LiveDot() {
  return <View style={styles.liveDot} />;
}

function expectedSub(expected: number): string {
  return expected > 0 ? `of ${expected} expected` : "no roster yet";
}

export function DashboardScreen() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async (showSpinner: boolean) => {
    if (showSpinner) {
      setLoading(true);
    }
    try {
      const result = await fetchDashboard();
      setData(result);
      setError(null);
    } catch (e) {
      setError(
        e instanceof ApiError ? e.message : "Could not load the dashboard.",
      );
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      void load(true);
      timer.current = setInterval(() => void load(false), REFRESH_MS);
      return () => {
        if (timer.current) {
          clearInterval(timer.current);
          timer.current = null;
        }
      };
    }, [load]),
  );

  const onRefresh = useCallback(() => {
    setRefreshing(true);
    void load(false);
  }, [load]);

  if (loading && !data) {
    return <LoadingState message="Loading convocation dashboard..." />;
  }

  if (error && !data) {
    return <ErrorState message={error} onRetry={() => void load(true)} />;
  }

  if (!data) {
    return (
      <EmptyState
        icon="stats-chart-outline"
        title="No data yet"
        message="The dashboard will appear once the backend is reachable."
      />
    );
  }

  const maxThroughput = Math.max(
    1,
    ...data.throughput.map((t) => t.count),
  );

  return (
    <ScrollView
      style={styles.root}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={onRefresh}
          colors={[colors.green]}
        />
      }
    >
      <View style={styles.banner}>
        <Svg style={StyleSheet.absoluteFill} width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none">
          <Defs>
            <LinearGradient id="dashBanner" x1="0" y1="0" x2="1" y2="1">
              <Stop offset="0" stopColor={colors.greenDeep} />
              <Stop offset="1" stopColor={colors.greenDark} />
            </LinearGradient>
          </Defs>
          <Rect x="0" y="0" width="100" height="100" fill="url(#dashBanner)" />
        </Svg>
        <View style={styles.bannerRow}>
          <View style={styles.livePill}>
            <LiveDot />
            <Text style={styles.liveText}>LIVE</Text>
          </View>
          <Text style={styles.bannerYear}>Convocation {CONVOCATION_YEAR}</Text>
        </View>
        <Text style={styles.bannerTitle}>Full Hall, Live</Text>
        <Text style={styles.bannerSub}>
          Every seat in the hall, counted in real time.
        </Text>
        <View style={styles.heroStat}>
          <CountUp value={data.inside_total} style={styles.heroNumber} />
          <Text style={styles.heroLabel}>people inside right now</Text>
          {data.expected_total > 0 ? (
            <>
              <View style={styles.progressTrack}>
                <View
                  style={[
                    styles.progressFill,
                    { width: `${data.arrival_pct}%` },
                  ]}
                />
              </View>
              <Text style={styles.heroSub}>
                {data.arrival_pct}% arrived - {data.inside_total} of{" "}
                {data.expected_total} expected
              </Text>
            </>
          ) : (
            <Text style={styles.heroSub}>No roster uploaded yet</Text>
          )}
        </View>
      </View>

      <View style={styles.kpiGrid}>
        <View style={styles.kpiRow}>
          <KpiCard
            title="Total Expected"
            value={data.expected_total}
            accent={colors.greenDark}
            icon={
              <Ionicons
                name="clipboard-outline"
                size={22}
                color={colors.greenDark}
              />
            }
            subtext={
              data.expected_total > 0
                ? "from the uploaded roster"
                : "No roster uploaded yet"
            }
          />
          <KpiCard
            title="Male Inside"
            value={data.male}
            accent={colors.emerald}
            icon={<Ionicons name="man" size={22} color={colors.emerald} />}
            subtext={expectedSub(data.expected_male)}
          />
        </View>
        <View style={styles.kpiRow}>
          <KpiCard
            title="Female Inside"
            value={data.female}
            accent={colors.green}
            icon={<Ionicons name="woman" size={22} color={colors.green} />}
            subtext={expectedSub(data.expected_female)}
          />
          <KpiCard
            title="Guests Inside"
            value={data.guests_inside}
            accent={colors.gold}
            icon={<Ionicons name="people" size={22} color={colors.gold} />}
            subtext={expectedSub(data.expected_guests)}
          />
        </View>
        <View style={styles.busyCard}>
          <Text style={styles.busyLabel}>Busiest gate</Text>
          <Text style={styles.busyValue} numberOfLines={1}>
            {data.busiest_gate}
          </Text>
        </View>
      </View>

      <SectionCard title="Gate Throughput" subtitle="Entries in the last 15 minutes">
        {data.throughput.length === 0 ? (
          <Text style={styles.muted}>No gates configured.</Text>
        ) : (
          data.throughput.map((t) => (
            <GateBar
              key={t.gate.id}
              label={t.gate.label}
              count={t.count}
              maxCount={maxThroughput}
            />
          ))
        )}
      </SectionCard>

      <SectionCard title="Gate Sync Status" subtitle="Offline-first: gates keep scanning without signal">
        <View style={styles.syncGrid}>
          {data.sync.map((s) => {
            const online = s.last !== null;
            return (
              <View key={s.gate.id} style={styles.syncCard}>
                <View style={styles.syncTop}>
                  <View style={[styles.syncDot, { backgroundColor: online ? colors.emerald : colors.amber }]} />
                  <Text style={styles.syncTitle} numberOfLines={1}>{s.gate.label}</Text>
                </View>
                <Text style={styles.syncMeta}>{s.count} scans</Text>
                <Text style={styles.syncMeta}>last {s.last ?? "never"}</Text>
              </View>
            );
          })}
        </View>
      </SectionCard>

      <SectionCard title="Live Scan Feed" subtitle="Newest scans slide in as they happen">
        {data.feed.length === 0 ? (
          <EmptyState
            icon="qr-code-outline"
            title="No scans yet"
            message="Scans from every gate will appear here in real time."
          />
        ) : (
          data.feed.map((item) => <ScanFeedItem key={item.id} item={item} />)
        )}
      </SectionCard>

      <Text style={styles.generated}>Updated {data.generated_at}</Text>
      <View style={styles.bottomPad} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  banner: {
    borderBottomLeftRadius: radius.lg,
    borderBottomRightRadius: radius.lg,
    overflow: "hidden",
    padding: spacing.lg,
    paddingTop: spacing.xl,
  },
  bannerRow: {
    alignItems: "center",
    flexDirection: "row",
    justifyContent: "space-between",
  },
  bannerSub: {
    color: "rgba(255,255,255,0.85)",
    fontSize: fontSize.body,
    marginTop: spacing.xs,
  },
  bannerTitle: {
    color: colors.white,
    fontSize: fontSize.display,
    fontWeight: fontWeight.bold,
    marginTop: spacing.sm,
  },
  bannerYear: {
    color: colors.gold,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.bold,
    letterSpacing: 1,
    textTransform: "uppercase",
  },
  bottomPad: {
    height: spacing.lg,
  },
  busyCard: {
    backgroundColor: colors.greenDark,
    borderRadius: radius.lg,
    elevation: 3,
    flex: 1,
    justifyContent: "center",
    marginTop: spacing.sm,
    minWidth: 0,
    padding: spacing.md,
    shadowColor: colors.greenDark,
    shadowOffset: { height: 2, width: 0 },
    shadowOpacity: 0.2,
    shadowRadius: 8,
  },
  busyLabel: {
    color: colors.gold,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.bold,
    textTransform: "uppercase",
  },
  busyValue: {
    color: colors.white,
    fontSize: fontSize.subheading,
    fontWeight: fontWeight.bold,
    marginTop: spacing.xs,
  },
  generated: {
    color: colors.muted,
    fontSize: fontSize.caption,
    marginTop: spacing.md,
    textAlign: "center",
  },
  heroLabel: {
    color: "rgba(255,255,255,0.85)",
    fontSize: fontSize.caption,
    marginTop: 2,
  },
  heroNumber: {
    color: colors.white,
    fontSize: 52,
    fontWeight: fontWeight.bold,
  },
  heroStat: {
    marginTop: spacing.md,
  },
  heroSub: {
    color: "rgba(255,255,255,0.85)",
    fontSize: fontSize.caption,
    marginTop: spacing.xs,
  },
  kpiGrid: {
    marginTop: spacing.md,
    paddingHorizontal: spacing.md,
  },
  kpiRow: {
    flexDirection: "row",
    gap: spacing.sm,
    marginBottom: spacing.sm,
  },
  liveDot: {
    backgroundColor: "#4ADE80",
    borderRadius: radius.full,
    height: 8,
    width: 8,
  },
  livePill: {
    alignItems: "center",
    backgroundColor: "rgba(255,255,255,0.18)",
    borderRadius: radius.full,
    flexDirection: "row",
    gap: 6,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
  },
  liveText: {
    color: colors.white,
    fontSize: fontSize.small,
    fontWeight: fontWeight.bold,
    letterSpacing: 1,
  },
  muted: {
    color: colors.muted,
    fontSize: fontSize.body,
  },
  progressFill: {
    backgroundColor: "#9BD1B0",
    borderRadius: radius.full,
    height: 8,
  },
  progressTrack: {
    backgroundColor: "rgba(255,255,255,0.22)",
    borderRadius: radius.full,
    height: 8,
    marginTop: spacing.sm,
    overflow: "hidden",
  },
  root: {
    backgroundColor: colors.background,
    flex: 1,
  },
  syncCard: {
    backgroundColor: colors.tint,
    borderRadius: radius.md,
    flex: 1,
    margin: spacing.xs,
    minWidth: "44%",
    padding: spacing.sm,
  },
  syncDot: {
    borderRadius: radius.full,
    height: 10,
    width: 10,
  },
  syncGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    marginHorizontal: -spacing.xs,
  },
  syncMeta: {
    color: colors.muted,
    fontSize: fontSize.caption,
    marginTop: 2,
  },
  syncTitle: {
    color: colors.greenDark,
    flex: 1,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.bold,
    marginLeft: spacing.xs,
  },
  syncTop: {
    alignItems: "center",
    flexDirection: "row",
  },
});
