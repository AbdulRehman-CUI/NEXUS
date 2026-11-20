"""Budget the system and user text that personal model adapters actually send."""

import json

from fastapi import HTTPException

from .providers import SYSTEM_PROMPT

GENERAL_SYSTEM = (
    "Answer the user's question directly. No documents or tools are available. Do not fabricate citations."
)


class PromptBudget:
    # One token per UTF-8 byte is the project's conservative cross-provider estimate.
    # Keep the existing reserve for provider-added role markers and chat templates.
    framing_tokens = 256

    def __init__(self, config, metadata):
        configured = config["context_window"]
        self.window = min(configured, metadata.get("context_window") or configured)
        self.output = config["max_output_tokens"]
        self.output_max = metadata.get("max_output_tokens")
        self.excerpt_limit = config["context_budget_bytes"]
        self.input_limit = self.window - self.output - self.framing_tokens

    def parts(self, question, evidence, general_chat=False):
        if general_chat:
            return GENERAL_SYSTEM, question
        content = json.dumps({"question": question, "evidence": evidence}, ensure_ascii=False)
        available = self.input_limit - len(SYSTEM_PROMPT.encode())
        if evidence and len(content.encode()) > available:
            # Keep the citation and its human-readable source context on the wire. The
            # full versioned locators stay in the evidence snapshot and source viewer.
            fields = ("citation_id", "chunk_id", "title", "page", "heading", "tags", "excerpt")
            for keys in (fields, ("citation_id", "excerpt")):
                sources = [{k: item[k] for k in keys if item.get(k) not in (None, [])} for item in evidence]
                content = json.dumps(
                    {"question": question, "evidence": sources}, ensure_ascii=False, separators=(",", ":")
                )
                if len(content.encode()) <= available:
                    break
        return SYSTEM_PROMPT, content

    def fits(self, question, evidence):
        system, content = self.parts(question, evidence)
        return len(system.encode()) + len(content.encode()) <= self.input_limit

    def checked_parts(self, question, evidence, general_chat=False):
        if self.output_max and self.output > self.output_max:
            raise HTTPException(
                422,
                f"The configured output limit of {self.output} tokens exceeds the advertised "
                f"maximum of {self.output_max}. Lower the model configuration's output limit.",
            )
        system, content = self.parts(question, evidence, general_chat)
        required = len(system.encode()) + len(content.encode())
        if required > self.input_limit:
            raise HTTPException(
                422,
                f"The {self.window}-token model window reserves {self.output} tokens for output "
                f"and {self.framing_tokens} for framing. The assembled input needs a conservative "
                f"{required} tokens. Shorten the question or its follow-up context, lower the configured "
                "output limit, or select a model configuration with a larger supported window.",
            )
        return system, content

    def counts(self, question, standalone, evidence, general_chat=False):
        system, content = self.checked_parts(standalone, evidence, general_chat)
        system_bytes, content_bytes = len(system.encode()), len(content.encode())
        question_bytes, standalone_bytes = len(question.encode()), len(standalone.encode())
        excerpt_bytes = sum(len(item["excerpt"].encode()) for item in evidence)
        return {
            "context_window_tokens": self.window,
            "reserved_output_tokens": self.output,
            "framing_tokens": self.framing_tokens,
            "system_bytes": system_bytes,
            "question_bytes": question_bytes,
            "follow_up_bytes": standalone_bytes - question_bytes,
            "excerpt_bytes": excerpt_bytes,
            "format_bytes": content_bytes - standalone_bytes - excerpt_bytes,
            "prompt_bytes": system_bytes + content_bytes,
        }
