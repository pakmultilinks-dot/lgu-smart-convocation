import { View } from "react-native";
import { colors } from "../theme";

/** Viewfinder corner brackets (web fallback + live overlay). */
export function ViewfinderCorners() {
  const corner = (position: object) => (
    <View style={[styles.corner, position]} />
  );
  return (
    <>
      {corner(styles.cornerTL)}
      {corner(styles.cornerTR)}
      {corner(styles.cornerBL)}
      {corner(styles.cornerBR)}
    </>
  );
}

const styles = {
  corner: {
    position: "absolute" as const,
    width: 30,
    height: 30,
    borderColor: colors.paper,
  },
  cornerTL: {
    top: 0,
    left: 0,
    borderTopWidth: 3,
    borderLeftWidth: 3,
    borderTopLeftRadius: 8,
  },
  cornerTR: {
    top: 0,
    right: 0,
    borderTopWidth: 3,
    borderRightWidth: 3,
    borderTopRightRadius: 8,
  },
  cornerBL: {
    bottom: 0,
    left: 0,
    borderBottomWidth: 3,
    borderLeftWidth: 3,
    borderBottomLeftRadius: 8,
  },
  cornerBR: {
    bottom: 0,
    right: 0,
    borderBottomWidth: 3,
    borderRightWidth: 3,
    borderBottomRightRadius: 8,
  },
};
