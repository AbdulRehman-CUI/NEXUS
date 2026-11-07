"use client";
import { useSyncExternalStore } from "react";
function subscribe(listener: () => void) {
  window.addEventListener("nexus-preference-change", listener);
  window.addEventListener("storage", listener);
  return () => {
    window.removeEventListener("nexus-preference-change", listener);
    window.removeEventListener("storage", listener);
  };
}
export function usePreference(key: string, fallback: string) {
  const value = useSyncExternalStore(
    subscribe,
    () => localStorage.getItem(key) || fallback,
    () => fallback,
  );
  return [
    value,
    (next: string) => {
      localStorage.setItem(key, next);
      window.dispatchEvent(new Event("nexus-preference-change"));
    },
  ] as const;
}
