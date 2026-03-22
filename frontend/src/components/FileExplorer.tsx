import { useEffect, useRef, useState } from 'react';
import { listProjectFiles } from '../services/api';
import type { FileTreeNode, ProjectFile } from '../types';

interface FileExplorerProps {
  sessionId: string | null;
  onFileSelect: (path: string) => void;
  selectedFile: string | null;
  generatingFiles: string[];
  refreshToken: number;
}

function extColor(filename: string): string {
  const ext = filename.slice(filename.lastIndexOf('.')).toLowerCase();
  if (ext === '.html') return 'var(--accent)';
  if (ext === '.css') return '#3b82f6';
  if (ext === '.js') return '#eab308';
  if (ext === '.json') return 'var(--success)';
  if (['.svg', '.png', '.jpg', '.jpeg', '.webp'].includes(ext)) return '#8b5cf6';
  return 'var(--text-muted)';
}

export function buildTree(files: ProjectFile[]): FileTreeNode[] {
  const root: FileTreeNode[] = [];
  const folderMap = new Map<string, FileTreeNode>();

  // Sort: folders first, then files, each group alphabetically
  const sorted = [...files].sort((a, b) => {
    const aHasDir = a.file_path.includes('/');
    const bHasDir = b.file_path.includes('/');
    if (aHasDir !== bHasDir) return aHasDir ? -1 : 1;
    return a.file_path.localeCompare(b.file_path);
  });

  for (const f of sorted) {
    const parts = f.file_path.split('/');
    if (parts.length === 1) {
      // Root-level file
      root.push({ name: f.file_path, path: f.file_path, type: 'file' });
    } else {
      // File inside a folder — ensure folder node exists
      const folderName = parts[0];
      let folder = folderMap.get(folderName);
      if (!folder) {
        folder = { name: folderName, path: folderName, type: 'folder', children: [] };
        folderMap.set(folderName, folder);
        root.push(folder);
      }
      folder.children!.push({
        name: parts.slice(1).join('/'),
        path: f.file_path,
        type: 'file',
      });
    }
  }

  // Sort root: folders first, then files
  root.sort((a, b) => {
    if (a.type !== b.type) return a.type === 'folder' ? -1 : 1;
    return a.name.localeCompare(b.name);
  });

  return root;
}

interface TreeNodeProps {
  node: FileTreeNode;
  depth: number;
  selectedFile: string | null;
  generatingFiles: string[];
  expandedFolders: Set<string>;
  onToggleFolder: (path: string) => void;
  onFileSelect: (path: string) => void;
}

function TreeNode({
  node,
  depth,
  selectedFile,
  generatingFiles,
  expandedFolders,
  onToggleFolder,
  onFileSelect,
}: TreeNodeProps) {
  const indent = 14 + depth * 16;

  if (node.type === 'folder') {
    const isOpen = expandedFolders.has(node.path);
    return (
      <>
        <div
          className="file-tree-row"
          style={{ paddingLeft: indent }}
          onClick={() => onToggleFolder(node.path)}
        >
          <svg
            width="10"
            height="10"
            viewBox="0 0 10 10"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            style={{
              flexShrink: 0,
              color: 'var(--text-muted)',
              transform: isOpen ? 'rotate(90deg)' : 'rotate(0deg)',
              transition: 'transform 150ms',
            }}
          >
            <path d="M3 2l4 3-4 3" />
          </svg>
          <span className="file-tree-folder-name">{node.name}</span>
        </div>
        {isOpen &&
          node.children?.map((child) => (
            <TreeNode
              key={child.path}
              node={child}
              depth={depth + 1}
              selectedFile={selectedFile}
              generatingFiles={generatingFiles}
              expandedFolders={expandedFolders}
              onToggleFolder={onToggleFolder}
              onFileSelect={onFileSelect}
            />
          ))}
      </>
    );
  }

  const isSelected = node.path === selectedFile;
  const isGenerating = generatingFiles.includes(node.path);
  const shortName = node.name.includes('/') ? node.name.slice(node.name.lastIndexOf('/') + 1) : node.name;

  return (
    <div
      className={`file-tree-row file-tree-file${isSelected ? ' file-tree-file--selected' : ''}${isGenerating ? ' file-generating' : ''}`}
      style={{ paddingLeft: indent }}
      onClick={() => onFileSelect(node.path)}
      title={node.path}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: '50%',
          background: extColor(shortName),
          flexShrink: 0,
          display: 'inline-block',
        }}
      />
      <span className="file-tree-file-name">{shortName}</span>
    </div>
  );
}

export function FileExplorer({
  sessionId,
  onFileSelect,
  selectedFile,
  generatingFiles,
  refreshToken,
}: FileExplorerProps) {
  const [files, setFiles] = useState<ProjectFile[]>([]);
  const [isEmpty, setIsEmpty] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set());
  const cancelledRef = useRef(false);

  useEffect(() => {
    if (!sessionId) return;

    cancelledRef.current = false;
    setIsEmpty(false);
    setFetchError(null);

    listProjectFiles(sessionId)
      .then((result) => {
        if (cancelledRef.current) return;
        if (!result || result.length === 0) {
          setFiles([]);
          setIsEmpty(true);
        } else {
          setFiles(result);
          // Auto-expand all folders on first load
          const folders = new Set<string>();
          for (const f of result) {
            if (f.file_path.includes('/')) {
              folders.add(f.file_path.split('/')[0]);
            }
          }
          setExpandedFolders(folders);
          setIsEmpty(false);
        }
      })
      .catch((err: unknown) => {
        if (cancelledRef.current) return;
        setFiles([]);
        setIsEmpty(false);
        const msg = err instanceof Error ? err.message : 'Could not load files';
        setFetchError(msg);
      });

    return () => {
      cancelledRef.current = true;
    };
  }, [sessionId, refreshToken]);

  const handleToggleFolder = (path: string) => {
    setExpandedFolders((prev) => {
      const next = new Set(prev);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return next;
    });
  };

  if (!sessionId) return null;

  const tree = buildTree(files);

  return (
    <div className="file-explorer">
      <div className="file-explorer-header">FILES</div>
      <div className="file-explorer-tree">
        {fetchError ? (
          <div className="file-explorer-empty">{fetchError}</div>
        ) : isEmpty ? (
          <div className="file-explorer-empty">No files yet</div>
        ) : (
          tree.map((node) => (
            <TreeNode
              key={node.path}
              node={node}
              depth={0}
              selectedFile={selectedFile}
              generatingFiles={generatingFiles}
              expandedFolders={expandedFolders}
              onToggleFolder={handleToggleFolder}
              onFileSelect={onFileSelect}
            />
          ))
        )}
      </div>
    </div>
  );
}
