import type { PipelineStage } from '../types';

interface Props {
  stages: PipelineStage[];
}

export function BuildLog({ stages }: Props) {
  const visible = stages.filter((s) => s.status === 'done' || s.status === 'running' || s.status === 'error');
  const isComplete = stages.find((s) => s.stage_key === 'complete')?.status === 'done';

  if (visible.length === 0) return null;

  return (
    <div className="build-progress" role="log" aria-label="Build progress" aria-live="polite">
      {visible
        .filter((s) => s.stage_key !== 'complete')
        .map((stage) => (
          <div
            key={stage.stage_key}
            className={`build-step build-step--${stage.status}`}
          >
            {stage.status === 'running' && <span className="build-step-dot" />}
            {stage.status === 'done' && <span className="build-step-check">✓</span>}
            {stage.status === 'error' && <span className="build-step-x">✗</span>}
            <span className="build-step-text">{stage.stage_label}</span>
            {stage.status === 'done' && stage.artifact_name && (
              <span className="build-step-artifact">{stage.artifact_name}</span>
            )}
          </div>
        ))}
      {isComplete && (
        <div className="build-step build-step--complete">
          <span className="build-step-check">✓</span>
          <span className="build-step-text">Done</span>
        </div>
      )}
    </div>
  );
}
