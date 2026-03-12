import { useCallback, useEffect, useRef, useState } from 'react';
import { getSessionHistory, sendMessage } from '../services/api';
import type { ChatResponse, Message, PipelineStage } from '../types';

const STAGE_DEFS = [
  { key: 'parse_intent',  label: 'Reading your idea' },
  { key: 'validate_idea', label: 'Validating concept' },
  { key: 'content_plan',  label: 'Planning content' },
  { key: 'image_assets',  label: 'Creating visual assets' },
  { key: 'generate_code', label: 'Generating code' },
  { key: 'apply_files',   label: 'Saving to workspace' },
  { key: 'quality_check', label: 'Quality check' },
  { key: 'complete',      label: 'Complete' },
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
  const [error, setError] = useState<string | null>(null);
  const [chatResponse, setChatResponse] = useState<ChatResponse | null>(null);
  const [pipelineStages, setPipelineStages] = useState<PipelineStage[]>(initialStages());
  const loadedSessionRef = useRef<string>('');
  const esRef = useRef<EventSource | null>(null);

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
      esRef.current?.close();
    };
  }, []);

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
        const assistantMsg: Message = {
          id: Date.now() + 1,
          session_id: sessionId,
          role: 'assistant',
          content: response.assistant_message,
          created_at: new Date().toISOString(),
        };
        setMessages((prev) => [...prev, assistantMsg]);
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Unknown error';
        setError(msg);
        setMessages((prev) => prev.filter((m) => m !== optimisticUserMsg));
      } finally {
        setIsLoading(false);
      }
    },
    [sessionId, isLoading],
  );

  // Pipeline-backed send — streams 8 stage events then delivers final ChatResponse
  const sendViaPipeline = useCallback(
    async (text: string, mockMode: boolean = false) => {
      if (!text.trim() || isLoading) return;
      const runId = `pipeline_${Date.now()}`;
      // #region agent log
      fetch('http://127.0.0.1:7942/ingest/59b4fe2b-fbec-4c75-a07b-b5ac8d9b0c55',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'ae58c9'},body:JSON.stringify({sessionId:'ae58c9',runId,hypothesisId:'H3',location:'frontend/src/hooks/useChat.ts:105',message:'sendViaPipeline invoked',data:{sessionId,loading:isLoading,textLen:text.trim().length},timestamp:Date.now()})}).catch(()=>{});
      // #endregion

      // Close any in-flight SSE
      esRef.current?.close();
      esRef.current = null;

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
        // 1. Start pipeline job
        const startRes = await fetch('/builder/generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: sessionId, message: text, mock_mode: mockMode }),
        });
        if (!startRes.ok) {
          const body = await startRes.json().catch(() => ({}));
          throw new Error(body.detail || `HTTP ${startRes.status}`);
        }
        const { job_id } = (await startRes.json()) as { job_id: string };

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
              // #region agent log
              fetch('http://127.0.0.1:7942/ingest/59b4fe2b-fbec-4c75-a07b-b5ac8d9b0c55',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'ae58c9'},body:JSON.stringify({sessionId:'ae58c9',runId,hypothesisId:'H2',location:'frontend/src/hooks/useChat.ts:154',message:'stage update received',data:{jobId:job_id,stageKey:key,status:event.status,artifactType:event.artifact_type},timestamp:Date.now()})}).catch(()=>{});
              // #endregion
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
              // #region agent log
              fetch('http://127.0.0.1:7942/ingest/59b4fe2b-fbec-4c75-a07b-b5ac8d9b0c55',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'ae58c9'},body:JSON.stringify({sessionId:'ae58c9',runId,hypothesisId:'H1',location:'frontend/src/hooks/useChat.ts:174',message:'pipeline complete received',data:{jobId:job_id,hasVersion:!!result.version_id,slug:result.slug || ''},timestamp:Date.now()})}).catch(()=>{});
              // #endregion
              setChatResponse(result);
              const assistantMsg: Message = {
                id: Date.now() + 1,
                session_id: sessionId,
                role: 'assistant',
                content: result.assistant_message,
                created_at: new Date().toISOString(),
              };
              setMessages((prev) => [...prev, assistantMsg]);
              resolve();
            } else if (event.type === 'pipeline_error') {
              es.close();
              esRef.current = null;
              reject(new Error((event.error as string) || 'Pipeline failed'));
            }
          };

          es.onerror = () => {
            // #region agent log
            fetch('http://127.0.0.1:7942/ingest/59b4fe2b-fbec-4c75-a07b-b5ac8d9b0c55',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'ae58c9'},body:JSON.stringify({sessionId:'ae58c9',runId,hypothesisId:'H1',location:'frontend/src/hooks/useChat.ts:194',message:'eventsource onerror fired',data:{jobId:job_id,readyState:es.readyState},timestamp:Date.now()})}).catch(()=>{});
            // #endregion
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
    [sessionId, isLoading],
  );

  const resetMessages = useCallback(() => {
    esRef.current?.close();
    esRef.current = null;
    setMessages([]);
    setChatResponse(null);
    setError(null);
    setPipelineStages(initialStages());
    loadedSessionRef.current = '';
  }, []);

  return {
    messages,
    sendMessage: send,
    sendViaPipeline,
    pipelineStages,
    isLoading,
    error,
    chatResponse,
    resetMessages,
  };
}
