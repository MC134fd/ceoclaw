import { useCallback } from 'react';

interface EditorTabsProps {
  openFiles: string[];
  activeFile: string | null;
  dirtyFiles: Set<string>;
  onSelectTab: (path: string) => void;
  onCloseTab: (path: string) => void;
}

function getDotColor(path: string): string {
  const ext = path.split('.').pop()?.toLowerCase();
  switch (ext) {
    case 'html':
    case 'htm':
      return 'var(--accent)';
    case 'css':
      return '#3b82f6';
    case 'js':
    case 'jsx':
      return '#eab308';
    case 'ts':
    case 'tsx':
      return '#3b82f6';
    case 'json':
      return 'var(--success)';
    case 'svg':
    case 'png':
      return '#8b5cf6';
    default:
      return 'var(--text-muted)';
  }
}

function basename(path: string): string {
  const segments = path.split('/');
  return segments[segments.length - 1] ?? path;
}

export function EditorTabs({ openFiles, activeFile, dirtyFiles, onSelectTab, onCloseTab }: EditorTabsProps) {
  const handleClose = useCallback(
    (e: React.MouseEvent, path: string) => {
      e.stopPropagation();
      onCloseTab(path);
    },
    [onCloseTab],
  );

  if (openFiles.length === 0) return null;

  return (
    <div className="editor-tabs">
      {openFiles.map((path) => {
        const isActive = path === activeFile;
        const isDirty = dirtyFiles.has(path);

        return (
          <div
            key={path}
            className={`editor-tab${isActive ? ' editor-tab--active' : ''}`}
            onClick={() => onSelectTab(path)}
          >
            <span
              className="editor-tab-dot"
              style={{ background: getDotColor(path) }}
            />
            <span className="editor-tab-name">{basename(path)}</span>
            {isDirty ? (
              <span className="editor-tab-dirty" />
            ) : (
              <button
                className="editor-tab-close"
                onClick={(e) => handleClose(e, path)}
                aria-label={`Close ${basename(path)}`}
              >
                ×
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
