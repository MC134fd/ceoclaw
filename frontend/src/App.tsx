import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useRef, useState } from 'react';
import { BuildLog } from './components/BuildLog';
import { ChatMessage } from './components/ChatMessage';
import { Composer } from './components/Composer';
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

const QUICK_PROMPTS = [
  'Build a premium SaaS landing page for a dog training app',
  'Turn this into a multi-page site with pricing, blog, and contact',
  'Add Stripe-ready pricing cards and signup CTA flow',
] as const;

export default function App() {
  const queryClient = useQueryClient();
  const { user, session, isLoading: authLoading, signInWithGoogle, signOut } = useAuth();
  const { sessionId, setSessionId, clearSession } = useSession();
  const { messages, sendViaPipeline, pipelineStages, isLoading, isTyping, error, chatResponse, resetMessages } =
    useChat(sessionId);

  const [currentSlug, setCurrentSlug] = useState<string | null>(null);
  const [landingUrl, setLandingUrl] = useState<string | null>(null);
  const [appUrl, setAppUrl] = useState<string | null>(null);
  const [lastModel, setLastModel] = useState<ModelInfo | null>(null);
  const [isSessionDrawerOpen, setIsSessionDrawerOpen] = useState(false);
  const [isOutOfCredits, setIsOutOfCredits] = useState(false);

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

  // Derive current generation phase from the active pipeline stage
  const generationPhase =
    pipelineStages.find((s) => s.status === 'running')?.stage_label ?? 'Generating...';

  const handleSend = useCallback(
    async (text: string) => {
      setIsOutOfCredits(false);
      try {
        await sendViaPipeline(text, false);
      } catch (err) {
        if (err instanceof InsufficientCreditsError) {
          setIsOutOfCredits(true);
        }
      }
    },
    [sendViaPipeline],
  );

  const handleNewSession = useCallback(() => {
    clearSession();
    resetMessages();
    setCurrentSlug(null);
    setLandingUrl(null);
    setAppUrl(null);
    setLastModel(null);
    setIsOutOfCredits(false);
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

  // ── Auth gate: show landing page when Supabase is configured but user is not signed in ──
  if (isAuthEnabled && !authLoading && !user) {
    return <LandingPage onSignIn={signInWithGoogle} />;
  }
  if (isAuthEnabled && authLoading) {
    return (
      <div className="app-root" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <span style={{ color: 'var(--text-dim)', fontSize: 14 }}>Signing in…</span>
      </div>
    );
  }

  return (
    <div className="app-root">
      {/* Topbar */}
      <header className="app-topbar">
        <div className="app-topbar-left">
          <button
            onClick={() => setIsSessionDrawerOpen((open) => !open)}
            className={
              isSessionDrawerOpen
                ? 'app-chats-button app-chats-button--active'
                : 'app-chats-button'
            }
            aria-label="Toggle sessions panel"
          >
            <span style={{ fontSize: 14, lineHeight: 1 }}>☰</span>
            Chats
          </button>
          <div className="app-brand">
            CEO<span style={{ color: 'var(--accent)' }}>Claw</span>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <ModelStatusBadge model={lastModel} />
          {user && <TopBarUser user={user} onSignOut={signOut} />}
        </div>
      </header>

      {/* Workspace */}
      <div className="app-workspace">
        {/* Chat panel */}
        <div className="app-chat-panel">
          {/* Error banner */}
          {error && (
            <div className="app-error-banner">
              <span>⚠</span>
              <span>{error}</span>
            </div>
          )}

          {/* Messages — scrollable region */}
          <div className="app-messages">
            {/* Welcome message */}
            {messages.length === 0 && (
              <>
                <div className="app-welcome-message">
                  Describe your product — I&apos;ll build a live preview instantly.
                </div>
                <div className="app-quick-prompts" aria-label="Quick prompts">
                  {QUICK_PROMPTS.map((prompt) => (
                    <button
                      key={prompt}
                      type="button"
                      className="app-quick-prompt"
                      onClick={() => handleSend(prompt)}
                      disabled={isLoading}
                    >
                      {prompt}
                    </button>
                  ))}
                </div>
              </>
            )}

            {messages.map((msg: Message, idx: number) => (
              <ChatMessage
                key={msg.id}
                message={msg}
                chatResponse={idx === lastAssistantIdx ? chatResponse : null}
                isTyping={isTyping && idx === lastAssistantIdx}
              />
            ))}

            {isLoading && <BuildLog stages={pipelineStages} />}
            <div ref={messagesEndRef} />
          </div>

          {/* Composer — always rendered, sticky at bottom */}
          <Composer
            onSubmit={handleSend}
            disabled={isLoading}
            placeholder="Describe your product or request a change…"
            outOfCredits={isOutOfCredits}
          />
        </div>

        {/* Preview pane */}
        <PreviewPane
          slug={currentSlug}
          landingUrl={landingUrl}
          appUrl={appUrl}
          sessionId={sessionId}
          isGenerating={isLoading}
          generationPhase={generationPhase}
          completionToken={chatResponse?.version_id ?? null}
        />

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
