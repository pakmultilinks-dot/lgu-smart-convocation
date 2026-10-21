import { Stack } from "expo-router";
import { useFonts } from "expo-font";
import * as SplashScreen from "expo-splash-screen";
import { useEffect } from "react";
import { StatusBar } from "expo-status-bar";
import {
  BricolageGrotesque_500Medium,
  BricolageGrotesque_800ExtraBold,
} from "@expo-google-fonts/bricolage-grotesque";
import { DMMono_400Regular, DMMono_500Medium } from "@expo-google-fonts/dm-mono";
import { colors, fonts } from "../src/theme";

export {
  // Catch any errors thrown by the Layout component.
  ErrorBoundary,
} from "expo-router";

export const unstable_settings = {
  // 35M R3: the root URL ("/") anchors to the LaunchScreen gate
  // (app/index.tsx), so every cold start runs the deterministic
  // mode-resolution rule before any destination renders.
  initialRouteName: "index",
};

void SplashScreen.preventAutoHideAsync();

/**
 * Root stack. Tab groups carry their own headers, so the stack stays hidden
 * — including the Guest Pass route (35M R2 item 6: the single "Guest Pass"
 * title lives in the screen's own AppHeader on cream, with its back
 * action; no duplicate ink native header). Fonts load once here; the
 * splash stays up until they are ready.
 */
export default function RootLayout() {
  const [fontsLoaded] = useFonts({
    BricolageGrotesque_500Medium,
    BricolageGrotesque_800ExtraBold,
    DMMono_400Regular,
    DMMono_500Medium,
  });

  useEffect(() => {
    if (fontsLoaded) void SplashScreen.hideAsync();
  }, [fontsLoaded]);

  if (!fontsLoaded) return null;

  return (
    <>
      {/* Default = dark icons for light screens; each Screen sets its own
          (expo-status-bar is the single status-bar system). */}
      <StatusBar style="dark" />
      <Stack
        screenOptions={{
          headerShadowVisible: false,
          headerStyle: { backgroundColor: colors.ink },
          headerTintColor: colors.paper,
          headerTitleStyle: {
            // 35M R2 (item 14): family encodes the weight — no RN
            // fontWeight synthesis on the custom family.
            fontFamily: fonts.displayMedium,
            fontSize: 15,
          },
        }}
      >
        <Stack.Screen name="index" options={{ headerShown: false }} />
        <Stack.Screen name="mode-picker" options={{ headerShown: false }} />
        <Stack.Screen name="(volunteer)" options={{ headerShown: false }} />
        <Stack.Screen name="(liveboard)" options={{ headerShown: false }} />
        <Stack.Screen name="(student)" options={{ headerShown: false }} />
        <Stack.Screen
          name="guest-pass"
          options={{ headerShown: false }}
        />
      </Stack>
    </>
  );
}
