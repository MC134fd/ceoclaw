/**
 * Supabase client singleton.
 *
 * Created only when VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY are set.
 * When the env vars are absent the module exports `null`, and the app runs in
 * anonymous mode (same behaviour as before auth was added).
 */
import { createClient, SupabaseClient } from '@supabase/supabase-js';

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined;

export const supabase: SupabaseClient | null =
  supabaseUrl && supabaseAnonKey ? createClient(supabaseUrl, supabaseAnonKey) : null;

/** True when Supabase auth is configured in this build. */
export const isAuthEnabled = supabase !== null;
