import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ModelStatusBadge } from '../components/ModelStatusBadge'
import type { ModelInfo } from '../types'

describe('ModelStatusBadge', () => {
  it('renders "Live (Flock)" for flock_live mode', () => {
    const model: ModelInfo = { provider: 'flock', model_mode: 'flock_live' }
    render(<ModelStatusBadge model={model} />)
    expect(screen.getByText('Live (Flock)')).toBeInTheDocument()
  })

  it('renders "Live (OpenAI)" for openai mode', () => {
    const model: ModelInfo = { provider: 'openai', model_mode: 'openai' }
    render(<ModelStatusBadge model={model} />)
    expect(screen.getByText('Live (OpenAI)')).toBeInTheDocument()
  })

  it('shows fallback indicator when fallback_used is true', () => {
    const model: ModelInfo = {
      provider: 'openai',
      model_mode: 'openai',
      fallback_used: true,
      fallback_reason: 'flock_error: timeout',
    }
    render(<ModelStatusBadge model={model} />)
    // The fallback indicator (↩) should be visible
    expect(screen.getByText('↩')).toBeInTheDocument()
    // The badge should have a title with the reason
    const badge = screen.getByTitle(/Fallback reason:/i)
    expect(badge).toBeInTheDocument()
    expect(badge.title).toContain('flock_error: timeout')
  })

  it('renders "Error" for unknown mode', () => {
    const model: ModelInfo = { provider: 'flock', model_mode: 'fallback' }
    render(<ModelStatusBadge model={model} />)
    expect(screen.getByText('Error')).toBeInTheDocument()
  })

  it('renders checking state when model is null', () => {
    render(<ModelStatusBadge model={null} />)
    expect(screen.getByText('Checking...')).toBeInTheDocument()
  })
})
