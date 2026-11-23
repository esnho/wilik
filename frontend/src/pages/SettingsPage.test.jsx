import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import SettingsPage from './SettingsPage'
import { createFetchMock, renderWithProviders } from '../test/helpers'

const currentUser = {
  id: 1,
  username: 'els',
  currency: 'EUR',
  decimal_separator: ',',
  theme_color: null,
  show_in_directory: true,
  guest_sort_by_price_enabled: false,
  guest_filter_by_label_enabled: false,
  guest_filter_by_brand_enabled: false,
  claim_management_enabled: false,
  lock_icon_claimed_only: false,
}

const lists = [
  { id: 1, name: 'Natale', code: 'abc123', share_token: 'share-1', gift_count: 1 },
  { id: 2, name: 'Compleanno', code: 'def456', share_token: 'share-2', gift_count: 0 },
]

function renderPage() {
  const fetchMock = createFetchMock([
    { match: (url) => url === '/api/lists', body: lists },
    {
      match: (url, init) => url === '/api/lists/2/share-token' && init?.method === 'POST',
      body: { ...lists[1], share_token: 'share-2-new' },
    },
    { match: (url) => url === '/api/settings', body: { claim_management_site_enabled: false } },
    {
      match: (url, init) => url === '/api/account' && init?.method === 'PUT',
      body: currentUser,
    },
  ])
  vi.stubGlobal('fetch', fetchMock)
  renderWithProviders(<SettingsPage currentUser={currentUser} onUpdate={() => {}} />)
  return fetchMock
}

describe('SettingsPage share section', () => {
  it('shows the share link of the selected list and can regenerate it per list', async () => {
    const fetchMock = renderPage()
    const user = userEvent.setup()
    vi.stubGlobal('confirm', vi.fn(() => true))

    // the share section has its own list selector, defaulting to the first list
    const selector = await screen.findByLabelText('List to share')
    expect(selector).toHaveValue('1')

    const linkInput = screen.getByRole('textbox', { name: 'Share link' })
    expect(linkInput).toHaveValue(`${window.location.origin}/list/share-1`)

    // switching lists swaps the link without reloading
    await user.selectOptions(selector, '2')
    expect(screen.getByRole('textbox', { name: 'Share link' })).toHaveValue(
      `${window.location.origin}/list/share-2`,
    )

    // regenerating only touches the selected list
    await user.click(screen.getByRole('button', { name: 'Generate new link' }))
    await waitFor(() => {
      expect(fetchMock.callsTo('/api/lists/2/share-token')).toHaveLength(1)
    })
    await waitFor(() => {
      expect(screen.getByRole('textbox', { name: 'Share link' })).toHaveValue(
        `${window.location.origin}/list/share-2-new`,
      )
    })
  })

  it('no longer shows the List name field in the General form', async () => {
    renderPage()

    await screen.findByLabelText('Currency')
    expect(screen.queryByLabelText('List name')).not.toBeInTheDocument()
  })

  it('saves General settings without sending list_name', async () => {
    const fetchMock = renderPage()
    const user = userEvent.setup()

    // the General section is the first form on the page
    await user.click(screen.getAllByRole('button', { name: 'Save' })[0])
    await waitFor(() => {
      expect(fetchMock.callsTo('/api/account')).toHaveLength(1)
    })
    const put = fetchMock.lastCallTo('/api/account')
    const payload = JSON.parse(put.init.body)
    expect(payload.list_name).toBeUndefined()
    expect(payload.currency).toBe('EUR')
  })
})

describe('SettingsPage guest settings', () => {
  it('saves the default visitor order together with the other guest settings', async () => {
    const fetchMock = renderPage()
    const user = userEvent.setup()

    const orderSelect = await screen.findByLabelText('Default order for visitors')
    await user.selectOptions(orderSelect, 'price')

    // the guest form is the third section: General, Appearance, Guest...
    await user.click(screen.getAllByRole('button', { name: 'Save' })[2])
    await waitFor(() => {
      expect(fetchMock.callsTo('/api/account')).toHaveLength(1)
    })
    const put = fetchMock.lastCallTo('/api/account')
    const payload = JSON.parse(put.init.body)
    expect(payload.guest_default_sort).toBe('price')
  })
})
