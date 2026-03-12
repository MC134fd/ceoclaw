import { useState } from 'react';
import type { FileChange, OperationInfo } from '../types';

interface Props {
  changes: FileChange[];
  operation?: OperationInfo;
}

const COLLAPSE_THRESHOLD = 3;

function getIcon(status: FileChange['status']): string {
  if (status === 'applied') return '✓';
  if (status === 'rejected') return '✗';
  return '–';
}

function getColor(status: FileChange['status']): string {
  if (status === 'applied') return 'var(--success)';
  if (status === 'rejected') return 'var(--error)';
  return 'var(--text-muted)';
}

function getActionLabel(action: FileChange['action']): string {
  if (action === 'create') return 'created';
  if (action === 'delete') return 'deleted';
  return 'updated';
}

function filename(path: string): string {
  return path.split('/').pop() ?? path;
}

const OPERATION_LABELS: Record<string, string> = {
  add_page: 'Add Page',
  add_component: 'Add Component',
  add_endpoint: 'Add Endpoint',
  add_feature: 'Add Feature',
  add_legal_page: 'Legal Page',
  modify_style: 'Style Change',
  general_edit: 'Edit',
};

export function ChangedFilesSummary({ changes, operation }: Props) {
  const [expanded, setExpanded] = useState(changes.length <= COLLAPSE_THRESHOLD);

  if (!changes.length) return null;

  const visible = expanded ? changes : changes.slice(0, COLLAPSE_THRESHOLD);
  const hidden = changes.length - COLLAPSE_THRESHOLD;

  return (
    <div
      style={{
        marginTop: 8,
        padding: '8px 10px',
        background: 'var(--surface-2)',
        borderRadius: 8,
        border: '1px solid var(--border)',
        fontSize: 12,
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          marginBottom: 4,
        }}
      >
        <span
          style={{
            fontWeight: 600,
            color: 'var(--text-muted)',
            fontSize: 11,
            textTransform: 'uppercase',
            letterSpacing: '0.04em',
          }}
        >
          Files changed
        </span>
        {operation && operation.type && operation.type !== 'general_edit' && (
          <span
            style={{
              fontSize: 10,
              fontWeight: 600,
              padding: '1px 7px',
              borderRadius: 4,
              background: 'rgba(99,102,241,0.15)',
              color: '#a5b4fc',
              letterSpacing: '0.02em',
            }}
            data-testid="operation-badge"
          >
            {OPERATION_LABELS[operation.type] ?? operation.type}
            {operation.target ? `: ${operation.target}` : ''}
          </span>
        )}
      </div>
      {visible.map((change, i) => (
        <div
          key={i}
          title={change.error || change.summary}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            padding: '2px 0',
            color: 'var(--text)',
          }}
        >
          <span
            style={{
              color: getColor(change.status),
              fontWeight: 700,
              width: 14,
              flexShrink: 0,
              textAlign: 'center',
            }}
          >
            {getIcon(change.status)}
          </span>
          <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>
            {getActionLabel(change.action)}
          </span>
          <code
            style={{
              fontFamily: 'monospace',
              fontSize: 11,
              color: 'var(--text)',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              maxWidth: 200,
            }}
          >
            {filename(change.path)}
          </code>
        </div>
      ))}
      {!expanded && hidden > 0 && (
        <button
          onClick={() => setExpanded(true)}
          style={{
            marginTop: 4,
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            color: 'var(--accent)',
            fontSize: 11,
            padding: 0,
          }}
        >
          + {hidden} more file{hidden !== 1 ? 's' : ''}
        </button>
      )}
      {expanded && changes.length > COLLAPSE_THRESHOLD && (
        <button
          onClick={() => setExpanded(false)}
          style={{
            marginTop: 4,
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            color: 'var(--text-muted)',
            fontSize: 11,
            padding: 0,
          }}
        >
          Show less
        </button>
      )}
    </div>
  );
}
