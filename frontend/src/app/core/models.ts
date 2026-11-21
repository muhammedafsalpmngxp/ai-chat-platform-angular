// Types mirroring backend/app/schemas.py

export interface User {
  id: string;
  username: string;
  display_name: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: 'bearer';
  expires_in: number;
  user: User;
}

export type MessageStatus = 'complete' | 'stopped' | 'refused';

export interface AttachmentInfo {
  id: string;
  name: string;
  mime: string;
  size: number;
  kind: 'image' | 'document';
  text_chars: number;
  truncated: boolean;
  created_at: string;
}

export interface Source {
  title: string;
  url: string;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  status: MessageStatus;
  model: string | null;
  attachments?: AttachmentInfo[];
  sources?: Source[];
  /** Web answers: how well the sources agreed. */
  confidence?: 'high' | 'medium' | 'low' | null;
  created_at: string;
}

export interface ClientConfig {
  max_upload_mb: number;
  max_files_per_chat: number;
  accept: string;
  search_enabled: boolean;
}

/** A file in the composer: uploading, ready to send, or failed. */
export interface PendingFile {
  key: string;
  name: string;
  size: number;
  kind: 'image' | 'document';
  previewUrl: string | null;
  info: AttachmentInfo | null;
  error: string | null;
}

export interface ChatSummary {
  id: string;
  title: string;
  model: string | null;
  /** Context window in use: last request's input + output tokens. */
  token_count: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cached_input_tokens: number;
  total_cost_usd: number;
  created_at: string;
  updated_at: string;
}

export interface ChatDetail extends ChatSummary {
  messages: ChatMessage[];
}

export type ModelTier = 'premium' | 'standard' | 'recommended' | 'low';

export interface ModelInfo {
  id: string;
  label: string;
  tier: ModelTier;
  /** USD per 1M tokens */
  input_price: number;
  output_price: number;
  cached_input_price: number | null;
  is_default: boolean;
  requires_reauth: boolean;
  warning: string | null;
  /** Price compared with the default model (80 = about 80x). */
  relative_cost: number;
}

export interface ModelCatalog {
  default_model: string;
  prices_as_of: string | null;
  premium_unlock_minutes: number;
  models: ModelInfo[];
}

/** A message as shown in the UI (may still be streaming or have failed). */
/** One LangGraph node as it runs for the current reply. */
export interface GraphStep {
  node: string;
  label: string;
  status: 'running' | 'done';
  detail?: string;
}

export interface UiMessage extends ChatMessage {
  pending?: boolean;
  error?: string;
  /** Live LangGraph progress while the reply is being produced. */
  steps?: GraphStep[];
}
