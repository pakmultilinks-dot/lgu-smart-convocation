// Public Medalist Board (Phase 6, §5; Phase 33 Part E): published honours
// for the active convocation — name, department, award, approved picture
// only. No authentication, no private fields; a record without a picture
// shows a monogram placeholder (the picture is required only to publish).
// Phase 33: the empty board reads as six distinct outcomes — no
// convocation, nothing published, no match for the active filters, or a
// filter the board no longer carries (each offers the right action),
// never one generic "No medalists to show". The board API publishes no
// list-level timestamp, so the screen shows no publication date rather
// than inventing one. Phase 8 freshness unchanged.

import { router } from "expo-router";
import { useCallback, useRef, useState } from "react";
import { Image, Pressable, StyleSheet, Text, View } from "react-native";
import { ApiError } from "../../src/api/client";
import * as medalistApi from "../../src/api/medalistApi";
import { useFreshServerData } from "../../src/hooks/useFreshServerData";
import { colors, fonts, radius, spacing } from "../../src/theme";
import { convocationLine } from "../../src/utils/convocation";
import {
  AppButton,
  AppHeader,
  EmptyState,
  ErrorState,
  LoadingState,
  Screen,
  SegmentedControl,
} from "../../src/ui";

type State = { error: string } | { board: medalistApi.MedalistBoard } | null;

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

const initials = (name: string) =>
  name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("");

const AWARD_STYLE: Record<string, { bg: string; fg: string }> = {
  gold: { bg: colors.gold, fg: colors.ink },
  silver: { bg: colors.track, fg: colors.ink },
  bronze: { bg: colors.amber, fg: colors.paper },
};

