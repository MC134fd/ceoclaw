import { useQuery } from '@tanstack/react-query';
import { listSessions } from '../services/api';
import type { Session } from '../types';

interface Props {
  currentSessionId: string;
  onSelectSession: (session: Session) => void;
  onNewSession: () => void;
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString([], { month: 'short', day: 'numeric' });
  } catch {
    return '';
  }
}

export function SessionSidebar({ currentSessionId, onSelectSession, onNewSession }: Props) {
  const { data: sessions = [], isLoading } = useQuery({
    queryKey: ['sessions'],
    queryFn: () => listSessions(20),
    staleTime: 10_000,
  });

  return (
    <aside
      style={{
        width: '100%',
        minWidth: 240,
        flexShrink: 0,
        background: 'var(--surface)',
        borderRight: '1px solid var(--border)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          padding: '14px 12px 10px',
          borderBottom: '1px solid var(--border)',
          flexShrink: 0,
        }}
      >
        <button
          onClick={onNewSession}
          style={{
            width: '100%',
            padding: '8px 12px',
            background: 'var(--accent)',
            color: '#fff',
            border: 'none',
            borderRadius: 8,
            cursor: 'pointer',
            fontSize: 13,
            fontWeight: 600,
            fontFamily: 'var(--font)',
            transition: 'background 0.15s',
          }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLButtonElement).style.background = 'var(--accent-hover)';
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLButtonElement).style.background = 'var(--accent)';
          }}
        >
          + New Session
        </button>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '6px 6px' }}>
        {isLoading && (
          <div style={{ padding: 12, color: 'var(--text-muted)', fontSize: 12, textAlign: 'center' }}>
            Loading sessions…
          </div>
        )}
        {!isLoading && sessions.length === 0 && (
          <div style={{ padding: 12, color: 'var(--text-muted)', fontSize: 12, textAlign: 'center' }}>
            No sessions yet.
          </div>
        )}
        {sessions.map((session) => {
          const isActive = session.session_id === currentSessionId;
          return (
            <button
              key={session.session_id}
              onClick={() => onSelectSession(session)}
              style={{
                display: 'flex',
                flexDirection: 'column',
                width: '100%',
                padding: '9px 10px',
                border: 'none',
                background: isActive ? 'rgba(99,102,241,0.12)' : 'transparent',
                borderRadius: 8,
                cursor: 'pointer',
                textAlign: 'left',
                gap: 2,
                marginBottom: 2,
                transition: 'background 0.1s',
              }}
              onMouseEnter={(e) => {
                if (!isActive)
                  (e.currentTarget as HTMLButtonElement).style.background = 'var(--surface-2)';
              }}
              onMouseLeave={(e) => {
                if (!isActive)
                  (e.currentTarget as HTMLButtonElement).style.background = 'transparent';
              }}
            >
              <span
                style={{
                  fontSize: 13,
                  fontWeight: isActive ? 600 : 500,
                  color: isActive ? 'var(--accent)' : 'var(--text)',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {session.product_name || session.slug || session.session_id.slice(0, 8)}
              </span>
              <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                {formatDate(session.updated_at)}
              </span>
            </button>
          );
        })}
      </div>
    </aside>
  );
}
