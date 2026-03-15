import { useCallback, useRef } from 'react';

interface Props {
  onSubmit: (text: string) => void;
  disabled?: boolean;
  placeholder?: string;
  /** When true, show an out-of-credits blocker banner instead of normal input. */
  outOfCredits?: boolean;
}

export function Composer({
  onSubmit,
  disabled = false,
  placeholder = 'Describe your product or request a change…',
  outOfCredits = false,
}: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const autoResize = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 220) + 'px';
  }, []);

  const handleSubmit = useCallback(() => {
    const el = textareaRef.current;
    if (!el || disabled) return;
    const text = el.value.trim();
    if (!text) return;
    onSubmit(text);
    el.value = '';
    el.style.height = '';
  }, [onSubmit, disabled]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSubmit();
      }
      // Shift+Enter: default behavior (newline)
    },
    [handleSubmit],
  );

  if (outOfCredits) {
    return (
      <div className="composer-wrapper">
        <div className="composer-credits-blocker">
          <span>⚡</span>
          <span>You&apos;ve used all your credits. Upgrade your plan to keep building.</span>
        </div>
      </div>
    );
  }

  return (
    <div className="composer-wrapper">
      <div className="composer-box">
        <textarea
          ref={textareaRef}
          onInput={autoResize}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          placeholder={placeholder}
          rows={3}
          autoComplete="off"
          spellCheck
          className="composer-textarea"
        />
        <div className="composer-footer">
          <span className="composer-hint">Enter to send · Shift+Enter for newline</span>
          <button
            onClick={handleSubmit}
            disabled={disabled}
            title="Send (Enter)"
            className="composer-send-btn"
            aria-label="Send message"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <path
                d="M7 12V2M7 2L2.5 6.5M7 2L11.5 6.5"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}
