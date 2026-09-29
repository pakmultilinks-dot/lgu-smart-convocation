import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import {
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import {
  ApiError,
  fetchBroadcasts,
  fetchGates,
  sendBroadcast,
  type BroadcastEntry,
  type Gate,
} from "../api/client";
import { PrimaryButton } from "../components/PrimaryButton";
import { SectionCard } from "../components/SectionCard";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { getVolunteerName } from "../store/settings";
import { colors, fontSize, fontWeight, radius, spacing } from "../theme";

const ALL_STUDENTS = "All students";
const MAX_MESSAGE = 500;

function LogItem({ entry }: { entry: BroadcastEntry }) {
  return (
    <View style={styles.logItem}>
      <View style={styles.logTop}>
        <View style={styles.logIcon}>
          <Ionicons name="megaphone" size={16} color={colors.green} />
        </View>
        <View style={styles.logHead}>
          <Text style={styles.logAudience}>{entry.audience}</Text>
          <Text style={styles.logMeta}>
            {entry.sent_by}
            {entry.sent_at ? ` \u00B7 ${entry.sent_at}` : ""}
          </Text>
        </View>
      </View>
      <Text style={styles.logMessage}>{entry.message}</Text>
    </View>
  );
}

export function BroadcastScreen() {
  const [gates, setGates] = useState<Gate[]>([]);
  const [audience, setAudience] = useState<string>(ALL_STUDENTS);
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [log, setLog] = useState<BroadcastEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadLog = useCallback(async (showSpinner: boolean) => {
    if (showSpinner) {
      setLoading(true);
    }
    try {
      setLog(await fetchBroadcasts());
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load the log.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void loadLog(true);
    void fetchGates().then(setGates).catch(() => setGates([]));
  }, [loadLog]);

  useFocusEffect(
    useCallback(() => {
      void loadLog(false);
    }, [loadLog]),
  );

  const send = async () => {
    if (message.trim().length === 0) {
      setFormError("Message text is required.");
      return;
    }
    if (message.trim().length > MAX_MESSAGE) {
      setFormError(`Keep the message under ${MAX_MESSAGE} characters.`);
      return;
    }
    setSending(true);
    setFormError(null);
    setNote(null);
    try {
      const sentBy = (await getVolunteerName()) || "Admin";
      const response = await sendBroadcast({
        audience,
        message: message.trim(),
        sent_by: sentBy,
      });
      setNote(response.note ?? "Broadcast logged.");
      setMessage("");
      await loadLog(false);
    } catch (e) {
      setFormError(
        e instanceof ApiError ? e.message : "Broadcast failed. Try again.",
      );
    } finally {
      setSending(false);
    }
  };

  const audiences = [ALL_STUDENTS, ...gates.map((g) => g.label)];
  const remaining = MAX_MESSAGE - message.length;

  return (
    <FlatList
      style={styles.root}
      data={log}
      keyExtractor={(item) => String(item.id)}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={() => {
            setRefreshing(true);
            void loadLog(false);
          }}
          colors={[colors.green]}
        />
      }
      ListHeaderComponent={
        <View>
          <SectionCard title="New Broadcast" subtitle="One message, every gate at once">
            <Text style={styles.label}>Audience</Text>
            <View style={styles.audienceRow}>
              {audiences.map((option) => {
                const active = option === audience;
                return (
                  <Pressable
                    key={option}
                    onPress={() => setAudience(option)}
                    style={({ pressed }) => [
                      styles.audienceChip,
                      active && styles.audienceChipActive,
                      pressed && styles.pressed,
                    ]}
                  >
                    <Text
                      style={[
                        styles.audienceText,
                        active && styles.audienceTextActive,
                      ]}
                    >
                      {option}
                    </Text>
                  </Pressable>
                );
              })}
            </View>

            <View style={styles.messageLabelRow}>
              <Text style={styles.label}>Message</Text>
              <Text style={[styles.charCount, remaining < 50 && styles.charCountLow]}>
                {message.length}/{MAX_MESSAGE}
              </Text>
            </View>
            <TextInput
              style={[styles.input, styles.messageInput]}
              value={message}
              onChangeText={setMessage}
              placeholder="Type the announcement for the convocation..."
              placeholderTextColor={colors.muted}
              multiline
              numberOfLines={4}
              textAlignVertical="top"
            />

            {formError && <Text style={styles.formError}>{formError}</Text>}
            {note && (
              <View style={styles.noteBox}>
                <Ionicons name="checkmark-circle" size={18} color={colors.green} />
                <Text style={styles.note}>{note}</Text>
              </View>
            )}

            <View style={styles.sendWrap}>
              <PrimaryButton
                title="Send broadcast"
                onPress={() => void send()}
                loading={sending}
              />
            </View>
          </SectionCard>
          <Text style={styles.logTitle}>Sent Log</Text>
        </View>
      }
      renderItem={({ item }) => <LogItem entry={item} />}
      contentContainerStyle={styles.listContent}
      ListEmptyComponent={
        loading ? (
          <LoadingState message="Loading broadcasts..." />
        ) : error ? (
          <ErrorState message={error} onRetry={() => void loadLog(true)} />
        ) : (
          <EmptyState
            icon="megaphone-outline"
            title="No broadcasts yet"
            message="Announcements sent from this screen will be logged here."
          />
        )
      }
    />
  );
}

const styles = StyleSheet.create({
  audienceChip: {
    backgroundColor: colors.tint,
    borderColor: colors.border,
    borderRadius: radius.full,
    borderWidth: 1,
    marginBottom: spacing.sm,
    marginRight: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  audienceChipActive: {
    backgroundColor: colors.green,
    borderColor: colors.green,
    elevation: 2,
    shadowColor: colors.greenDark,
    shadowOffset: { height: 1, width: 0 },
    shadowOpacity: 0.25,
    shadowRadius: 4,
  },
  audienceRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    marginTop: spacing.xs,
  },
  audienceText: {
    color: colors.text,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.semibold,
  },
  audienceTextActive: {
    color: colors.white,
  },
  charCount: {
    color: colors.muted,
    fontSize: fontSize.caption,
  },
  charCountLow: {
    color: colors.amber,
    fontWeight: fontWeight.bold,
  },
  formError: {
    color: colors.red,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.semibold,
    marginTop: spacing.sm,
  },
  input: {
    backgroundColor: colors.inputBg,
    borderColor: colors.border,
    borderRadius: radius.md,
    borderWidth: 1,
    color: colors.text,
    fontSize: fontSize.body,
    marginTop: spacing.xs,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  label: {
    color: colors.greenDark,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.bold,
    marginTop: spacing.md,
    textTransform: "uppercase",
  },
  listContent: {
    flexGrow: 1,
    paddingBottom: spacing.xl,
    paddingHorizontal: spacing.md,
  },
  logAudience: {
    color: colors.greenDark,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.bold,
  },
  logHead: {
    flex: 1,
    marginLeft: spacing.sm,
  },
  logIcon: {
    alignItems: "center",
    backgroundColor: colors.tint,
    borderRadius: radius.full,
    height: 34,
    justifyContent: "center",
    width: 34,
  },
  logItem: {
    backgroundColor: colors.card,
    borderRadius: radius.lg,
    elevation: 2,
    marginBottom: spacing.sm,
    padding: spacing.md,
    shadowColor: colors.greenDark,
    shadowOffset: { height: 1, width: 0 },
    shadowOpacity: 0.08,
    shadowRadius: 6,
  },
  logMessage: {
    color: colors.text,
    fontSize: fontSize.body,
    lineHeight: 21,
    marginTop: spacing.sm,
  },
  logMeta: {
    color: colors.muted,
    fontSize: fontSize.caption,
    marginTop: 1,
  },
  logTitle: {
    color: colors.greenDark,
    fontSize: fontSize.subheading,
    fontWeight: fontWeight.bold,
    marginBottom: spacing.sm,
    marginTop: spacing.lg,
  },
  logTop: {
    alignItems: "center",
    flexDirection: "row",
  },
  messageInput: {
    minHeight: 110,
  },
  messageLabelRow: {
    alignItems: "center",
    flexDirection: "row",
    justifyContent: "space-between",
  },
  note: {
    color: colors.green,
    flex: 1,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.semibold,
    marginLeft: spacing.xs,
  },
  noteBox: {
    alignItems: "center",
    backgroundColor: colors.emeraldSoft,
    borderRadius: radius.md,
    flexDirection: "row",
    marginTop: spacing.sm,
    padding: spacing.sm,
  },
  pressed: {
    opacity: 0.85,
    transform: [{ scale: 0.96 }],
  },
  root: {
    backgroundColor: colors.background,
    flex: 1,
  },
  sendWrap: {
    marginTop: spacing.md,
  },
});
