"use client";
import { memo, useState } from "react";
import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { visit } from "unist-util-visit";
import type { Root, Text, Link as MarkdownLink } from "mdast";
import type { Citation } from "../lib/api";
import { Icon } from "./icon";
import "katex/dist/katex.min.css";

function remarkCitations({ citations }: { citations: Citation[] }) {
  return (tree: Root) => {
    visit(tree, "text", (node: Text, index, parent) => {
      if (
        index === undefined ||
        !parent ||
        parent.type === "link" ||
        parent.type === "linkReference"
      )
        return;
      const parts = node.value.split(/(\[C[a-zA-Z0-9]+\])/g);
      if (parts.length === 1) return;
      const nodes: (Text | MarkdownLink)[] = parts
        .filter(Boolean)
        .map((value) => {
          const citation = citations.find(
            (c) => `[${c.citation_id}]` === value,
          );
          return citation
            ? {
                type: "link",
                url: `#nexus-citation-${citation.citation_id}`,
                children: [
                  {
                    type: "text",
                    value: String(citations.indexOf(citation) + 1),
                  },
                ],
              }
            : { type: "text", value };
        });
      parent.children.splice(index, 1, ...nodes);
      return index + nodes.length;
    });
  };
}
function CodeBlock({ children }: { children: React.ReactNode }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="code-block">
      <button
        className="copy-code"
        aria-label="Copy code"
        onClick={async (event) => {
          const text =
            event.currentTarget.parentElement?.querySelector("pre")
              ?.textContent || "";
          try {
            await navigator.clipboard.writeText(text);
            setCopied(true);
            setTimeout(() => setCopied(false), 1800);
          } catch {
            setCopied(false);
          }
        }}
      >
        <Icon name={copied ? "check" : "copy"} size={14} />
        {copied ? "Copied" : "Copy code"}
      </button>
      <pre>{children}</pre>
    </div>
  );
}
export default memo(function RichMessage({
  content,
  citations,
  onCitation,
}: {
  content: string;
  citations: Citation[];
  onCitation: (citation: Citation) => void;
}) {
  return (
    <div className="markdown-body">
      <ReactMarkdown
        skipHtml
        remarkPlugins={[
          remarkGfm,
          remarkMath,
          [remarkCitations, { citations }],
        ]}
        rehypePlugins={[
          [
            rehypeKatex,
            {
              trust: false,
              throwOnError: false,
              maxExpand: 1000,
              output: "htmlAndMathml",
            },
          ],
        ]}
        urlTransform={defaultUrlTransform}
        components={{
          a: ({ href, children }) => {
            const citation = href?.startsWith("#nexus-citation-")
              ? citations.find(
                  (c) => href === `#nexus-citation-${c.citation_id}`,
                )
              : null;
            return citation ? (
              <button
                className="inline-citation"
                onClick={() => onCitation(citation)}
                disabled={citation.available === false}
                title={
                  citation.available === false
                    ? citation.unavailable_reason
                    : `${citation.title}${citation.page ? ` · page ${citation.page}` : citation.heading ? ` · ${citation.heading}` : ""}`
                }
                aria-label={`Open source: ${citation.title}`}
              >
                {citation.available === false ? "Source unavailable" : children}
                <Icon name="external" size={10} />
              </button>
            ) : (
              <a href={href} target="_blank" rel="noopener noreferrer">
                {children}
                <span className="sr-only"> (opens a new tab)</span>
              </a>
            );
          },
          img: ({ alt }) => (
            <span className="blocked-image">
              Image omitted{alt ? `: ${alt}` : ""} · external images are never
              loaded automatically
            </span>
          ),
          pre: ({ children }) => <CodeBlock>{children}</CodeBlock>,
          table: ({ children }) => (
            <div
              className="markdown-table-scroll"
              tabIndex={0}
              role="region"
              aria-label="Answer table"
            >
              <table>{children}</table>
            </div>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
});
