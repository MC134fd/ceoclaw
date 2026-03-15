import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { deleteSession, listSessions } from '../services/api';
import type { Session } from '../types';

interface Props {
  currentSessionId: string;
  onSelectSession: (session: Session) => void;
  onNewSession: () => void;
  onSessionDeleted?: (sessionId: string) => void;
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString([], { month: 'short', day: 'numeric' });
  } catch {
    return '';
  }
}

export function SessionSidebar({ currentSessionId, onSelectSession, onNewSession, onSessionDeleted }: Props) {
  const queryClient = useQueryClient();
  const [confirmId, setConfirmId] = useState<string | null>(null);

  const { data: sessions = [], isLoading } = useQuery({
    queryKey: ['sessions'],
    queryFn: () => listSessions(50),
    staleTime: 10_000,
  });

  const deleteMutation = useMutation({
    mutationFn: (sessionId: string) => deleteSession(sessionId),
    onSuccess: (_data, sessionId) => {
      void queryClient.invalidateQueries({ queryKey: ['sessions'] });
      setConfirmId(null);
      onSessionDeleted?.(sessionId);
    },
  });

  return (
    <aside className="sidebar-inner">
      <div className="sidebar-header">
        <button onClick={onNewSession} className="sidebar-new-btn">
          + New Session
        </button>
      </div>

      <div className="sidebar-list">
        {isLoading && (
          <div className="sidebar-empty">Loading sessions…</div>
        )}
        {!isLoading && sessions.length === 0 && (
          <div className="sidebar-empty">No sessions yet.</div>
        )}
        {sessions.map((session) => {
          const isActive = session.session_id === currentSessionId;
          const isConfirming = confirmId === session.session_id;
          const isDeleting = deleteMutation.isPending && deleteMutation.variables === session.session_id;

          return (
            <div
              key={session.session_id}
              className={[
                'sidebar-item',
                isActive ? 'sidebar-item--active' : '',
                isDeleting ? 'sidebar-item--deleting' : '',
              ]
                .filter(Boolean)
                .join(' ')}
            >
              {/* Session name button */}
              <button
                onClick={() => onSelectSession(session)}
                className="sidebar-item-btn"
              >
                <span className="sidebar-item-name">
                  {session.product_name || session.slug || session.session_id.slice(0, 8)}
                </span>
                <span className="sidebar-item-date">{formatDate(session.updated_at)}</span>
              </button>

              {/* Delete controls — always visible */}
              {!isDeleting && (
                isConfirming ? (
                  <div className="sidebar-confirm">
                    <button
                      onClick={(e) => { e.stopPropagation(); deleteMutation.mutate(session.session_id); }}
                      className="sidebar-confirm-delete"
                    >
                      Delete
                    </button>
                    <button
                      onClick={(e) => { e.stopPropagation(); setConfirmId(null); }}
                      className="sidebar-confirm-cancel"
                    >
                      ✕
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={(e) => { e.stopPropagation(); setConfirmId(session.session_id); }}
                    title="Delete session"
                    className="sidebar-delete-btn"
                  >
                    ✕
                  </button>
                )
              )}
            </div>
          );
        })}
      </div>
    </aside>
  );
}
