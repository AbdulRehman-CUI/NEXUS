"use client";
import { useState } from "react";
import { api } from "../lib/api";
export function AnswerFeedback({
  messageId,
  workspaceId,
}: {
  messageId: string;
  workspaceId: string;
}) {
  const [notice, setNotice] = useState("");
  return (
    <div className="answer-feedback">
      <span>Was the evidence useful?</span>
      {["helpful", "not_helpful", "wrong_citation", "missing_evidence"].map(
        (rating) => (
          <button
            className="text-button"
            key={rating}
            onClick={async () => {
              try {
                await api(
                  `/api/messages/${messageId}/feedback?workspace_id=${workspaceId}`,
                  { method: "POST", body: JSON.stringify({ rating }) },
                );
                setNotice("Feedback saved privately for review.");
              } catch (cause) {
                setNotice(
                  cause instanceof Error ? cause.message : "Feedback failed",
                );
              }
            }}
          >
            {rating.replaceAll("_", " ")}
          </button>
        ),
      )}
      <span role="status">{notice}</span>
    </div>
  );
}
