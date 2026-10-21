import { Ionicons } from "@expo/vector-icons";
import { router, useLocalSearchParams } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Platform, ScrollView, Share, Text, View } from "react-native";
import QRCode from "react-native-qrcode-svg";
import ViewShot, { type ViewShotRef } from "react-native-view-shot";
import { fetchAppConfig, fetchGuestPass, type AppConfig, type GuestPass } from "../api/client";
import { UNIVERSITY_NAME } from "../config";
import { colors, fonts, radius, spacing } from "../theme";
import { maskPhone } from "../utils/phone";
import {
  AppButton,
  AppHeader,
  ErrorState,
  LoadingState,
  Screen,
  SectionCard,
  StatusPill,
} from "../ui";

/**
 * Guest Pass — full-screen QR presentation for one guest. Phase 35C: the
 * pass is an ink ticket on paper (the screen's single raised element) —
 * no green panel, no gradient. The artwork stays unmistakable and the QR
 * stays high-contrast for the gate scanners.
 */
export function GuestPassScreen() {
  const params = useLocalSearchParams<{ gid?: string }>();
  const gid = typeof params.gid === "string" ? params.gid : "";
  const gidNum = Number(gid);
  const gidValid = !!gid && Number.isInteger(gidNum);

  const [pass, setPass] = useState<GuestPass | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Phase 35K (F): the institution name on the pass artwork is a saved
  // setting, not a hard-coded constant — the local constant remains as the
  // offline fallback only.
  const [cfg, setCfg] = useState<AppConfig | null>(null);
  // 35L (A): share + save-as-image feedback (honest notes, no fake
  // success — a failed share/save always explains itself).
  const [actionNote, setActionNote] = useState<string | null>(null);
  const [savingImage, setSavingImage] = useState(false);
  const shotRef = useRef<ViewShotRef>(null);

  // State updates only after await — keeps the effect below lint-safe.
  const refresh = useCallback(async () => {
    try {
      setPass(await fetchGuestPass(gidNum));
      setError(null);
    } catch (e) {
      setPass(null);
      setError(
        e instanceof Error
          ? e.message
          : "The pass could not be loaded. Check the connection and retry.",
      );
    }
  }, [gidNum]);

  const retry = () => {
    setError(null);
    void refresh();
  };

  useEffect(() => {
    if (!gidValid) return;
    void (async () => {
      await refresh();
    })();
  }, [gidValid, refresh]);

  // Phase 35K (F): best-effort config load — the pass still renders from
  // the fallback constant if the server is unreachable.
  useEffect(() => {
    void fetchAppConfig()
      .then(setCfg)
      .catch(() => setCfg(null));
  }, []);

  // 35L (A1): share the pass through the device share sheet (WhatsApp is
  // available there — no custom WhatsApp UI). The message carries the
  // pass information: identity, host (masked phone — 35M R2 item 4) and
  // the QR payload. No pass ID line (35M R2 item 5) — the QR itself is
  // the gate's identity check.
  const sharePass = useCallback(async () => {
    if (!pass) return;
    const message = [
      "LGU Convocation — Guest Pass",
      `Name: ${pass.name}`,
      `Host: ${pass.host_roll_no} · ${pass.phone ? maskPhone(pass.phone) : "No phone"}`,
      `QR code payload: ${pass.payload}`,
      "Show this pass at the gate — it is single-use.",
    ].join("\n");
    try {
      await Share.share({ message });
      setActionNote(null);
    } catch {
      // Web without a share sheet, or the sheet was dismissed — say so.
      setActionNote("Sharing is not available here — show the pass on this screen instead.");
    }
  }, [pass]);

  // 35L (A2): save the pass as an image (ticket artwork + QR + white
  // quiet zone) to the device photo library. Android-first; web gets an
  // honest note instead of a broken flow.
  const saveAsImage = useCallback(async () => {
    if (!pass) return;
    if (Platform.OS === "web") {
      setActionNote("Saving an image is available in the phone app.");
      return;
    }
    // 35M (I): expo-media-library is native-only. A static import evaluates
    // its module graph on web/SSR too, where requireNativeModule has no
    // "ExpoMediaLibraryNext" — `class Query extends undefined` crashes every
    // web route at load (dev SSR "Server Error"). Require it lazily here so
    // only the native path — the one that actually uses it — loads it.
    const MediaLibrary = await import("expo-media-library");
    if (!shotRef.current) return;
    setSavingImage(true);
    try {
      const perm = await MediaLibrary.requestPermissionsAsync();
      if (!perm.granted) {
        setActionNote("Photo library permission is needed to save the pass image.");
        return;
      }
      const uri = await shotRef.current.capture?.();
      if (!uri) {
        setActionNote("The pass image could not be captured. Try again.");
        return;
      }
      await MediaLibrary.saveToLibraryAsync(uri);
      setActionNote("Pass image saved to your photos.");
    } catch {
      setActionNote("The pass image could not be saved. Try again.");
    } finally {
      setSavingImage(false);
    }
  }, [pass]);

  // QA fix cycle 3 (Issue 2): the header no longer repeats the host
  // sentence — the host lives once, in the passMeta rows on the artwork.

  // QA fix cycle 2 (guest pass): "Valid for {date}" from the server's
  // configured convocation datetime — never a hard-coded date.
  const validDate = (() => {
    const iso = cfg?.event.datetime;
    if (!iso) return null;
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return null;
    const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    return `${d.getDate()} ${months[d.getMonth()]} ${d.getFullYear()}`;
  })();

  return (
    // 35M R2 (item 6): cream/light body with dark status icons — the ink
    // native header is gone (headerShown: false in the route config), so
    // the single "Guest Pass" title lives in the in-screen AppHeader.
    // 35M item 14 → 33-QA (I11): fixed frame — a bounded scroll area
    // holds the pass artwork + rules; Share + Save sit side by side in
    // the bottom action area, all visible without any scrolling at
    // 360×800. QA fix cycle 2: the pinned "Back to guests" button is
    // gone — the header back arrow is the single way back. 35M item 14:
    // the name renders ONCE — on the ticket panel; the header subtitle
    // carries the host reference only.
    <Screen scroll={false}>
      <AppHeader
        onBack={() =>
          router.canGoBack() ? router.back() : router.replace("/mode-picker")
        }
        title="Guest Pass"
        right={
          pass ? (
            <StatusPill
              state={
                pass.status === "revoked"
                  ? "duplicate"
                  : pass.used
                    ? "nodata"
                    : "accept"
              }
              label={
                pass.status === "revoked" ? "Revoked" : pass.used ? "Used" : "Ready"
              }
              size="sm"
            />
          ) : undefined
        }
      />

      {!gidValid ? (
        <SectionCard>
          <ErrorState
            title="Pass unavailable"
            body="This pass link is incomplete. Ask the host to share it again."
          />
        </SectionCard>
      ) : error ? (
        <SectionCard>
          <ErrorState title="Pass unavailable" body={error} onRetry={retry} />
        </SectionCard>
      ) : !pass ? (
        <SectionCard>
          <LoadingState label="Loading pass…" />
        </SectionCard>
      ) : (
        <>
          {/* 35M item 14: bounded scroll area (artwork + rules only).
              33-QA (I11): "Back to guests" is no longer buried under the
              scroll content — it is pinned in the bottom action area. */}
          <ScrollView
            style={styles.bodyScroll}
            contentContainerStyle={styles.bodyScrollContent}
            showsVerticalScrollIndicator={false}
            keyboardShouldPersistTaps="handled"
          >
            {/* Ink ticket panel — the pass reads as official on paper.
                35L (A2): ViewShot wraps the artwork for save-as-image. */}
            <ViewShot
              ref={shotRef}
              options={{ format: "png", quality: 1 }}
              style={styles.shotWrap}
            >
              <View style={styles.passPanel}>
                <Text style={styles.passEyebrow}>
                  {(cfg?.university || UNIVERSITY_NAME).toUpperCase()}
                </Text>
                <Text style={styles.passTitle}>Convocation Guest Pass</Text>
                <Text style={styles.passName} numberOfLines={2}>
                  {pass.name}
                </Text>
                {/* 35L (B1): the QR renders on PURE WHITE with a wide
                    quiet zone — never cream/tinted — so any gate scanner
                    reads it at full contrast. */}
                <View style={styles.qrPlate}>
                  <QRCode
                    value={pass.payload}
                    size={200}
                    backgroundColor="#FFFFFF"
                    color={colors.ink}
                  />
                </View>
                {/* QA fix cycle 3 (Issue 3): stacked sans rows — Host /
                    ID / Phone / Valid — each a single line (never a
                    wrapped row), left-aligned across the panel width. */}
                <View style={styles.passMeta}>
                  {pass.host_name ? (
                    <Text style={styles.passMetaText} numberOfLines={1}>
                      {`Host: ${pass.host_name}`}
                    </Text>
                  ) : null}
                  <Text style={styles.passMetaText} numberOfLines={1}>
                    {`ID: ${pass.host_roll_no}`}
                  </Text>
                  <Text style={styles.passMetaText} numberOfLines={1}>
                    {`Phone: ${pass.phone ? maskPhone(pass.phone) : "No phone"}`}
                  </Text>
                  {validDate ? (
                    <Text style={styles.passMetaText} numberOfLines={1}>
                      {`Valid: ${validDate}`}
                    </Text>
                  ) : null}
                </View>
              </View>
            </ViewShot>
            <View style={styles.rulesRow}>
              <Ionicons name="information-circle" size={18} color={colors.ink} />
              {/* 35M R2 (item 7): exact mandated copy. */}
              <Text style={styles.rulesText}>
                Single-use. Shows as used after the first scan.
              </Text>
            </View>
          </ScrollView>
          {/* 35M item 14 → 33-QA (I11) → QA fix cycle 2: bottom action
              area — Share + Save side by side only. The pinned "Back to
              guests" button is gone; the header back arrow is the
              navigation path (one clear way back). */}
          <View style={styles.bottomActions}>
            {/* 35L (A): share through the OS sheet + save as image. */}
            <View style={styles.actionRow}>
              <AppButton
                label="Share pass"
                icon="share-outline"
                onPress={() => void sharePass()}
                style={styles.actionBtn}
              />
              <AppButton
                label={savingImage ? "Saving..." : "Save as image"}
                icon="image-outline"
                variant="secondary"
                loading={savingImage}
                onPress={() => void saveAsImage()}
                style={styles.actionBtn}
              />
            </View>
            {actionNote ? <Text style={styles.actionNote}>{actionNote}</Text> : null}
          </View>
        </>
      )}
    </Screen>
  );
}

