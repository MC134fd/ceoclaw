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

export interface Blueprint {
  business_name: string;
  business_positioning: string;
  target_user: string;
  feature_list: string[];
  design_direction: {
    design_family: string;
    palette_name: string;
    font_pair: { display: string; body: string };
    motion_preset: string;
    spacing_policy: string;
    consistency_profile_id: string;
  };
  page_map: Array<{ path: string; purpose: string }>;
  cta_flow: Array<{ from: string; to: string; label: string }>;
  build_steps: string[];
  quality_gates: string[];
}

export interface CreditMeta {
  credits_before: number | null;
  credits_after: number | null;
  cost: number;
  tier: string;
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
  blueprint?: Blueprint;
  layout_plan?: Record<string, unknown>;
  consistency_profile_id?: string;
  credits?: CreditMeta;
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
  active_provider: 'openai' | 'mock';  // flock removed from union
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

export interface ClarificationResponse {
  needs_clarification: true;
  questions: string[];
  reason: string;
  job_id: null;
}
