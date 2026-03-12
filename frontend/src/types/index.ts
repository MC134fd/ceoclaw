export interface Message {
  id: number;
  session_id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  created_at: string;
}

export interface Session {
  session_id: string;
  slug: string;
  product_name: string;
  version_id: string;
  created_at: string;
  updated_at: string;
  message_count?: number;
}

export interface FileChange {
  path: string;
  action: 'create' | 'update' | 'delete';
  status: 'applied' | 'skipped' | 'rejected';
  summary: string;
  error?: string;
}

export interface ModelInfo {
  provider: string;
  model_mode: string;
  fallback_used?: boolean;
  fallback_reason?: string;
}

export interface OperationInfo {
  type: string;  // "add_page" | "add_component" | "add_endpoint" | "general_edit" | etc.
  target: string;
  metadata: Record<string, unknown>;
}

export interface ChatResponse {
  session_id: string;
  assistant_message: string;
  product_name: string;
  slug: string;
  landing_url: string;
  app_url: string;
  model: ModelInfo;
  version_id: string;
  changes: FileChange[];
  files_applied: string[];
  files_skipped: string[];
  warnings: string[];
  operation?: OperationInfo;
  design_system?: Record<string, unknown>;
}

export interface SessionHistory {
  session_id: string;
  slug: string;
  product_name: string;
  version_id: string;
  created_at: string;
  updated_at: string;
  messages: Message[];
  landing_url: string;
  app_url: string;
}

export interface ProviderStatus {
  flock: { configured: boolean; reachable: boolean; error: string | null };
  openai: { configured: boolean; reachable: boolean; error: string | null };
  active_provider: 'flock' | 'openai' | 'mock';
}

export type PreviewTab = 'landing' | 'app';

export interface StyleSeed {
  archetype: string;
  palette: string;
  density: string;
  motion: string;
}

export interface VersionRecord {
  id: number;
  session_id: string;
  version_id: string;
  file_list: string[];
  created_at: string;
}

export type PipelineStageStatus = 'pending' | 'running' | 'done' | 'error';

export interface PipelineStage {
  stage_key: string;
  stage_label: string;
  status: PipelineStageStatus;
  duration_ms?: number;
  artifact_type?: string;
  artifact_name?: string;
  error?: string;
}
