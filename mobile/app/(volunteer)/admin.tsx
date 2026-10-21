import { AdminGate } from "../../src/components/AdminGate";
import { AdminScreen } from "../../src/screens/AdminScreen";

export default function AdminRoute() {
  return (
    <AdminGate>
      <AdminScreen />
    </AdminGate>
  );
}
