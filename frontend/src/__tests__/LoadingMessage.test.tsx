import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { LoadingMessage } from '../components/LoadingMessage'

describe('LoadingMessage', () => {
  it('renders the "Building…" label', () => {
    render(<LoadingMessage />)
    expect(screen.getByText('Building…')).toBeInTheDocument()
  })

  it('has role="status" for accessibility', () => {
    render(<LoadingMessage />)
    expect(screen.getByRole('status')).toBeInTheDocument()
  })

  it('has aria-live="polite"', () => {
    render(<LoadingMessage />)
    expect(screen.getByRole('status')).toHaveAttribute('aria-live', 'polite')
  })

  it('has a descriptive aria-label', () => {
    render(<LoadingMessage />)
    expect(screen.getByRole('status')).toHaveAttribute('aria-label', 'Building your app')
  })

  it('renders the spinner element with aria-hidden', () => {
    const { container } = render(<LoadingMessage />)
    const spinner = container.querySelector('[aria-hidden="true"]')
    expect(spinner).toBeInTheDocument()
  })
})
