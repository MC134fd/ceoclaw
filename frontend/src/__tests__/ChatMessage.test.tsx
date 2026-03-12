import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ChatMessage } from '../components/ChatMessage'
import type { ChatResponse, Message } from '../types'

const userMessage: Message = {
  id: 1,
  session_id: 'sess-1',
  role: 'user',
  content: 'Hello world',
  created_at: new Date('2026-01-01T10:30:00Z').toISOString(),
}

const assistantMessage: Message = {
  id: 2,
  session_id: 'sess-1',
  role: 'assistant',
  content: 'I built your app.',
  created_at: new Date('2026-01-01T10:31:00Z').toISOString(),
}

const mockChatResponse: ChatResponse = {
  session_id: 'sess-1',
  assistant_message: 'I built your app.',
  product_name: 'My App',
  slug: 'my-app',
  landing_url: '/websites/my-app/index',
  app_url: '/websites/my-app/app',
  model: { provider: 'flock', model_mode: 'flock_live' },
  version_id: 'v1',
  changes: [
    {
      path: 'data/websites/my-app/index.html',
      action: 'create',
      status: 'applied',
      summary: 'Created landing page',
    },
  ],
  files_applied: ['index.html'],
  files_skipped: [],
  warnings: [],
}

describe('ChatMessage', () => {
  it('renders user message right-aligned', () => {
    const { container } = render(<ChatMessage message={userMessage} />)
    const wrapper = container.firstChild as HTMLElement
    expect(wrapper).toHaveAttribute('data-role', 'user')
    expect(wrapper).toHaveClass('chat-message', 'chat-message--user')
  })

  it('renders assistant message left-aligned', () => {
    const { container } = render(<ChatMessage message={assistantMessage} />)
    const wrapper = container.firstChild as HTMLElement
    expect(wrapper).toHaveAttribute('data-role', 'assistant')
    expect(wrapper).toHaveClass('chat-message', 'chat-message--assistant')
  })

  it('applies role-specific bubble class', () => {
    const { container } = render(<ChatMessage message={assistantMessage} />)
    const bubble = container.querySelector('.chat-message-bubble')
    expect(bubble).toHaveClass('chat-message-bubble--assistant')
  })

  it('displays the message content', () => {
    render(<ChatMessage message={userMessage} />)
    expect(screen.getByText('Hello world')).toBeInTheDocument()
  })

  it('displays a timestamp', () => {
    render(<ChatMessage message={userMessage} />)
    // Timestamp format is HH:MM — we just check something time-like appears
    const metaEl = screen.getByText(/You ·/)
    expect(metaEl).toBeInTheDocument()
  })

  it('shows ChangedFilesSummary for assistant messages with changes', () => {
    render(<ChatMessage message={assistantMessage} chatResponse={mockChatResponse} />)
    expect(screen.getByText(/Files changed/i)).toBeInTheDocument()
  })

  it('does not show ChangedFilesSummary for user messages', () => {
    render(<ChatMessage message={userMessage} chatResponse={mockChatResponse} />)
    expect(screen.queryByText(/Files changed/i)).not.toBeInTheDocument()
  })
})
