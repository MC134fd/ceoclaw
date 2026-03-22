import { useQuery } from '@tanstack/react-query';
import { listSessions } from '../services/api';
import type { Session } from '../types';

export type DashboardView = 'home' | 'all-apps' | 'integrations' | 'community';

interface Props {
  currentView: DashboardView;
  onNavigate: (view: DashboardView) => void;
  onSelectSession: (session: Session) => void;
}

const NAV_ITEMS: { id: DashboardView; label: string; icon: JSX.Element }[] = [
  {
    id: 'home',
    label: 'Home',
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M2 6.5L8 2l6 4.5V13a1 1 0 01-1 1H3a1 1 0 01-1-1V6.5z" />
        <path d="M6 14V9h4v5" />
      </svg>
    ),
  },
  {
    id: 'all-apps',
    label: 'All Apps',
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <rect x="1.5" y="1.5" width="5" height="5" rx="1" />
        <rect x="9.5" y="1.5" width="5" height="5" rx="1" />
        <rect x="1.5" y="9.5" width="5" height="5" rx="1" />
        <rect x="9.5" y="9.5" width="5" height="5" rx="1" />
      </svg>
    ),
  },
  {
    id: 'integrations',
    label: 'Integrations',
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M5.5 2v3a1.5 1.5 0 01-3 0V2" />
        <path d="M4 5v2.5a2.5 2.5 0 005 0V5" />
        <path d="M10.5 2v3a1.5 1.5 0 003 0V2" />
        <path d="M12 5v2.5a2.5 2.5 0 01-5 0" />
        <path d="M8 10v4" />
      </svg>
    ),
  },
  {
    id: 'community',
    label: 'Community',
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="8" cy="5" r="2.5" />
        <path d="M3 14c0-2.8 2.2-5 5-5s5 2.2 5 5" />
      </svg>
    ),
  },
];

export function DashboardSidebar({ currentView, onNavigate, onSelectSession }: Props) {
  const { data: sessions = [] } = useQuery({
    queryKey: ['sessions'],
    queryFn: () => listSessions(50),
    staleTime: 10_000,
  });

  const recentSessions = sessions.slice(0, 5);

  return (
    <aside className="dash-sidebar">
      <div className="dash-sidebar-brand">
        CEO<span>Claw</span>
      </div>

      <nav className="dash-sidebar-nav">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.id}
            className={`dash-nav-item${currentView === item.id ? ' dash-nav-item--active' : ''}`}
            onClick={() => onNavigate(item.id)}
          >
            {item.icon}
            {item.label}
          </button>
        ))}
      </nav>

      <div className="dash-sidebar-section-title">Recents</div>
      <div className="dash-sidebar-recents">
        {recentSessions.length === 0 && (
          <div className="dash-recent-empty">No recent projects</div>
        )}
        {recentSessions.map((session) => (
          <button
            key={session.session_id}
            className="dash-recent-item"
            onClick={() => onSelectSession(session)}
          >
            <span className="dash-recent-dot" />
            <span className="dash-recent-name">
              {session.product_name || session.slug || session.session_id.slice(0, 8)}
            </span>
          </button>
        ))}
      </div>

      <div className="dash-sidebar-footer">
        <button className="dash-upgrade-btn">
          <span className="dash-upgrade-icon">◆</span>
          Upgrade your plan
        </button>
      </div>
    </aside>
  );
}
