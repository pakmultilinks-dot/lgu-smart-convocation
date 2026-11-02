import { AdminGate } from "../src/components/AdminGate";
import { BroadcastScreen } from "../src/screens/BroadcastScreen";

export default function AdministratorMessages() {
  return <AdminGate><BroadcastScreen /></AdminGate>;
}
