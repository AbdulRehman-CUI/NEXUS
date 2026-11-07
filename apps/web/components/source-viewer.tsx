"use client";

import { useEffect, useRef } from "react";
import { API, type Source } from "../lib/api";
import { Icon } from "./icon";

export function SourceViewer({
  source,
  onClose,
}: {
  source: Source;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  function close() {
    const element = dialog.current;
    if (!element) return;
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) {
      onClose();
      return;
    }
    element.classList.add("is-closing");
    if (closeTimer.current) clearTimeout(closeTimer.current);
    closeTimer.current = setTimeout(onClose, 140);
  }
  useEffect(() => {
    const element = dialog.current;
    const previous = document.activeElement;
    element?.showModal();
    return () => {
      if (closeTimer.current) clearTimeout(closeTimer.current);
      element?.close();
      if (previous instanceof HTMLElement && previous.isConnected)
        previous.focus({ preventScroll: true });
    };
  }, []);
  const page = source.citation?.page || source.spans[0]?.page;
  return (
    <dialog
      ref={dialog}
      className="source-dialog"
      onCancel={(event) => {
        event.preventDefault();
        close();
      }}
      aria-labelledby="source-title"
    >
      <header>
        <div>
          <span className="eyebrow">ORIGINAL EVIDENCE</span>
          <h2 id="source-title">{source.document.title}</h2>
        </div>
        <button
          className="icon-button"
          onClick={close}
          aria-label="Close source"
        >
          <Icon name="close" />
        </button>
      </header>
      <div className="source-content">
        {source.spans.map((span) => (
          <section key={span.id}>
            <h3>
              {span.page
                ? `Page ${span.page}`
                : span.heading || "Document text"}
            </h3>
            <p className="source-text">
              {source.citation ? (
                <>
                  {span.text.slice(0, source.citation.start)}
                  <mark>
                    {span.text.slice(
                      source.citation.start,
                      source.citation.end,
                    )}
                  </mark>
                  {span.text.slice(source.citation.end)}
                </>
              ) : (
                span.text
              )}
            </p>
          </section>
        ))}
        {source.document.extension === ".pdf" && (
          <iframe
            title={`Original PDF${page ? `, page ${page}` : ""}`}
            src={`${API}${source.file_url}${page ? `#page=${page}` : ""}`}
          />
        )}
      </div>
      <footer>
        <span>Text offsets refer to the normalized source passage.</span>
        <a
          className="button secondary"
          href={`${API}${source.file_url}${page ? `#page=${page}` : ""}`}
          target="_blank"
          rel="noreferrer"
        >
          Open original <Icon name="external" size={16} />
        </a>
      </footer>
    </dialog>
  );
}
