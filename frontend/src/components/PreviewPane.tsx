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
              className={`preview-versions-btn${showVersions ? ' preview-versions-btn--active' : ''}`}
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
          <div className="preview-versions-header">Version History</div>
          {versionsLoading && (
            <div className="preview-version-date">Loading...</div>
          )}
          {!versionsLoading && versions.length === 0 && (
            <div className="preview-version-date">No versions saved yet.</div>
          )}
          {!versionsLoading &&
            versions.map((v) => (
              <div key={v.version_id} className="preview-version-item">
                <div className="preview-version-info">
                  <div className="preview-version-id">{v.version_id}</div>
                  <div className="preview-version-date">
                    {v.file_list.length} file{v.file_list.length !== 1 ? 's' : ''} &middot;{' '}
                    {new Date(v.created_at).toLocaleString()}
                  </div>
                </div>
                <button
                  onClick={() => handleRestore(v.version_id)}
                  disabled={restoring === v.version_id}
                  className="preview-restore-btn"
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
            <div className="preview-placeholder-icon">🏗</div>
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
              <div className="preview-loading-inner">
                <span className="preview-loading-title">Updating preview...</span>
                <span className="preview-loading-phase">{generationPhase}</span>
              </div>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
