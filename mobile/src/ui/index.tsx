// Shared university UI: cool backgrounds, white groups, green actions.
// Status always carries text; color reinforces meaning.

import { useContext, type ReactNode } from "react";
import { BottomTabBarHeightContext } from "expo-router/js-tabs";
import {
  ActivityIndicator,
  Image,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
  type StyleProp,
  type TextInputProps,
  type TextStyle,
  type ViewStyle,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { StatusBar } from "expo-status-bar";
import { Ionicons } from "@expo/vector-icons";
import {
  colors,
  fonts,
  fontSize,
  radius,
  spacing,
  text,
} from "../theme";
import { safePercent } from "../utils/progress";

// ------------------------------------------------------------------ Screen

export function Screen({
  children,
  dark = false,
  scroll = true,
  stickyHeader = false,
  statusBar,
  style,
}: {
  children: ReactNode;
  /** Ink field behind the content (Launch, Mode Picker brand moments). */
  dark?: boolean;
  scroll?: boolean;
  /** Phase 33 (§4): stick the FIRST scroll child (the AppHeader) to the
      top so page context stays reachable while a long screen scrolls.
      Opt-in — every other screen is unchanged. */
  stickyHeader?: boolean;
  /** Status-bar icon style. Defaults from `dark`. */
  statusBar?: "light" | "dark";
  style?: StyleProp<ViewStyle>;
}) {
  // Tabs already reserve the device's bottom inset; applying it twice
  // creates an unusable strip above the tab bar on Android.
  const tabHeight = useContext(BottomTabBarHeightContext);
  const body = scroll ? (
    <ScrollView
      // 35M R3: explicit flex — the scroll container always has a bounded
      // height, so every screen scrolls vertically whenever content
      // exceeds the viewport instead of clipping (no reliance on content
      // fitting; web and native behave the same).
      style={styles.flex1}
      contentContainerStyle={styles.screenScroll}
      keyboardShouldPersistTaps="handled"
      stickyHeaderIndices={stickyHeader ? [0] : undefined}
      // 24A5: when a field (e.g. the phone input low on the Profile screen)
      // takes focus, the scroll inset follows the keyboard so the field is
      // never covered — the OS resizes the view, we just track it. Android's
      // default `resize` window mode handles its side; this covers iOS.
      automaticallyAdjustKeyboardInsets
      showsVerticalScrollIndicator={false}
    >
      {children}
    </ScrollView>
  ) : (
    <View style={[styles.screenScroll, styles.screenFixed, styles.flex1]}>{children}</View>
  );
  return (
    <SafeAreaView
      style={[styles.screen, dark ? styles.screenDark : styles.screenLight, style]}
      edges={tabHeight ? ["top", "left", "right"] : ["top", "left", "right", "bottom"]}
    >
      {/* One status-bar system: dark icons on paper, light on ink. */}
      <StatusBar style={statusBar ?? (dark ? "light" : "dark")} />
      {body}
    </SafeAreaView>
  );
}

// ----------------------------------------------------------------- Header

export function AppHeader({
  eyebrow,
  eyebrowSans = false,
  title,
  titleSize,
  subtitle,
  right,
  dark = false,
  crest = false,
  onBack,
  onCrestPress,
  onCrestLongPress,
  crestHoldMs = 3000,
}: {
  eyebrow?: string;
  /** 35M R2 (item 12): render the eyebrow in the sans/display family
      (displayMedium 13) instead of DM Mono — Home's "Volunteer
      Operations" is the only screen that opts in. */
  eyebrowSans?: boolean;
  title: string;
  subtitle?: string;
  right?: ReactNode;
  dark?: boolean;
  crest?: boolean;
  /** Pushed admin routes (Phase 35G): a visible in-screen back action on
      the light header. Screens without onBack are unchanged. */
  onBack?: () => void;
  /** Public displays (Phase 35F fix): a short press on the crest — the
      screen decides single- vs double-tap semantics. Without a press or
      long-press prop the crest is inert decoration — no control. */
  onCrestPress?: () => void;
  /** Public displays: a hold on the crest (default ~3s; screens pass
      crestHoldMs) arms the protected exit. */
  onCrestLongPress?: () => void;
  /** Crest long-press delay in ms (Phase 35H). Default 3000; the live
      dashboard passes 2000 for a faster protected exit. */
  crestHoldMs?: number;
  /** 35M item 2: per-screen title size override — a long configured
      title wraps balanced at 20pt without shrinking the shared default. */
  titleSize?: number;
}) {
  return (
    <View style={styles.header}>
      {/* Phase 35I (Z): the back action is its own full-width zone ABOVE
          the title — never visually merged with the heading. */}
      {onBack ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Back"
          onPress={onBack}
          hitSlop={8}
          style={({ pressed }) => [styles.backPressable, pressed && styles.crestPressed]}
        >
          <Ionicons
            name="chevron-back"
            size={24}
            color={dark ? colors.paper : colors.ink}
          />
          <Text style={[styles.backLabel, dark && styles.textOnDark]}>Back</Text>
        </Pressable>
      ) : null}
      <View style={styles.headerMain}>
        {/* Left zone: eyebrow/title/subtitle. flex:1 + minWidth:0 lets the
            text shrink and wrap INSIDE its own zone (Phase 35A bugs 6 + 10). */}
        <View style={styles.headerLeft}>
          {eyebrow ? (
            <Text
              style={[
                eyebrowSans ? styles.eyebrowSans : text.label,
                dark && styles.textOnDark,
              ]}
            >
              {eyebrow}
            </Text>
          ) : null}
          <View style={styles.headerTitleRow}>
            {crest ? (
              onCrestPress || onCrestLongPress ? (
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="Tap or hold to exit the live dashboard"
                  delayLongPress={crestHoldMs}
                  onPress={onCrestPress}
                  onLongPress={onCrestLongPress}
                  hitSlop={8}
                  style={({ pressed }) => [
                    styles.crestPressable,
                    pressed && styles.crestPressed,
                  ]}
                >
                  <LguMark size={42} dark={dark} />
                </Pressable>
              ) : (
                <LguMark size={42} dark={dark} />
              )
            ) : null}
            <Text
              style={[
                styles.headerTitle,
                titleSize ? { fontSize: titleSize, letterSpacing: -0.5 } : null,
                dark && styles.textOnDark,
              ]}
              numberOfLines={2}
            >
              {title}
            </Text>
          </View>
          {subtitle ? (
            <Text style={[styles.headerSubtitle, dark && styles.textMutedOnDark]} numberOfLines={2}>
              {subtitle}
            </Text>
          ) : null}
        </View>
        {right ? <View style={styles.headerRight}>{right}</View> : null}
      </View>
    </View>
  );
}

