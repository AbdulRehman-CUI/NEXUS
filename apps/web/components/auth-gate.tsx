"use client";
import { createContext, useContext, useEffect, useRef, useState } from "react";
import { api, setCsrf } from "../lib/api";

type Identity = {
  profile: "local" | "server";
  user: { username: string; admin: boolean } | null;
  csrf: string | null;
};
const IdentityContext = createContext<{
  identity: Identity | null;
  logout: () => Promise<void>;
}>({ identity: null, logout: async () => {} });
export const useIdentity = () => useContext(IdentityContext);

export function AuthGate({ children }: { children: React.ReactNode }) {
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [loading, setLoading] = useState(true);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loginRequired, setLoginRequired] = useState(false);
  const [setupAvailable, setSetupAvailable] = useState(false);
  const [setupToken, setSetupToken] = useState("");
  const setupFragment = useRef("");
  useEffect(() => {
    let active = true;
    const fragment = new URLSearchParams(window.location.hash.slice(1));
    const token = fragment.get("setup") || setupFragment.current;
    setupFragment.current = token;
    if (token) {
      history.replaceState(null, "", window.location.pathname + window.location.search);
    }
    api<{ available: boolean }>("/api/auth/setup")
      .then((status) => {
        if (active) {
          setSetupAvailable(status.available);
          setSetupToken(token);
        }
      })
      .catch(() => {});
    api<Identity>("/api/auth/me")
      .then((value) => {
        if (active) {
          setCsrf(value.csrf);
          setIdentity(value);
        }
      })
      .catch((cause) => {
        if (active) {
          setLoginRequired(cause.message === "Sign in to continue.");
          setError(
            cause.message === "Sign in to continue." ? "" : cause.message,
          );
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    function expired() {
      setCsrf(null);
      setIdentity(null);
      setLoginRequired(true);
      setError("Your session ended. Sign in again.");
    }
    window.addEventListener("nexus-auth-required", expired);
    return () => {
      active = false;
      window.removeEventListener("nexus-auth-required", expired);
    };
  }, []);
  if (loading)
    return (
      <main className="auth-page">
        <p role="status">Opening your knowledge workspace…</p>
      </main>
    );
  if (!identity && !loginRequired)
    return (
      <main className="auth-page">
        <section className="settings-card auth-card">
          <h1>Connect to NEXUS.</h1>
          <p role="alert">
            {error || "The API could not be reached. Start the API and retry."}
          </p>
          <button className="button" onClick={() => window.location.reload()}>
            Retry connection
          </button>
        </section>
      </main>
    );
  if (!identity)
    return (
      <main className="auth-page">
        <form
          className="settings-card auth-card"
          onSubmit={async (event) => {
            event.preventDefault();
            setBusy(true);
            setError("");
            try {
              if (setupAvailable) {
                await api("/api/auth/setup", {
                  method: "POST",
                  body: JSON.stringify({ username, password, token: setupToken }),
                });
                setSetupAvailable(false);
                setSetupToken("");
              }
              const value = await api<Identity>("/api/auth/login", {
                method: "POST",
                body: JSON.stringify({ username, password }),
              });
              setCsrf(value.csrf);
              setIdentity(value);
              setPassword("");
            } catch (cause) {
              setError(
                cause instanceof Error ? cause.message : "Sign in failed.",
              );
            } finally {
              setBusy(false);
            }
          }}
        >
          <span className="eyebrow">NEXUS · SERVER PROFILE</span>
          <h1>Your knowledge, privately.</h1>
          <p>{setupAvailable ? "Create your owner account to open NEXUS." : "Sign in with an account created by your administrator."}</p>
          {setupAvailable && <label>Setup token<input type="password" autoComplete="off" value={setupToken} onChange={(event) => setSetupToken(event.target.value)} required /></label>}
          <label>
            Username
            <input
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              required
              maxLength={64}
            />
          </label>
          <label>
            Password
            <input
              type="password"
              autoComplete={setupAvailable ? "new-password" : "current-password"}
              minLength={setupAvailable ? 12 : 1}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
              maxLength={256}
            />
          </label>
          {error && (
            <p role="alert" className="document-error">
              {error}
            </p>
          )}
          <button className="button" disabled={busy}>
            {busy ? "Opening workspace…" : setupAvailable ? "Create owner account" : "Sign in"}
          </button>
          <p className="field-help">
            {setupAvailable ? "Use at least 12 characters. The private setup token works only for the first account." : "No public signup. Ask your administrator about account recovery."}
          </p>
        </form>
      </main>
    );
  return (
    <IdentityContext.Provider
      value={{
        identity,
        logout: async () => {
          await api("/api/auth/logout", { method: "POST" });
          setCsrf(null);
          setIdentity(null);
          setLoginRequired(true);
          localStorage.removeItem("nexus-workspace");
        },
      }}
    >
      {children}
    </IdentityContext.Provider>
  );
}
