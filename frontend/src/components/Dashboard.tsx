import { useCallback, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { deleteSession, listSessions } from '../services/api';
import type { Session } from '../types';

const PASTEL_COLORS = [
  '#4A413A', '#2F4752', '#8C6A43', '#5A4A3A', '#3D5260',
  '#6B5344', '#2E3E47', '#7A5C3C', '#3A4A52', '#5C4A38',
];

function getProjectColor(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash);
  }
  return PASTEL_COLORS[Math.abs(hash) % PASTEL_COLORS.length];
}

function timeAgo(iso: string): string {
  try {
    const diff = Date.now() - new Date(iso).getTime();
    const mins = Math.floor(diff / 60_000);
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs} hour${hrs !== 1 ? 's' : ''} ago`;
    const days = Math.floor(hrs / 24);
    return `${days} day${days !== 1 ? 's' : ''} ago`;
  } catch {
    return '';
  }
}

// ─── Home View ───────────────────────────────────────────────────────────────

interface HomeViewProps {
  sessions: Session[];
  onSelectSession: (session: Session) => void;
  onNewChat: (text: string) => void;
  onDeleteSession: (sessionId: string) => void;
  onViewAllApps?: () => void;
}

function HomeView({ sessions, onSelectSession, onNewChat, onDeleteSession, onViewAllApps }: HomeViewProps) {
  const [input, setInput] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleSubmit = useCallback(() => {
    const text = input.trim();
    if (!text) return;
    setInput('');
    onNewChat(text);
  }, [input, onNewChat]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSubmit();
      }
    },
    [handleSubmit],
  );

  return (
    <div className="dashboard-main">
      <div className="dash-hero">
        <h1>What will you build next?</h1>
        <p>Describe your app idea and I&apos;ll generate a live preview.</p>

        <div className="dash-input-card">
          <textarea
            ref={textareaRef}
            className="dash-input-textarea"
            placeholder="Describe the app you want to create..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={3}
          />
          <div className="dash-input-footer">
            <div className="dash-input-actions-left">
              <button className="dash-input-icon-btn" aria-label="Attach" type="button">
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M8 2v12M2 8h12" />
                </svg>
              </button>
              <button className="dash-input-icon-btn" aria-label="Settings" type="button">
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M2 4h12M4 8h8M6 12h4" />
                </svg>
              </button>
            </div>
            <div className="dash-input-actions-right">
              <span className="dash-input-plan-label">Plan</span>
              <button className="dash-input-send-btn" onClick={handleSubmit} aria-label="Send" type="button">
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M14 2L2 8.5l4.5 1.8L14 2zM6.5 10.3V14L9 11" />
                </svg>
              </button>
            </div>
          </div>
        </div>
      </div>

      <div className="dash-content-section">
        <div className="dash-tabs-row">
          <button className="dash-tab dash-tab--active" type="button">
            Recent apps
          </button>
          <div className="dash-tabs-spacer" />
          {onViewAllApps && (
            <button className="dash-view-all" type="button" onClick={onViewAllApps}>
              View all →
            </button>
          )}
        </div>

        <div className="dash-projects-grid">
          {sessions.length === 0 && (
            <div className="dash-empty-state">
              No projects yet. Describe an idea above to get started.
            </div>
          )}
          {sessions.slice(0, 6).map((session) => (
            <ProjectCard key={session.session_id} session={session} onClick={() => onSelectSession(session)} onDelete={onDeleteSession} />
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── All Apps View ───────────────────────────────────────────────────────────

interface AllAppsViewProps {
  sessions: Session[];
  onSelectSession: (session: Session) => void;
  onDeleteSession: (sessionId: string) => void;
}

function AllAppsView({ sessions, onSelectSession, onDeleteSession }: AllAppsViewProps) {
  const [search, setSearch] = useState('');

  const filtered = sessions.filter((s) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      s.product_name?.toLowerCase().includes(q) ||
      s.slug?.toLowerCase().includes(q)
    );
  });

  return (
    <div className="dashboard-main">
      <div className="dash-all-apps-header">
        <h2 className="dash-all-apps-title">Apps</h2>
        <div className="dash-all-apps-controls">
          <input
            className="dash-search-input"
            placeholder="Search apps..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <span className="dash-filter-badge">Apps</span>
          <span className="dash-workspace-label">My apps (personal workspace)</span>
        </div>
      </div>

      <div className="dash-projects-grid">
        {filtered.length === 0 && (
          <div className="dash-empty-state">No apps found.</div>
        )}
        {filtered.map((session) => (
          <ProjectCard key={session.session_id} session={session} onClick={() => onSelectSession(session)} onDelete={onDeleteSession} />
        ))}
      </div>

      <div className="dash-pagination">
        <button className="dash-page-btn" type="button">Previous</button>
        <button className="dash-page-btn" type="button">Next</button>
      </div>
    </div>
  );
}

// ─── Project Card ────────────────────────────────────────────────────────────

interface ProjectCardProps {
  session: Session;
  onClick: () => void;
  onDelete: (sessionId: string) => void;
}

function ProjectCard({ session, onClick, onDelete }: ProjectCardProps) {
  const [confirming, setConfirming] = useState(false);
  const name = session.product_name || session.slug || 'Untitled';
  const color = getProjectColor(name);
  const initial = name.charAt(0).toUpperCase();

  const handleDelete = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      if (!confirming) {
        setConfirming(true);
        return;
      }
      onDelete(session.session_id);
    },
    [confirming, onDelete, session.session_id],
  );

  const handleCancelDelete = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    setConfirming(false);
  }, []);

  return (
    <button className="dash-project-card" onClick={onClick} type="button">
      <div className="dash-project-card-top">
        <div className="dash-project-icon" style={{ background: color }}>
          {initial}
        </div>
        <div className="dash-project-actions">
          {confirming ? (
            <>
              <button
                className="dash-project-delete-confirm"
                onClick={handleDelete}
                type="button"
                aria-label="Confirm delete"
              >
                Delete
              </button>
              <button
                className="dash-project-delete-cancel"
                onClick={handleCancelDelete}
                type="button"
                aria-label="Cancel delete"
              >
                Cancel
              </button>
            </>
          ) : (
            <button
              className="dash-project-menu"
              onClick={handleDelete}
              type="button"
              aria-label="Delete project"
            >
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M2 4h12M5.333 4V2.667a1.333 1.333 0 011.334-1.334h2.666a1.333 1.333 0 011.334 1.334V4M12.667 4v9.333a1.333 1.333 0 01-1.334 1.334H4.667a1.333 1.333 0 01-1.334-1.334V4h9.334z" />
              </svg>
            </button>
          )}
        </div>
      </div>
      <div className="dash-project-name">{name}</div>
      <div className="dash-project-desc">
        {session.slug ? session.slug.replace(/-/g, ' ') : 'No description'}
      </div>
      <div className="dash-project-meta">
        Created {timeAgo(session.created_at)}
      </div>
    </button>
  );
}

// ─── Dashboard Export ────────────────────────────────────────────────────────

type DashboardView = 'home' | 'all-apps';

interface DashboardProps {
  view: DashboardView;
  onSelectSession: (session: Session) => void;
  onNewChat: (text: string) => void;
  onViewAllApps?: () => void;
}

export function Dashboard({ view, onSelectSession, onNewChat, onViewAllApps }: DashboardProps) {
  const queryClient = useQueryClient();
  const { data: sessions = [] } = useQuery({
    queryKey: ['sessions'],
    queryFn: () => listSessions(50),
    staleTime: 10_000,
  });

  const handleDeleteSession = useCallback(
    async (sessionId: string) => {
      try {
        await deleteSession(sessionId);
        void queryClient.invalidateQueries({ queryKey: ['sessions'] });
      } catch {
        // Silent fail — card will remain
      }
    },
    [queryClient],
  );

  if (view === 'all-apps') {
    return <AllAppsView sessions={sessions} onSelectSession={onSelectSession} onDeleteSession={handleDeleteSession} />;
  }

  return <HomeView sessions={sessions} onSelectSession={onSelectSession} onNewChat={onNewChat} onDeleteSession={handleDeleteSession} onViewAllApps={onViewAllApps} />;
}