/** Crest mark — the verified transparent 444px LGU seal, directly on paper. */
const LGU_LOGO = require("../../assets/lgu-logo.png");
export function LguMark({ size = 36, dark = false }: { size?: number; dark?: boolean }) {
  return (
    <Image
      source={LGU_LOGO}
      accessibilityLabel="Lahore Garrison University seal"
      style={{ width: size, height: size, opacity: dark ? 0.92 : 1 }}
      resizeMode="contain"
    />
  );
}

// --------------------------------------------------------------- Eyebrow

/** Phase 35I (X): a bold sans section title — no trailing rule, no
    all-caps mono. Sections read as clear, calm headings. */
export function SectionEyebrow({
  children,
  dark = false,
  style,
}: {
  children: ReactNode;
  dark?: boolean;
  style?: StyleProp<TextStyle>;
}) {
  return (
    <Text style={[styles.eyebrowText, dark && styles.textOnDark, style]}>{children}</Text>
  );
}

// ---------------------------------------------------------- Metric block

export function MetricBlock({
  eyebrow,
  value,
  caption,
  dark = false,
  tone = "ink",
  align,
}: {
  eyebrow?: string;
  value: string;
  caption?: string;
  dark?: boolean;
  tone?: "ink" | "brand" | "onDark";
  align?: "flex-start" | "center" | "flex-end";
}) {
  const valueColor =
    tone === "onDark" || dark ? colors.paper : colors.ink;
  return (
    <View style={[align ? { alignItems: align } : null]}>
      {eyebrow ? (
        <Text style={[text.label, dark && styles.textOnDark]}>{eyebrow}</Text>
      ) : null}
      <Text
        style={[
          styles.metric,
          { color: valueColor },
          align === "center" && styles.textCenter,
        ]}
      >
        {value}
      </Text>
      {caption ? (
        <Text style={[text.helper, dark && styles.textMutedOnDark, styles.metricCaption]}>
          {caption}
        </Text>
      ) : null}
    </View>
  );
}

