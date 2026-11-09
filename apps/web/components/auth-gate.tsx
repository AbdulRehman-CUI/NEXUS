"use client";
import { createContext, useContext, useEffect, useState } from "react";
import { initializeSession, type Identity } from "../lib/api";

const IdentityContext = createContext<{
  identity: Identity | null;
  sessionError: string;
  generation: number;
  retry: () => void;
}>({ identity: null, sessionError: "", generation: 0, retry: () => {} });
export const useIdentity = () => useContext(IdentityContext);

export function WorkspaceSession({ children }: { children: React.ReactNode }) {
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [sessionError, setSessionError] = useState("");
  const [generation, setGeneration] = useState(0);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    function connect() {
      setSessionError("");
      initializeSession().then(
        (session) => {
          if (active) setIdentity(session);
        },
        (cause: unknown) => {
          if (active)
            setSessionError(
              cause instanceof Error
                ? cause.message
                : "Could not open your workspace.",
            );
        },
      );
    }
    function expired() {
      setIdentity(null);
      setGeneration((value) => value + 1);
      connect();
    }
    window.addEventListener("nexus-session-expired", expired);
    connect();
    return () => {
      active = false;
      window.removeEventListener("nexus-session-expired", expired);
    };
  }, [attempt]);
  return (
    <IdentityContext.Provider
      value={{
        identity,
        sessionError,
        generation,
        retry: () => setAttempt((value) => value + 1),
      }}
    >
      {children}
    </IdentityContext.Provider>
  );
}
