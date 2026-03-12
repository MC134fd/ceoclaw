import { useCallback, useRef } from 'react';

interface Props {
  onSubmit: (text: string) => void;
  disabled?: boolean;
  placeholder?: string;
}

export function Composer({ onSubmit, disabled = false, placeholder = 'Describe your product or request a change…' }: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const autoResize = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 240) + 'px';
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

  return (
    <div
      style={{
        padding: '10px 14px 14px',
        borderTop: '1px solid var(--border)',
        flexShrink: 0,
      }}
    >
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          background: 'var(--surface-2)',
          border: '1px solid var(--border)',
          borderRadius: 14,
          overflow: 'hidden',
          transition: 'border-color 0.15s, box-shadow 0.15s',
        }}
        onFocusCapture={(e) => {
          (e.currentTarget as HTMLDivElement).style.borderColor = 'var(--accent)';
          (e.currentTarget as HTMLDivElement).style.boxShadow =
            '0 0 0 3px rgba(99,102,241,0.18)';
        }}
        onBlurCapture={(e) => {
          (e.currentTarget as HTMLDivElement).style.borderColor = 'var(--border)';
          (e.currentTarget as HTMLDivElement).style.boxShadow = 'none';
        }}
      >
        <textarea
          ref={textareaRef}
          onInput={autoResize}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          placeholder={placeholder}
          rows={3}
          autoComplete="off"
          spellCheck
          style={{
            width: '100%',
            minHeight: 80,
            maxHeight: 240,
            padding: '12px 14px 6px',
            border: 'none',
            outline: 'none',
            resize: 'none',
            fontFamily: 'var(--font)',
            fontSize: 14,
            lineHeight: 1.55,
            color: 'var(--text)',
            background: 'transparent',
            opacity: disabled ? 0.5 : 1,
          }}
        />
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '6px 10px 8px',
          }}
        >
          <span
            style={{
              fontSize: 11,
              color: 'var(--text-muted)',
            }}
          >
            Enter to send · Shift+Enter for newline
          </span>
          <button
            onClick={handleSubmit}
            disabled={disabled}
            title="Send (Enter)"
            style={{
              width: 32,
              height: 32,
              borderRadius: '50%',
              border: 'none',
              background: disabled ? 'var(--border)' : 'var(--accent)',
              color: '#fff',
              cursor: disabled ? 'not-allowed' : 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
              transition: 'background 0.15s',
            }}
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
