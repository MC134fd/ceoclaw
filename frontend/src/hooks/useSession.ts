import { useCallback, useState } from 'react';
import { newSessionId } from '../services/api';

const KEY = 'ceoclaw_session_id';

function loadSessionId(): string {
  try {
    return localStorage.getItem(KEY) || newSessionId();
  } catch {
    return newSessionId();
  }
}

export function useSession() {
  const [sessionId, setSessionIdState] = useState<string>(loadSessionId);

  const setSessionId = useCallback((id: string) => {
    setSessionIdState(id);
    try {
      localStorage.setItem(KEY, id);
    } catch {
      // ignore storage errors
    }
  }, []);

  const clearSession = useCallback(() => {
    const fresh = newSessionId();
    setSessionIdState(fresh);
    try {
      localStorage.setItem(KEY, fresh);
    } catch {
      // ignore storage errors
    }
  }, []);

  return { sessionId, setSessionId, clearSession };
}
