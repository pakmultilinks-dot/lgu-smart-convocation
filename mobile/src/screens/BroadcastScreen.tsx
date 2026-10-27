import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { Modal, Pressable, Text, View } from "react-native";
import {
  ApiError,
  fetchAppConfig,
  fetchBroadcastAudience,
  fetchBroadcasts,
  fetchGates,
  sendBroadcast,
  type BroadcastEntry,
  type BroadcastGateAudience,
  type Gate,
} from "../api/client";
import { getVolunteerName } from "../store/settings";
import { colors, fonts, radius, spacing } from "../theme";
import { text } from "../theme/typography";
import {
  AppButton,
  AppHeader,
  ErrorState,
  Field,
  LoadingState,
  Screen,
  SectionCard,
  SectionEyebrow,
  SegmentedControl,
  formatLocalClock,
} from "../ui";

type Audience = "all" | "gate" | "volunteers";

// Announcement length limit (Phase 35G/35K): the server-configured
// message_char_limit from /api/config is authoritative; 160 is only the
// offline fallback before config loads (Part K — one shared limit).
const MESSAGE_LIMIT_FALLBACK = 160;

/**
 * Announcement — logs a message to the backend record (admin surface,
 * behind the PIN gate in app/(volunteer)/broadcast.tsx). The delivery
 * mode comes from the server (/api/config → broadcast_mode): "demo"
 * (default) records only and says so; "real" records too and states that
 * no delivery gateway is configured. The success note is the SERVER's
 * note — the client never invents an outcome (Phase 35K Part G).
 */