export default function MedalistBoardScreen() {
  const [state, setState] = useState<State>(null);
  const [stale, setStale] = useState(false);
  const [photoBase, setPhotoBase] = useState("");
  const [category, setCategory] = useState("");
  const [department, setDepartment] = useState("");
  const hasDataRef = useRef(false);

  const load = useCallback(
    async (silent = false, overrides?: { category?: string; department?: string }) => {
      const cat = overrides?.category ?? category;
      const dep = overrides?.department ?? department;
      if (!silent) setState(null);
      try {
        const [board, photos] = await Promise.all([
          medalistApi.fetchBoard({
            department: dep || undefined,
            category: cat || undefined,
          }),
          medalistApi.photoBase(),
        ]);
        hasDataRef.current = true;
        setPhotoBase(photos);
        setState({ board });
        setStale(false);
      } catch (e) {
        // A failed background refresh keeps the last board on screen (stale
        // badge) — a network failure is never a rejection.
        if (silent && hasDataRef.current) {
          setStale(true);
          return;
        }
        setState({
          error:
            e instanceof ApiError
              ? e.message
              : "The medalist board could not be loaded. Check the connection.",
        });
      }
    },
    [category, department],
  );

  // Focus / resume / manual / ≤30s cadence — one shared rule (the latest
  // filter selection rides along through the hook's refresh ref).
  const refresh = useFreshServerData(() => load(true));

  if (!state) {
    return (
      <Screen scroll={false}>
        <LoadingState label="Loading the medalist board..." />
      </Screen>
    );
  }
  if ("error" in state) {
    return (
      <Screen scroll={false}>
        <ErrorState
          title="Board unavailable"
          body={state.error}
          onRetry={() => void load()}
        />
      </Screen>
    );
  }

  const { board } = state;
  const chips = [
    { label: "All departments", value: "" },
    ...board.departments.map((d) => ({ label: d, value: d })),
  ];
  // Phase 33 Part E: the SAME state variables drive the query and the
  // "Showing:" line, so the displayed filters can never drift from the
  // request. A selected filter the board no longer carries is called out
  // separately from "no match" — the data no longer supports it.
  const filtered = category !== "" || department !== "";
  const unsupported =
    (category !== "" && !board.categories.includes(category)) ||
    (department !== "" && !board.departments.includes(department));
  const resetFilters = () => {
    setCategory("");
    setDepartment("");
    void load(true, { category: "", department: "" });
  };

  return (
    <Screen>
      <AppHeader
        eyebrow="Honours"
        title="Medalist Board"
        subtitle={convocationLine(board.convocation)}
        onBack={() => router.back()}
      />
      {stale ? (
        <Text style={styles.stale}>
          Offline — showing the last loaded board. Retrying automatically.
        </Text>
      ) : null}
      {board.convocation === null ? (
        <EmptyState
          title="No convocation configured"
          body="The medalist board will appear once the convocation is set up."
        />
      ) : (
        <>
          {board.categories.length > 0 ? (
            <SegmentedControl
              options={[
                { label: "All", value: "" },
                ...board.categories.map((c) => ({ label: cap(c), value: c })),
              ]}
              value={category}
              onChange={(c) => {
                setCategory(c);
                void load(true, { category: c });
              }}
            />
          ) : null}
          {chips.length > 2 ? (
            <View style={styles.chips}>
              {chips.map((c) => (
                <Pressable
                  key={c.value}
                  onPress={() => {
                    setDepartment(c.value);
                    void load(true, { department: c.value });
                  }}
                  style={[styles.chip, c.value === department && styles.chipActive]}
                >
                  <Text
                    style={[
                      styles.chipText,
                      c.value === department && styles.chipTextActive,
                    ]}
                  >
                    {c.label}
                  </Text>
                </Pressable>
              ))}
            </View>
          ) : null}
          {board.medalists.length === 0 ? (
            unsupported ? (
              <EmptyState
                title="This filter is no longer available"
                body="The board changed since the filter was applied. Reset the filters to see the current published list."
                actionLabel="Reset filters"
                onAction={resetFilters}
              />
            ) : filtered ? (
              <EmptyState
                title="No medalists match these filters"
                body="No published medalist matches the current selection. Reset the filters to see the full published list."
                actionLabel="Reset filters"
                onAction={resetFilters}
              />
            ) : (
              <EmptyState
                title="No medalists published yet"
                body="The university has not published any medalists for this convocation yet. Published honours will appear here."
                actionLabel="Refresh"
                onAction={() => void refresh()}
              />
            )
          ) : (
            <>
              <Text style={styles.count}>
                {`${board.medalists.length} published medalist${board.medalists.length === 1 ? "" : "s"}${
                  filtered
                    ? ` · Showing: ${[category && cap(category), department]
                        .filter(Boolean)
                        .join(" · ")}`
                    : ""
                }`}
              </Text>
              <View style={styles.grid}>
                {board.medalists.map((m) => {
                  const award = AWARD_STYLE[m.award_category] ?? {
                    bg: colors.track,
                    fg: colors.ink,
                  };
                  return (
                    <View key={m.id} style={styles.card}>
                      {photoBase && m.has_photo ? (
                        <Image
                          source={{ uri: `${photoBase}/${m.id}` }}
                          style={styles.photo}
                          accessibilityLabel={`${m.student_name} photograph`}
                        />
                      ) : (
                        <View style={[styles.photo, styles.placeholder]}>
                          <Text style={styles.placeholderText}>
                            {initials(m.student_name) || "?"}
                          </Text>
                        </View>
                      )}
                      <View
                        style={[
                          styles.award,
                          { backgroundColor: award.bg },
                        ]}
                      >
                        <Text style={[styles.awardText, { color: award.fg }]}>
                          {cap(m.award_category)}
                          {m.position ? ` · ${m.position}` : ""}
                        </Text>
                      </View>
                      <Text style={styles.name} numberOfLines={2}>
                        {m.student_name}
                      </Text>
                      <Text style={styles.dept} numberOfLines={1}>
                        {m.department}
                      </Text>
                    </View>
                  );
                })}
              </View>
              {filtered ? (
                <AppButton
                  label="Reset filters"
                  variant="secondary"
                  onPress={resetFilters}
                  style={styles.refresh}
                />
              ) : null}
              <AppButton
                label="Refresh"
                variant="ghost"
                icon="refresh"
                onPress={() => void refresh()}
                style={styles.refresh}
              />
            </>
          )}
        </>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  chips: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.xs,
    marginBottom: spacing.md,
  },
  chip: {
    borderWidth: 1,
    borderColor: colors.track,
    borderRadius: radius.md,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    backgroundColor: colors.paper,
  },
  chipActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  chipText: { color: colors.ink, fontFamily: fonts.mono, fontSize: 12 },
  chipTextActive: { color: colors.paper },
  count: {
    color: colors.muted,
    fontFamily: fonts.mono,
    fontSize: 12,
    marginBottom: spacing.sm,
  },
  stale: {
    color: colors.amber,
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    marginBottom: spacing.sm,
  },
  refresh: { marginTop: spacing.lg },
  grid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.sm,
  },
  card: {
    flexGrow: 1,
    flexBasis: "46%",
    backgroundColor: colors.paper,
    borderWidth: 1,
    borderColor: colors.track,
    borderRadius: radius.md,
    padding: spacing.sm,
    alignItems: "center",
  },
  photo: {
    width: 84,
    height: 84,
    borderRadius: 42,
    marginBottom: spacing.sm,
  },
  placeholder: {
    backgroundColor: colors.track,
    alignItems: "center",
    justifyContent: "center",
  },
  placeholderText: {
    color: colors.muted,
    fontFamily: fonts.displayMedium,
    fontSize: 26,
  },
  award: {
    borderRadius: radius.md,
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    marginBottom: spacing.xs,
  },
  awardText: { fontFamily: fonts.mono, fontSize: 11, textTransform: "uppercase" },
  name: {
    color: colors.ink,
    fontFamily: fonts.displayMedium,
    fontSize: 14,
    textAlign: "center",
  },
  dept: {
    color: colors.muted,
    fontFamily: fonts.mono,
    fontSize: 11,
    textAlign: "center",
    marginTop: 2,
  },
});
