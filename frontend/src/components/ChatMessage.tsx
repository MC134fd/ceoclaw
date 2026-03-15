import type { ChatResponse, FileChange, Message, ModelInfo } from '../types';
import { ChangedFilesSummary } from './ChangedFilesSummary';
import { ModelStatusBadge } from './ModelStatusBadge';

interface Props {
  message: Message;
  // Optional: only provided for the last assistant message
  chatResponse?: ChatResponse | null;
  /** True while the typewriter animation is running for this message */
  isTyping?: boolean;
}

function formatTime(isoString: string): string {
  try {
    return new Date(isoString).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '';
  }
}

/** Minimal inline markdown: **bold** and `code` */
function formatContent(text: string): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  // Split on **bold** and `code`
  const regex = /(\*\*(.+?)\*\*|`([^`]+)`)/g;
  let last = 0;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > last) {
      // plain text segment — handle newlines
      const segment = text.slice(last, match.index);
      pushText(parts, segment, last);
    }
    if (match[0].startsWith('**')) {
      parts.push(<strong key={match.index}>{match[2]}</strong>);
    } else {
      parts.push(
        <code
          key={match.index}
          style={{
            fontFamily: 'monospace',
            fontSize: '0.9em',
            background: 'rgba(0,0,0,0.07)',
            borderRadius: 4,
            padding: '1px 5px',
          }}
        >
          {match[3]}
        </code>,
      );
    }
    last = match.index + match[0].length;
  }

  if (last < text.length) {
    pushText(parts, text.slice(last), last + 10000);
  }

  return parts;
}

function pushText(parts: React.ReactNode[], text: string, keyBase: number): void {
  const lines = text.split('\n');
  lines.forEach((line, i) => {
    if (i > 0) parts.push(<br key={`br-${keyBase}-${i}`} />);
    if (line) parts.push(line);
  });
}

export function ChatMessage({ message, chatResponse, isTyping = false }: Props) {
  const isUser = message.role === 'user';
  const isAssistant = message.role === 'assistant';

  // Only show changes / model badge for assistant messages that have a chatResponse
  const changes: FileChange[] = isAssistant && chatResponse ? chatResponse.changes : [];
  const modelInfo: ModelInfo | null = isAssistant && chatResponse ? chatResponse.model : null;
  const operation = isAssistant && chatResponse ? chatResponse.operation : undefined;

  return (
    <div className={`chat-message chat-message--${message.role}`} data-role={message.role}>
      <div className={`chat-message-bubble chat-message-bubble--${message.role}`}>
        {formatContent(message.content)}
        {isTyping && isAssistant && <span className="typing-cursor" aria-hidden="true" />}
        {changes.length > 0 && (
          <ChangedFilesSummary changes={changes} operation={operation} />
        )}
        {modelInfo && (
          <div style={{ marginTop: 8 }}>
            <ModelStatusBadge model={modelInfo} />
          </div>
        )}
      </div>
      <div className="chat-message-meta">
        {isUser ? 'You' : 'CEOClaw'} · {formatTime(message.created_at)}
      </div>
    </div>
  );
}
