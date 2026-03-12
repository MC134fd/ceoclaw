import type { PipelineStage } from '../types';

interface Props {
  stages: PipelineStage[];
}

function StatusIcon({ status }: { status: PipelineStage['status'] }) {
  if (status === 'pending') {
    return <span className="build-log-icon build-log-icon--pending">○</span>;
  }
  if (status === 'running') {
    return <span className="build-log-icon build-log-icon--running build-log-spinner" />;
  }
  if (status === 'done') {
    return <span className="build-log-icon build-log-icon--done">✓</span>;
  }
  // error
  return <span className="build-log-icon build-log-icon--error">✗</span>;
}

export function BuildLog({ stages }: Props) {
  const hasStarted = stages.some((s) => s.status !== 'pending');

  return (
    <div className="build-log" role="log" aria-label="Build progress" aria-live="polite">
      <div className="build-log-header">Building your product...</div>
      {stages.map((stage) => {
        const isVisible = hasStarted || stage.status !== 'pending';
        return (
          <div
            key={stage.stage_key}
            className={`build-log-row build-log-row--${stage.status}${isVisible ? ' build-log-row--visible' : ''}`}
          >
            <StatusIcon status={stage.status} />
            <span className="build-log-label">{stage.stage_label}</span>
            {stage.status === 'running' && (
              <span className="build-log-pulse" />
            )}
            {stage.status === 'done' && stage.artifact_name && (
              <span className="build-log-artifact">{stage.artifact_name}</span>
            )}
            {stage.status === 'done' && stage.duration_ms !== undefined && (
              <span className="build-log-duration">{stage.duration_ms}ms</span>
            )}
            {stage.status === 'error' && stage.error && (
              <span className="build-log-error-text">{stage.error}</span>
            )}
          </div>
        );
      })}
    </div>
  );
}
