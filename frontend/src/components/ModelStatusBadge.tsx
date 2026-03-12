import type { ModelInfo } from '../types';

interface Props {
  model: ModelInfo | null;
}

interface BadgeConfig {
  label: string;
  color: string;
  bg: string;
  dot: string;
}

function getBadgeConfig(model: ModelInfo | null): BadgeConfig {
  if (!model) {
    return { label: 'Checking...', color: 'var(--text-muted)', bg: 'var(--surface-2)', dot: 'var(--text-muted)' };
  }

  const { model_mode, provider } = model;

  if (model_mode === 'flock_live') {
    return { label: 'Live (Flock)', color: 'var(--success)', bg: 'rgba(34,197,94,0.12)', dot: 'var(--success)' };
  }
  if (model_mode === 'openai' || provider === 'openai') {
    return { label: 'Live (OpenAI)', color: '#3b82f6', bg: 'rgba(59,130,246,0.12)', dot: '#3b82f6' };
  }
  if (model_mode === 'fallback_mock') {
    return { label: 'Fallback Mock', color: 'var(--warning)', bg: 'rgba(245,158,11,0.12)', dot: 'var(--warning)' };
  }
  if (model_mode === 'mock' || provider === 'mock') {
    return { label: 'Mock', color: 'var(--text-muted)', bg: 'var(--surface-2)', dot: 'var(--text-muted)' };
  }
  // error / unknown
  return { label: 'Error', color: 'var(--error)', bg: 'rgba(239,68,68,0.12)', dot: 'var(--error)' };
}

export function ModelStatusBadge({ model }: Props) {
  const cfg = getBadgeConfig(model);
  const showFallback = model?.fallback_used && model.fallback_reason;
  const title = showFallback ? `Fallback reason: ${model!.fallback_reason}` : undefined;

  return (
    <span
      title={title}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '6px',
        padding: '3px 10px',
        borderRadius: '20px',
        background: cfg.bg,
        color: cfg.color,
        fontSize: '12px',
        fontWeight: 500,
        cursor: title ? 'help' : 'default',
        userSelect: 'none',
      }}
    >
      <span
        style={{
          width: 7,
          height: 7,
          borderRadius: '50%',
          background: cfg.dot,
          flexShrink: 0,
          display: 'inline-block',
        }}
      />
      {cfg.label}
      {showFallback && (
        <span style={{ fontSize: 10, opacity: 0.8 }}>↩</span>
      )}
    </span>
  );
}
