import type { CSSProperties } from 'react';

const spinnerStyle: CSSProperties = {
  width: 16,
  height: 16,
  borderRadius: '50%',
  border: '2px solid var(--border)',
  borderTopColor: 'var(--accent)',
  flexShrink: 0,
  animation: 'spinnerRotate 0.75s linear infinite',
};

const wrapperStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  padding: '10px 14px',
  background: 'var(--surface-2)',
  border: '1px solid var(--border)',
  borderRadius: 14,
  borderBottomLeftRadius: 4,
  width: 'fit-content',
  alignSelf: 'flex-start',
  animation: 'msgIn 0.15s ease-out',
};

const labelStyle: CSSProperties = {
  fontSize: 13,
  color: 'var(--text-muted)',
  fontWeight: 500,
  letterSpacing: '0.01em',
};

export function LoadingMessage() {
  return (
    <div role="status" aria-live="polite" aria-label="Building your app" style={wrapperStyle}>
      <span style={spinnerStyle} aria-hidden="true" />
      <span style={labelStyle}>Building…</span>
    </div>
  );
}
