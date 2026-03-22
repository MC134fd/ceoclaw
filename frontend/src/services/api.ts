import type {
  ChatResponse,
  ProjectFile,
  ProviderStatus,
  Session,
  SessionHistory,
  StyleSeed,
  VersionRecord,
} from '../types';

const BASE_URL = '';

// ---------------------------------------------------------------------------
// Auth token retrieval
// ---------------------------------------------------------------------------

/**
 * Returns the current Supabase access token, or null in anonymous mode.
 * Dynamically imported to avoid a hard dep on supabase in non-auth builds.
 */
async function getAccessToken(): Promise<string | null> {
  const { supabase } = await import('../lib/supabase');
  if (!supabase) return null;
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? null;
}

/** Build auth headers, injecting Bearer token when available. */
async function authHeaders(extra?: Record<string, string>): Promise<Record<string, string>> {
  const token = await getAccessToken();
  const headers: Record<string, string> = { 'Content-Type': 'application/json', ...extra };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  return headers;
}

// ---------------------------------------------------------------------------
// HTTP helpers
// ---------------------------------------------------------------------------

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    // Surface 401 as a sign-in prompt signal
    if (res.status === 401) {
      throw new AuthError('Session expired — please sign in again');
    }
    let detail = res.statusText;
    try {
      const body = await res.json();
      // Credits-exhausted 402
      if (res.status === 402 && body.detail?.error === 'insufficient_credits') {
        throw new InsufficientCreditsError(
          body.detail.message ?? 'Insufficient credits',
          body.detail.balance ?? 0,
          body.detail.required ?? 1,
          body.detail.tier ?? 'free',
        );
      }
      detail = body.detail?.message ?? body.detail ?? body.message ?? detail;
    } catch (inner) {
      if (inner instanceof ApiError) throw inner;
    }
    throw new Error(`HTTP ${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Custom error types
// ---------------------------------------------------------------------------

export class ApiError extends Error {}

export class AuthError extends ApiError {}

export class InsufficientCreditsError extends ApiError {
  constructor(
    message: string,
    public readonly balance: number,
    public readonly required: number,
    public readonly tier: string,
  ) {
    super(message);
    this.name = 'InsufficientCreditsError';
  }
}

// ---------------------------------------------------------------------------
// Builder API
// ---------------------------------------------------------------------------

export async function sendMessage(
  sessionId: string,
  message: string,
  styleSeed?: StyleSeed,
): Promise<ChatResponse> {
  const body: Record<string, unknown> = {
    session_id: sessionId,
    message,
  };
  if (styleSeed) body.style_seed = styleSeed;

  const res = await fetch(`${BASE_URL}/builder/chat`, {
    method: 'POST',
    headers: await authHeaders(),
    body: JSON.stringify(body),
  });
  return handleResponse<ChatResponse>(res);
}

export async function listSessions(limit: number = 20): Promise<Session[]> {
  const res = await fetch(`${BASE_URL}/builder/sessions?limit=${limit}`, {
    headers: await authHeaders(),
  });
  return handleResponse<Session[]>(res);
}

export async function getSession(sessionId: string): Promise<Session> {
  const res = await fetch(`${BASE_URL}/builder/sessions/${encodeURIComponent(sessionId)}`, {
    headers: await authHeaders(),
  });
  return handleResponse<Session>(res);
}

export async function getSessionHistory(sessionId: string): Promise<SessionHistory> {
  const res = await fetch(
    `${BASE_URL}/builder/sessions/${encodeURIComponent(sessionId)}/messages`,
    { headers: await authHeaders() },
  );
  return handleResponse<SessionHistory>(res);
}

export async function checkProviderStatus(): Promise<ProviderStatus> {
  const res = await fetch(`${BASE_URL}/builder/provider/status`);
  return handleResponse<ProviderStatus>(res);
}

export function newSessionId(): string {
  return crypto.randomUUID();
}

export async function deleteSession(sessionId: string): Promise<void> {
  const res = await fetch(`${BASE_URL}/builder/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'DELETE',
    headers: await authHeaders(),
  });
  await handleResponse<{ status: string }>(res);
}

