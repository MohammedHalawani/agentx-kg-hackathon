import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { LanguageProvider } from '@/components/i18n/LanguageProvider'
import { ThemeProvider } from '@/components/theme/ThemeProvider'
import { SidebarProvider } from '@/components/ui/sidebar'
import { AppHeader } from './AppHeader'

function shell(view: 'intake' | 'audit' = 'intake', scopeLoading = false) {
  return render(
    <ThemeProvider>
      <LanguageProvider>
        <SidebarProvider>
          <AppHeader view={view} scope="demo" scopeLoading={scopeLoading} />
        </SidebarProvider>
      </LanguageProvider>
    </ThemeProvider>,
  )
}

describe('AppHeader', () => {
  it('shows the active view in the breadcrumb trail', () => {
    shell('audit')
    expect(screen.getByRole('navigation', { name: 'breadcrumb' })).toBeTruthy()
    expect(screen.getByText('Audit')).toBeTruthy()
  })

  it('skeletons scope context only while meta is loading', () => {
    shell('intake', true)
    expect(document.querySelector('[data-slot="skeleton"]')).toBeTruthy()
  })
})
