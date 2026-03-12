import type {
  ChatResponse,
  ProviderStatus,
  Session,
  SessionHistory,
  StyleSeed,
  VersionRecord,
} from '../types';

const BASE_URL = '';

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || body.message || detail;
    } catch {
      // ignore json parse error
    }
    throw new Error(`HTTP ${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export async function sendMessage(
  sessionId: string,
  message: string,
  mockMode: boolean = false,
  styleSeed?: StyleSeed,
): Promise<ChatResponse> {
  const body: Record<string, unknown> = {
    session_id: sessionId,
    message,
    mock_mode: mockMode,
  };
  if (styleSeed) {
    body.style_seed = styleSeed;
  }

  const res = await fetch(`${BASE_URL}/builder/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return handleResponse<ChatResponse>(res);
}

export async function listSessions(limit: number = 20): Promise<Session[]> {
  const res = await fetch(`${BASE_URL}/builder/sessions?limit=${limit}`);
  return handleResponse<Session[]>(res);
}

export async function getSession(sessionId: string): Promise<Session> {
  const res = await fetch(`${BASE_URL}/builder/sessions/${encodeURIComponent(sessionId)}`);
  return handleResponse<Session>(res);
}

export async function getSessionHistory(sessionId: string): Promise<SessionHistory> {
  const res = await fetch(
    `${BASE_URL}/builder/sessions/${encodeURIComponent(sessionId)}/messages`,
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

export async function listVersions(sessionId: string): Promise<VersionRecord[]> {
  const res = await fetch(
    `${BASE_URL}/builder/sessions/${encodeURIComponent(sessionId)}/versions`,
  );
  return handleResponse<VersionRecord[]>(res);
}

export async function restoreVersion(
  sessionId: string,
  versionId: string,
): Promise<{ version_id: string; files_applied: string[] }> {
  const res = await fetch(
    `${BASE_URL}/builder/sessions/${encodeURIComponent(sessionId)}/versions/${encodeURIComponent(versionId)}/restore`,
    { method: 'POST' },
  );
  return handleResponse<{ version_id: string; files_applied: string[] }>(res);
}
