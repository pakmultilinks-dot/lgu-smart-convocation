import { useEffect, useRef, useState } from "react";
import { Animated, Text, type TextStyle } from "react-native";

interface Props {
  value: number;
  style?: TextStyle;
  duration?: number;
}

/** Number that tweens to its new value with a smooth count-up animation. */
export function CountUp({ value, style, duration = 900 }: Props) {
  const animRef = useRef(new Animated.Value(0));
  const [text, setText] = useState("0");
  const lastRef = useRef(0);

  useEffect(() => {
    const anim = animRef.current;
    anim.setValue(lastRef.current);
    const id = anim.addListener(({ value: v }: { value: number }) =>
      setText(String(Math.round(v))),
    );
    Animated.timing(anim, {
      duration,
      toValue: value,
      useNativeDriver: false,
    }).start(({ finished }) => {
      if (finished) {
        lastRef.current = value;
      }
    });
    return () => {
      anim.removeListener(id);
    };
  }, [value, duration]);

  return <Text style={style}>{text}</Text>;
}
