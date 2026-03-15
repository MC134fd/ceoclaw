/**
 * useAuth — Supabase authentication state hook.
 *
 * Returns:
 *   user          — Supabase User object or null
 *   session       — Supabase Session (contains access_token) or null
 *   isLoading     — true while the initial session is being resolved
 *   signInWithGoogle — triggers Google OAuth redirect
 *   signOut       — clears the session
 *
 * When Supabase is not configured (supabase === null), the hook returns
 * a stable anonymous state so the rest of the app behaves as before.
 */
import type { Session, User } from '@supabase/supabase-js';
import { useCallback, useEffect, useState } from 'react';
import { isAuthEnabled, supabase } from '../lib/supabase';

interface AuthState {
  user: User | null;
  session: Session | null;
  isLoading: boolean;
  signInWithGoogle: () => Promise<void>;
  signOut: () => Promise<void>;
}

const ANONYMOUS_STATE: AuthState = {
  user: null,
  session: null,
  isLoading: false,
  signInWithGoogle: async () => {},
  signOut: async () => {},
};

export function useAuth(): AuthState {
  const [user, setUser] = useState<User | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [isLoading, setIsLoading] = useState(isAuthEnabled);

  useEffect(() => {
    if (!supabase) return;

    // Hydrate the initial session from local storage
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setUser(data.session?.user ?? null);
      setIsLoading(false);
    });

    // Subscribe to auth state changes (sign-in, sign-out, token refresh)
    const { data: listener } = supabase.auth.onAuthStateChange((_event, newSession) => {
      setSession(newSession);
      setUser(newSession?.user ?? null);
      setIsLoading(false);
    });

    return () => {
      listener.subscription.unsubscribe();
    };
  }, []);

  const signInWithGoogle = useCallback(async () => {
    if (!supabase) return;
    await supabase.auth.signInWithOAuth({
      provider: 'google',
      options: {
        redirectTo: window.location.origin,
      },
    });
  }, []);

  const signOut = useCallback(async () => {
    if (!supabase) return;
    await supabase.auth.signOut();
  }, []);

  if (!isAuthEnabled) return ANONYMOUS_STATE;

  return { user, session, isLoading, signInWithGoogle, signOut };
}
