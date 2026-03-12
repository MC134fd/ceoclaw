import { useCallback, useEffect, useRef, useState } from 'react';
import type { PreviewTab, VersionRecord } from '../types';
import { listVersions, restoreVersion } from '../services/api';

interface Props {
  slug: string | null;
  landingUrl: string | null;
  appUrl: string | null;
  previewPath?: string | null;
  sessionId?: string | null;
  isGenerating?: boolean;
  generationPhase?: string;
  completionToken?: string | null;
}

export function PreviewPane({
  slug,
  landingUrl,
  appUrl,
  previewPath,
  sessionId,
  isGenerating = false,
  generationPhase = 'Generating updates...',
  completionToken = null,
}: Props) {
  const [activeTab, setActiveTab] = useState<PreviewTab>('landing');
  const [viewportMode, setViewportMode] = useState<'desktop' | 'tablet' | 'mobile'>('desktop');
  const [refreshKey, setRefreshKey] = useState(0);
  const [showVersions, setShowVersions] = useState(false);
  const [versions, setVersions] = useState<VersionRecord[]>([]);
  const [versionsLoading, setVersionsLoading] = useState(false);
  const [restoring, setRestoring] = useState<string | null>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const wasGeneratingRef = useRef(false);
  const lastCompletionTokenRef = useRef<string | null>(null);

  // Determine current URL: prefer explicit previewPath, otherwise tab-based
  const currentUrl = previewPath
    ? (slug ? `/websites/${slug}/${previewPath}` : null)
    : activeTab === 'landing'
    ? landingUrl
    : appUrl;
  const hasPreview = Boolean(slug && currentUrl);

  // Refresh when slug changes (new content)
  useEffect(() => {
    if (slug) {
      setRefreshKey((k) => k + 1);
    }
  }, [slug]);

  // Refresh exactly once when generation completes.
  useEffect(() => {
    if (wasGeneratingRef.current && !isGenerating) {
      const shouldRefresh =
        completionToken === null || completionToken !== lastCompletionTokenRef.current;
      // #region agent log
      fetch('http://127.0.0.1:7942/ingest/59b4fe2b-fbec-4c75-a07b-b5ac8d9b0c55',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'ae58c9'},body:JSON.stringify({sessionId:'ae58c9',runId:`preview_${Date.now()}`,hypothesisId:'H4',location:'frontend/src/components/PreviewPane.tsx:57',message:'generation transition detected',data:{wasGenerating:wasGeneratingRef.current,isGenerating,completionToken,lastToken:lastCompletionTokenRef.current,shouldRefresh},timestamp:Date.now()})}).catch(()=>{});
      // #endregion
      if (shouldRefresh) {
        setRefreshKey((k) => k + 1);
        if (completionToken) {
          lastCompletionTokenRef.current = completionToken;
        }
      }
    }
    wasGeneratingRef.current = isGenerating;
  }, [isGenerating, completionToken]);

  const handleRefresh = useCallback(() => {
    setRefreshKey((k) => k + 1);
  }, []);

  const handleToggleVersions = useCallback(async () => {
    if (!showVersions && sessionId) {
      setVersionsLoading(true);
      try {
        const data = await listVersions(sessionId);
        setVersions(data);
      } catch {
        setVersions([]);
      } finally {
        setVersionsLoading(false);
      }
    }
    setShowVersions((v) => !v);
  }, [showVersions, sessionId]);

  const handleRestore = useCallback(
    async (versionId: string) => {
      if (!sessionId) return;
      setRestoring(versionId);
      try {
        await restoreVersion(sessionId, versionId);
        setRefreshKey((k) => k + 1);
        setShowVersions(false);
      } catch {
        // silently ignore — user can retry
      } finally {
        setRestoring(null);
      }
    },
    [sessionId],
  );

  const iframeSrc = hasPreview ? `${currentUrl}?t=${refreshKey}` : '';

  return (
    <section className="preview-pane">
      {/* Header */}
      <div className="preview-pane-header">
        {/* Tab toggle — only when no explicit previewPath */}
        {!previewPath && (
          <div className="preview-tabs">
            {(['landing', 'app'] as PreviewTab[]).map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`preview-tab ${activeTab === tab ? 'preview-tab-active' : ''}`}
              >
                {tab === 'landing' ? 'Landing' : 'App'}
              </button>
            ))}
          </div>
        )}
        {previewPath && (
          <span style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'monospace' }}>
            {previewPath}
          </span>
        )}

        <div className="preview-actions">
          <div className="preview-viewport" role="tablist" aria-label="Preview viewport">
            {(['desktop', 'tablet', 'mobile'] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                role="tab"
                aria-selected={viewportMode === mode}
                onClick={() => setViewportMode(mode)}
                className={`preview-viewport-btn ${
                  viewportMode === mode ? 'preview-viewport-btn--active' : ''
                }`}
              >
                {mode === 'desktop' ? 'D' : mode === 'tablet' ? 'T' : 'M'}
              </button>
            ))}
          </div>
          {/* Versions button */}
          {sessionId && (
            <button
              onClick={handleToggleVersions}
              style={{
                padding: '4px 10px',
                borderRadius: 6,
                border: '1px solid var(--border)',
                background: showVersions ? 'var(--accent)' : 'var(--surface-2)',
                color: showVersions ? '#fff' : 'var(--text-muted)',
                fontSize: 11,
                cursor: 'pointer',
                fontFamily: 'var(--font)',
                transition: 'all 0.12s',
              }}
              data-testid="versions-button"
            >
              Versions
            </button>
          )}
          {hasPreview && (
            <a
              href={currentUrl ?? '#'}
              target="_blank"
              rel="noopener noreferrer"
              className="preview-link-button"
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLAnchorElement).style.color = 'var(--accent)';
                (e.currentTarget as HTMLAnchorElement).style.borderColor = 'var(--accent)';
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLAnchorElement).style.color = 'var(--text-muted)';
                (e.currentTarget as HTMLAnchorElement).style.borderColor = 'var(--border)';
              }}
              data-testid="open-new-tab"
            >
              ↗ Open
            </a>
          )}
          <button
            onClick={handleRefresh}
            className="preview-button"
          >
            ↺ Refresh
          </button>
        </div>
      </div>

      {/* Versions panel */}
      {showVersions && (
        <div className="preview-versions-panel" data-testid="versions-panel">
          <div
            style={{
              fontWeight: 600,
              fontSize: 12,
              color: 'var(--text-muted)',
              textTransform: 'uppercase',
              letterSpacing: '0.06em',
              marginBottom: 10,
            }}
          >
            Version History
          </div>
          {versionsLoading && (
            <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>Loading...</div>
          )}
          {!versionsLoading && versions.length === 0 && (
            <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>No versions saved yet.</div>
          )}
          {!versionsLoading &&
            versions.map((v) => (
              <div
                key={v.version_id}
                style={{
                  padding: '8px 0',
                  borderBottom: '1px solid var(--border)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: 8,
                }}
              >
                <div>
                  <div style={{ fontSize: 11, fontFamily: 'monospace', color: 'var(--text)' }}>
                    {v.version_id}
                  </div>
                  <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>
                    {v.file_list.length} file{v.file_list.length !== 1 ? 's' : ''} &middot;{' '}
                    {new Date(v.created_at).toLocaleString()}
                  </div>
                </div>
                <button
                  onClick={() => handleRestore(v.version_id)}
                  disabled={restoring === v.version_id}
                  style={{
                    padding: '3px 10px',
                    borderRadius: 5,
                    border: '1px solid var(--border)',
                    background: 'var(--surface-2)',
                    color: 'var(--accent)',
                    fontSize: 11,
                    cursor: restoring === v.version_id ? 'wait' : 'pointer',
                    flexShrink: 0,
                  }}
                  data-testid={`restore-${v.version_id}`}
                >
                  {restoring === v.version_id ? '...' : 'Restore'}
                </button>
              </div>
            ))}
        </div>
      )}

      {/* Body */}
      <div className="preview-pane-body">
        {!hasPreview && (
          <div className="preview-placeholder" data-testid="preview-placeholder">
            <div
              style={{
                width: 56,
                height: 56,
                borderRadius: 16,
                background: 'var(--surface-2)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 28,
              }}
            >
              🏗
            </div>
            <p style={{ textAlign: 'center', maxWidth: 240, lineHeight: 1.5, margin: 0 }}>
              Your generated site will appear here after your first message.
            </p>
          </div>
        )}
        {hasPreview && (
          <div className={`preview-canvas preview-canvas--${viewportMode}`}>
            <iframe
              ref={iframeRef}
              src={iframeSrc}
              title="Generated site preview"
              className="preview-iframe"
              data-testid="preview-iframe"
            />
          </div>
        )}
        {isGenerating && (
          <div className="preview-loading-overlay" data-testid="preview-loading-overlay">
            <div className="preview-loading-shimmer" />
            <div className="preview-loading-card">
              <span className="preview-loading-spinner" />
              <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)' }}>
                  Updating preview...
                </span>
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{generationPhase}</span>
              </div>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
