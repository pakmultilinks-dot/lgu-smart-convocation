import { Redirect } from "expo-router";

export default function NotFound() {
  // Route unknown paths through the root redirect so the saved mode decides
  // the destination (volunteer home or live dashboard) — deterministic.
  return <Redirect href="/" />;
}
