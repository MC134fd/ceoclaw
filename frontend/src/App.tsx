import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useRef, useState } from 'react';
import { BuildLog } from './components/BuildLog';
import { ChatMessage } from './components/ChatMessage';
import { CodeEditor } from './components/CodeEditor';
import { ComingSoon } from './components/ComingSoon';
import { Composer } from './components/Composer';
import { Dashboard } from './components/Dashboard';
import { DashboardSidebar } from './components/DashboardSidebar';
import type { DashboardView } from './components/DashboardSidebar';
import { EditorTabs } from './components/EditorTabs';
import { FileExplorer } from './components/FileExplorer';
import { HomePage } from './components/HomePage';
import { LandingPage } from './components/LandingPage';
import { ModelStatusBadge } from './components/ModelStatusBadge';
import { PreviewPane } from './components/PreviewPane';
import { SessionSidebar } from './components/SessionSidebar';
import { TopBarUser } from './components/TopBarUser';
import { useAuth } from './hooks/useAuth';
import { useChat } from './hooks/useChat';
import { useSession } from './hooks/useSession';
import { isAuthEnabled } from './lib/supabase';
import { InsufficientCreditsError, getSessionHistory } from './services/api';
import type { Message, ModelInfo, Session } from './types';

export default function App() {
  const queryClient = useQueryClient();
  const { user, isLoading: authLoading, signInWithGoogle, signInWithEmail, signUpWithEmail, signOut } = useAuth();
  const { sessionId, setSessionId, clearSession } = useSession();
  const { messages, sendViaPipeline, pipelineStages, isLoading, isTyping, error, chatResponse, resetMessages, generatingFiles, fileProgress } =
    useChat(sessionId);

  const [showHome, setShowHome] = useState(true);
  const [view, setView] = useState<'dashboard' | 'chat'>('dashboard');
  const [dashboardView, setDashboardView] = useState<DashboardView>('home');
  const [currentSlug, setCurrentSlug] = useState<string | null>(null);
  const [landingUrl, setLandingUrl] = useState<string | null>(null);
  const [appUrl, setAppUrl] = useState<string | null>(null);
  const [lastModel, setLastModel] = useState<ModelInfo | null>(null);
  const [isSessionDrawerOpen, setIsSessionDrawerOpen] = useState(false);
  const [isOutOfCredits, setIsOutOfCredits] = useState(false);
  const [pendingPrompt, setPendingPrompt] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [centerView, setCenterView] = useState<'preview' | 'code'>('preview');
  const [fileRefreshToken, setFileRefreshToken] = useState(0);
  const [openFiles, setOpenFiles] = useState<string[]>([]);
  const [dirtyFiles, setDirtyFiles] = useState<Set<string>>(new Set());
  const [editorRefreshToken, setEditorRefreshToken] = useState(0);

  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages, isLoading]);

  // When chatResponse updates, extract preview URLs
  useEffect(() => {
    if (chatResponse) {
      if (chatResponse.slug) setCurrentSlug(chatResponse.slug);
      if (chatResponse.landing_url) setLandingUrl(chatResponse.landing_url);
      if (chatResponse.app_url) setAppUrl(chatResponse.app_url);
      if (chatResponse.model) setLastModel(chatResponse.model);
    }
  }, [chatResponse]);

  // Refresh file explorer when a generation completes
  useEffect(() => {
    if (chatResponse?.version_id) {
      setFileRefreshToken((t) => t + 1);
    }
  }, [chatResponse?.version_id]);

  // Refresh editor content when AI finishes generating
  useEffect(() => {
    if (chatResponse?.version_id) {
      setEditorRefreshToken((t) => t + 1);
    }
  }, [chatResponse?.version_id]);

  const handleFileSelect = useCallback((path: string) => {
    setSelectedFile(path);
    setCenterView('code');
    setOpenFiles((prev) => prev.includes(path) ? prev : [...prev, path]);
  }, []);

  const handleCloseTab = useCallback((path: string) => {
    setOpenFiles((prev) => {
      const next = prev.filter((p) => p !== path);
      if (path === selectedFile) {
        const idx = prev.indexOf(path);
        const newActive = next[Math.min(idx, next.length - 1)] ?? null;
        setSelectedFile(newActive);
        if (!newActive) setCenterView('preview');
      }
      return next;
    });
    setDirtyFiles((prev) => {
      const next = new Set(prev);
      next.delete(path);
      return next;
    });
  }, [selectedFile]);

  const handleDirtyChange = useCallback((path: string, isDirty: boolean) => {
    setDirtyFiles((prev) => {
      const next = new Set(prev);
      if (isDirty) next.add(path);
      else next.delete(path);
      return next;
    });
  }, []);

  const handleEditorSave = useCallback(() => {
    setFileRefreshToken((t) => t + 1);
  }, []);

  // Derive current generation phase from the active pipeline stage
  const generationPhase =
    pipelineStages.find((s) => s.status === 'running')?.stage_label ?? 'Generating...';

  const handleSend = useCallback(
    async (text: string) => {
      setIsOutOfCredits(false);
      try {
        await sendViaPipeline(text, selectedFile);
      } catch (err) {
        if (err instanceof InsufficientCreditsError) {
          setIsOutOfCredits(true);
        }
      }
    },
    [sendViaPipeline, selectedFile],
  );

  const handleNewSession = useCallback(() => {
    clearSession();
    resetMessages();
    setCurrentSlug(null);
    setLandingUrl(null);
    setAppUrl(null);
    setLastModel(null);
    setIsOutOfCredits(false);
    setSelectedFile(null);
    setCenterView('preview');
    setOpenFiles([]);
    setDirtyFiles(new Set());
    setEditorRefreshToken(0);
    void queryClient.invalidateQueries({ queryKey: ['sessions'] });
  }, [clearSession, resetMessages, queryClient]);

  const handleSessionDeleted = useCallback(
    (deletedId: string) => {
      if (deletedId === sessionId) {
        handleNewSession();
      }
    },
    [sessionId, handleNewSession],
  );

  const handleSelectSession = useCallback(
    async (session: Session) => {
      setSessionId(session.session_id);
      setIsSessionDrawerOpen(false);
      resetMessages();
      setCurrentSlug(null);
      setLandingUrl(null);
      setAppUrl(null);
      setLastModel(null);
      setSelectedFile(null);
      setCenterView('preview');
      setOpenFiles([]);
      setDirtyFiles(new Set());
      setFileRefreshToken((t) => t + 1);

      try {
        const history = await getSessionHistory(session.session_id);
        if (history.slug) {
          setCurrentSlug(history.slug);
          setLandingUrl(history.landing_url || `/websites/${history.slug}/index`);
          setAppUrl(history.app_url || `/websites/${history.slug}/app`);
        }
      } catch {
        // Ignore: useChat will handle loading from the new sessionId
      }
    },
    [setSessionId, resetMessages],
  );

  const handleDashboardSelectSession = useCallback(
    async (session: Session) => {
      await handleSelectSession(session);
      setView('chat');
    },
    [handleSelectSession],
  );

  const handleDashboardNewChat = useCallback(
    (text: string) => {
      handleNewSession();
      setPendingPrompt(text);
      setView('chat');
    },
    [handleNewSession],
  );

  // Auto-send the pending prompt after switching to chat view
  useEffect(() => {
    if (pendingPrompt && view === 'chat') {
      const prompt = pendingPrompt;
      setPendingPrompt(null);
      void handleSend(prompt);
    }
  }, [pendingPrompt, view, handleSend]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setIsSessionDrawerOpen(false);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  // Find the last assistant message index to attach chatResponse
  const lastAssistantIdx = (() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === 'assistant') return i;
    }
    return -1;
  })();

  // ── Home page gate: show marketing homepage first ──
  // Skip for returning authenticated users — take them straight to their dashboard.
  if (showHome && !(isAuthEnabled && !authLoading && user)) {
    return <HomePage onGetStarted={() => setShowHome(false)} />;
  }

  // ── Auth gate: show landing page when Supabase is configured but user is not signed in ──
  if (isAuthEnabled && !authLoading && !user) {
    return <LandingPage onSignIn={signInWithGoogle} onEmailSignIn={signInWithEmail} onEmailSignUp={signUpWithEmail} />;
  }
  if (isAuthEnabled && authLoading) {
    return (
      <div className="app-root" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <span style={{ color: 'var(--text-dim)', fontSize: 14 }}>Signing in…</span>
      </div>
    );
  }

  // ── Dashboard gate ──
  if (view === 'dashboard') {
    const COMING_SOON_VIEWS = ['integrations', 'community'] as const;
    const comingSoonTitle: Record<string, string> = {
      integrations: 'Integrations',
      community: 'Community',
    };

    return (
      <div className="dashboard-layout">
        <DashboardSidebar
          currentView={dashboardView}
          onNavigate={setDashboardView}
          onSelectSession={handleDashboardSelectSession}
        />
        <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minWidth: 0 }}>
          {/* Dashboard topbar */}
          <header style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '0 28px',
            height: 52,
            borderBottom: '1px solid var(--border)',
            background: 'var(--surface)',
            flexShrink: 0,
          }}>
            <div className="app-brand">
              CEO<span style={{ color: 'var(--accent-bronze)' }}>Claw</span>
            </div>
            <button
              onClick={async () => { await signOut(); setShowHome(true); }}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                padding: '5px 12px',
                borderRadius: 4,
                border: '1px solid var(--border-strong)',
                background: 'transparent',
                color: 'var(--text-secondary)',
                fontSize: 12,
                fontFamily: 'var(--font)',
                letterSpacing: '0.01em',
                cursor: 'pointer',
                transition: 'all 150ms ease',
              }}
              onMouseEnter={e => {
                (e.currentTarget as HTMLButtonElement).style.background = 'var(--surface-2)';
                (e.currentTarget as HTMLButtonElement).style.color = 'var(--text)';
              }}
              onMouseLeave={e => {
                (e.currentTarget as HTMLButtonElement).style.background = 'transparent';
                (e.currentTarget as HTMLButtonElement).style.color = 'var(--text-secondary)';
              }}
            >
              <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M10 12L6 8l4-4" />
              </svg>
              Back to Home
            </button>
          </header>
          {(COMING_SOON_VIEWS as readonly string[]).includes(dashboardView) ? (
            <ComingSoon title={comingSoonTitle[dashboardView] ?? dashboardView} />
          ) : (
            <Dashboard
              view={dashboardView === 'all-apps' ? 'all-apps' : 'home'}
              onSelectSession={handleDashboardSelectSession}
              onNewChat={handleDashboardNewChat}
              onViewAllApps={() => setDashboardView('all-apps')}
            />
          )}
        </div>
      </div>
    );
  }

  // ── Chat view ──
  return (
    <div className="app-root">
      {/* Topbar */}
      <header className="app-topbar">
        <div className="app-topbar-left">
          <button
            onClick={() => setView('dashboard')}
            className="app-back-btn"
            aria-label="Back to dashboard"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M10 12L6 8l4-4" />
            </svg>
          </button>
          <div className="app-brand">
            CEO<span style={{ color: 'var(--accent-bronze)' }}>Claw</span>
          </div>
          {currentSlug && (
            <span className="app-project-label">
              {chatResponse?.product_name || currentSlug}
            </span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <ModelStatusBadge model={lastModel} />
          {user && <TopBarUser user={user} onSignOut={signOut} />}
        </div>
      </header>

      {/* Workspace */}
      <div className="app-workspace">
        {/* Chat panel — left side */}
        <div className="app-chat-panel">
          {error && (
            <div className="app-error-banner">
              <span>⚠</span>
              <span>{error}</span>
            </div>
          )}

          <div className="app-messages">
            {messages.length === 0 && (
              <div className="app-welcome-message">
                Describe your product — I&apos;ll build a live preview instantly.
              </div>
            )}

            {messages.map((msg: Message, idx: number) => (
              <ChatMessage
                key={msg.id}
                message={msg}
                chatResponse={idx === lastAssistantIdx ? chatResponse : null}
                isTyping={isTyping && idx === lastAssistantIdx}
              />
            ))}

            {isLoading && fileProgress && (
              <div className="file-progress-indicator">
                <span className="file-progress-dot" />
                <span className="file-progress-text">
                  Writing <code>{fileProgress.current}</code>
                </span>
                <span className="file-progress-count">
                  {fileProgress.index}/{fileProgress.total}
                </span>
              </div>
            )}

            {isLoading && <BuildLog stages={pipelineStages} />}
            <div ref={messagesEndRef} />
          </div>

          <Composer
            onSubmit={handleSend}
            disabled={isLoading}
            placeholder="Describe your product or request a change…"
            outOfCredits={isOutOfCredits}
          />
        </div>

        {/* Center panel */}
        <div className="app-center-panel">
          {/* View toggle tabs */}
          <div className="app-center-tabs">
            <button
              className={`app-center-tab${centerView === 'preview' ? ' app-center-tab--active' : ''}`}
              onClick={() => setCenterView('preview')}
            >
              Preview
            </button>
            <button
              className={`app-center-tab${centerView === 'code' ? ' app-center-tab--active' : ''}`}
              onClick={() => setCenterView('code')}
            >
              Code
            </button>
          </div>

          <div style={{ display: centerView === 'preview' ? 'flex' : 'none', flexDirection: 'column', flex: 1, minHeight: 0 }}>
            <PreviewPane
              slug={currentSlug}
              landingUrl={landingUrl}
              appUrl={appUrl}
              sessionId={sessionId}
              isGenerating={isLoading}
              generationPhase={generationPhase}
              completionToken={chatResponse?.version_id ?? null}
            />
          </div>

          <div style={{ display: centerView === 'code' ? 'flex' : 'none', flex: 1, minHeight: 0, overflow: 'hidden' }}>
            {/* File explorer embedded inside code view */}
            {currentSlug && (
              <div className="app-code-file-explorer">
                <FileExplorer
                  sessionId={sessionId}
                  onFileSelect={handleFileSelect}
                  selectedFile={selectedFile}
                  generatingFiles={generatingFiles}
                  refreshToken={fileRefreshToken}
                />
              </div>
            )}
            <div className="app-code-editor-area">
              <EditorTabs
                openFiles={openFiles}
                activeFile={selectedFile}
                dirtyFiles={dirtyFiles}
                onSelectTab={setSelectedFile}
                onCloseTab={handleCloseTab}
              />
              <CodeEditor
                sessionId={sessionId}
                filePath={selectedFile}
                onDirtyChange={handleDirtyChange}
                onSave={handleEditorSave}
                refreshToken={editorRefreshToken}
              />
            </div>
          </div>
        </div>

        {/* Session drawer — always mounted; CSS handles open/close transition */}
        <div
          aria-hidden={!isSessionDrawerOpen}
          onClick={() => setIsSessionDrawerOpen(false)}
          className={
            isSessionDrawerOpen
              ? 'app-session-drawer-backdrop app-session-drawer-backdrop--open'
              : 'app-session-drawer-backdrop'
          }
        />
        <div
          role="dialog"
          aria-label="Chat sessions"
          aria-modal="true"
          className={
            isSessionDrawerOpen
              ? 'app-session-drawer-panel app-session-drawer-panel--open'
              : 'app-session-drawer-panel'
          }
        >
          <SessionSidebar
            currentSessionId={sessionId}
            onSelectSession={handleSelectSession}
            onNewSession={handleNewSession}
            onSessionDeleted={handleSessionDeleted}
          />
        </div>
      </div>
    </div>
  );
}
