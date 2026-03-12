import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { PreviewPane } from '../components/PreviewPane'

describe('PreviewPane', () => {
  it('shows placeholder when no slug is provided', () => {
    render(<PreviewPane slug={null} landingUrl={null} appUrl={null} />)
    expect(screen.getByTestId('preview-placeholder')).toBeInTheDocument()
    expect(screen.queryByTestId('preview-iframe')).not.toBeInTheDocument()
  })

  it('defaults to Landing tab', () => {
    render(<PreviewPane slug={null} landingUrl={null} appUrl={null} />)
    const tabs = screen.getAllByRole('button')
    const landingTab = tabs.find((t) => t.textContent === 'Landing')
    expect(landingTab).toBeDefined()
    expect(landingTab).toHaveClass('preview-tab-active')
  })

  it('shows iframe when slug is provided', () => {
    render(
      <PreviewPane
        slug="my-app"
        landingUrl="/websites/my-app/index"
        appUrl="/websites/my-app/app"
      />,
    )
    expect(screen.getByTestId('preview-iframe')).toBeInTheDocument()
    expect(screen.queryByTestId('preview-placeholder')).not.toBeInTheDocument()
  })

  it('iframe src points to landing URL by default', () => {
    render(
      <PreviewPane
        slug="my-app"
        landingUrl="/websites/my-app/index"
        appUrl="/websites/my-app/app"
      />,
    )
    const iframe = screen.getByTestId('preview-iframe') as HTMLIFrameElement
    expect(iframe.src).toContain('/websites/my-app/index')
  })

  it('switching to App tab updates iframe src', async () => {
    const user = userEvent.setup()
    render(
      <PreviewPane
        slug="my-app"
        landingUrl="/websites/my-app/index"
        appUrl="/websites/my-app/app"
      />,
    )
    const appTab = screen.getByRole('button', { name: 'App' })
    await user.click(appTab)
    const iframe = screen.getByTestId('preview-iframe') as HTMLIFrameElement
    expect(iframe.src).toContain('/websites/my-app/app')
    expect(appTab).toHaveClass('preview-tab-active')
  })

  it('"Open in new tab" link has correct href', () => {
    render(
      <PreviewPane
        slug="my-app"
        landingUrl="/websites/my-app/index"
        appUrl="/websites/my-app/app"
      />,
    )
    const link = screen.getByTestId('open-new-tab') as HTMLAnchorElement
    expect(link.href).toContain('/websites/my-app/index')
    expect(link.target).toBe('_blank')
  })
})
