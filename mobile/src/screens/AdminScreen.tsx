import { Ionicons } from "@expo/vector-icons";
import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import {
  ApiError,
  fetchGates,
  type Gate,
} from "../api/client";
import {
  getSettings,
  updateSettings,
  type ConvocationSettings,
} from "../api/settingsApi";
import { PrimaryButton } from "../components/PrimaryButton";
import { SectionCard } from "../components/SectionCard";
import {
  DEFAULT_API_BASE_URL,
  getApiBaseUrl,
  getVolunteerName,
  isValidBaseUrl,
  setApiBaseUrl,
  setVolunteerName,
} from "../store/settings";
import { colors, fontSize, fontWeight, radius, spacing } from "../theme";

const CONNECT_TIMEOUT_MS = 10000;

function splitDatetime(datetime: string): { date: string; time: string } {
  const match = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})/.exec(datetime);
  if (match) {
    return { date: match[1], time: match[2] };
  }
  return { date: "", time: "" };
}

export function AdminScreen() {
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [convocationName, setConvocationName] = useState("");
  const [year, setYear] = useState("");
  const [date, setDate] = useState("");
  const [time, setTime] = useState("");
  const [venue, setVenue] = useState("");
  const [saving, setSaving] = useState(false);
  const [savedNote, setSavedNote] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const [volunteer, setVolunteer] = useState("");
  const [volunteerSaved, setVolunteerSaved] = useState(false);

  const [baseUrl, setBaseUrl] = useState(DEFAULT_API_BASE_URL);
  const [urlError, setUrlError] = useState<string | null>(null);
  const [urlSaved, setUrlSaved] = useState(false);
  const [testing, setTesting] = useState(false);
  const [reachability, setReachability] = useState<string | null>(null);
  const [reachable, setReachable] = useState(false);

  const [gates, setGates] = useState<Gate[]>([]);

  const load = () => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    void (async () => {
      try {
        const [settings, storedUrl, storedVolunteer] = await Promise.all([
          getSettings(),
          getApiBaseUrl(),
          getVolunteerName(),
        ]);
        if (cancelled) return;
        const split = splitDatetime(settings.convocation_datetime ?? "");
        setConvocationName(settings.convocation_name ?? "");
        setYear(settings.convocation_year ?? "");
        setDate(split.date);
        setTime(split.time);
        setVenue(settings.venue ?? "");
        setBaseUrl(storedUrl);
        setVolunteer(storedVolunteer);
        try {
          const loadedGates = await fetchGates();
          if (!cancelled) setGates(loadedGates);
        } catch {
          if (!cancelled) setGates([]);
        }
      } catch (e) {
        if (!cancelled) {
          setLoadError(
            e instanceof ApiError
              ? `Could not load settings: ${e.message}`
              : "Could not load settings.",
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  };

  useEffect(() => load(), []);

  const saveSettings = async () => {
    setFormError(null);
    setSavedNote(null);
    if (!convocationName.trim()) {
      setFormError("Enter the convocation name.");
      return;
    }
    if (!/^\d{4}$/.test(year.trim())) {
      setFormError("Enter the year as 4 digits, for example 2026.");
      return;
    }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date.trim())) {
      setFormError("Enter the date as YYYY-MM-DD, for example 2026-12-12.");
      return;
    }
    if (!/^\d{2}:\d{2}$/.test(time.trim())) {
      setFormError("Enter the time as HH:MM, for example 09:00.");
      return;
    }
    if (!venue.trim()) {
      setFormError("Enter the venue.");
      return;
    }
    setSaving(true);
    try {
      const patch: Partial<ConvocationSettings> = {
        convocation_name: convocationName.trim(),
        convocation_year: year.trim(),
        convocation_datetime: `${date.trim()}T${time.trim()}:00+05:00`,
        venue: venue.trim(),
      };
      const updated = await updateSettings(patch);
      const split = splitDatetime(updated.convocation_datetime ?? "");
      setConvocationName(updated.convocation_name ?? "");
      setYear(updated.convocation_year ?? "");
      setDate(split.date);
      setTime(split.time);
      setVenue(updated.venue ?? "");
      setSavedNote("Saved. The new convocation details are live.");
    } catch (e) {
      setFormError(
        e instanceof ApiError
          ? `Could not save: ${e.message}`
          : "Could not save the settings.",
      );
    } finally {
      setSaving(false);
    }
  };

  const saveVolunteer = async () => {
    await setVolunteerName(volunteer);
    setVolunteerSaved(true);
    setTimeout(() => setVolunteerSaved(false), 2500);
  };

  const saveUrl = async () => {
    if (!isValidBaseUrl(baseUrl)) {
      setUrlError("Enter a valid URL, for example http://192.168.1.10:5000");
      return;
    }
    setUrlError(null);
    await setApiBaseUrl(baseUrl);
    setUrlSaved(true);
    setTimeout(() => setUrlSaved(false), 2500);
  };

  const testConnection = async () => {
    setTesting(true);
    setReachability(null);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), CONNECT_TIMEOUT_MS);
    try {
      const response = await fetch(`${baseUrl.trim()}/api/gates`, {
        signal: controller.signal,
      });
      clearTimeout(timer);
      if (!response.ok) {
        setReachable(false);
        setReachability(`Not reachable: server returned ${response.status}.`);
        return;
      }
      const body = (await response.json()) as { gates?: Gate[] };
      const count = Array.isArray(body.gates) ? body.gates.length : 0;
      setReachable(true);
      setReachability(`Reachable. ${count} gate(s) found.`);
    } catch {
      clearTimeout(timer);
      setReachable(false);
      setReachability("Not reachable. Check the URL and server.");
    } finally {
      setTesting(false);
    }
  };

  if (loading) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator size="large" color={colors.green} />
        <Text style={styles.loadingText}>Loading admin settings...</Text>
      </View>
    );
  }

  if (loadError) {
    return (
      <View style={styles.centered}>
        <Ionicons name="alert-circle" size={40} color={colors.red} />
        <Text style={styles.errorText}>{loadError}</Text>
        <Text style={styles.errorHint}>
          If this is a fresh install, set the backend URL in the Settings tab
          first, then retry.
        </Text>
        <PrimaryButton
          title="Retry"
          onPress={() => load()}
          variant="outline"
          style={styles.retryButton}
        />
      </View>
    );
  }

  return (
    <ScrollView style={styles.root}>
      <SectionCard
        title="Convocation Details"
        subtitle="Shown on the Live Board and ID cards"
      >
        <Text style={styles.label}>Convocation name</Text>
        <TextInput
          style={styles.input}
          value={convocationName}
          onChangeText={setConvocationName}
          placeholder="LGU Convocation"
          placeholderTextColor={colors.muted}
        />
        <Text style={styles.label}>Year</Text>
        <TextInput
          style={styles.input}
          value={year}
          onChangeText={setYear}
          placeholder="2026"
          placeholderTextColor={colors.muted}
          keyboardType="numeric"
          maxLength={4}
        />
        <View style={styles.row}>
          <View style={styles.flex}>
            <Text style={styles.label}>Date</Text>
            <TextInput
              style={styles.input}
              value={date}
              onChangeText={setDate}
              placeholder="2026-12-12"
              placeholderTextColor={colors.muted}
              autoCapitalize="none"
              autoCorrect={false}
            />
          </View>
          <View style={styles.flex}>
            <Text style={styles.label}>Time</Text>
            <TextInput
              style={styles.input}
              value={time}
              onChangeText={setTime}
              placeholder="09:00"
              placeholderTextColor={colors.muted}
              autoCapitalize="none"
              autoCorrect={false}
            />
          </View>
        </View>
        <Text style={styles.label}>Venue</Text>
        <TextInput
          style={styles.input}
          value={venue}
          onChangeText={setVenue}
          placeholder="Main Hall"
          placeholderTextColor={colors.muted}
        />
        {formError && <Text style={styles.error}>{formError}</Text>}
        <PrimaryButton
          title="Save convocation details"
          onPress={() => void saveSettings()}
          loading={saving}
          style={styles.topMargin}
        />
        {savedNote && (
          <View style={styles.savedBox}>
            <Ionicons name="checkmark-circle" size={18} color={colors.green} />
            <Text style={styles.saved}>{savedNote}</Text>
          </View>
        )}
      </SectionCard>

      <SectionCard title="Volunteer" subtitle="Shown on every scan you make">
        <Text style={styles.label}>Volunteer name</Text>
        <TextInput
          style={styles.input}
          value={volunteer}
          onChangeText={setVolunteer}
          placeholder="Your name as shown on scans"
          placeholderTextColor={colors.muted}
          autoCapitalize="words"
        />
        <PrimaryButton
          title="Save name"
          onPress={() => void saveVolunteer()}
          style={styles.topMargin}
        />
        {volunteerSaved && (
          <View style={styles.savedBox}>
            <Ionicons name="checkmark-circle" size={18} color={colors.green} />
            <Text style={styles.saved}>Volunteer name saved.</Text>
          </View>
        )}
      </SectionCard>

      <SectionCard
        title="Backend Connection"
        subtitle="Where this app sends its scans"
      >
        <Text style={styles.label}>API base URL</Text>
        <TextInput
          style={styles.input}
          value={baseUrl}
          onChangeText={setBaseUrl}
          placeholder={DEFAULT_API_BASE_URL}
          placeholderTextColor={colors.muted}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
        />
        {urlError && <Text style={styles.error}>{urlError}</Text>}
        <View style={styles.buttonRow}>
          <PrimaryButton
            title="Save URL"
            onPress={() => void saveUrl()}
            style={styles.flexButton}
          />
          <PrimaryButton
            title="Test connection"
            onPress={() => void testConnection()}
            loading={testing}
            variant="outline"
            style={styles.flexButton}
          />
        </View>
        {urlSaved && (
          <View style={styles.savedBox}>
            <Ionicons name="checkmark-circle" size={18} color={colors.green} />
            <Text style={styles.saved}>API base URL saved.</Text>
          </View>
        )}
        {reachability && (
          <View
            style={[
              styles.healthBox,
              reachable ? styles.healthOk : styles.healthBad,
            ]}
          >
            <Ionicons
              name={reachable ? "checkmark-circle" : "alert-circle"}
              size={18}
              color={reachable ? colors.green : colors.red}
            />
            <Text
              style={[
                styles.healthText,
                { color: reachable ? colors.green : colors.red },
              ]}
            >
              {reachability}
            </Text>
          </View>
        )}
      </SectionCard>

      <SectionCard title="Gates" subtitle="Read only, managed by the server">
        {gates.length === 0 ? (
          <Text style={styles.mutedText}>No gates found on the server.</Text>
        ) : (
          gates.map((gate) => (
            <View key={gate.id} style={styles.gateRow}>
              <Ionicons name="location" size={18} color={colors.green} />
              <View style={styles.gateText}>
                <Text style={styles.gateName}>{gate.label}</Text>
                <Text style={styles.gateId}>
                  Gate #{gate.id} ({gate.code})
                </Text>
              </View>
            </View>
          ))
        )}
      </SectionCard>

      <View style={styles.bottomPad} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  bottomPad: {
    height: spacing.xl,
  },
  buttonRow: {
    flexDirection: "row",
    gap: spacing.sm,
    marginTop: spacing.md,
  },
  centered: {
    alignItems: "center",
    backgroundColor: colors.background,
    flex: 1,
    gap: spacing.sm,
    justifyContent: "center",
    padding: spacing.lg,
  },
  error: {
    color: colors.red,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.semibold,
    marginTop: spacing.xs,
  },
  errorText: {
    color: colors.red,
    fontSize: fontSize.body,
    textAlign: "center",
  },
  errorHint: {
    color: colors.muted,
    fontSize: fontSize.caption,
    marginTop: spacing.sm,
    textAlign: "center",
  },
  retryButton: {
    marginTop: spacing.md,
    minWidth: 160,
  },
  flex: {
    flex: 1,
  },
  flexButton: {
    flex: 1,
  },
  gateId: {
    color: colors.muted,
    fontSize: fontSize.caption,
  },
  gateName: {
    color: colors.text,
    fontSize: fontSize.body,
    fontWeight: fontWeight.semibold,
  },
  gateRow: {
    alignItems: "center",
    borderBottomColor: colors.border,
    borderBottomWidth: 1,
    flexDirection: "row",
    gap: spacing.sm,
    paddingVertical: spacing.sm,
  },
  gateText: {
    flex: 1,
  },
  healthBad: {
    backgroundColor: colors.redSoft,
  },
  healthBox: {
    alignItems: "center",
    borderRadius: radius.md,
    flexDirection: "row",
    gap: spacing.xs,
    marginTop: spacing.sm,
    padding: spacing.sm,
  },
  healthOk: {
    backgroundColor: colors.emeraldSoft,
  },
  healthText: {
    flex: 1,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.semibold,
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
    marginTop: spacing.sm,
    textTransform: "uppercase",
  },
  loadingText: {
    color: colors.muted,
    fontSize: fontSize.body,
  },
  mutedText: {
    color: colors.muted,
    fontSize: fontSize.body,
  },
  root: {
    backgroundColor: colors.background,
    flex: 1,
  },
  row: {
    flexDirection: "row",
    gap: spacing.sm,
  },
  saved: {
    color: colors.green,
    flex: 1,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.semibold,
    marginLeft: spacing.xs,
  },
  savedBox: {
    alignItems: "center",
    backgroundColor: colors.emeraldSoft,
    borderRadius: radius.md,
    flexDirection: "row",
    marginTop: spacing.sm,
    padding: spacing.sm,
  },
  topMargin: {
    marginTop: spacing.md,
  },
});
