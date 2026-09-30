import { useEffect, useState } from "react";
import { Animated, StyleSheet, Text, View } from "react-native";
import { Circle, Svg } from "react-native-svg";
import { colors, fontSize, fontWeight, radius, spacing } from "../theme";

const AnimatedCircle = Animated.createAnimatedComponent(Circle);

interface Props {
  value: number;
  size?: number;
  strokeWidth?: number;
  label?: string;
  sublabel?: string;
}

/** Bold animated progress ring built with react-native-svg. */
export function ProgressRing({
  value,
  size = 190,
  strokeWidth = 18,
  label,
  sublabel,
}: Props) {
  const clamped = Math.min(100, Math.max(0, value));
  const [progress] = useState(() => new Animated.Value(0));
  const r = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * r;

  useEffect(() => {
    Animated.timing(progress, {
      duration: 900,
      toValue: clamped,
      useNativeDriver: true,
    }).start();
  }, [clamped, progress]);

  const dashOffset = progress.interpolate({
    inputRange: [0, 100],
    outputRange: [circumference, 0],
  });

  return (
    <View style={[styles.wrap, { width: size, height: size }]}>
      <Svg width={size} height={size}>
        <Circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          stroke={colors.emeraldSoft}
          strokeWidth={strokeWidth}
          fill="none"
        />
        <AnimatedCircle
          cx={size / 2}
          cy={size / 2}
          r={r}
          stroke={colors.emerald}
          strokeWidth={strokeWidth}
          fill="none"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={dashOffset}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      </Svg>
      <View style={styles.center}>
        {label ? <Text style={styles.label}>{label}</Text> : null}
        {sublabel ? <Text style={styles.sublabel}>{sublabel}</Text> : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  center: {
    alignItems: "center",
    inset: 0,
    justifyContent: "center",
    position: "absolute",
  },
  label: {
    color: colors.greenDark,
    fontSize: fontSize.display,
    fontWeight: fontWeight.bold,
  },
  sublabel: {
    color: colors.muted,
    fontSize: fontSize.caption,
    fontWeight: fontWeight.medium,
    marginTop: spacing.xs / 2,
  },
  wrap: {
    alignItems: "center",
    borderRadius: radius.lg,
    justifyContent: "center",
  },
});
