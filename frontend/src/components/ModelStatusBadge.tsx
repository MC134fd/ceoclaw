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
    return { label: 'Live (OpenAI)', color: '#4FA3A5', bg: 'rgba(79,163,165,0.10)', dot: '#4FA3A5' };
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
        padding: '3px 9px',
        borderRadius: '4px',
        background: cfg.bg,
        color: cfg.color,
        fontSize: '11.5px',
        fontWeight: 500,
        letterSpacing: '0.01em',
        cursor: title ? 'help' : 'default',
        userSelect: 'none',
        border: '1px solid rgba(0,0,0,0.05)',
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
