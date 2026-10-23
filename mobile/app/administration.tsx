import { AdminGate } from "../src/components/AdminGate";
import { AdminScreen } from "../src/screens/AdminScreen";

// Outside operational groups: administrators can always reopen dashboards.
export default function AdministrationRoute() {
  return <AdminGate><AdminScreen /></AdminGate>;
}
