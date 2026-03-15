import { useCallback, useEffect, useRef, useState } from 'react';
import { InsufficientCreditsError, getSessionHistory, sendMessage } from '../services/api';
import { supabase } from '../lib/supabase';
import type { ChatResponse, Message, PipelineStage } from '../types';


const STAGE_DEFS = [
  { key: 'parse_intent',             label: 'Understanding your idea' },
  { key: 'business_concept',         label: 'Defining business concept' },
  { key: 'feature_architecture',     label: 'Planning feature architecture' },
  { key: 'design_direction',         label: 'Selecting visual direction' },
  { key: 'information_architecture', label: 'Mapping pages and user flow' },
  { key: 'implementation_plan',      label: 'Preparing implementation plan' },
  { key: 'generate_index',           label: 'Generating index page' },
  { key: 'generate_pages',           label: 'Generating additional pages' },
  { key: 'generate_assets',          label: 'Generating icons/visual assets' },
  { key: 'wire_navigation',          label: 'Wiring buttons and navigation' },
  { key: 'quality_check',            label: 'Validating quality and responsiveness' },
  { key: 'complete',                 label: 'Complete' },
] as const;

function initialStages(): PipelineStage[] {
  return STAGE_DEFS.map((s) => ({
    stage_key: s.key,
    stage_label: s.label,
    status: 'pending' as const,
  }));
}

