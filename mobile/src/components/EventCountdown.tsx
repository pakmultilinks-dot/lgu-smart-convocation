// Annual-cycle countdown (Phase 29 §3). The server publishes each
// occasion's phase and a UTC `starts_at` instant, so this component never
// guesses the device timezone and never invents a start time. Honest rules:
// a countdown appears only for a confirmed/announced start that is upcoming
// or today; a date with no published start time shows plain days ("3 days
// to go") and never a fake clock; a provisional (expected) date never
// counts down; a passed date reads "Completed" — never a negative count.
// The pure logic (pickNextOccasion / countdownText) is exported for tests.

import { useEffect, useState } from "react";
import { StyleSheet, Text, View } from "react-native";
import type { OccasionInfo } from "../api/eventApi";
import { colors, fonts, radius, spacing } from "../theme";

const DAY_MS = 86_400_000;

/** The occasion the clock belongs to: the first announced/confirmed
    occasion that is upcoming or live; else the most recently completed
    announced one (so the screen can honestly say "Completed"); else null. */
export function pickNextOccasion(
  occasions: readonly OccasionInfo[] | null | undefined,
): OccasionInfo | null {
  if (!occasions?.length) return null;
  const announced = (o: OccasionInfo) =>
    o.state === "confirmed" || o.state === "announced";
  return (
    occasions.find(
      (o) => announced(o) && (o.phase === "upcoming" || o.phase === "live"),
    ) ??
    [...occasions]
      .reverse()
      .find((o) => announced(o) && o.phase === "completed") ??
    null
  );
}

/** Pure countdown text at `nowMs`. Null when no countdown should show
    (unannounced or provisional — the clock must never imply certainty the
    published schedule does not have). */
export function countdownText(o: OccasionInfo, nowMs: number): string | null {
  if (o.state === "not_announced" || o.state === "expected") return null;
  if (o.phase === "completed") return "Completed";
  const start = o.starts_at ? Date.parse(o.starts_at) : NaN;
  if (Number.isNaN(start)) {
    // No published start time: days only — never a fabricated clock.
    if (o.days_until === null) return null;
    if (o.phase === "live" || o.days_until <= 0) return "Today";
    return `${o.days_until} day${o.days_until === 1 ? "" : "s"} to go`;
  }
  const left = start - nowMs;
  if (left <= 0) {
    // Clock skew between the server instant and the device: the start has
    // begun, so it is happening now — "Completed" needs the server's phase.
    return o.phase === "live" || left > -DAY_MS
      ? "Happening now"
      : "Completed";
  }
  const s = Math.floor(left / 1000);
  const d = Math.floor(s / 86400);
  if (d > 0) return `${d} day${d === 1 ? "" : "s"} to go`;
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(
    s % 60,
  ).padStart(2, "0")}`;
}

/** Ticks a live clock once a second; a days-only countdown re-checks every
    minute (the value itself is server-derived, so this only picks up a
    phase change); no interval at all when there is nothing to show. */
export function useCountdown(o: OccasionInfo | null): string | null {
  const [now, setNow] = useState(() => Date.now());
  const live =
    !!o &&
    o.starts_at !== null &&
    o.phase !== "completed" &&
    o.state !== "not_announced" &&
    o.state !== "expected";
  useEffect(() => {
    if (!live) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [live, o?.starts_at]);
  return o ? countdownText(o, now) : null;
}

export function EventCountdown({
  occasions,
  portalTz,
}: {
  occasions?: readonly OccasionInfo[] | null;
  portalTz?: string | null;
}) {
  const next = pickNextOccasion(occasions);
  const text = useCountdown(next);
  if (!next || !text) return null;
  const when = [next.date, next.time].filter(Boolean).join(" · ");
  return (
    <View style={styles.card}>
      <Text style={styles.eyebrow}>
        {text === "Completed" ? next.label : `Countdown · ${next.label}`}
      </Text>
      <Text style={styles.value}>{text}</Text>
      <Text style={styles.sub}>
        {[when, next.venue, portalTz ? `(${portalTz})` : ""]
          .filter(Boolean)
          .join(" · ")}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    borderWidth: 1,
    borderColor: colors.ink,
    borderRadius: radius.sm,
    backgroundColor: colors.paper,
    padding: spacing.md,
    marginBottom: spacing.lg,
    gap: spacing.sm,
  },
  eyebrow: {
    fontFamily: fonts.displayMedium,
    fontSize: 11,
    color: colors.muted,
    textTransform: "uppercase" as const,
    letterSpacing: 0.4,
  },
  value: {
    fontFamily: fonts.display,
    fontSize: 24,
    color: colors.ink,
  },
  sub: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.muted,
  },
});
