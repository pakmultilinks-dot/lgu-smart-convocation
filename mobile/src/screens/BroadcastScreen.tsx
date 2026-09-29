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

function LogItem({ entry }: { entry: BroadcastEntry }) {
  return (
    <View style={styles.logItem}>
      <Text style={styles.logMessage}>{entry.message}</Text>
      <Text style={styles.logMeta}>
        {entry.audience} · {entry.sent_by} · {entry.sent_at}
      </Text>
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
        />
      }
      ListHeaderComponent={
        <View>
          <SectionCard title="New Broadcast">
            <Text style={styles.label}>Audience</Text>
            <View style={styles.audienceRow}>
              {audiences.map((option) => {
                const active = option === audience;
                return (
                  <Pressable
                    key={option}
                    onPress={() => setAudience(option)}
                    style={[
                      styles.audienceChip,
                      active && styles.audienceChipActive,
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

            <Text style={styles.label}>Message</Text>
            <TextInput
              style={[styles.input, styles.messageInput]}
              value={message}
              onChangeText={setMessage}
              placeholder="Type the announcement for the convocation..."
              multiline
              numberOfLines={4}
              textAlignVertical="top"
            />

            {formError && <Text style={styles.formError}>{formError}</Text>}
            {note && <Text style={styles.note}>{note}</Text>}

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
    backgroundColor: colors.background,
    borderColor: colors.border,
    borderRadius: radius.full,
    borderWidth: 1,
    marginBottom: spacing.sm,
    marginRight: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  audienceChipActive: {
    backgroundColor: colors.navy,
    borderColor: colors.navy,
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
    color: colors.navy,
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
  logItem: {
    backgroundColor: colors.card,
    borderRadius: radius.md,
    elevation: 1,
    marginBottom: spacing.sm,
    padding: spacing.md,
    shadowColor: "#0B2447",
    shadowOffset: { height: 1, width: 0 },
    shadowOpacity: 0.06,
    shadowRadius: 3,
  },
  logMessage: {
    color: colors.text,
    fontSize: fontSize.body,
  },
  logMeta: {
    color: colors.muted,
    fontSize: fontSize.caption,
    marginTop: spacing.xs,
  },
  logTitle: {
    color: colors.navy,
    fontSize: fontSize.subheading,
    fontWeight: fontWeight.bold,
    marginBottom: spacing.sm,
    marginTop: spacing.lg,
  },
  messageInput: {
    minHeight: 110,
  },
  note: {
    backgroundColor: colors.amberSoft,
    borderRadius: radius.sm,
    color: colors.amber,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.semibold,
    marginTop: spacing.sm,
    padding: spacing.sm,
  },
  root: {
    backgroundColor: colors.background,
    flex: 1,
  },
  sendWrap: {
    marginTop: spacing.md,
  },
});
