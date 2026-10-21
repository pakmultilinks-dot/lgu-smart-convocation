import type { BarcodeScanningResult } from "expo-camera";
import { useCallback, useEffect, useRef, useState } from "react";
import { Platform, type LayoutChangeEvent } from "react-native";
import {
  FRACTION_COMFORT,
  QR_LEAVE_MS,
  ZOOM_MAX,
  ZOOM_STEP,
  ZOOM_TICK_MS,
} from "./scannerConstants";

/**
 * Auto-zoom engine — eases the camera zoom toward the level justified by the
 * QR bounds, and eases back out when the code leaves the frame. The motion
 * curve (step + tick + comfort fraction) is the proven Phase 30 behavior.
 */
export function useScannerZoom() {
  const [zoom, setZoom] = useState(0);
  const targetZoomRef = useRef(0);
  const lastBoundsAtRef = useRef(0);
  const cameraWidthRef = useRef(0);

  // Auto-zoom tick: ease the zoom toward the target derived from QR bounds.
  useEffect(() => {
    if (Platform.OS === "web") return;
    const id = setInterval(() => {
      setZoom((current) => {
        const target =
          Date.now() - lastBoundsAtRef.current > QR_LEAVE_MS
            ? 0
            : targetZoomRef.current;
        if (Math.abs(target - current) < ZOOM_STEP) return target;
        return current + Math.sign(target - current) * ZOOM_STEP;
      });
    }, ZOOM_TICK_MS);
    return () => clearInterval(id);
  }, []);

  /** Track QR bounds on every scan callback so auto-zoom follows the code. */
  const trackBounds = useCallback((scan: BarcodeScanningResult) => {
    if (!scan.bounds || scan.bounds.size.width <= 0) return;
    lastBoundsAtRef.current = Date.now();
    const viewWidth = Math.max(1, cameraWidthRef.current);
    const fraction = scan.bounds.size.width / viewWidth;
    targetZoomRef.current =
      fraction >= FRACTION_COMFORT
        ? 0
        : Math.min(
            ZOOM_MAX,
            ((FRACTION_COMFORT - fraction) / FRACTION_COMFORT) * ZOOM_MAX,
          );
  }, []);

  const onCameraLayout = useCallback((e: LayoutChangeEvent) => {
    cameraWidthRef.current = e.nativeEvent.layout.width || 0;
  }, []);

  return { zoom, trackBounds, onCameraLayout };
}
