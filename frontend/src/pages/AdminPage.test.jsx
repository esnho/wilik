import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AdminPage from './AdminPage'
import { createFetchMock, renderWithProviders } from '../test/helpers'

const users = [
  {
    id: 1,
    username: 'els',
    is_admin: true,
    currency: 'EUR',
    decimal_separator: ',',
    theme_color: null,
    show_in_directory: true,
    show_image_placeholder: true,
    show_background_pattern: true,
    guest_sort_by_price_enabled: false,
    guest_filter_by_label_enabled: false,
    guest_filter_by_brand_enabled: false,
    claim_management_enabled: false,
    lock_icon_claimed_only: false,
  },
]

function renderPage() {
  const fetchMock = createFetchMock([
    { match: (url) => url === '/api/users', body: users },
    { match: (url) => url === '/api/version', body: { version: 'test' } },
    { match: (url) => url === '/api/settings', body: {} },
    {
      match: (url, init) => url === '/api/users/1' && init?.method === 'PUT',
      body: users[0],
    },
  ])
  vi.stubGlobal('fetch', fetchMock)
  renderWithProviders(<AdminPage currentUser={{ ...users[0], username: 'admin' }} onUpdate={() => {}} />)
  return fetchMock
}

describe('AdminPage edit user', () => {
  it('no longer shows the List name field in the edit form', async () => {
    renderPage()
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'Edit user' }))
    await screen.findByLabelText('Currency')
    expect(screen.queryByLabelText('List name')).not.toBeInTheDocument()
  })

  it('saves General settings without sending list_name', async () => {
    const fetchMock = renderPage()
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'Edit user' }))
    const currencySelect = await screen.findByLabelText('Currency')
    // the General Save is the one inside the same form as the Currency field
    await user.click(currencySelect.closest('form').querySelector('button[type="submit"]'))

    await waitFor(() => {
      expect(fetchMock.callsTo('/api/users/1')).toHaveLength(1)
    })
    const put = fetchMock.lastCallTo('/api/users/1')
    const payload = JSON.parse(put.init.body)
    expect(payload.list_name).toBeUndefined()
    expect(payload.currency).toBe('EUR')
  })
})
