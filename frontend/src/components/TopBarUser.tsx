/**
 * TopBarUser — displays user avatar, name, credit balance, and tier badge.
 * Shown in the top-right corner of the app when auth is enabled.
 */
import { useQuery } from '@tanstack/react-query';
import type { User } from '@supabase/supabase-js';
import { getAccountCredits } from '../services/api';

interface Props {
  user: User;
  onSignOut: () => void;
}

export function TopBarUser({ user, onSignOut }: Props) {
  const displayName =
    user.user_metadata?.full_name ??
    user.user_metadata?.name ??
    user.email?.split('@')[0] ??
    'User';
  const avatarUrl: string | undefined =
    user.user_metadata?.avatar_url ?? user.user_metadata?.picture;

  const { data: credits } = useQuery({
    queryKey: ['account-credits'],
    queryFn: getAccountCredits,
    staleTime: 30_000,
    retry: false,
  });

  const balance = credits?.balance;
  const tier = credits ? (credits.balance !== null ? 'free' : 'anon') : '';

  return (
    <div className="topbar-user">
      {/* Credits badge */}
      {balance !== null && balance !== undefined && (
        <span className="topbar-credits" title={`${balance} credit(s) remaining`}>
          ⚡ {balance}
        </span>
      )}

      {/* Tier badge */}
      {tier && tier !== 'anon' && (
        <span className="topbar-tier">{tier}</span>
      )}

      {/* Avatar */}
      {avatarUrl ? (
        <img
          src={avatarUrl}
          alt={displayName}
          className="topbar-avatar"
          referrerPolicy="no-referrer"
        />
      ) : (
        <span className="topbar-avatar topbar-avatar--initials">
          {displayName.charAt(0).toUpperCase()}
        </span>
      )}

      {/* Name + sign-out */}
      <span className="topbar-username" title={user.email ?? ''}>
        {displayName}
      </span>
      <button className="topbar-signout-btn" onClick={onSignOut} title="Sign out">
        Sign out
      </button>
    </div>
  );
}
