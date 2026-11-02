import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { fetchAppConfig } from "../api/client";

export type DataMode = "demo" | "live" | "unknown";

const DataModeContext = createContext<DataMode>("unknown");

export function DataModeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<DataMode>("unknown");

  useEffect(() => {
    let active = true;
    void fetchAppConfig()
      .then((config) => {
        if (active) setMode(config.data_mode);
      })
      .catch(() => {
        if (active) setMode("unknown");
      });
    return () => { active = false; };
  }, []);

  return <DataModeContext.Provider value={mode}>{children}</DataModeContext.Provider>;
}

export function useDataMode(): DataMode {
  return useContext(DataModeContext);
}
