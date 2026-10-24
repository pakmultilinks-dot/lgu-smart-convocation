import { LiveBoardScreen } from "../../src/screens/LiveBoardScreen";
import { DashboardAccessGate } from "../../src/components/DashboardAccessGate";

export default function LiveboardIndexRoute() {
  return <DashboardAccessGate mode="liveboard"><LiveBoardScreen /></DashboardAccessGate>;
}
