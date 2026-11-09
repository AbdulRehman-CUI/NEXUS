"use client";

import Link from "next/link";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  streamAnswer,
  uploadFile,
  type Chat,
  type Citation,
  type Document,
  type Message,
  type PublicSettings,
  type Source,
  type Workspace,
} from "../lib/api";
import { Icon } from "./icon";
import { SourceViewer } from "./source-viewer";
import { RetrievalControls, type ChatRetrieval } from "./retrieval-controls";
const VaultManager = dynamic(
  () => import("./vault-manager").then((module) => module.VaultManager),
  { loading: () => <Skeleton /> },
);
const GraphExplorer = dynamic(
  () => import("./graph-explorer").then((module) => module.GraphExplorer),
  { loading: () => <Skeleton /> },
);
const AdvancedSettings = dynamic(
  () => import("./advanced-settings").then((module) => module.AdvancedSettings),
  { loading: () => <Skeleton /> },
);
import { NavigationRail } from "./navigation-rail";
import { Brand, PageTransition, Skeleton } from "./motion-system";
import { VirtualList } from "./virtual-list";
import { WorkspaceSearch } from "./workspace-search";
const RichMessage = dynamic(() => import("./rich-message"), {
  loading: () => <span className="loader tiny" />,
});
import { AnswerFeedback } from "./answer-feedback";
import { useIdentity } from "./auth-gate";
import { activeModel, type AISelection } from "../lib/byok";
const ModelPicker = dynamic(
  () => import("./byok-controls").then((module) => module.ModelPicker),
  { loading: () => <Skeleton label="Loading model connections" /> },
);
const ByokControls = dynamic(
  () => import("./byok-controls").then((module) => module.ByokControls),
  { loading: () => <Skeleton label="Loading model connections" /> },
);
const ReleaseControls = dynamic(
  () => import("./release-controls").then((module) => module.ReleaseControls),
  { loading: () => <Skeleton /> },
);
const DiagnosticsPanel = dynamic(
  () => import("./diagnostics-panel").then((module) => module.DiagnosticsPanel),
  { loading: () => <Skeleton /> },
);

type Mode =
  | "chat"
  | "models"
  | "library"
  | "settings"
  | "vaults"
  | "graph"
  | "diagnostics";
const modeLabels: Record<Mode, string> = {
  chat: "Ask your knowledge",
  models: "Models",
  library: "Document library",
  settings: "Settings & providers",
  vaults: "Obsidian vaults",
  graph: "Knowledge graph",
  diagnostics: "Diagnostics & help",
};

export function WorkspaceApp({ mode }: { mode: Mode }) {
  const { generation } = useIdentity();
  return <WorkspaceContent key={generation} mode={mode} />;
}

