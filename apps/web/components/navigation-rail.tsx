"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import type { Workspace } from "../lib/api";
import { Icon } from "./icon";
import { navigateWithTransition } from "./motion-system";
import { useIdentity } from "./auth-gate";
import { usePreference } from "../lib/preferences";

const destinations = [
  { id: "chat", href: "/", icon: "chat", label: "Ask your knowledge" },
  { id: "library", href: "/library", icon: "files", label: "Document library" },
  { id: "vaults", href: "/vaults", icon: "book", label: "Obsidian vaults" },
  { id: "graph", href: "/graph", icon: "graph", label: "Knowledge graph" },
  {
    id: "diagnostics",
    href: "/diagnostics",
    icon: "chart",
    label: "Diagnostics & help",
  },
] as const;
export function NavigationRail({
  mode,
  busy,
  workspaces,
  workspaceId,
  onWorkspace,
  onCreate,
  onHistory,
  onSearch,
  mobileOpen,
  onMobileClose,
  onError,
}: {
  mode: string;
  busy: boolean;
  workspaces: Workspace[];
  workspaceId: string;
  onWorkspace: (id: string) => void;
  onCreate: () => void;
  onHistory: () => void;
  onSearch: () => void;
  mobileOpen: boolean;
  onMobileClose: () => void;
  onError: (cause: unknown) => void;
}) {
  const router = useRouter();
  const { identity, logout } = useIdentity();
  const [pinnedValue, savePinned] = usePreference("nexus-rail-pinned", "false");
  const pinned = pinnedValue === "true";
  const setPinned = (value: boolean) => savePinned(String(value));
  const [theme, setTheme] = usePreference("nexus-theme", "dark");
  const [panel, setPanel] = useState<"workspace" | "account" | null>(null);
  const drawer = useRef<HTMLDialogElement>(null);
  const popover = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document
      .querySelector<HTMLMetaElement>('meta[name="theme-color"]')
      ?.setAttribute("content", theme === "dark" ? "#0d0f15" : "#f3f4f8");
  }, [theme]);
  useEffect(() => {
    const dialog = drawer.current;
    if (mobileOpen && !dialog?.open) dialog?.showModal();
    if (!mobileOpen && dialog?.open) dialog.close();
  }, [mobileOpen]);
  useEffect(() => {
    const dialog = popover.current;
    if (panel && !dialog?.open) dialog?.showModal();
    if (!panel && dialog?.open) dialog.close();
  }, [panel]);
  function go(event: React.MouseEvent<HTMLAnchorElement>, href: string) {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.button !== 0)
      return;
    event.preventDefault();
    onMobileClose();
    setPanel(null);
    navigateWithTransition(router.push, href);
  }
  const links = destinations.map((item, index) => (
    <Link
      key={item.id}
      href={item.href}
      className={`rail-item ${mode === item.id ? "active" : ""}`}
      aria-label={item.label}
      aria-current={mode === item.id ? "page" : undefined}
      onClick={(event) => go(event, item.href)}
      style={{ "--item-index": index } as React.CSSProperties}
    >
      <span className="rail-icon">
        <Icon name={item.icon} />
      </span>
      <span className="rail-label">{item.label}</span>
    </Link>
  ));
  return (
    <>
      <aside
        className={`navigation-rail ${pinned ? "is-pinned" : ""}`}
        aria-label="Workspace navigation"
      >
        <Link
          href="/"
          className="rail-mark"
          aria-label="NEXUS home"
          onClick={(event) => go(event, "/")}
        >
          <span aria-hidden="true">
            N<span>·</span>
          </span>
        </Link>
        <button
          className="rail-item workspace-trigger"
          aria-label="Switch workspace"
          disabled={busy}
          onClick={() => setPanel("workspace")}
        >
          <span className="workspace-avatar">
            {workspaces.find((w) => w.id === workspaceId)?.name.slice(0, 1) ||
              "W"}
          </span>
          <span className="rail-label">Switch workspace</span>
        </button>
        <div className="rail-divider" />
        <nav className="rail-links" aria-label="Main navigation">
          {links}
          <Link
            href="/settings"
            className={`rail-item ${mode === "settings" ? "active" : ""}`}
            aria-label="Settings & providers"
            aria-current={mode === "settings" ? "page" : undefined}
            onClick={(event) => go(event, "/settings")}
          >
            <span className="rail-icon">
              <Icon name="settings" />
            </span>
            <span className="rail-label">Settings & providers</span>
          </Link>
        </nav>
        <div className="rail-bottom">
          <button
            className="rail-item"
            aria-label="Search workspace"
            onClick={onSearch}
          >
            <span className="rail-icon">
              <Icon name="search" />
            </span>
            <span className="rail-label">Search workspace</span>
            <kbd className="rail-shortcut">⌘ K</kbd>
          </button>
          <button
            className="rail-item"
            aria-label="Toggle conversations"
            onClick={onHistory}
          >
            <span className="rail-icon">
              <Icon name="history" />
            </span>
            <span className="rail-label">Conversations</span>
          </button>
          <button
            className="rail-item"
            aria-label={pinned ? "Unpin navigation" : "Pin navigation expanded"}
            aria-pressed={pinned}
            onClick={() => {
              setPinned(!pinned);
              localStorage.setItem("nexus-rail-pinned", String(!pinned));
            }}
          >
            <span className="rail-icon">
              <Icon name="pin" />
            </span>
            <span className="rail-label">
              {pinned ? "Unpin navigation" : "Pin navigation"}
            </span>
          </button>
          <button
            className="rail-item"
            aria-label="Account and appearance"
            onClick={() => setPanel("account")}
          >
            <span className="profile-orb">
              {identity?.user?.username.slice(0, 1).toUpperCase() || "Y"}
            </span>
            <span className="rail-label">Account & appearance</span>
          </button>
        </div>
      </aside>
      <dialog
        className="mobile-nav modal-surface"
        ref={drawer}
        aria-label="Navigation"
        onCancel={onMobileClose}
      >
        <header>
          <span className="brand">NEXUS</span>
          <button
            className="icon-button"
            aria-label="Close navigation"
            onClick={onMobileClose}
          >
            <Icon name="close" />
          </button>
        </header>
        <button
          className="button secondary"
          disabled={busy}
          onClick={() => {
            onMobileClose();
            setPanel("workspace");
          }}
        >
          Switch workspace
        </button>
        <nav>
          {links}
          <Link
            href="/settings"
            className="rail-item"
            aria-label="Settings & providers"
            onClick={(event) => go(event, "/settings")}
          >
            <Icon name="settings" />
            <span>Settings & providers</span>
          </Link>
        </nav>
        <button
          className="button secondary"
          onClick={() => {
            onHistory();
            onMobileClose();
          }}
        >
          Conversations
        </button>
        <button
          className="button secondary"
          onClick={() => {
            onMobileClose();
            setPanel("account");
          }}
        >
          Account & appearance
        </button>
      </dialog>
      <dialog
        className={`rail-popover modal-surface ${panel === "account" ? "account-popover" : ""}`}
        ref={popover}
        aria-label={
          panel === "workspace"
            ? "Workspace selector"
            : "Account and appearance"
        }
        onCancel={() => setPanel(null)}
        onClick={(event) => {
          if (event.target === event.currentTarget) setPanel(null);
        }}
      >
        <header>
          <h2>{panel === "workspace" ? "Your workspaces" : "Your account"}</h2>
          <button
            className="icon-button"
            aria-label="Close panel"
            onClick={() => setPanel(null)}
          >
            <Icon name="close" size={17} />
          </button>
        </header>
        {panel === "workspace" ? (
          <>
            <label>
              Workspace
              <select
                aria-label="Workspace"
                value={workspaceId}
                onChange={(event) => {
                  onWorkspace(event.target.value);
                  setPanel(null);
                }}
              >
                {workspaces.map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name}
                  </option>
                ))}
              </select>
            </label>
            <button
              className="button primary"
              onClick={() => {
                setPanel(null);
                onCreate();
              }}
            >
              <Icon name="plus" size={16} />
              Create workspace
            </button>
          </>
        ) : (
          <>
            <p>
              {identity?.user
                ? `Signed in as ${identity.user.username}`
                : "Local single-user workspace"}
            </p>
            <p className="field-help">
              {identity?.profile === "server"
                ? "Authenticated sessions · workspace roles enforced"
                : "On-device storage · loopback access"}
            </p>
            <button
              className="button secondary"
              onClick={() => {
                const next = theme === "dark" ? "light" : "dark";
                setTheme(next);
                document.documentElement.dataset.theme = next;
                localStorage.setItem("nexus-theme", next);
              }}
            >
              <Icon name={theme === "dark" ? "sun" : "moon"} size={17} />
              {theme === "dark"
                ? "Switch to light appearance"
                : "Switch to dark appearance"}
            </button>
            {identity?.profile === "server" && (
              <button
                className="button secondary"
                onClick={() => logout().catch(onError)}
              >
                Sign out
              </button>
            )}
          </>
        )}
      </dialog>
    </>
  );
}
