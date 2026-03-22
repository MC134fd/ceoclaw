import Editor, { type OnMount } from '@monaco-editor/react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { getFileContent, updateFileContent } from '../services/api';

interface CodeEditorProps {
  sessionId: string;
  filePath: string | null;
  onDirtyChange: (path: string, isDirty: boolean) => void;
  onSave: () => void;
  refreshToken: number;
}

function getLanguage(path: string): string {
  const ext = path.split('.').pop()?.toLowerCase();
  const map: Record<string, string> = {
    html: 'html', htm: 'html',
    css: 'css',
    js: 'javascript', jsx: 'javascript',
    ts: 'typescript', tsx: 'typescript',
    json: 'json',
    md: 'markdown',
    sql: 'sql',
    svg: 'xml', xml: 'xml',
    py: 'python',
    txt: 'plaintext',
  };
  return map[ext ?? ''] ?? 'plaintext';
}

export function CodeEditor({ sessionId, filePath, onDirtyChange, onSave, refreshToken }: CodeEditorProps) {
  const [content, setContent] = useState('');
  const [savedContent, setSavedContent] = useState('');
  const [isLoadingFile, setIsLoadingFile] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [showSavedToast, setShowSavedToast] = useState(false);

  const editorRef = useRef<Parameters<OnMount>[0] | null>(null);
  const autoSaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Stable ref for handleSave so Monaco keybinding always calls the latest version
  const handleSaveRef = useRef<() => Promise<void>>(async () => {});

  const handleSave = useCallback(async () => {
    if (!filePath || isSaving || content === savedContent) return;
    setIsSaving(true);
    try {
      await updateFileContent(sessionId, filePath, content);
      setSavedContent(content);
      onSave();
      setShowSavedToast(true);
      setTimeout(() => setShowSavedToast(false), 1500);
    } catch {
      // Silently fail — user can retry with Cmd+S
    } finally {
      setIsSaving(false);
    }
  }, [filePath, sessionId, content, savedContent, isSaving, onSave]);

  useEffect(() => {
    handleSaveRef.current = handleSave;
  }, [handleSave]);

  // Load file content when filePath changes
  useEffect(() => {
    if (!filePath) {
      setContent('');
      setSavedContent('');
      setLoadError(null);
      return;
    }

    let cancelled = false;
    setIsLoadingFile(true);
    setLoadError(null);

    getFileContent(sessionId, filePath)
      .then((res) => {
        if (!cancelled) {
          setContent(res.content);
          setSavedContent(res.content);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setLoadError(err instanceof Error ? err.message : 'Failed to load file');
        }
      })
      .finally(() => {
        if (!cancelled) setIsLoadingFile(false);
      });

    return () => { cancelled = true; };
  }, [filePath, sessionId]);

  // AI refresh — re-fetch file content when generation completes (only if not dirty)
  useEffect(() => {
    if (!filePath || refreshToken === 0) return;
    if (content !== savedContent) return;

    let cancelled = false;
    getFileContent(sessionId, filePath)
      .then((res) => {
        if (!cancelled) {
          setContent(res.content);
          setSavedContent(res.content);
        }
      })
      .catch(() => {
        // Silent — file may not exist yet
      });

    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshToken]);

  // Dirty tracking
  useEffect(() => {
    if (filePath) {
      onDirtyChange(filePath, content !== savedContent);
    }
  }, [content, savedContent, filePath, onDirtyChange]);

  // Auto-save with debounce — captures path+content in closure for tab-switch safety
  useEffect(() => {
    if (!filePath || content === savedContent) return;

    const currentPath = filePath;
    const currentContent = content;

    const timer = setTimeout(async () => {
      try {
        await updateFileContent(sessionId, currentPath, currentContent);
        setSavedContent((prev) => {
          // Only update if we're still on the same file and content hasn't changed further
          if (prev !== currentContent) return prev;
          return currentContent;
        });
      } catch {
        // Silent fail
      }
    }, 2000);

    autoSaveTimerRef.current = timer;
    return () => clearTimeout(timer);
  }, [content, savedContent, filePath, sessionId]);

  // Prevent browser save dialog on Cmd+S / Ctrl+S
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 's') {
        e.preventDefault();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  const handleEditorMount: OnMount = useCallback((editor, monaco) => {
    editorRef.current = editor;
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
      handleSaveRef.current();
    });
  }, []);

  if (!filePath) {
    return (
      <div className="code-editor-empty">
        Select a file from the explorer to start editing
      </div>
    );
  }

  if (isLoadingFile) {
    return (
      <div className="code-editor-loading">
        Loading...
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="code-editor-error">
        {loadError}
      </div>
    );
  }

  return (
    <div className="code-editor-wrapper">
      {showSavedToast && (
        <div className="code-editor-saved-toast">Saved</div>
      )}
      <Editor
        height="100%"
        language={getLanguage(filePath)}
        value={content}
        onChange={(value) => setContent(value ?? '')}
        onMount={handleEditorMount}
        theme="vs-dark"
        loading={<div className="code-editor-loading">Loading editor...</div>}
        options={{
          minimap: { enabled: false },
          fontSize: 13,
          lineNumbers: 'on',
          wordWrap: 'on',
          scrollBeyondLastLine: false,
          automaticLayout: true,
          tabSize: 2,
          padding: { top: 12 },
          fontFamily: '\'JetBrains Mono\', \'Fira Code\', \'Cascadia Code\', \'SF Mono\', monospace',
          renderLineHighlight: 'line',
          cursorBlinking: 'smooth',
          smoothScrolling: true,
          bracketPairColorization: { enabled: true },
          guides: { bracketPairs: true },
          scrollbar: {
            verticalScrollbarSize: 6,
            horizontalScrollbarSize: 6,
          },
        }}
      />
    </div>
  );
}
