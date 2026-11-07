"use client";
import { useEffect, useRef, useState } from "react";
import type { Chat, Document } from "../lib/api";
import { Icon } from "./icon";
export function WorkspaceSearch({
  open,
  onClose,
  documents,
  chats,
  onDocument,
  onChat,
  onNew,
  onEdit,
}: {
  open: boolean;
  onClose: () => void;
  documents: Document[];
  chats: Chat[];
  onDocument: (doc: Document) => void;
  onChat: (chat: Chat) => void;
  onNew: () => void;
  onEdit: (chat: Chat, action: "rename" | "delete") => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [query, setQuery] = useState("");
  useEffect(() => {
    if (open) dialog.current?.showModal();
    else dialog.current?.close();
  }, [open]);
  const docs = documents
    .filter((d) => d.title.toLowerCase().includes(query.toLowerCase()))
    .slice(0, 8);
  const conversations = chats
    .filter((c) => c.title.toLowerCase().includes(query.toLowerCase()))
    .slice(0, 6);
  return (
    <dialog
      ref={dialog}
      className="search-dialog modal-surface"
      aria-label="Search workspace"
      onCancel={onClose}
    >
      <header>
        <Icon name="search" />
        <input
          autoFocus
          aria-label="Search workspace sources and conversations"
          placeholder="Search sources and conversations…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <button
          className="icon-button"
          aria-label="Close search"
          onClick={onClose}
        >
          <Icon name="close" size={17} />
        </button>
      </header>
      <div className="search-results">
        <p className="eyebrow">SOURCES</p>
        {docs.map((doc) => (
          <button
            key={doc.id}
            disabled={doc.status !== "ready"}
            onClick={() => {
              onClose();
              onDocument(doc);
            }}
          >
            <Icon name="files" size={17} />
            <span>
              {doc.title}
              <small>
                {doc.extension.slice(1).toUpperCase()} · {doc.status}
              </small>
            </span>
            <Icon name="external" size={14} />
          </button>
        ))}
        <p className="eyebrow">CONVERSATIONS</p>
        <button
          onClick={() => {
            onClose();
            onNew();
          }}
        >
          <Icon name="plus" size={17} />
          <span>New conversation</span>
        </button>
        {conversations.map((chat) => (
          <div className="search-conversation" key={chat.id}>
            <button
              onClick={() => {
                onClose();
                onChat(chat);
              }}
            >
              <Icon name="chat" size={17} />
              <span>{chat.title}</span>
              <Icon name="chevron" size={14} />
            </button>
            <button
              className="icon-button"
              aria-label={`Rename ${chat.title}`}
              onClick={() => {
                onClose();
                onEdit(chat, "rename");
              }}
            >
              <Icon name="edit" size={15} />
            </button>
            <button
              className="icon-button"
              aria-label={`Delete ${chat.title}`}
              onClick={() => {
                onClose();
                onEdit(chat, "delete");
              }}
            >
              <Icon name="trash" size={15} />
            </button>
          </div>
        ))}
        {!docs.length && !conversations.length && (
          <p className="field-help">
            No matching names in this workspace. Search document contents using
            chat retrieval.
          </p>
        )}
      </div>
      <footer>
        <kbd>ESC</kbd> to close · source and conversation names only
      </footer>
    </dialog>
  );
}