export async function listVersions(sessionId: string): Promise<VersionRecord[]> {
  const res = await fetch(
    `${BASE_URL}/builder/sessions/${encodeURIComponent(sessionId)}/versions`,
    { headers: await authHeaders() },
  );
  return handleResponse<VersionRecord[]>(res);
}

export async function restoreVersion(
  sessionId: string,
  versionId: string,
): Promise<{ version_id: string; files_applied: string[] }> {
  const res = await fetch(
    `${BASE_URL}/builder/sessions/${encodeURIComponent(sessionId)}/versions/${encodeURIComponent(versionId)}/restore`,
    { method: 'POST', headers: await authHeaders() },
  );
  return handleResponse<{ version_id: string; files_applied: string[] }>(res);
}

// ---------------------------------------------------------------------------
// Account API
// ---------------------------------------------------------------------------

export interface AccountMe {
  id: string;
  email: string;
  display_name: string | null;
  avatar_url: string | null;
  tier: string;
  auth_required: boolean;
}

export interface AccountCredits {
  user_id: string;
  balance: number | null;
  monthly_allocation: number | null;
  credits_enforced: boolean;
  cost_per_generation: number;
  ledger: Array<{ id: number; delta: number; reason: string; created_at: string }>;
}

export async function getAccountMe(): Promise<AccountMe> {
  const res = await fetch(`${BASE_URL}/account/me`, { headers: await authHeaders() });
  return handleResponse<AccountMe>(res);
}

export async function getAccountCredits(): Promise<AccountCredits> {
  const res = await fetch(`${BASE_URL}/account/credits`, { headers: await authHeaders() });
  return handleResponse<AccountCredits>(res);
}

// ---------------------------------------------------------------------------
// Project file API
// ---------------------------------------------------------------------------

export async function listProjectFiles(sessionId: string): Promise<ProjectFile[]> {
  const res = await fetch(
    `${BASE_URL}/builder/sessions/${encodeURIComponent(sessionId)}/files`,
    { headers: await authHeaders() },
  );
  const body = await handleResponse<{ session_id: string; files: ProjectFile[] }>(res);
  return body.files ?? [];
}

export async function getFileContent(
  sessionId: string,
  filePath: string,
): Promise<{ session_id: string; file_path: string; content: string; file_type: string; size_bytes: number; updated_at: string }> {
  const res = await fetch(
    `${BASE_URL}/builder/sessions/${encodeURIComponent(sessionId)}/files/${filePath}`,
    { headers: await authHeaders() },
  );
  return handleResponse<{ session_id: string; file_path: string; content: string; file_type: string; size_bytes: number; updated_at: string }>(res);
}

export async function updateFileContent(
  sessionId: string,
  filePath: string,
  content: string,
): Promise<void> {
  const res = await fetch(
    `${BASE_URL}/builder/sessions/${encodeURIComponent(sessionId)}/files/${filePath}`,
    {
      method: 'PUT',
      headers: await authHeaders(),
      body: JSON.stringify({ content }),
    },
  );
  await handleResponse<{ status: string }>(res);
}

export async function createProjectFile(
  sessionId: string,
  filePath: string,
  content: string = '',
): Promise<void> {
  const res = await fetch(
    `${BASE_URL}/builder/sessions/${encodeURIComponent(sessionId)}/files`,
    {
      method: 'POST',
      headers: await authHeaders(),
      body: JSON.stringify({ path: filePath, content }),
    },
  );
  await handleResponse<{ status: string }>(res);
}

export async function deleteProjectFile(
  sessionId: string,
  filePath: string,
): Promise<void> {
  const res = await fetch(
    `${BASE_URL}/builder/sessions/${encodeURIComponent(sessionId)}/files/${filePath}`,
    {
      method: 'DELETE',
      headers: await authHeaders(),
    },
  );
  await handleResponse<{ status: string }>(res);
}