// ------------------------------------------------------------- StatusPill

export type PillState =
  | "live"
  | "stale"
  | "offline"
  | "connecting"
  | "queued"
  | "accept"
  | "duplicate"
  | "invalid"
  | "nodata"
  | "info";

/** Dot color reinforces; the label always carries the meaning. */
const PILL_DOT: Record<PillState, string> = {
  live: colors.valid,
  stale: colors.amber,
  offline: colors.amber,
  connecting: colors.muted,
  queued: colors.ink,
  accept: colors.valid,
  duplicate: colors.amber,
  invalid: colors.invalid,
  nodata: colors.muted,
  info: colors.ink,
};

export function StatusPill({
  state,
  label,
  size = "md",
}: {
  state: PillState;
  label: string;
  size?: "md" | "sm";
}) {
  return (
    <View style={[styles.pill, size === "sm" && styles.pillSm]}>
      <View style={[styles.pillDot, { backgroundColor: PILL_DOT[state] }]} />
      <Text
        style={[text.labelMedium, styles.pillLabel, size === "sm" && styles.pillTextSm]}
        numberOfLines={1}
      >
        {label}
      </Text>
    </View>
  );
}

// ------------------------------------------------------- SegmentedControl

export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  activeColor,
}: {
  options: { label: string; value: T }[];
  value: T;
  onChange: (value: T) => void;
  /** QA fix cycle 4 (Finding 2): optional semantic fill for the selected
      segment (Entry = green success, Exit = amber contrast). Defaults to
      the neutral ink fill so every other caller is unchanged. The label
      stays paper for contrast on any provided accent. */
  activeColor?: string;
}) {
  return (
    <View style={styles.segment}>
      {options.map((option) => {
        const active = option.value === value;
        return (
          <Pressable
            key={option.value}
            accessibilityRole="button"
            accessibilityState={{ selected: active }}
            accessibilityLabel={option.label}
            onPress={() => onChange(option.value)}
            style={[
              styles.segmentItem,
              active && styles.segmentItemActive,
              active && activeColor ? { backgroundColor: activeColor } : null,
            ]}
          >
            <Text numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.8} style={[styles.segmentLabel, active && styles.segmentLabelActive]}>
              {option.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

// -------------------------------------------------------------- AppButton

const BUTTON_VARIANTS = {
  primary: { bg: colors.ink, fg: colors.paper, border: colors.ink },
  secondary: { bg: "transparent", fg: colors.ink, border: colors.ink },
  ghost: { bg: "transparent", fg: colors.ink, border: "transparent" },
  danger: { bg: "transparent", fg: colors.invalid, border: colors.invalid },
} as const;

export function AppButton({
  label,
  onPress,
  variant = "primary",
  icon,
  disabled = false,
  loading = false,
  size = "md",
  style,
}: {
  label: string;
  onPress: () => void;
  variant?: "primary" | "secondary" | "ghost" | "danger";
  icon?: keyof typeof Ionicons.glyphMap;
  disabled?: boolean;
  loading?: boolean;
  size?: "md" | "lg";
  style?: StyleProp<ViewStyle>;
}) {
  const v = BUTTON_VARIANTS[variant];
  const inactive = disabled || loading;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ disabled: inactive }}
      disabled={inactive}
      onPress={onPress}
      style={({ pressed }) => [
        styles.btn,
        size === "lg" && styles.btnLg,
        // Phase 35I (V): disabled/loading = pale track fill, no strong
        // border — visibly quiet, never low-contrast ink-on-ink.
        {
          backgroundColor: inactive ? colors.track : v.bg,
          borderColor: inactive ? colors.track : v.border,
        },
        pressed && styles.btnPressed,
        style,
      ]}
    >
      {loading ? (
        <ActivityIndicator size="small" color={inactive ? colors.muted : v.fg} />
      ) : icon ? (
        <Ionicons name={icon} size={18} color={inactive ? colors.muted : v.fg} />
      ) : null}
      <Text style={[styles.btnLabel, { color: inactive ? colors.muted : v.fg }]}>
        {label}
      </Text>
    </Pressable>
  );
}

// ------------------------------------------------------------------ Field

export function Field({
  label,
  hint,
  error,
  style,
  ...inputProps
}: TextInputProps & {
  /** Phase 35I (T.6): optional — rendered only when provided (a field whose
      placeholder already identifies it does not need a redundant label). */
  label?: string;
  hint?: string;
  error?: string | null;
  style?: StyleProp<ViewStyle>;
}) {
  return (
    <View style={[styles.fieldWrap, style]}>
      {label ? <Text style={styles.fieldLabel}>{label}</Text> : null}
      <TextInput
          accessibilityLabel={label}
        placeholderTextColor={colors.muted}
        {...inputProps}
        style={[styles.input, !!error && styles.inputError]}
      />
      {error ? <Text style={styles.fieldError}>{error}</Text> : null}
      {hint && !error ? <Text style={styles.fieldHint}>{hint}</Text> : null}
    </View>
  );
}

// ---------------------------------------------------------------- ListRow

export function ListRow({
  title,
  subtitle,
  trailing,
  onPress,
  tone = "default",
}: {
  title: string;
  subtitle?: string;
  trailing?: ReactNode;
  onPress?: () => void;
  tone?: "default" | "brand" | "danger";
}) {
  const titleColor =
    tone === "brand" ? colors.ink : tone === "danger" ? colors.invalid : colors.ink;
  const content = (
    <View style={styles.row}>
      <View style={styles.flex1}>
        {/* Names and important text wrap — never ellipsised (bug 9). */}
        <Text style={[styles.rowTitle, { color: titleColor }]}>{title}</Text>
        {subtitle ? <Text style={styles.rowSubtitle}>{subtitle}</Text> : null}
      </View>
      {trailing ?? (onPress ? (
        <Ionicons name="chevron-forward" size={18} color={colors.muted} />
      ) : null)}
    </View>
  );
  if (onPress) {
    return (
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={title}
        onPress={onPress}
        style={({ pressed }) => [pressed && styles.rowPressed]}
      >
        {content}
      </Pressable>
    );
  }
  return content;
}

// ------------------------------------------------------------ SectionCard

/**
 * Borderless section — the card stack is gone. Sections sit directly on the
 * paper, separated by whitespace and a thin/dashed rule. tone="tint" keeps a
 * quiet dashed top rule; tone="dark" is the single ink field (Launch moments).
 */
export function SectionCard({
  children,
  tone = "card",
  pad = true,
  style,
}: {
  children: ReactNode;
  tone?: "card" | "tint" | "dark";
  pad?: boolean;
  style?: StyleProp<ViewStyle>;
}) {
  return (
    <View
      style={[
        styles.sectionCard,
        tone === "tint" && styles.sectionCardTint,
        tone === "dark" && styles.sectionCardDark,
        pad && styles.sectionPad,
        style,
      ]}
    >
      {children}
    </View>
  );
}

// --------------------------------------------------------- Progress track

export function ProgressTrack({
  pct,
  value,
  max,
  tone = "brand",
  height = 6,
  fillColor,
  trackColor,
}: {
  /** Pre-computed 0..100 percent (clamped; NaN-safe). Prefer value/max. */
  pct?: number;
  /** Raw value + max — fill width = value / max via the shared safe math
      (Phase 35A bugs 1 + 2: 0 means empty; max<=0 → empty, never NaN). */
  value?: number;
  max?: number;
  tone?: "brand" | "mint";
  height?: number;
  /** Fill override — e.g. paper fill on an ink-selected row. */
  fillColor?: string;
  /** Track background override (Phase 35I J: on tinted sections the default
      paper track is invisible — pass a darker track there). */
  trackColor?: string;
}) {
  void tone; // legacy prop — ink fill for every on-palette tone
  const clamped =
    value !== undefined && max !== undefined
      ? safePercent(value, max)
      : safePercent(pct ?? 0, 100);
  const trackStyle = { height, backgroundColor: trackColor ?? colors.track };
  // At 0 (or invalid input) the track renders EMPTY — no fill element at
  // all, so "full at 0" is structurally impossible.
  if (clamped <= 0) {
    return <View style={[styles.track, trackStyle]} />;
  }
  return (
    <View style={[styles.track, trackStyle]}>
      <View
        style={[
          styles.trackFill,
          { width: `${clamped}%`, height, backgroundColor: fillColor ?? colors.ink },
        ]}
      />
    </View>
  );
}

// -------------------------------------------------------- Empty / Error

export function EmptyState({
  icon = "file-tray-outline",
  title,
  body,
  actionLabel,
  onAction,
}: {
  icon?: keyof typeof Ionicons.glyphMap;
  title: string;
  body: string;
  actionLabel?: string;
  onAction?: () => void;
}) {
  return (
    <View style={styles.stateWrap}>
      <Ionicons name={icon} size={22} color={colors.muted} />
      <Text style={styles.stateTitle}>{title}</Text>
      <Text style={styles.stateBody}>{body}</Text>
      {actionLabel && onAction ? (
        <AppButton label={actionLabel} onPress={onAction} variant="secondary" style={styles.stateAction} />
      ) : null}
    </View>
  );
}

export function ErrorState({
  title,
  body,
  onRetry,
}: {
  title: string;
  body: string;
  onRetry?: () => void;
}) {
  return (
    <View style={styles.stateWrap}>
      <Ionicons name="alert-circle-outline" size={22} color={colors.invalid} />
      <Text style={styles.stateTitle}>{title}</Text>
      <Text style={styles.stateBody}>{body}</Text>
      {onRetry ? (
        <AppButton label="Retry" onPress={onRetry} icon="refresh" style={styles.stateAction} />
      ) : null}
    </View>
  );
}

export function LoadingState({ label = "Loading..." }: { label?: string }) {
  return (
    <View style={styles.stateWrap}>
      <ActivityIndicator size="large" color={colors.ink} />
      <Text style={styles.stateBody}>{label}</Text>
    </View>
  );
}

// --------------------------------------------------------- Offline banner

export function OfflineBanner({
  lastSyncedAt,
  onRetry,
  title = "Offline mode",
  body,
}: {
  lastSyncedAt: number | null;
  /** Optional self-recovery action (volunteer surfaces pass it). Public
      displays omit it — the board's poll loop reconnects on its own
      (Phase 35F: no operator controls on the public dashboard). */
  onRetry?: () => void;
  title?: string;
  body?: string;
}) {
  return (
    <View style={styles.offlineBanner}>
      <View style={[styles.pillDot, { backgroundColor: colors.amber }]} />
      <View style={styles.flex1}>
        <Text style={styles.offlineTitle}>{title}</Text>
        <Text style={styles.offlineBody}>
          {body ??
            `Local scans remain available${
              lastSyncedAt ? ` · Last synchronized ${formatClock(lastSyncedAt)}` : ""
            }`}
        </Text>
      </View>
      {onRetry ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Retry connection"
          onPress={onRetry}
          style={({ pressed }) => [styles.offlineRetry, pressed && styles.btnPressed]}
        >
          <Text style={styles.offlineRetryText}>Retry</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

/** Phase 35I (Y): 12-hour local clock for status surfaces. */
export function formatClock(ms: number): string {
  return new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/** Server timestamps arrive as "YYYY-MM-DD HH:MM:SS" (Asia/Karachi). Phase
    35I (Y): rendered in the viewer's own local 12-hour time — parsed as
    Karachi wall-clock (UTC+5) so volunteer history reads correctly on any
    device. Both exported clock helpers share this single implementation. */
export function formatServerClock(ts: string | null | undefined): string {
  if (!ts) return "";
  const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(ts);
  if (!m) return ts;
  const utc = Date.UTC(
    Number(m[1]),
    Number(m[2]) - 1,
    Number(m[3]),
    Number(m[4]) - 5, // stored wall-clock is Asia/Karachi (UTC+5)
    Number(m[5]),
  );
  const date = new Date(utc);
  if (Number.isNaN(date.getTime())) return ts;
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/** Local wall-clock for server timestamps (Phase 35H). Alias of
    formatServerClock — one 12-hour implementation everywhere (35I Y). */
export function formatLocalClock(ts: string | null | undefined): string {
  return formatServerClock(ts);
}

/**
 * Freshness of a polling display.
 * Phase 35I (L): pass offlineMs to delay the OFFLINE verdict (default 0
 * keeps the original immediate behavior).
 * 33-QA (I16): an explicitly failed refresh never reads as live. The age
 * of the last success alone used to keep the green state for the whole
 * stale window while every request was failing; a failure now surfaces
 * as STALE immediately and reaches OFFLINE once offlineMs elapses.
 */
export function freshnessState(
  online: boolean | null,
  lastOkAt: number,
  now: number,
  staleMs: number,
  offlineMs = 0,
): "live" | "stale" | "offline" | "connecting" {
  if (online === null) return "connecting";
  // 33-QA (I16): a failed refresh must never read as live — even while
  // the last success is recent. The offlineMs grace still delays only
  // the OFFLINE verdict; STALE covers the gap truthfully.
  if (online === false && lastOkAt > 0) {
    const age = now - lastOkAt;
    return offlineMs > 0 && age < offlineMs ? "stale" : "offline";
  }
  if (lastOkAt > 0) {
    const age = now - lastOkAt;
    if (age < staleMs) return "live";
    if (offlineMs > 0 && age < offlineMs) return "stale";
    return offlineMs > 0 ? "offline" : "stale";
  }
  // No successful refresh yet.
  return online === false ? (offlineMs > 0 ? "stale" : "offline") : "connecting";
}

// ----------------------------------------------------------------- Styles

const styles = StyleSheet.create({
  flex1: { flex: 1 },
  itemsCenter: { alignItems: "center" },
  textCenter: { textAlign: "center" },
  textOnDark: { color: colors.paper },
  textMutedOnDark: { color: "rgba(246,241,228,0.72)" },

  screen: { flex: 1 },
  screenLight: { backgroundColor: colors.paper },
  screenDark: { backgroundColor: colors.ink },
  screenScroll: {
    paddingHorizontal: spacing.screen,
    paddingTop: spacing.md,
    paddingBottom: spacing.xxl,
    gap: spacing.lg,
  },
  screenFixed: { paddingBottom: spacing.sm, gap: spacing.sm },

  header: {
    gap: spacing.xs,
    // Phase 33 (§4): padding (not margin) so the opaque paper background
    // covers the full strip below the title when the header is sticky —
    // visual spacing below the header is unchanged.
    paddingBottom: spacing.xs,
    backgroundColor: colors.paper,
  },
  headerMain: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.md,
  },
  headerLeft: { flex: 1, minWidth: 0 },
  headerTitleRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
  },
  headerTitle: {
    // 35M R2 (item 14): family encodes the weight (display = 800 face);
    // no RN fontWeight synthesis on custom fonts.
    fontFamily: fonts.display,
    fontSize: fontSize.title,
    letterSpacing: -0.6,
    color: colors.ink,
    flexShrink: 1,
  },
  headerSubtitle: {
    fontFamily: fonts.displayMedium,
    fontSize: fontSize.body,
    color: colors.muted,
    marginTop: 2,
  },
  headerRight: {
    flexShrink: 0,
    minHeight: 48,
    justifyContent: "flex-start",
    alignItems: "flex-end",
    gap: spacing.xs,
  },
  crestPressable: {
    minWidth: 48,
    minHeight: 48,
    alignItems: "center",
    justifyContent: "center",
  },
  crestPressed: { opacity: 0.6 },
  backPressable: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    alignSelf: "flex-start",
    minHeight: 44,
    marginTop: 2,
    marginLeft: -8,
    paddingRight: spacing.sm,
  },
  backLabel: {
    fontFamily: fonts.displayMedium,
    fontSize: fontSize.body,
    color: colors.ink,
  },

  // 35M R2 (item 12): sans header eyebrow variant — displayMedium 13,
  // no DM Mono, no letter-spacing trickery.
  eyebrowSans: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.ink,
    letterSpacing: 0.2,
  },

  eyebrowText: {
    // 35M R2 (item 14): displayMedium had no bold face — RN requested
    // bold anyway and Android fell back to Roboto. The bold sans section
    // eyebrow now uses the loaded 800 family directly.
    fontFamily: fonts.display,
    fontSize: 13,
    color: colors.ink,
    letterSpacing: 0.2,
  },

  metric: {
    fontFamily: fonts.display,
    fontSize: fontSize.hero,
    letterSpacing: -2,
    color: colors.ink,
    marginTop: 2,
  },
  metricCaption: {
    marginTop: 2,
  },

  // 33-QA (P8-30): a paper chip on a paper screen was invisible — the
  // hairline border was all that separated pill from surface, so the
  // dot read as a stray mark. The pill now sits on the track fill (dot
  // + label read as ONE status chip) and the label carries an explicit
  // ink color (RN's default black is off-palette).
  pill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: radius.full,
    borderWidth: 1,
    borderColor: colors.track,
    backgroundColor: colors.track,
    alignSelf: "flex-start",
  },
  pillSm: { paddingHorizontal: 8, paddingVertical: 4 },
  pillLabel: {
    // Finding 13: larger, high-contrast status label. Ink on track is
    // ~13:1; a bigger size keeps Live/Online/Ready/Active legible at a
    // glance on shared gate devices.
    color: colors.ink,
    fontSize: 15,
  },
  pillDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  pillTextSm: {
    fontSize: fontSize.label,
    letterSpacing: 0.2,
  },

  segment: {
    flexDirection: "row",
    backgroundColor: colors.track,
    borderRadius: radius.sm,
    padding: 3,
    gap: 3,
  },
  segmentItem: {
    flex: 1,
    minHeight: 42,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: radius.sm - 1,
    paddingHorizontal: 4,
  },
  segmentItemActive: {
    backgroundColor: colors.ink,
  },
  segmentLabel: {
    flexShrink: 1,
    // 35I (P) + Scanner Fix Round 1 (item 4): control text — active =
    // bold paper on ink (clearly selected), inactive = ink on track
    // (fully readable, visibly unfilled). Entry/Exit are never
    // differentiated beyond the active state. 35M R2 (item 14): the
    // active label uses the 800 family directly instead of asking RN
    // for bold on the 500 family (which fell back to Roboto).
    fontFamily: fonts.displayMedium,
    fontSize: fontSize.body,
    color: colors.ink,
  },
  segmentLabelActive: {
    color: colors.paper,
    fontFamily: fonts.display,
  },

  btn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
    minHeight: 52,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.button,
    borderWidth: 1.5,
  },
  btnLg: { minHeight: 56 },
  btnPressed: { opacity: 0.85, transform: [{ scale: 0.985 }] },
  btnLabel: {
    fontFamily: fonts.displayMedium,
    fontSize: fontSize.body,
  },

  fieldWrap: { gap: 6 },
  input: {
    minHeight: 48,
    borderWidth: 1,
    borderColor: colors.track,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.md,
    fontFamily: fonts.displayMedium,
    fontSize: fontSize.body,
    color: colors.ink,
    backgroundColor: colors.paper,
  },
  inputError: { borderColor: colors.invalid },
  fieldLabel: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.ink,
  },
  fieldError: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.invalid,
  },
  fieldHint: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.muted,
  },

  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    minHeight: 48,
    paddingVertical: spacing.sm,
  },
  rowPressed: { opacity: 0.7 },
  rowTitle: {
    fontFamily: fonts.displayMedium,
    fontSize: fontSize.body,
    letterSpacing: -0.2,
  },
  rowSubtitle: {
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.muted,
    marginTop: 2,
  },

  sectionCard: {
    backgroundColor: colors.card,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.track,
    gap: spacing.sm,
  },
  sectionCardTint: {
    backgroundColor: colors.card,
  },
  sectionCardDark: {
    backgroundColor: colors.ink,
    borderRadius: radius.md,
  },
  sectionPad: {
    padding: spacing.md,
  },

  track: {
    backgroundColor: colors.track,
    width: "100%",
    overflow: "hidden",
  },
  trackFill: {
    backgroundColor: colors.ink,
  },

  stateWrap: {
    alignItems: "center",
    paddingVertical: spacing.lg,
    paddingHorizontal: spacing.md,
    gap: spacing.sm,
  },
  stateTitle: {
    fontFamily: fonts.display,
    fontSize: fontSize.title,
    letterSpacing: -0.4,
    color: colors.ink,
    textAlign: "center",
  },
  stateBody: {
    fontFamily: fonts.displayMedium,
    fontSize: fontSize.body,
    color: colors.muted,
    textAlign: "center",
    lineHeight: 22,
  },
  stateAction: { marginTop: spacing.sm, alignSelf: "stretch" },

  offlineBanner: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    backgroundColor: colors.paper,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.amber,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  offlineTitle: {
    fontFamily: fonts.monoMedium,
    fontSize: fontSize.label,
    color: colors.ink,
  },
  offlineBody: {
    fontFamily: fonts.mono,
    fontSize: fontSize.label,
    color: colors.muted,
  },
  offlineRetry: {
    paddingHorizontal: spacing.md,
    minHeight: 40,
    justifyContent: "center",
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.ink,
  },
  offlineRetryText: {
    fontFamily: fonts.monoMedium,
    fontSize: fontSize.label,
    color: colors.ink,
  },
});
