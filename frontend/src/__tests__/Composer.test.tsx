import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Composer } from '../components/Composer'

describe('Composer', () => {
  it('shows the Enter to send hint text', () => {
    render(<Composer onSubmit={vi.fn()} />)
    expect(screen.getByText(/Enter to send/i)).toBeInTheDocument()
  })

  it('calls onSubmit when Enter is pressed', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    render(<Composer onSubmit={onSubmit} />)
    const textarea = screen.getByRole('textbox')
    await user.click(textarea)
    await user.type(textarea, 'hello')
    await user.keyboard('{Enter}')
    expect(onSubmit).toHaveBeenCalledWith('hello')
  })

  it('does NOT call onSubmit when Shift+Enter is pressed', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    render(<Composer onSubmit={onSubmit} />)
    const textarea = screen.getByRole('textbox')
    await user.click(textarea)
    await user.type(textarea, 'line one')
    await user.keyboard('{Shift>}{Enter}{/Shift}')
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('calls onSubmit when the submit button is clicked', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    render(<Composer onSubmit={onSubmit} />)
    const textarea = screen.getByRole('textbox')
    await user.click(textarea)
    await user.type(textarea, 'test message')
    const button = screen.getByRole('button')
    await user.click(button)
    expect(onSubmit).toHaveBeenCalledWith('test message')
  })

  it('does not call onSubmit when disabled', () => {
    const onSubmit = vi.fn()
    render(<Composer onSubmit={onSubmit} disabled />)
    const textarea = screen.getByRole('textbox')
    // Textarea is disabled, typing won't work
    expect(textarea).toBeDisabled()
    const button = screen.getByRole('button')
    expect(button).toBeDisabled()
  })
})