export function BroadcastScreen() {
  const router = useRouter();
  const [audience, setAudience] = useState<Audience>("all");
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [history, setHistory] = useState<BroadcastEntry[] | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [gates, setGates] = useState<Gate[]>([]);
  const [gatesError, setGatesError] = useState<string | null>(null);
  // 35J (M): "By gate" multi-selects gates — one or several — rendered as
  // 2-column tiles (same visual model as the scanner gate sheet).
  const [selectedGateIds, setSelectedGateIds] = useState<number[]>([]);
  // Phase 35K: server-configured state — audience count (roster-based,
  // NOT the attendance target), delivery mode and message limit all come
  // from /api/config; demo defaults apply until it loads or when offline.
  const [audienceCount, setAudienceCount] = useState<number | null>(null);
  const [broadcastMode, setBroadcastMode] = useState<"demo" | "real">("demo");
  const [messageLimit, setMessageLimit] = useState(MESSAGE_LIMIT_FALLBACK);
  // By-gate audience from the server (real scan history, never fabricated).
  // Raw fetch result; the effective value below is derived at render so a
  // deselected audience/gate never needs a synchronous setState in an effect.
  // 33-QA (I15): per_gate carries each selected gate's own count, ordered
  // largest first by the server — the breakdown renders under the tiles.
  const [gateAudienceRaw, setGateAudienceRaw] = useState<{
    count: number;
    basis: string;
    per_gate?: BroadcastGateAudience[];
  } | null>(null);

  const loadHistory = useCallback(async () => {
    try {
      const entries = await fetchBroadcasts();
      setHistory(entries);
      setHistoryError(null);
    } catch (e) {
      setHistory(null);
      setHistoryError(
        e instanceof Error
          ? e.message
          : "Announcement history could not be loaded.",
      );
    }
  }, []);

  // Real gate list (Phase 35G): "By gate" offers the actual gates as
  // selectable targets — not just the words "By gate" with no next step.
  const loadGates = useCallback(async () => {
    try {
      const list = await fetchGates();
      setGates(list);
      setGatesError(null);
    } catch (e) {
      setGates([]);
      setGatesError(
        e instanceof ApiError
          ? e.message
          : "Gates could not be loaded. Check the connection and retry.",
      );
    }
  }, []);

  // Server configuration (Phase 35K): audience count, delivery mode and
  // message limit — one source of truth shared with the backend queries.
  const loadConfig = useCallback(async () => {
    try {
      const cfg = await fetchAppConfig();
      setBroadcastMode(cfg.broadcast_mode === "real" ? "real" : "demo");
      setMessageLimit(
        cfg.message_char_limit > 0
          ? cfg.message_char_limit
          : MESSAGE_LIMIT_FALLBACK,
      );
      setAudienceCount(
        cfg.announcement_audience_count > 0
          ? cfg.announcement_audience_count
          : null,
      );
    } catch {
      // Offline: keep the demo defaults — never claim a mode we did not read.
      setBroadcastMode("demo");
      setMessageLimit(MESSAGE_LIMIT_FALLBACK);
      setAudienceCount(null);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      void loadHistory();
      void loadGates();
      void loadConfig();
    }, [loadHistory, loadGates, loadConfig]),
  );

  // By-gate audience (Phase 35K Part I): the server derives the count from
  // real scan history — students currently inside at the selected gates —
  // and returns the basis rule with it. Fetched whenever the selection
  // changes; the effective value is derived at render (never shown for a
  // different audience or an empty gate selection).
  useEffect(() => {
    if (audience !== "gate" || selectedGateIds.length === 0) return;
    let cancelled = false;
    void (async () => {
      try {
        const res = await fetchBroadcastAudience(selectedGateIds);
        if (!cancelled) {
          setGateAudienceRaw({
            count: res.count,
            basis: res.basis,
            per_gate: res.per_gate,
          });
        }
      } catch {
        if (!cancelled) setGateAudienceRaw(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [audience, selectedGateIds]);

  const gateAudience =
    audience === "gate" && selectedGateIds.length > 0 ? gateAudienceRaw : null;

  const selectedGates = gates.filter((g) => selectedGateIds.includes(g.id));
  const gateCountText = `${selectedGateIds.length} gate${
    selectedGateIds.length === 1 ? "" : "s"
  } selected`;
  const isDemo = broadcastMode === "demo";
  // 35M item 1: the "All students" audience is labelled simply
  // "Students" on the chip + result line. The label doubles as the
  // audience value in the API payload — the confirmation dialogs keep
  // their pinned "all students" wording (navigation-broadcast/ui-35h).
  const audienceLabel =
    audience === "all"
      ? "Students"
      : audience === "volunteers"
        ? "Volunteers"
        : selectedGates.map((g) => g.label).join(", ");
  const audienceDisplay =
    audience === "all"
      ? audienceCount
        ? `Students · ${audienceCount.toLocaleString()}`
        : "Students"
      : audience === "volunteers"
        ? "Volunteers"
        : selectedGates.length > 0
          ? gateAudience
            ? `${gateAudience.count.toLocaleString()} students · ${gateCountText}`
            : gateCountText
          : "No gates selected";
  // The real audience count carried by the confirm action — roster-based
  // for "All students", scan-derived for "By gate" (never the attendance
  // target, Phase 35K Part I).
  const actionCount =
    audience === "all"
      ? audienceCount
      : audience === "gate"
        ? gateAudience?.count ?? null
        : null;
  // 35J (P0) + 35K (G) → QA fix cycle 2: the confirm action names the
  // real outcome — "Save" in demo mode (saved to the log only), "Send
  // announcement" in real mode (recorded; no delivery gateway
  // configured). The count is the actual audience, never fabricated.
  const finalLabel =
    actionCount != null
      ? isDemo
        ? `Save for ${actionCount.toLocaleString()}`
        : `Send announcement for ${actionCount.toLocaleString()}`
      : isDemo
        ? "Save announcement"
        : "Send announcement";
  const primaryLabel = isDemo ? "Save announcement" : "Send announcement";

  const review = useCallback(() => {
    const trimmed = message.trim();
    if (!trimmed) {
      setNote({ ok: false, text: "Enter a message before logging." });
      return;
    }
    if (trimmed.length > messageLimit) {
      setNote({
        ok: false,
        text: `Messages are limited to ${messageLimit} characters.`,
      });
      return;
    }
    if (audience === "gate" && selectedGateIds.length === 0) {
      setNote({
        ok: false,
        text: "Choose at least one gate for this announcement.",
      });
      return;
    }
    setNote(null);
    setConfirmOpen(true);
  }, [audience, message, messageLimit, selectedGateIds]);

  const sendNow = useCallback(async () => {
    const trimmed = message.trim();
    if (!trimmed || !audienceLabel) {
      setConfirmOpen(false);
      return;
    }
    setSending(true);
    setNote(null);
    try {
      const sentBy = (await getVolunteerName()).trim() || "Admin";
      // sendBroadcast attaches the X-Admin-Pin header from the device gate.
      const result = await sendBroadcast({
        audience: audienceLabel,
        message: trimmed,
        sent_by: sentBy,
      });
      setNote({
        ok: true,
        // Phase 35K (G): the SERVER's note is the outcome — demo mode says
        // logged/not-sent, real mode says recorded/no gateway. The client
        // never invents a delivery claim.
        text: result.note ?? "Announcement recorded.",
      });
      setMessage("");
      setSelectedGateIds([]);
      setConfirmOpen(false);
      await loadHistory();
    } catch (e) {
      setNote({
        ok: false,
        text:
          e instanceof ApiError
            ? e.message
            : "The message could not be logged. Check the connection and retry.",
      });
      if (e instanceof ApiError && e.status === 401) {
        setConfirmOpen(false);
      }
    } finally {
      setSending(false);
    }
  }, [audienceLabel, loadHistory, message]);

  return (
    // Light in-screen header (Phase 35G: dark native header removed).
    <Screen>
      <AppHeader
        onBack={() =>
          router.canGoBack() ? router.back() : router.replace("/(volunteer)/more")
        }
        title="Operational message log"
        // 35M R2 (item 10): mandated subtitle copy — announcement is a log,
        // not a delivery.
        subtitle="Operational message log for event teams"
      />

      <AppButton label="Publish in student Updates" variant="secondary" onPress={() => router.push("/administration")} />

      {/* 35J (P0) + 35K (G): demo-mode honesty — visible BEFORE composing
          when the server reports demo mode (the default). In real mode the
          banner is hidden and the labels say "Send"; the server still
          records only (no delivery gateway configured) and its note says so. */}
      {isDemo ? (
        <View style={styles.demoBanner}>
          <Ionicons
            name="information-circle-outline"
            size={18}
            color={colors.ink}
          />
          <Text style={styles.demoBannerText}>
            Demo mode — announcements are saved only. Nothing is sent.
          </Text>
        </View>
      ) : null}

      <SectionCard>
        <SectionEyebrow>Audience</SectionEyebrow>
        <SegmentedControl<Audience>
          options={[
            { label: "Students", value: "all" },
            { label: "By gate", value: "gate" },
            { label: "Volunteers", value: "volunteers" },
          ]}
          value={audience}
          onChange={(next) => {
            setAudience(next);
            setNote(null);
          }}
        />
        {audience === "gate" ? (
          gatesError ? (
            <ErrorState
              title="Gates unavailable"
              body={gatesError}
              onRetry={() => void loadGates()}
            />
          ) : gates.length === 0 ? (
            <LoadingState label="Loading gates..." />
          ) : (
            <>
              {/* 35J (M): 2-column tiles — same visual model as the
                  scanner gate sheet (ink fill + paper text + checkmark). */}
              <View style={styles.gateGrid}>
                {gates.map((g) => {
                  const selected = selectedGateIds.includes(g.id);
                  return (
                    <Pressable
                      key={g.id}
                      accessibilityRole="button"
                      accessibilityState={{ selected }}
                      accessibilityLabel={g.label}
                      onPress={() => {
                        setNote(null);
                        setSelectedGateIds((prev) =>
                          prev.includes(g.id)
                            ? prev.filter((id) => id !== g.id)
                            : [...prev, g.id],
                        );
                      }}
                      style={[
                        styles.gateTile,
                        selected && styles.gateTileSelected,
                      ]}
                    >
                      <Text
                        numberOfLines={2}
                        style={[
                          styles.gateTileText,
                          selected && styles.gateTileTextSelected,
                        ]}
                      >
                        {g.label}
                      </Text>
                      {selected ? (
                        <Ionicons name="checkmark" size={18} color={colors.paper} />
                      ) : null}
                    </Pressable>
                  );
                })}
              </View>
              {/* 35J (M): the selected count is always explicit. QA fix
                  cycle 2: one-tap "Select all gates" for the common case. */}
              <Text style={styles.gateCount}>{gateCountText}</Text>
              {selectedGateIds.length < gates.length ? (
                <AppButton
                  label="Select all gates"
                  icon="checkmark-done-outline"
                  variant="ghost"
                  onPress={() => setSelectedGateIds(gates.map((g) => g.id))}
                />
              ) : null}
              {/* 33-QA (I15) → QA fix cycle 2: the server's per-gate
                  breakdown, ordered largest audience first — "· N inside
                  now" states the live inside-count basis. */}
              {gateAudience?.per_gate && gateAudience.per_gate.length > 0 ? (
                <View style={styles.gateAudienceBreakdown}>
                  {gateAudience.per_gate.map((g) => (
                    <Text key={g.id} style={styles.gateAudienceLine}>
                      {g.label} · {g.count.toLocaleString()} inside now
                    </Text>
                  ))}
                </View>
              ) : null}
            </>
          )
        ) : null}
        <Field
          label="Message"
          placeholder="e.g. Convocation gates open at 9:00 AM at the Main Gate."
          value={message}
          onChangeText={(t) => {
            setMessage(t);
            setNote(null);
          }}
          multiline
          numberOfLines={4}
          textAlignVertical="top"
          maxLength={messageLimit}
          style={styles.messageField}
        />
        <Text style={styles.counter}>
          {message.length} / {messageLimit}
        </Text>
        <Text style={styles.helper}>
          Gate, time, action — keep it short and operational.
        </Text>
        {note ? (
          <Text style={note.ok ? styles.noteOk : styles.noteFail}>{note.text}</Text>
        ) : null}
        <AppButton
          label={primaryLabel}
          icon="megaphone-outline"
          disabled={message.trim().length === 0}
          onPress={review}
        />
      </SectionCard>

      <SectionCard>
        <SectionEyebrow>Recent announcements</SectionEyebrow>
        {historyError ? (
          <ErrorState
            title="History unavailable"
            body={historyError}
            onRetry={() => void loadHistory()}
          />
        ) : history === null ? (
          // 35M R2 (item 8): a proper loading line on the empty history
          // slot (existing text primitive — the tiny indicator dot is
          // gone). Gates-loading keeps LoadingState below.
          <Text style={styles.emptyLine}>Loading history...</Text>
        ) : history.length === 0 ? (
          // 35J (O): one restrained line — no card, no illustration.
          <Text style={styles.emptyLine}>No announcements yet.</Text>
        ) : (
          history.map((entry) => (
            <View key={entry.id} style={styles.historyRow}>
              <Text style={styles.historyMessage}>{entry.message}</Text>
              <Text style={styles.historyMeta}>{entry.audience}</Text>
              <Text style={styles.historyMeta}>By {entry.sent_by}</Text>
              <Text style={styles.historyMeta}>
                {formatLocalClock(entry.sent_at)}
              </Text>
            </View>
          ))
        )}
      </SectionCard>

      {/* Confirmation sheet (Phase 35G): the first tap never sends — the
          operator reviews audience + message and confirms with the final
          action, which carries the real audience count. */}
      <Modal
        visible={confirmOpen}
        transparent
        animationType="slide"
        onRequestClose={() => setConfirmOpen(false)}
      >
        <Pressable style={styles.sheetBackdrop} onPress={() => setConfirmOpen(false)}>
          <Pressable style={styles.sheetPanel} onPress={() => undefined}>
            {/* 35J (P0/N) + 35K (G): the sheet names the real action in
                Bricolage — "Log" in demo mode, "Send" in real mode; the
                helper states the server's delivery reality. */}
            <Text style={styles.sheetTitle}>
              {audience === "all"
                ? isDemo
                  ? "Save announcement to all students?"
                  : "Send announcement to all students?"
                : isDemo
                  ? `Save announcement to ${audienceLabel}?`
                  : `Send announcement to ${audienceLabel}?`}
            </Text>
            <Text style={styles.sheetHelper}>
              {isDemo
                ? "Demo mode: recorded in the broadcast log only — nothing is sent by SMS."
                : "Recorded in the broadcast log — no delivery gateway is configured on this server."}
            </Text>
            <View style={styles.sheetField}>
              <Text style={styles.sheetLabel}>Audience</Text>
              <Text style={styles.sheetValue}>{audienceDisplay}</Text>
            </View>
            <View style={styles.sheetField}>
              <Text style={styles.sheetLabel}>Message</Text>
              <Text style={styles.sheetValue}>{message.trim()}</Text>
            </View>
            <AppButton
              label={finalLabel}
              icon="megaphone-outline"
              loading={sending}
              onPress={() => void sendNow()}
            />
            <AppButton
              label="Go back"
              variant="ghost"
              disabled={sending}
              onPress={() => setConfirmOpen(false)}
            />
          </Pressable>
        </Pressable>
      </Modal>
    </Screen>
  );
}

const styles = {
  messageField: {
    marginTop: spacing.sm,
  },
  counter: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.muted,
    marginTop: 6,
    textAlign: "right" as const,
  },
  helper: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.muted,
    lineHeight: 18,
  },
  noteOk: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.valid,
    lineHeight: 18,
    marginTop: spacing.sm,
  },
  noteFail: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.invalid,
    lineHeight: 18,
    marginTop: spacing.sm,
  },
  // 35J (P0): demo-mode honesty strip — visible before composing.
  // 35M R2 (item 9): flat tinted informational strip — the tint
  // background IS the signal; no border, no radius, no interaction.
  demoBanner: {
    flexDirection: "row" as const,
    alignItems: "center" as const,
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    backgroundColor: colors.tint,
  },
  demoBannerText: {
    flex: 1,
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.ink,
  },
  // 35J (M): by-gate tiles — 2-column, same visual model as the
  // scanner gate sheet (ink fill + paper text + checkmark when active).
  gateGrid: {
    flexDirection: "row" as const,
    flexWrap: "wrap" as const,
    gap: spacing.sm,
    marginTop: spacing.md,
  },
  gateTile: {
    flexBasis: "48%" as const,
    flexGrow: 1,
    flexDirection: "row" as const,
    alignItems: "center" as const,
    justifyContent: "space-between" as const,
    gap: spacing.sm,
    minHeight: 48,
    paddingHorizontal: spacing.md,
    borderWidth: 1,
    borderColor: colors.track,
    borderRadius: radius.sm,
    backgroundColor: colors.paper,
  },
  gateTileSelected: {
    backgroundColor: colors.ink,
    borderColor: colors.ink,
  },
  gateTileText: {
    flex: 1,
    fontFamily: fonts.displayMedium,
    fontSize: 15,
    color: colors.ink,
  },
  gateTileTextSelected: {
    // 35M R2 (item 14): family encodes the weight — display (bold) for
    // the selected tile's paper label on ink.
    fontFamily: fonts.display,
    color: colors.paper,
  },
  // 35J (M): the selected count is always explicit ("2 gates selected").
  gateCount: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.muted,
    marginTop: spacing.sm,
  },
  // 33-QA (I15): per-gate audience rows under the selected-count line —
  // same quiet 13px sans, ordered largest first by the server.
  gateAudienceBreakdown: {
    marginTop: spacing.xs,
    gap: 2,
  },
  gateAudienceLine: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.muted,
  },
  // 35J (O): one restrained line — no card, no illustration.
  emptyLine: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.muted,
    paddingVertical: spacing.sm,
  },
  historyRow: {
    gap: 4,
    paddingVertical: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  historyMessage: {
    fontFamily: fonts.displayMedium,
    fontSize: 15,
    color: colors.ink,
    lineHeight: 21,
  },
  historyMeta: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.muted,
  },
  sheetBackdrop: {
    flex: 1,
    backgroundColor: colors.overlay,
    justifyContent: "flex-end" as const,
  },
  sheetPanel: {
    backgroundColor: colors.paper,
    borderTopLeftRadius: 16,
    borderTopRightRadius: 16,
    paddingHorizontal: spacing.screen,
    paddingTop: spacing.lg,
    // Bottom safe-area clearance for the sheet (Phase 35G Part O).
    paddingBottom: spacing.xxl,
    gap: spacing.md,
  },
  // 35J (N): the sheet title is a Bricolage heading; labels below are
  // readable sans 13 — DM Mono is never used for sentences or labels.
  sheetTitle: [text.sectionTitle, { color: colors.ink }],
  sheetHelper: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.muted,
    lineHeight: 18,
  },
  sheetField: {
    gap: 4,
  },
  sheetLabel: text.helper,
  sheetValue: [text.body, { color: colors.ink, lineHeight: 21 }],
};