const styles = {
  shotWrap: {
    borderRadius: radius.button,
  },
  passPanel: {
    backgroundColor: colors.ink,
    borderRadius: radius.button,
    padding: spacing.lg,
    alignItems: "center" as const,
    gap: spacing.xs,
  },
  bodyScroll: {
    flex: 1,
  },
  bodyScrollContent: {
    gap: spacing.lg,
    paddingBottom: spacing.md,
  },
  bottomActions: {
    // 35M item 14: pinned above the safe-area inset (the Screen adds
    // its bottom padding); share + save stay visible without scrolling.
    // 33-QA (I11): Share/Save share one row; Back is pinned below.
    gap: spacing.sm,
    paddingTop: spacing.sm,
  },
  actionRow: {
    // 33-QA (I11): Share + Save share one row at narrow widths.
    flexDirection: "row" as const,
    gap: spacing.sm,
  },
  actionBtn: {
    flex: 1,
  },
  passEyebrow: {
    // 35M items 15/18: the university line is a plain sans label —
    // not wide mono lettering.
    fontFamily: fonts.displayMedium,
    color: "rgba(246,241,228,0.72)",
    fontSize: 11,
    letterSpacing: 0.4,
  },
  passTitle: {
    // 35M item 2: slightly smaller so "Convocation Guest Pass" wraps
    // balanced at 360px — never a one-word orphan line.
    fontFamily: fonts.display,
    color: colors.paper,
    fontSize: 21,
    letterSpacing: -0.4,
    marginBottom: spacing.md,
    textAlign: "center" as const,
  },
  qrPlate: {
    // 35L (B1): PURE white plate + wide quiet zone around the modules.
    backgroundColor: "#FFFFFF",
    padding: spacing.lg,
    borderRadius: radius.sm,
    marginBottom: spacing.md,
  },
  passName: {
    // QA fix cycle 2 (guest pass): the guest's name is the ticket's
    // focal line — prominent sans, at the TOP of the artwork (above the
    // QR), centered on the ink panel.
    fontFamily: fonts.display,
    color: colors.paper,
    fontSize: 24,
    letterSpacing: -0.4,
    textAlign: "center" as const,
    marginBottom: spacing.md,
  },
  passMeta: {
    // QA fix cycle 3 (Issue 3): stacked column of full-width single-line
    // rows — sans (operational reading), never narrow mono columns.
    alignSelf: "stretch" as const,
    gap: 2,
  },
  passMetaText: {
    fontFamily: fonts.displayMedium,
    color: colors.paper,
    fontSize: 13,
  },
  rulesRow: {
    flexDirection: "row" as const,
    gap: spacing.sm,
    // 35M item 14: spacing now comes from the scroll content gap.
  },
  rulesText: {
    flex: 1,
    // 33-QA (I7): the icon + text row must not inflate past the
    // header column at narrow widths (Yoga automatic minimum sizing).
    minWidth: 0,
    fontFamily: fonts.displayMedium,
    fontSize: 15,
    color: colors.muted,
    lineHeight: 21,
  },
  actionNote: {
    // 35M item 18: helper sentence — sans, not DM Mono.
    fontFamily: fonts.displayMedium,
    fontSize: 13,
    color: colors.muted,
  },
};
