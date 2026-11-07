export type ProviderId =
  | "openrouter"
  | "google"
  | "openai"
  | "anthropic"
  | "groq"
  | "ollama"
  | "compatible";
export type ProviderModel = {
  id: string;
  name: string;
  provider: ProviderId;
  context_window: number | null;
  max_output_tokens: number | null;
  supported_parameters: string[];
  capabilities: string[];
  cost_status: "free" | "paid" | "unknown";
  pricing: {
    input_per_token: number;
    output_per_token: number;
    currency: string;
    source: string;
  } | null;
};
export type Connection = {
  status: string;
  message: string;
  checked_at?: string;
  model_status?: string;
};
export type ConfigurationDraft = {
  name: string;
  provider: ProviderId;
  model: string;
  base_url: string;
  remote_consent: boolean;
  allow_paid: boolean;
  streaming: boolean;
  temperature: number | null;
  max_output_tokens: number;
  context_window: number;
  context_budget_bytes: number;
  max_calls_per_day: number;
  spending_warning_usd: number | null;
  timeout_seconds: number;
  token_parameter: "max_tokens" | "max_completion_tokens";
};
export type AIConfiguration = ConfigurationDraft & {
  id: string;
  destination: string;
  is_default: boolean;
  credential_configured: boolean;
  connection: Connection;
  updated_at: string;
  temperature_supported: boolean;
  model_metadata: ProviderModel | null;
};
export type AISelection = {
  active: AIConfiguration | null;
  unavailable: boolean;
  selection: string | null;
  workspace_cloud_allowed: boolean;
  configurations: Pick<
    AIConfiguration,
    "id" | "name" | "provider" | "model" | "is_default"
  >[];
};
export type ProviderCatalog = {
  default_unavailable: boolean;
  configurations: AIConfiguration[];
  providers: {
    id: ProviderId;
    name: string;
    description: string;
    remote: boolean;
  }[];
  credential_storage: { enabled: boolean; message: string };
};
export type ProviderUsage = {
  events: {
    id: string;
    configuration_id: string | null;
    provider: string;
    model: string;
    status: string;
    input_tokens: number | null;
    output_tokens: number | null;
    cost_usd: number | null;
    cost_source: string | null;
    elapsed_ms: number;
    created_at: string;
  }[];
  summaries: {
    configuration_id: string;
    known_cost_usd: number;
    unknown_cost_requests: number;
    warning_usd: number | null;
    warning_reached: boolean;
  }[];
  note: string;
};
export function configurationDraft(
  config?: AIConfiguration,
): ConfigurationDraft {
  return {
    name: config?.name ?? "",
    provider: config?.provider ?? "openrouter",
    model: config?.model ?? "",
    base_url: config?.base_url ?? "",
    remote_consent: config?.remote_consent ?? false,
    allow_paid: config?.allow_paid ?? false,
    streaming: config?.streaming ?? true,
    temperature: config?.temperature ?? null,
    max_output_tokens: config?.max_output_tokens ?? 1000,
    context_window: config?.context_window ?? 8192,
    context_budget_bytes: config?.context_budget_bytes ?? 4000,
    max_calls_per_day: config?.max_calls_per_day ?? 20,
    spending_warning_usd: config?.spending_warning_usd ?? null,
    timeout_seconds: config?.timeout_seconds ?? 45,
    token_parameter: config?.token_parameter ?? "max_tokens",
  };
}
