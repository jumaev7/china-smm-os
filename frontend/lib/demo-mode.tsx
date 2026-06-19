"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  DEMO_MODE_STORAGE_KEY,
  DEMO_PACKAGE_STORAGE_KEY,
  type DemoFactoryPackageId,
} from "./commercial-demo-api";

type DemoModeContextValue = {
  enabled: boolean;
  activePackage: DemoFactoryPackageId | null;
  toggle: () => void;
  enable: (packageId?: DemoFactoryPackageId) => void;
  disable: () => void;
  setPackage: (packageId: DemoFactoryPackageId | null) => void;
};

const DemoModeContext = createContext<DemoModeContextValue | null>(null);

function readStoredBool(key: string): boolean {
  if (typeof window === "undefined") return false;
  return localStorage.getItem(key) === "true";
}

function readStoredPackage(): DemoFactoryPackageId | null {
  if (typeof window === "undefined") return null;
  const val = localStorage.getItem(DEMO_PACKAGE_STORAGE_KEY);
  if (val === "haocheng" || val === "toy_manufacturer" || val === "textile_factory") {
    return val;
  }
  return null;
}

export function DemoModeProvider({ children }: { children: ReactNode }) {
  const [enabled, setEnabled] = useState(false);
  const [activePackage, setActivePackage] = useState<DemoFactoryPackageId | null>(null);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setEnabled(readStoredBool(DEMO_MODE_STORAGE_KEY));
    setActivePackage(readStoredPackage());
    setHydrated(true);
  }, []);

  const persist = useCallback((nextEnabled: boolean, pkg: DemoFactoryPackageId | null) => {
    localStorage.setItem(DEMO_MODE_STORAGE_KEY, String(nextEnabled));
    if (pkg) {
      localStorage.setItem(DEMO_PACKAGE_STORAGE_KEY, pkg);
    } else {
      localStorage.removeItem(DEMO_PACKAGE_STORAGE_KEY);
    }
  }, []);

  const enable = useCallback(
    (packageId?: DemoFactoryPackageId) => {
      setEnabled(true);
      if (packageId) setActivePackage(packageId);
      persist(true, packageId ?? activePackage);
    },
    [activePackage, persist],
  );

  const disable = useCallback(() => {
    setEnabled(false);
    persist(false, activePackage);
  }, [activePackage, persist]);

  const toggle = useCallback(() => {
    setEnabled((prev) => {
      const next = !prev;
      persist(next, activePackage);
      return next;
    });
  }, [activePackage, persist]);

  const setPackage = useCallback(
    (packageId: DemoFactoryPackageId | null) => {
      setActivePackage(packageId);
      if (packageId) {
        setEnabled(true);
        persist(true, packageId);
      } else {
        persist(enabled, null);
      }
    },
    [enabled, persist],
  );

  const value = useMemo(
    () => ({
      enabled: hydrated ? enabled : false,
      activePackage: hydrated ? activePackage : null,
      toggle,
      enable,
      disable,
      setPackage,
    }),
    [hydrated, enabled, activePackage, toggle, enable, disable, setPackage],
  );

  return <DemoModeContext.Provider value={value}>{children}</DemoModeContext.Provider>;
}

export function useDemoMode() {
  const ctx = useContext(DemoModeContext);
  if (!ctx) {
    throw new Error("useDemoMode must be used within DemoModeProvider");
  }
  return ctx;
}

export function useDemoModeOptional() {
  return useContext(DemoModeContext);
}
