import { useFocusEffect } from "expo-router";
import { useCallback, useRef, useState } from "react";
import {
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import {
  ApiError,
  fetchDashboard,
  type DashboardData,
} from "../api/client";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { GateBar } from "../components/GateBar";
import { KpiCard } from "../components/KpiCard";
import { ScanFeedItem } from "../components/ScanFeedItem";
import { SectionCard } from "../components/SectionCard";
import { colors, fontSize, fontWeight, radius, spacing } from "../theme";

const REFRESH_MS = 5000;

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
        <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
      }
    >
      <View style={styles.kpiGrid}>
        <View style={styles.kpiRow}>
          <KpiCard title="Inside Now" value={String(data.inside_total)} accent={colors.navy} />
          <KpiCard title="Male" value={String(data.male)} accent={colors.navySoft} />
        </View>
        <View style={styles.kpiRow}>
          <KpiCard title="Female" value={String(data.female)} accent={colors.gold} />
          <KpiCard title="Guests" value={String(data.guests_inside)} accent={colors.green} />
        </View>
        <View style={styles.wideCard}>
          <Text style={styles.wideLabel}>Busiest Gate</Text>
          <Text style={styles.wideValue}>{data.busiest_gate}</Text>
        </View>
      </View>

      <SectionCard title="Gate Throughput (last 15 min)">
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

      <SectionCard title="Gate Sync Status">
        <View style={styles.chipRow}>
          {data.sync.map((s) => (
            <View key={s.gate.id} style={styles.chip}>
              <Text style={styles.chipTitle}>{s.gate.label}</Text>
              <Text style={styles.chipMeta}>
                {s.count} scans · last {s.last ?? "never"}
              </Text>
            </View>
          ))}
        </View>
      </SectionCard>

      <SectionCard title="Live Scan Feed">
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
  bottomPad: {
    height: spacing.lg,
  },
  chip: {
    backgroundColor: colors.background,
    borderColor: colors.border,
    borderRadius: radius.md,
    borderWidth: 1,
    marginBottom: spacing.sm,
    marginRight: spacing.sm,
    padding: spacing.sm,
  },
  chipMeta: {
    color: colors.muted,
    fontSize: fontSize.caption,
    marginTop: 2,
  },
  chipRow: {
    flexDirection: "row",
    flexWrap: "wrap",
  },
  chipTitle: {
    color: colors.navy,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.bold,
  },
  generated: {
    color: colors.muted,
    fontSize: fontSize.caption,
    marginTop: spacing.md,
    textAlign: "center",
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
  muted: {
    color: colors.muted,
    fontSize: fontSize.body,
  },
  root: {
    backgroundColor: colors.background,
    flex: 1,
  },
  wideCard: {
    backgroundColor: colors.navy,
    borderRadius: radius.md,
    elevation: 2,
    padding: spacing.md,
    shadowColor: "#0B2447",
    shadowOffset: { height: 1, width: 0 },
    shadowOpacity: 0.15,
    shadowRadius: 4,
  },
  wideLabel: {
    color: colors.goldSoft,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.medium,
  },
  wideValue: {
    color: colors.white,
    fontSize: fontSize.heading,
    fontWeight: fontWeight.bold,
    marginTop: 2,
  },
});
