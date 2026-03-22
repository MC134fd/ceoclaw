/**
 * Tests for the useChat hook, focused on the race condition where a history
 * fetch returning empty results could wipe an optimistic user message.
 */
import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// ---------------------------------------------------------------------------
// Module mocks — must be declared before the import under test
// ---------------------------------------------------------------------------

vi.mock('../lib/supabase', () => ({ supabase: null }))

const mockGetSessionHistory = vi.fn()
const mockSendMessage = vi.fn()

vi.mock('../services/api', () => ({
  getSessionHistory: (...args: unknown[]) => mockGetSessionHistory(...args),
  sendMessage: (...args: unknown[]) => mockSendMessage(...args),
  InsufficientCreditsError: class InsufficientCreditsError extends Error {},
}))

// ---------------------------------------------------------------------------
// Import hook after mocks are in place
// ---------------------------------------------------------------------------

import { useChat } from '../hooks/useChat'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Returns a Promise plus manual resolve/reject handles. */
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

const EMPTY_HISTORY = { messages: [], slug: null, landing_url: null, app_url: null }
const SESSION_ID = 'test-session-abc'

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('useChat — optimistic message race', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('preserves the optimistic user message when history resolves empty after send', async () => {
    // History fetch is deferred so we can let send() run first.
    const hist = deferred<typeof EMPTY_HISTORY>()
    mockGetSessionHistory.mockReturnValue(hist.promise)

    mockSendMessage.mockResolvedValue({
      session_id: SESSION_ID,
      assistant_message: 'Done!',
      product_name: 'Test App',
      slug: 'test-app',
      landing_url: '/websites/test-app/index',
      app_url: '/websites/test-app/app',
      model: { provider: 'openai', model_mode: 'openai' },
      version_id: 'v1',
      changes: [],
      files_applied: [],
      files_skipped: [],
      warnings: [],
    })

    const { result } = renderHook(() => useChat(SESSION_ID))

    // sendMessage (legacy path) appends optimistic user message synchronously.
    act(() => {
      void result.current.sendMessage('build me a landing page')
    })

    // User bubble must be visible immediately.
    expect(result.current.messages).toHaveLength(1)
    expect(result.current.messages[0].role).toBe('user')
    expect(result.current.messages[0].content).toBe('build me a landing page')

    // Now the history fetch resolves with an empty array — the bug would
    // wipe the optimistic message here.
    act(() => {
      hist.resolve(EMPTY_HISTORY)
    })

    // Give React time to process the state update from the history fetch.
    await waitFor(() => {
      expect(mockGetSessionHistory).toHaveBeenCalledWith(SESSION_ID)
    })

    // The optimistic user message must still be in the list.
    expect(result.current.messages.some((m) => m.content === 'build me a landing page')).toBe(true)
  })

  it('replaces messages with real server history when non-empty', async () => {
    const serverMessages = [
      { id: 1, session_id: SESSION_ID, role: 'user', content: 'old prompt', created_at: '2024-01-01T00:00:00Z' },
      { id: 2, session_id: SESSION_ID, role: 'assistant', content: 'old reply', created_at: '2024-01-01T00:01:00Z' },
    ]
    mockGetSessionHistory.mockResolvedValue({ messages: serverMessages, slug: 'old-app', landing_url: null, app_url: null })

    const { result } = renderHook(() => useChat(SESSION_ID))

    await waitFor(() => {
      expect(result.current.messages).toHaveLength(2)
    })

    expect(result.current.messages[0].content).toBe('old prompt')
    expect(result.current.messages[1].content).toBe('old reply')
  })

  it('leaves messages empty when history is empty and no sends have occurred', async () => {
    mockGetSessionHistory.mockResolvedValue(EMPTY_HISTORY)

    const { result } = renderHook(() => useChat(SESSION_ID))

    await waitFor(() => {
      expect(mockGetSessionHistory).toHaveBeenCalledWith(SESSION_ID)
    })

    expect(result.current.messages).toHaveLength(0)
  })
})