function WorkspaceContent({ mode }: { mode: Mode }) {
  const { identity, sessionError, retry } = useIdentity();
  const router = useRouter();
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState("");
  const [chats, setChats] = useState<Chat[]>([]);
  const [chatId, setChatId] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [settings, setSettings] = useState<PublicSettings | null>(null);
  const [question, setQuestion] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(true);
  const [historyQuery, setHistoryQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [libraryView, setLibraryView] = useState<"list" | "grid">("grid");
  const [libraryPage, setLibraryPage] = useState(0);
  const [dragOver, setDragOver] = useState(false);
  const [settingsTab, setSettingsTab] = useState("models");
  const canManageServer = identity?.profile === "local" || identity?.user?.admin;
  const settingsTabs = [
    ["models", "Models & privacy"],
    ["retrieval", "Retrieval & indexes"],
    ...(canManageServer ? [["defaults", "Server defaults"]] : []),
  ];
  const [answering, setAnswering] = useState(false);
  const [aiSelection, setAiSelection] = useState<AISelection | null>(null);
  const [streamedText, setStreamedText] = useState("");
  const generationAbort = useRef<AbortController | null>(null);
  const conversation = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const [source, setSource] = useState<Source | null>(null);
  const [sourceLoading, setSourceLoading] = useState(false);
  const [model, setModel] = useState("");
  const [provider, setProvider] = useState<"mock" | "groq">("mock");
  const [freeConfirmed, setFreeConfirmed] = useState(false);
  const [consent, setConsent] = useState(false);
  const [retrieval, setRetrieval] = useState<ChatRetrieval>({
    filters: {},
    diagnostics: false,
  });
  const [libraryQuery, setLibraryQuery] = useState("");
  const [librarySort, setLibrarySort] = useState("newest");
  const bottom = useRef<HTMLDivElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const selection = useRef(0);
  const activeWorkspace = workspaces.find((w) => w.id === workspaceId);
  const selectedModel = activeModel(aiSelection);
  const readyDocuments = documents.filter(
    (d) => d.status === "ready" && !d.needs_reindex,
  );
  const latestCitations =
    messages.filter((m) => m.role === "assistant").at(-1)?.citations || [];
  const visibleDocuments = documents
    .filter((doc) =>
      doc.title.toLocaleLowerCase().includes(libraryQuery.toLocaleLowerCase()),
    )
    .toSorted((a, b) =>
      librarySort === "title"
        ? a.title.localeCompare(b.title)
        : librarySort === "status"
          ? a.status.localeCompare(b.status)
          : b.created_at.localeCompare(a.created_at),
    );

  const fail = useCallback(
    (cause: unknown) =>
      setError(
        cause instanceof Error
          ? cause.message
          : "Something went wrong. Please try again.",
      ),
    [],
  );

  const loadWorkspace = useCallback(
    async (id: string) => {
      const sequence = ++selection.current;
      setLoading(true);
      setWorkspaceId(id);
      setMessages([]);
      setChatId("");
      setSource(null);
      setAiSelection(null);
      setStreamedText("");
      try {
        const [docs, history, ai] = await Promise.all([
          api<Document[]>(`/api/workspaces/${id}/documents`),
          api<Chat[]>(`/api/workspaces/${id}/chats`),
          api<AISelection>(`/api/workspaces/${id}/ai-selection`),
        ]);
        if (sequence !== selection.current) return;
        setDocuments(docs);
        setChats(history);
        setAiSelection(ai);
        localStorage.setItem("nexus-workspace", id);
      } catch (cause) {
        fail(cause);
      } finally {
        if (sequence === selection.current) setLoading(false);
      }
    },
    [fail],
  );

  useEffect(() => {
    if (!identity) return;
    let cancelled = false;
    async function initialize() {
      try {
        const [spaces, config] = await Promise.all([
          api<Workspace[]>("/api/workspaces"),
          api<PublicSettings>("/api/settings/public"),
        ]);
        if (cancelled) return;
        setWorkspaces(spaces);
        setSettings(config);
        setProvider(config.generation_provider);
        setModel(config.generation_model);
        setFreeConfirmed(config.free_tier_confirmed);
        const saved = localStorage.getItem("nexus-workspace");
        const id = spaces.find((w) => w.id === saved)?.id || spaces[0]?.id;
        if (id) {
          setConsent(spaces.find((w) => w.id === id)?.cloud_opt_in || false);
          await loadWorkspace(id);
        } else setLoading(false);
      } catch (cause) {
        if (!cancelled) {
          fail(cause);
          setLoading(false);
        }
      }
    }
    void initialize();
    return () => {
      cancelled = true;
    };
  }, [loadWorkspace, fail, identity]);

  useEffect(() => {
    if (
      !workspaceId ||
      !documents.some((d) =>
        ["queued", "processing", "deleting"].includes(d.status),
      )
    )
      return;
    let cancelled = false;
    const timer = setInterval(async () => {
      try {
        const docs = await api<Document[]>(
          `/api/workspaces/${workspaceId}/documents`,
        );
        if (!cancelled) setDocuments(docs);
      } catch {
        /* A foreground action reports connection errors; polling retries quietly. */
      }
    }, 2000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [workspaceId, documents]);

  useEffect(() => {
    if (stickToBottom.current)
      bottom.current?.scrollIntoView({
        behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
          ? "instant"
          : "smooth",
      });
  }, [messages, busy, streamedText]);

  const reloadAI = useCallback(async () => {
    if (workspaceId) {
      const next = await api<AISelection>(`/api/workspaces/${workspaceId}/ai-selection`);
      setAiSelection(next);
      setConsent(next.workspace_cloud_allowed);
      setWorkspaces((spaces) =>
        spaces.map((space) =>
          space.id === workspaceId
            ? { ...space, cloud_opt_in: next.workspace_cloud_allowed }
            : space,
        ),
      );
    }
  }, [workspaceId]);

  async function chooseChat(chat: Chat) {
    if (busy) return;
    if (mode !== "chat") {
      router.push(`/?chat=${encodeURIComponent(chat.id)}`);
      return;
    }
    const sequence = ++selection.current;
    try {
      const detail = await api<{ messages: Message[] }>(
        `/api/chats/${chat.id}?workspace_id=${workspaceId}`,
      );
      if (sequence === selection.current) {
        setChatId(chat.id);
        setMessages(detail.messages);
        setMobileOpen(false);
      }
    } catch (cause) {
      fail(cause);
    }
  }

  useEffect(() => {
    if (mode !== "chat" || !workspaceId || loading) return;
    const id = new URLSearchParams(window.location.search).get("chat");
    if (!id) return;
    let cancelled = false;
    api<{ messages: Message[] }>(
      `/api/chats/${encodeURIComponent(id)}?workspace_id=${workspaceId}`,
    )
      .then((detail) => {
        if (!cancelled) {
          setChatId(id);
          setMessages(detail.messages);
          window.history.replaceState({}, "", "/");
        }
      })
      .catch(fail);
    return () => {
      cancelled = true;
    };
  }, [mode, workspaceId, loading, fail]);

  async function newWorkspace() {
    const name = window.prompt("Name your workspace");
    if (!name?.trim()) return;
    try {
      const workspace = await api<Workspace>("/api/workspaces", {
        method: "POST",
        body: JSON.stringify({ name: name.trim() }),
      });
      setWorkspaces([...workspaces, workspace]);
      setConsent(false);
      await loadWorkspace(workspace.id);
    } catch (cause) {
      fail(cause);
    }
  }

  async function newChat() {
    if (mode !== "chat") {
      router.push("/");
      return;
    }
    selection.current++;
    setChatId("");
    setMessages([]);
    setQuestion("");
    setMobileOpen(false);
    document.getElementById("question")?.focus();
  }

  async function send(event: React.FormEvent) {
    event.preventDefault();
    if (!question.trim() || busy || !workspaceId || !selectedModel) return;
    const content = question.trim();
    const controller = new AbortController();
    generationAbort.current = controller;
    setAnswering(true);
    setStreamedText("");
    stickToBottom.current = true;
    setBusy(true);
    setError("");
    try {
      let id = chatId;
      if (!id) {
        const chat = await api<Chat>(`/api/workspaces/${workspaceId}/chats`, {
          method: "POST",
        });
        id = chat.id;
        setChatId(id);
      }
      const answer = aiSelection?.active?.streaming
        ? await streamAnswer(
            `/api/chats/${id}/messages/stream?workspace_id=${workspaceId}`,
            { content, ...retrieval },
            controller.signal,
            setStreamedText,
          )
        : await api<Message>(
            `/api/chats/${id}/messages?workspace_id=${workspaceId}`,
            {
              method: "POST",
              body: JSON.stringify({ content, ...retrieval }),
              signal: controller.signal,
            },
          );
      setStreamedText("");
      setAnswering(false);
      setMessages((previous) => [
        ...previous,
        {
          id: crypto.randomUUID(),
          role: "user",
          content,
          provider: null,
          citations: [],
        },
        answer,
      ]);
      setQuestion("");
      setChats(await api<Chat[]>(`/api/workspaces/${workspaceId}/chats`));
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === "AbortError") {
        setNotice(
          "Stopped waiting. The server may still save this answer; open conversation history to check.",
        );
        setChats(await api<Chat[]>(`/api/workspaces/${workspaceId}/chats`));
      } else fail(cause);
    } finally {
      generationAbort.current = null;
      setAnswering(false);
      setStreamedText("");
      setBusy(false);
    }
  }

  async function upload(files: FileList | File[] | null) {
    if (!files?.length || !workspaceId) return;
    setBusy(true);
    setError("");
    try {
      let duplicates = 0;
      for (const file of Array.from(files)) {
        setUploadProgress(0);
        const result = await uploadFile(workspaceId, file, setUploadProgress);
        if (result.duplicate) duplicates++;
      }
      setDocuments(
        await api<Document[]>(`/api/workspaces/${workspaceId}/documents`),
      );
      setNotice(
        duplicates
          ? `${duplicates} existing document(s) recognized. New files are queued for indexing.`
          : "Upload complete. Your documents are being indexed locally.",
      );
    } catch (cause) {
      fail(cause);
    } finally {
      setBusy(false);
      setUploadProgress(null);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  const openSource = useCallback(
    async (citation: Citation) => {
      setSourceLoading(true);
      try {
        setSource(await api<Source>(citation.source_url));
      } catch (cause) {
        fail(cause);
      } finally {
        setSourceLoading(false);
      }
    },
    [fail],
  );

  async function documentAction(
    doc: Document,
    action: "reindex" | "delete" | "open",
  ) {
    if (
      action === "delete" &&
      !window.confirm(
        `Delete ${doc.title} and its indexed evidence? This also removes its saved citations.`,
      )
    )
      return;
    try {
      if (action === "open")
        setSource(
          await api<Source>(
            `/api/documents/${doc.id}/source?workspace_id=${workspaceId}`,
          ),
        );
      else {
        await api(
          `/api/documents/${doc.id}${action === "reindex" ? "/reindex" : ""}?workspace_id=${workspaceId}`,
          { method: action === "delete" ? "DELETE" : "POST" },
        );
        setDocuments(
          await api<Document[]>(`/api/workspaces/${workspaceId}/documents`),
        );
      }
    } catch (cause) {
      fail(cause);
    }
  }

  async function editChat(chat: Chat, action: "rename" | "delete") {
    const title =
      action === "rename"
        ? window.prompt("Conversation title", chat.title)
        : null;
    if (action === "rename" && !title?.trim()) return;
    if (
      action === "delete" &&
      !window.confirm(`Delete conversation “${chat.title}”?`)
    )
      return;
    try {
      await api(`/api/chats/${chat.id}?workspace_id=${workspaceId}`, {
        method: action === "rename" ? "PATCH" : "DELETE",
        ...(title ? { body: JSON.stringify({ title }) } : {}),
      });
      setChats(await api<Chat[]>(`/api/workspaces/${workspaceId}/chats`));
      if (action === "delete" && chatId === chat.id) {
        setChatId("");
        setMessages([]);
      }
    } catch (cause) {
      fail(cause);
    }
  }

  async function saveSettings(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const config = await api<PublicSettings>("/api/settings/public", {
        method: "PATCH",
        body: JSON.stringify({
          generation_provider: provider,
          generation_model: model,
          free_tier_confirmed: freeConfirmed,
        }),
      });
      const workspace = await api<Workspace>(`/api/workspaces/${workspaceId}`, {
        method: "PATCH",
        body: JSON.stringify({ cloud_opt_in: consent }),
      });
      setSettings(config);
      setWorkspaces(
        workspaces.map((w) => (w.id === workspace.id ? workspace : w)),
      );
      setNotice("Provider settings and workspace privacy choice saved.");
    } catch (cause) {
      fail(cause);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    function shortcut(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setSearchOpen((value) => !value);
      }
    }
    window.addEventListener("keydown", shortcut);
    return () => window.removeEventListener("keydown", shortcut);
  }, []);
  const filteredChats = chats.filter((chat) =>
    chat.title.toLowerCase().includes(historyQuery.toLowerCase()),
  );
  const renderChat = (chat: Chat) => (
    <div className={`chat-row ${chatId === chat.id ? "selected" : ""}`}>
      <button
        className="chat-title"
        onClick={() => chooseChat(chat)}
        disabled={busy}
      >
        <Icon name="chat" size={15} />
        <span>{chat.title}</span>
      </button>
      <button
        className="icon-button small"
        aria-label={`Rename ${chat.title}`}
        onClick={() => editChat(chat, "rename")}
        disabled={busy}
      >
        <Icon name="edit" size={13} />
      </button>
      <button
        className="icon-button small"
        aria-label={`Delete ${chat.title}`}
        onClick={() => editChat(chat, "delete")}
        disabled={busy}
      >
        <Icon name="trash" size={13} />
      </button>
    </div>
  );

  const renderDocument = (doc: Document) => (
    <article className="document-row" key={doc.id}>
      <span className={`file-symbol ${doc.extension.slice(1)}`}>
        <Icon name="files" size={21} />
      </span>
      <div className="document-info">
        <button
          className="document-title"
          onClick={() => documentAction(doc, "open")}
          disabled={doc.status !== "ready"}
        >
          {doc.title}
        </button>
        <span>
          {doc.extension.slice(1).toUpperCase()} ·{" "}
          {doc.size < 1024 * 1024
            ? `${Math.max(1, Math.round(doc.size / 1024))} KB`
            : `${(doc.size / 1024 / 1024).toFixed(1)} MB`}{" "}
          · {new Date(doc.created_at).toLocaleDateString()}
        </span>
        {doc.error && <p className="document-error">{doc.error}</p>}
      </div>
      <span className={`document-status ${doc.status}`}>
        {["queued", "processing"].includes(doc.status) && (
          <span className="loader tiny" />
        )}
        {doc.needs_reindex
          ? "reindex required"
          : doc.status.replaceAll("_", " ")}
      </span>
      <button
        className="icon-button"
        aria-label={`Reindex ${doc.title}`}
        disabled={["queued", "processing"].includes(doc.status)}
        onClick={() =>
          documentAction(doc, doc.status === "deleting" ? "delete" : "reindex")
        }
      >
        <Icon name="refresh" size={17} />
      </button>
      <button
        className="icon-button danger"
        aria-label={`Delete ${doc.title}`}
        onClick={() => documentAction(doc, "delete")}
      >
        <Icon name="trash" size={17} />
      </button>
    </article>
  );
  return (
    <div className={`app-shell mode-${mode}`}>
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <NavigationRail
        mode={mode}
        busy={busy || !identity}
        workspaces={workspaces}
        workspaceId={workspaceId}
        onWorkspace={(id) => {
          setConsent(
            workspaces.find((w) => w.id === id)?.cloud_opt_in || false,
          );
          void loadWorkspace(id);
        }}
        onCreate={identity?.guest ? undefined : newWorkspace}
        onHistory={() => {
          if (matchMedia("(max-width:900px)").matches) setSearchOpen(true);
          else setHistoryOpen((value) => !value);
        }}
        onSearch={() => setSearchOpen(true)}
        mobileOpen={mobileOpen}
        onMobileClose={() => setMobileOpen(false)}
      />
      {mode === "chat" && (
        <aside
          className={`conversation-pane ${historyOpen ? "" : "is-collapsed"}`}
          aria-label="Conversation history"
        >
          <div className="conversation-pane-heading">
            <span className="eyebrow">YOUR SPACE</span>
            <button
              className="icon-button"
              aria-label="Hide conversations"
              onClick={() => setHistoryOpen(false)}
            >
              <Icon name="menu" size={16} />
            </button>
          </div>
          <h2>{activeWorkspace?.name || "Workspace"}</h2>
          <button
            className="new-chat"
            onClick={newChat}
            disabled={busy || !workspaceId}
          >
            <Icon name="plus" size={17} />
            New conversation<kbd>↗</kbd>
          </button>
          <label className="history-search">
            <Icon name="search" size={14} />
            <input
              aria-label="Search conversations"
              placeholder="Search conversations"
              value={historyQuery}
              onChange={(event) => setHistoryQuery(event.target.value)}
            />
          </label>
          <div className="section-label">
            RECENT CONVERSATIONS{" "}
            <span>{filteredChats.length.toString().padStart(2, "0")}</span>
            <button
              className="icon-button"
              aria-label="Refresh conversations"
              onClick={() =>
                api<Chat[]>(`/api/workspaces/${workspaceId}/chats`)
                  .then(setChats)
                  .catch(fail)
              }
            >
              <Icon name="refresh" size={13} />
            </button>
          </div>
          {filteredChats.length ? (
            <VirtualList
              items={filteredChats}
              rowHeight={44}
              render={renderChat}
              label="Recent conversations"
              className="chat-list"
            />
          ) : (
            <p className="sidebar-empty">
              A new thought starts here.
              <br />
              Your conversations will appear here.
            </p>
          )}
          <div className="history-footer">
            <span className="status-dot" />
            Local sources. Traceable answers.
          </div>
        </aside>
      )}
      <div className="main-column">
        <header className="workspace-context">
          <button
            className="icon-button mobile-toggle"
            aria-label="Open navigation"
            onClick={() => setMobileOpen(true)}
          >
            <Icon name="menu" />
          </button>
          <Brand />
          <span className="context-divider" />
          <span className="context-workspace">
            {activeWorkspace?.name || "Your workspace"}
          </span>
          <span className="context-section">{modeLabels[mode]}</span>
          <Link
            className="button primary select-llm"
            href="/models"
            aria-label={selectedModel ? `Change model: ${selectedModel.model}` : "Select LLM"}
          >
            <Icon name="spark" size={16} />
            <span>{selectedModel?.model ?? "Select LLM"}</span>
          </Link>
        </header>
        <PageTransition>
          <main
            id="main"
            className={mode === "chat" ? "chat-main" : "page-main"}
          >
            {sessionError && (
              <div className="alert error" role="alert">
                <span>{sessionError}</span>
                <button className="button secondary" onClick={retry}>Retry connection</button>
              </div>
            )}
            {error && (
              <div className="alert error" role="alert">
                <span>{error}</span>
                <button
                  className="icon-button"
                  aria-label="Dismiss error"
                  onClick={() => setError("")}
                >
                  <Icon name="close" size={16} />
                </button>
              </div>
            )}
            {notice && (
              <div className="alert notice" role="status">
                <span>{notice}</span>
                <button
                  className="icon-button"
                  aria-label="Dismiss notification"
                  onClick={() => setNotice("")}
                >
                  <Icon name="close" size={16} />
                </button>
              </div>
            )}
            {sourceLoading && (
              <div className="source-loading" role="status">
                Opening original evidence…
              </div>
            )}
            {loading && mode !== "chat" && mode !== "models" ? (
              <div className="loading-state" role="status">
                <Skeleton />
              </div>
            ) : !workspaceId && identity && !loading ? (
              <div className="page-content">
                <span className="eyebrow">WELCOME TO NEXUS</span>
                <h1>Create your first workspace.</h1>
                <p>
                  Begin with a private workspace, then add a PDF, Markdown, DOCX
                  or the included synthetic vault.
                </p>
                <button className="button primary" onClick={newWorkspace}>
                  Create workspace
                </button>
              </div>
            ) : mode === "models" ? (
              <div className="page-content settings-content">
                <div className="page-heading">
                  <div>
                    <h1>Select an LLM</h1>
                    <p>Connect a provider and choose the model for this workspace.</p>
                  </div>
                </div>
                {workspaceId && aiSelection ? (
                  <ModelPicker
                    key={workspaceId}
                    workspaceId={workspaceId}
                    selection={aiSelection}
                    onChanged={reloadAI}
                    onSaved={() => router.push("/")}
                  />
                ) : !sessionError && <Skeleton label="Opening your workspace" />}
              </div>
            ) : mode === "chat" ? (
              <>
                {workspaceId && <RetrievalControls
                  key={workspaceId}
                  workspaceId={workspaceId}
                  documents={documents}
                  disabled={busy}
                  onChange={setRetrieval}
                  onError={fail}
                />}
                <div
                  className="conversation"
                  ref={conversation}
                  onScroll={(event) => {
                    const node = event.currentTarget;
                    stickToBottom.current =
                      node.scrollHeight - node.scrollTop - node.clientHeight <
                      120;
                  }}
                  aria-live="polite"
                >
                  {!messages.length &&
                  !(answering && aiSelection?.active?.streaming) ? (
                    <div className="welcome">
                      <div className="welcome-depth" aria-hidden="true">
                        <span className="orbit orbit-one" />
                        <span className="orbit orbit-two" />
                        <span className="depth-dot dot-one" />
                        <span className="depth-dot dot-two" />
                      </div>
                      <div className="welcome-emblem">
                        <Icon name="spark" size={31} />
                      </div>
                      <span className="eyebrow">YOUR KNOWLEDGE, CONNECTED</span>
                      <h1>
                        Your knowledge.
                        <br />
                        <em>One connected space.</em>
                      </h1>
                      <p>
                        Bring your documents. Ask a question.
                        <br />
                        Get answers you can trace back to the source.
                      </p>
                      <div className="starter-grid">
                        <button
                          onClick={() => {
                            setQuestion(
                              "What are the key takeaways from my documents?",
                            );
                            document.getElementById("question")?.focus();
                          }}
                        >
                          <Icon name="book" />
                          <strong>See the bigger picture</strong>
                          <span>Find the key ideas in your documents</span>
                          <b>↗</b>
                        </button>
                        <button
                          onClick={() => {
                            setQuestion(
                              "Where do my documents agree or differ?",
                            );
                            document.getElementById("question")?.focus();
                          }}
                        >
                          <Icon name="spark" />
                          <strong>Connect the dots</strong>
                          <span>Explore a question across your sources</span>
                          <b>↗</b>
                        </button>
                      </div>
                      <div className="recent-knowledge">
                        <div className="section-label">
                          RECENT KNOWLEDGE
                          <Link href="/library">
                            View library <Icon name="external" size={12} />
                          </Link>
                        </div>
                        {documents.slice(0, 3).map((doc) => (
                          <button
                            key={doc.id}
                            onClick={() => documentAction(doc, "open")}
                            disabled={doc.status !== "ready"}
                          >
                            <span
                              className={`file-symbol ${doc.extension.slice(1)}`}
                            >
                              <Icon name="files" size={16} />
                            </span>
                            <span>
                              {doc.title}
                              <small>
                                {doc.extension.slice(1).toUpperCase()} ·{" "}
                                {doc.status}
                              </small>
                            </span>
                            <Icon name="chevron" size={14} />
                          </button>
                        ))}
                        {!documents.length && (
                          <Link className="recent-empty" href="/library">
                            <Icon name="plus" size={17} />
                            Add your first source
                            <span>PDF, Markdown, DOCX or text</span>
                          </Link>
                        )}
                      </div>
                      <div className="welcome-foot">
                        <span className="status-dot" />
                        {readyDocuments.length ? (
                          `${readyDocuments.length} document${readyDocuments.length === 1 ? "" : "s"} ready to explore`
                        ) : (
                          <>
                            Start with a PDF, Markdown, or text file{" "}
                            <Link href="/library">
                              Add your first document ↗
                            </Link>
                          </>
                        )}
                      </div>
                    </div>
                  ) : (
                    <div className="message-list">
                      {messages.map((message) => (
                        <article
                          className={`message ${message.role}`}
                          key={message.id}
                        >
                          <div className="message-avatar">
                            {message.role === "user" ? (
                              "Y"
                            ) : (
                              <Icon name="spark" size={17} />
                            )}
                          </div>
                          <div className="message-body">
                            <div className="message-author">
                              {message.role === "user" ? "You" : "NEXUS"}
                              {message.provider === "mock" && (
                                <span className="subtle-tag">
                                  EXTRACTIVE DEMO
                                </span>
                              )}
                            </div>
                            <div className="answer-text">
                              {message.role === "user" ? (
                                <p>{message.content}</p>
                              ) : (
                                <RichMessage
                                  content={message.content}
                                  citations={message.citations}
                                  onCitation={openSource}
                                />
                              )}
                            </div>
                            {message.role === "assistant" && (
                              <AnswerFeedback
                                messageId={message.id}
                                workspaceId={workspaceId}
                              />
                            )}
                            {message.citations.length > 0 && (
                              <div className="message-evidence">
                                <Icon name="check" size={14} />
                                {message.citations.length} source passage
                                {message.citations.length === 1 ? "" : "s"} ·
                                click a citation to verify
                              </div>
                            )}
                            {message.diagnostics &&
                              typeof message.diagnostics.elapsed_ms ===
                                "number" && (
                                <details className="message-diagnostics">
                                  <summary>
                                    Retrieval diagnostics ·{" "}
                                    {message.diagnostics.mode} ·{" "}
                                    {message.diagnostics.elapsed_ms.toFixed(1)}{" "}
                                    ms
                                  </summary>
                                  <p>
                                    Embedding:{" "}
                                    {message.diagnostics.embedding_provider} ·{" "}
                                    {message.diagnostics.embedding_provider ===
                                    "hash"
                                      ? "lexical hash demo; not semantic understanding"
                                      : message.diagnostics.embedding_model}
                                  </p>
                                  <p>
                                    {message.diagnostics.authorized_documents}{" "}
                                    authorized documents ·{" "}
                                    {message.diagnostics.candidate_count}{" "}
                                    candidates ·{" "}
                                    {message.diagnostics.excerpt_bytes} excerpt
                                    bytes ·{" "}
                                    {message.diagnostics.additional_cloud_calls}{" "}
                                    additional cloud calls
                                  </p>
                                  <p>
                                    Standalone query:{" "}
                                    {message.diagnostics.standalone_query}
                                  </p>
                                  {message.diagnostics.warnings.map(
                                    (warning, index) => (
                                      <p key={index}>{warning}</p>
                                    ),
                                  )}
                                  <pre>
                                    {JSON.stringify(
                                      {
                                        stages: message.diagnostics.stages,
                                        final: message.diagnostics.final,
                                      },
                                      null,
                                      2,
                                    )}
                                  </pre>
                                </details>
                              )}
                          </div>
                        </article>
                      ))}
                      {answering && aiSelection?.active?.streaming && (
                        <>
                          <article className="message user pending-message">
                            <div className="message-avatar">Y</div>
                            <div className="message-body">
                              <div className="message-author">You</div>
                              <div className="answer-text">
                                <p>{question}</p>
                              </div>
                            </div>
                          </article>
                          {streamedText && (
                            <article className="message assistant provisional-message">
                              <div className="message-avatar">
                                <Icon name="spark" size={17} />
                              </div>
                              <div className="message-body">
                                <div className="message-author">
                                  NEXUS
                                  <span className="subtle-tag">
                                    PROVISIONAL
                                  </span>
                                </div>
                                <div className="provisional-text">
                                  {streamedText}
                                </div>
                                <p className="provisional-note" role="status">
                                  Generating · source references become
                                  clickable after verification.
                                </p>
                              </div>
                            </article>
                          )}
                        </>
                      )}
                      {answering && !streamedText && (
                        <div className="thinking" role="status">
                          <span className="loader" />
                          Finding evidence and preparing your answer…
                        </div>
                      )}
                      <div ref={bottom} />
                    </div>
                  )}
                </div>
                <div className="composer-wrap">
                  <form className="composer" onSubmit={send}>
                    <label className="sr-only" htmlFor="question">
                      Ask a question about your documents
                    </label>
                    <textarea
                      id="question"
                      placeholder="Ask anything about your documents…"
                      value={question}
                      onChange={(event) => setQuestion(event.target.value)}
                      rows={2}
                      maxLength={4000}
                      disabled={busy}
                      onKeyDown={(event) => {
                        if (
                          event.key === "Enter" &&
                          !event.shiftKey &&
                          !event.nativeEvent.isComposing
                        ) {
                          event.preventDefault();
                          event.currentTarget.form?.requestSubmit();
                        }
                      }}
                    />
                    <div className="composer-tools">
                      <Link href="/library" className="attach-link">
                        <Icon name="plus" size={17} />
                        <span>Add sources</span>
                      </Link>
                      <Link href="/models" className="composer-model">
                        <Icon name="spark" size={13} />
                        {selectedModel?.model ?? "Select an LLM to start chatting"}
                        <Icon name="chevron" size={12} />
                      </Link>
                      {answering && (
                        <button
                          type="button"
                          className="stop-waiting"
                          onClick={() => generationAbort.current?.abort()}
                          title="Stops receiving this response. Provider usage may still be charged; check history before retrying."
                        >
                          <Icon name="stop" size={13} />
                          {aiSelection?.active?.streaming
                            ? "Stop response"
                            : "Stop waiting"}
                        </button>
                      )}
                      <button
                        type="submit"
                        className="send-button"
                        disabled={
                          busy ||
                          !question.trim() ||
                          !workspaceId ||
                          !selectedModel
                        }
                        aria-label="Send question"
                      >
                        <Icon name="arrow" size={19} />
                      </button>
                    </div>
                  </form>
                  <p className="composer-disclaimer">
                    {identity?.guest && !readyDocuments.length
                      ? "Add sources for answers with citations. Without sources, the model answers directly."
                      : "Always follow the evidence. Answers may be incomplete."}
                  </p>
                </div>
              </>
            ) : mode === "diagnostics" ? (
              <DiagnosticsPanel workspaceId={workspaceId} onError={fail} guest={!!identity?.guest} />
            ) : mode === "vaults" ? (
              <VaultManager
                key={workspaceId}
                workspaceId={workspaceId}
                onSource={setSource}
                onError={fail}
              />
            ) : mode === "graph" ? (
              <GraphExplorer
                key={workspaceId}
                workspaceId={workspaceId}
                onSource={setSource}
                onError={fail}
              />
            ) : mode === "library" ? (
              <div className="page-content library-content">
                <span className="eyebrow">YOUR KNOWLEDGE BASE</span>
                <div className="page-heading">
                  <div>
                    <h1>A home for your sources.</h1>
                    <p>Add the documents you want to think with.</p>
                  </div>
                  <button
                    className="button primary"
                    onClick={() => fileInput.current?.click()}
                    disabled={busy || !workspaceId}
                  >
                    <Icon name="plus" size={18} />
                    Add documents
                  </button>
                </div>
                <input
                  ref={fileInput}
                  type="file"
                  className="sr-only"
                  aria-label="Upload documents"
                  accept=".pdf,.md,.txt,.docx"
                  multiple
                  onChange={(event) => upload(event.target.files)}
                />
                <div
                  className={`upload-zone ${dragOver ? "is-dragging" : ""}`}
                  onDragOver={(event) => {
                    event.preventDefault();
                    setDragOver(true);
                  }}
                  onDragLeave={(event) => {
                    if (
                      !(event.relatedTarget instanceof Node) ||
                      !event.currentTarget.contains(event.relatedTarget)
                    )
                      setDragOver(false);
                  }}
                  onDrop={(event) => {
                    event.preventDefault();
                    setDragOver(false);
                    if (!busy) void upload(event.dataTransfer.files);
                  }}
                >
                  <div className="upload-symbol">
                    <Icon name="upload" size={25} />
                  </div>
                  <h2>Make room for a new perspective</h2>
                  <p>
                    Drop files here, or{" "}
                    <button
                      className="text-button"
                      disabled={busy}
                      onClick={() => fileInput.current?.click()}
                    >
                      browse your computer
                    </button>
                  </p>
                  <span>
                    Text-based PDF, Markdown, TXT, DOCX · up to{" "}
                    {settings?.max_upload_mb || 20} MB each
                  </span>
                  {uploadProgress !== null && (
                    <div className="upload-progress" role="status">
                      <progress max={100} value={uploadProgress} />
                      <span>Uploading · {uploadProgress}%</span>
                    </div>
                  )}
                </div>
                <div className="note-filter-row library-filters">
                  <label>
                    Search documents
                    <input
                      value={libraryQuery}
                      onChange={(event) => {
                        setLibraryQuery(event.target.value);
                        setLibraryPage(0);
                      }}
                      placeholder="Find a filename"
                    />
                  </label>
                  <label>
                    Sort by
                    <select
                      value={librarySort}
                      onChange={(event) => setLibrarySort(event.target.value)}
                    >
                      <option value="newest">Newest first</option>
                      <option value="title">Filename</option>
                      <option value="status">Ingestion status</option>
                    </select>
                  </label>
                  <Link className="button secondary" href="/vaults">
                    Browse vault notes & tags ↗
                  </Link>
                </div>
                <div className="library-summary">
                  <button
                    className="button secondary"
                    disabled={
                      busy ||
                      !documents.some((d) =>
                        ["failed", "needs_ocr"].includes(d.status),
                      )
                    }
                    onClick={async () => {
                      setBusy(true);
                      try {
                        const ids = documents
                          .filter((d) =>
                            ["failed", "needs_ocr"].includes(d.status),
                          )
                          .slice(0, 100)
                          .map((d) => d.id);
                        const result = await api<{ accepted: number }>(
                          `/api/workspaces/${workspaceId}/batch-reindex`,
                          {
                            method: "POST",
                            body: JSON.stringify({ document_ids: ids }),
                          },
                        );
                        setNotice(
                          `${result.accepted} document jobs accepted. Review individual status for remaining failures.`,
                        );
                        await loadWorkspace(workspaceId);
                      } catch (cause) {
                        fail(cause);
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    Retry failed documents
                  </button>
                  <h2>
                    All documents <span>{documents.length}</span>
                  </h2>
                  <span>
                    {readyDocuments.length} ready ·{" "}
                    {
                      documents.filter((d) =>
                        ["queued", "processing"].includes(d.status),
                      ).length
                    }{" "}
                    indexing
                  </span>
                </div>
                <div className="library-view-controls">
                  <span>
                    {visibleDocuments.length} sources in your knowledge base
                  </span>
                  <div role="group" aria-label="Document layout">
                    <button
                      className={`icon-button ${libraryView === "grid" ? "active" : ""}`}
                      aria-label="Grid view"
                      aria-pressed={libraryView === "grid"}
                      onClick={() => setLibraryView("grid")}
                    >
                      <Icon name="grid" size={17} />
                    </button>
                    <button
                      className={`icon-button ${libraryView === "list" ? "active" : ""}`}
                      aria-label="List view"
                      aria-pressed={libraryView === "list"}
                      onClick={() => setLibraryView("list")}
                    >
                      <Icon name="list" size={17} />
                    </button>
                  </div>
                </div>
                <div
                  className={`document-list ${libraryView === "grid" ? "document-grid" : "document-rows"}`}
                >
                  {visibleDocuments.length ? (
                    libraryView === "list" ? (
                      <VirtualList
                        items={visibleDocuments}
                        rowHeight={128}
                        render={renderDocument}
                        label="Document list"
                        className="virtual-document-list"
                      />
                    ) : (
                      visibleDocuments
                        .slice(libraryPage * 30, libraryPage * 30 + 30)
                        .map(renderDocument)
                    )
                  ) : (
                    <div className="library-empty">
                      <Icon name="book" size={28} />
                      <h3>Good questions start with good sources.</h3>
                      <p>Your uploaded documents will appear here.</p>
                    </div>
                  )}
                </div>
                {libraryView === "grid" && visibleDocuments.length > 30 && (
                  <div className="pagination">
                    <button
                      className="button secondary"
                      disabled={libraryPage === 0}
                      onClick={() => setLibraryPage((page) => page - 1)}
                    >
                      Previous
                    </button>
                    <span>
                      Page {libraryPage + 1} of{" "}
                      {Math.ceil(visibleDocuments.length / 30)}
                    </span>
                    <button
                      className="button secondary"
                      disabled={
                        (libraryPage + 1) * 30 >= visibleDocuments.length
                      }
                      onClick={() => setLibraryPage((page) => page + 1)}
                    >
                      Next
                    </button>
                  </div>
                )}
                <p className="page-note">
                  Documents are stored and indexed on this computer. Scanned
                  PDFs use optional OCR when explicitly enabled. DOCX text,
                  headings and tables are supported; embedded images remain
                  text-only.
                </p>
              </div>
            ) : (
              <div className="page-content settings-content">
                <span className="eyebrow">MAKE IT YOURS</span>
                <div className="page-heading">
                  <div>
                    <h1>Your models. Your choice.</h1>
                    <p>Local evidence, with generation on your terms.</p>
                  </div>
                </div>
                <div
                  className="settings-tabs"
                  role="tablist"
                  aria-label="Settings sections"
                >
                  {settingsTabs.map(([id, label]) => (
                    <button
                      key={id}
                      role="tab"
                      tabIndex={settingsTab === id ? 0 : -1}
                      aria-selected={settingsTab === id}
                      aria-controls={`settings-${id}`}
                      id={`tab-${id}`}
                      onClick={() => setSettingsTab(id)}
                      onKeyDown={(event) => {
                        const ids = settingsTabs.map(([tab]) => tab);
                        const index = ids.indexOf(id);
                        const next =
                          event.key === "ArrowRight"
                            ? ids[(index + 1) % ids.length]
                            : event.key === "ArrowLeft"
                              ? ids[(index + ids.length - 1) % ids.length]
                              : event.key === "Home"
                                ? ids[0]
                                : event.key === "End"
                                  ? ids.at(-1)
                                  : null;
                        if (next) {
                          event.preventDefault();
                          setSettingsTab(next);
                          document.getElementById(`tab-${next}`)?.focus();
                        }
                      }}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                <div
                  role="tabpanel"
                  id="settings-retrieval"
                  aria-labelledby="tab-retrieval"
                  hidden={settingsTab !== "retrieval"}
                >
                  <AdvancedSettings
                    key={workspaceId}
                    workspaceId={workspaceId}
                    onError={fail}
                  />
                </div>
                <div
                  role="tabpanel"
                  id="settings-models"
                  aria-labelledby="tab-models"
                  hidden={settingsTab !== "models"}
                >
                  {identity?.guest ? (
                    <section className="settings-card">
                      <h2>Model and provider</h2>
                      <Link className="button primary" href="/models">Manage your model</Link>
                    </section>
                  ) : <>
                  <ByokControls
                    key={workspaceId}
                    workspaceId={workspaceId}
                    selection={aiSelection}
                    onChanged={reloadAI}
                    onError={fail}
                  />
                  <details className="settings-card workspace-administration">
                    <summary>Workspace defaults and administration</summary>
                    <ReleaseControls
                      workspaceId={workspaceId}
                      cloudPermission={aiSelection?.workspace_cloud_allowed}
                      onSaved={reloadAI}
                      onError={fail}
                    />
                  </details>
                  </>}
                </div>
                {canManageServer && <div
                  role="tabpanel"
                  id="settings-defaults"
                  aria-labelledby="tab-defaults"
                  hidden={settingsTab !== "defaults"}
                >
                  <p className="knowledge-disclosure">
                    Legacy server-wide defaults require an administrator in
                    server mode. A saved workspace model policy takes
                    precedence. Generation applies immediately; embedding
                    changes use the validated rebuild workflow.
                  </p>
                  <form onSubmit={saveSettings}>
                    <section className="settings-card">
                      <div className="card-heading">
                        <Icon name="spark" />
                        <div>
                          <h2>Answer provider</h2>
                          <p>
                            Switch generation without changing your document
                            index.
                          </p>
                        </div>
                      </div>
                      <label htmlFor="provider">Generation provider</label>
                      <select
                        id="provider"
                        value={provider}
                        onChange={(event) =>
                          setProvider(event.target.value as "mock" | "groq")
                        }
                      >
                        <option value="mock">
                          Offline demo — deterministic evidence extraction
                        </option>
                        <option value="groq">
                          Groq — eligible Free Plan account
                        </option>
                      </select>
                      <p className="field-help">
                        Offline demo quotes matching passages. Real generated
                        answers require a configured cloud provider.
                      </p>
                      <label htmlFor="model">Cloud model ID</label>
                      <input
                        id="model"
                        value={model}
                        onChange={(event) => setModel(event.target.value)}
                        required
                        maxLength={150}
                      />
                      <p className="field-help">
                        Choose a model available to your eligible free account.
                        Models and quotas can change.
                      </p>
                      <div className="key-status">
                        <span
                          className={`status-dot ${settings?.groq_key_configured ? "" : "amber"}`}
                        />
                        {settings?.groq_key_configured
                          ? "Server API key configured"
                          : "Server API key not configured"}
                      </div>
                      <p className="field-help">
                        Add NEXUS_GROQ_API_KEY to the server .env and restart
                        the API. Keys never enter the browser.
                      </p>
                      <label className="checkbox-row">
                        <input
                          type="checkbox"
                          checked={freeConfirmed}
                          onChange={(event) =>
                            setFreeConfirmed(event.target.checked)
                          }
                        />
                        <span>
                          I have checked that my Groq account and selected model
                          are eligible for its Free Plan.
                        </span>
                      </label>
                      <button
                        type="button"
                        className="button secondary"
                        disabled={
                          busy ||
                          !settings?.groq_key_configured ||
                          !settings.free_tier_confirmed
                        }
                        onClick={async () => {
                          try {
                            const result = await api<{
                              model_available: boolean;
                            }>("/api/providers/groq/check", { method: "POST" });
                            setNotice(
                              result.model_available
                                ? "Groq is reachable and the saved model is available. Billing tier and quota still require your own verification."
                                : "Groq is reachable, but the saved model is unavailable. Choose another model.",
                            );
                          } catch (cause) {
                            fail(cause);
                          }
                        }}
                      >
                        Check saved provider
                        <Icon name="external" size={15} />
                      </button>
                    </section>
                    <section className="settings-card privacy-card">
                      <div className="card-heading">
                        <Icon name="book" />
                        <div>
                          <h2>A clear boundary for your knowledge</h2>
                          <p>
                            Privacy choice for{" "}
                            {activeWorkspace?.name || "this workspace"}.
                          </p>
                        </div>
                      </div>
                      <p className="privacy-disclosure">
                        Cloud models receive your question and retrieved
                        document excerpts. Original files remain local. Your
                        provider&apos;s data policies apply.
                      </p>
                      <label className="checkbox-row">
                        <input
                          type="checkbox"
                          checked={consent}
                          onChange={(event) => setConsent(event.target.checked)}
                        />
                        <span>
                          I explicitly allow retrieved excerpts from this
                          workspace to be sent to the configured cloud model.
                        </span>
                      </label>
                      <p className="field-help">
                        Off by default. You can revoke this choice at any time.
                        No remote generation happens in offline demo mode.
                      </p>
                    </section>
                    <section className="settings-card">
                      <div className="card-heading">
                        <Icon name="settings" />
                        <div>
                          <h2>Local index</h2>
                          <p>Configured by the server environment.</p>
                        </div>
                      </div>
                      <dl className="settings-details">
                        <div>
                          <dt>Embedding adapter</dt>
                          <dd>{settings?.embedding_provider}</dd>
                        </div>
                        <div>
                          <dt>Embedding model</dt>
                          <dd>{settings?.embedding_model}</dd>
                        </div>
                        <div>
                          <dt>Storage</dt>
                          <dd>SQLite · Chroma · local files</dd>
                        </div>
                      </dl>
                      <p className="field-help">
                        After changing embedding or chunk settings, reindex your
                        documents in the library. Hash embeddings are for
                        offline tests and demos only.
                      </p>
                    </section>
                    <div className="settings-footer">
                      <span>
                        No paid fallback. No automatic provider switching.
                      </span>
                      <button
                        className="button primary"
                        type="submit"
                        disabled={busy || !workspaceId}
                      >
                        {busy ? "Saving…" : "Save settings"}
                        <Icon name="check" size={16} />
                      </button>
                    </div>
                  </form>
                </div>}
                <p className="page-note">
                  {settings?.security} Server deployments require TLS, secure
                  cookies and explicitly configured hosts/origins.
                </p>
              </div>
            )}
          </main>
        </PageTransition>
      </div>

      {mode === "chat" && (
        <aside className="evidence-panel" aria-label="Source evidence">
          <div className="evidence-header">
            <Icon name="book" size={18} />
            <h2>Source evidence</h2>
            <span>{latestCitations.length.toString().padStart(2, "0")}</span>
          </div>
          {latestCitations.length ? (
            <div className="citation-list">
              {latestCitations.map((citation, index) => (
                <button
                  className="citation-card"
                  key={citation.citation_id}
                  onClick={() => openSource(citation)}
                  disabled={citation.available === false}
                >
                  <span className="citation-number">{index + 1}</span>
                  <strong>{citation.title}</strong>
                  <span className="citation-locator">
                    {citation.page
                      ? `Page ${citation.page}`
                      : citation.heading || "Text passage"}
                  </span>
                  <p>
                    {citation.excerpt.slice(0, 220)}
                    {citation.excerpt.length > 220 ? "…" : ""}
                  </p>
                  <span className="view-source">
                    {citation.available === false
                      ? "Source unavailable after revision/deletion"
                      : "View source"}
                    <Icon name="external" size={13} />
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <div className="evidence-empty">
              <div className="evidence-illustration">
                <span />
                <span />
                <span />
                <Icon name="book" size={24} />
              </div>
              <h3>Every answer has a story.</h3>
              <p>
                When you ask a question, the passages behind your answer will
                appear here.
              </p>
              <span>
                Read the answer.
                <br />
                Explore the evidence.
              </span>
            </div>
          )}
          <div className="evidence-bottom">
            <Icon name="check" size={16} />
            <p>
              Citations link to actual passages.
              <br />A source you can always return to.
            </p>
          </div>
        </aside>
      )}
      <WorkspaceSearch
        open={searchOpen}
        onClose={() => setSearchOpen(false)}
        documents={documents}
        chats={chats}
        onDocument={(doc) => documentAction(doc, "open")}
        onChat={chooseChat}
        onNew={newChat}
        onEdit={editChat}
      />
      {source && (
        <SourceViewer source={source} onClose={() => setSource(null)} />
      )}
    </div>
  );
}