export function useChat(sessionId: string) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isTyping, setIsTyping] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [chatResponse, setChatResponse] = useState<ChatResponse | null>(null);
  const [pipelineStages, setPipelineStages] = useState<PipelineStage[]>(initialStages());
  const loadedSessionRef = useRef<string>('');
  const esRef = useRef<EventSource | null>(null);
  const typingTimerRef = useRef<number | null>(null);

  const stopTypingAnimation = useCallback(() => {
    if (typingTimerRef.current !== null) {
      window.clearInterval(typingTimerRef.current);
      typingTimerRef.current = null;
    }
    setIsTyping(false);
  }, []);

  const appendAssistantMessageWithTyping = useCallback(
    (content: string) =>
      new Promise<void>((resolve) => {
        stopTypingAnimation();

        const assistantMsgId = Date.now() + 1;
        const createdAt = new Date().toISOString();
        const fullText = content ?? '';

        const assistantMsg: Message = {
          id: assistantMsgId,
          session_id: sessionId,
          role: 'assistant',
          content: '',
          created_at: createdAt,
        };
        setMessages((prev) => [...prev, assistantMsg]);

        if (!fullText) {
          resolve();
          return;
        }

        setIsTyping(true);
        const tickMs = 16;
        const charsPerTick = Math.max(1, Math.ceil(fullText.length / 140));
        let index = 0;

        typingTimerRef.current = window.setInterval(() => {
          index = Math.min(fullText.length, index + charsPerTick);
          const nextSlice = fullText.slice(0, index);

          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === assistantMsgId
                ? {
                    ...msg,
                    content: nextSlice,
                  }
                : msg,
            ),
          );

          if (index >= fullText.length) {
            stopTypingAnimation();
            resolve();
          }
        }, tickMs);
      }),
    [sessionId, stopTypingAnimation],
  );

  // Load history when sessionId changes
  useEffect(() => {
    if (!sessionId || loadedSessionRef.current === sessionId) return;
    loadedSessionRef.current = sessionId;

    let cancelled = false;
    getSessionHistory(sessionId)
      .then((history) => {
        if (!cancelled) {
          setMessages(history.messages ?? []);
          setError(null);
        }
      })
      .catch(() => {
        if (!cancelled) setMessages([]);
      });

    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  // Cleanup SSE on unmount
  useEffect(() => {
    return () => {
      stopTypingAnimation();
      esRef.current?.close();
    };
  }, [stopTypingAnimation]);

  // Legacy direct send (kept for backward compat)
  const send = useCallback(
    async (text: string, mockMode: boolean = false) => {
      if (!text.trim() || isLoading) return;
      setIsLoading(true);
      setError(null);

      const optimisticUserMsg: Message = {
        id: Date.now(),
        session_id: sessionId,
        role: 'user',
        content: text,
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, optimisticUserMsg]);

      try {
        const response = await sendMessage(sessionId, text, mockMode);
        setChatResponse(response);
        void appendAssistantMessageWithTyping(response.assistant_message);
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Unknown error';
        setError(msg);
        setMessages((prev) => prev.filter((m) => m !== optimisticUserMsg));
      } finally {
        setIsLoading(false);
      }
    },
    [sessionId, isLoading, appendAssistantMessageWithTyping],
  );

  // Pipeline-backed send — streams 8 stage events then delivers final ChatResponse
  const sendViaPipeline = useCallback(
    async (text: string, mockMode: boolean = false) => {
      if (!text.trim() || isLoading) return;

      // Close any in-flight SSE
      esRef.current?.close();
      esRef.current = null;
      stopTypingAnimation();

      setIsLoading(true);
      setError(null);
      setPipelineStages(initialStages());

      const optimisticUserMsg: Message = {
        id: Date.now(),
        session_id: sessionId,
        role: 'user',
        content: text,
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, optimisticUserMsg]);

      try {
        // 1. Start pipeline job (attach auth token when available)
        const token = supabase
          ? (await supabase.auth.getSession()).data.session?.access_token
          : null;
        const startHeaders: Record<string, string> = { 'Content-Type': 'application/json' };
        if (token) startHeaders['Authorization'] = `Bearer ${token}`;

        const startRes = await fetch('/builder/generate', {
          method: 'POST',
          headers: startHeaders,
          body: JSON.stringify({ session_id: sessionId, message: text, mock_mode: mockMode }),
        });
        if (!startRes.ok) {
          const body = await startRes.json().catch(() => ({}));
          // Surface insufficient-credits as a dedicated error type
          if (startRes.status === 402 && body.detail?.error === 'insufficient_credits') {
            throw new InsufficientCreditsError(
              body.detail.message ?? 'Insufficient credits',
              body.detail.balance ?? 0,
              body.detail.required ?? 1,
              body.detail.tier ?? 'free',
            );
          }
          throw new Error(body.detail?.message ?? body.detail ?? `HTTP ${startRes.status}`);
        }
      type StartResponse =
        | { job_id: string; needs_clarification?: false }
        | { needs_clarification: true; questions: string[]; reason: string; job_id: null };

      const startBody = (await startRes.json()) as StartResponse;

      if (startBody.needs_clarification) {
        const clarifyMsg = [
          'I need a bit more detail before I can build this. Could you answer:',
          ...startBody.questions.map((q: string, i: number) => `${i + 1}. ${q}`),
        ].join('\n');
        void appendAssistantMessageWithTyping(clarifyMsg);
        return;
      }

      const { job_id } = startBody as { job_id: string };

        // 2. Stream events via EventSource
        await new Promise<void>((resolve, reject) => {
          const es = new EventSource(`/builder/generate/${job_id}/events`);
          esRef.current = es;

          es.onmessage = (evt) => {
            let event: Record<string, unknown>;
            try {
              event = JSON.parse(evt.data) as Record<string, unknown>;
            } catch {
              return;
            }

            if (event.type === 'stage_update') {
              const key = event.stage_key as string;
              setPipelineStages((prev) =>
                prev.map((s) =>
                  s.stage_key === key
                    ? {
                        ...s,
                        status: (event.status as PipelineStage['status']) ?? s.status,
                        duration_ms: (event.duration_ms as number | undefined) ?? s.duration_ms,
                        artifact_type: (event.artifact_type as string | undefined) ?? s.artifact_type,
                        artifact_name: (event.artifact_name as string | undefined) ?? s.artifact_name,
                        error: (event.error as string | undefined) ?? s.error,
                      }
                    : s,
                ),
              );
            } else if (event.type === 'pipeline_complete') {
              es.close();
              esRef.current = null;
              const result = event.result as ChatResponse;
              setChatResponse(result);
              void appendAssistantMessageWithTyping(result.assistant_message);
              resolve();
            } else if (event.type === 'pipeline_error') {
              es.close();
              esRef.current = null;
              reject(new Error((event.error as string) || 'Pipeline failed'));
            }
          };

          es.onerror = () => {
            es.close();
            esRef.current = null;
            reject(new Error('Connection lost — please try again'));
          };
        });
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Unknown error';
        setError(msg);
        setMessages((prev) => prev.filter((m) => m !== optimisticUserMsg));
      } finally {
        setIsLoading(false);
      }
    },
    [sessionId, isLoading, appendAssistantMessageWithTyping, stopTypingAnimation],
  );

  const resetMessages = useCallback(() => {
    stopTypingAnimation();
    esRef.current?.close();
    esRef.current = null;
    setMessages([]);
    setChatResponse(null);
    setError(null);
    setPipelineStages(initialStages());
    loadedSessionRef.current = '';
  }, [stopTypingAnimation]);

  return {
    messages,
    sendMessage: send,
    sendViaPipeline,
    pipelineStages,
    isLoading,
    isTyping,
    error,
    chatResponse,
    resetMessages,
  };
}
