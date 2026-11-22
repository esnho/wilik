import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import WishlistPage from './WishlistPage'
import { createFetchMock, renderWithProviders } from '../test/helpers'

const currentUser = {
  id: 1,
  username: 'els',
  currency: 'EUR',
  decimal_separator: ',',
  claim_management_enabled: false,
  lock_icon_claimed_only: false,
  show_image_placeholder: true,
  show_background_pattern: true,
}

const lists = [
  { id: 1, name: 'Natale', code: 'abc123', share_token: 'share-1', gift_count: 1 },
  { id: 2, name: 'Compleanno', code: 'def456', share_token: 'share-2', gift_count: 0 },
]

function renderPage({
  items = [],
  lists: theLists = lists,
  route = '/',
  deleteResponse = { status: 204, body: '' },
} = {}) {
  const fetchMock = createFetchMock([
    {
      match: (url, init) => url === '/api/lists' && (init?.method ?? 'GET') === 'GET',
      body: theLists,
    },
    {
      match: (url, init) => url === '/api/lists' && init?.method === 'POST',
      status: 201,
      body: { id: 3, name: 'Viaggio', code: 'ghi789', share_token: 'share-3', gift_count: 0 },
    },
    {
      match: (url, init) => url === '/api/lists/1' && init?.method === 'PUT',
      body: { id: 1, name: 'Natale 2026', code: 'abc123', share_token: 'share-1', gift_count: 1 },
    },
    {
      match: (url, init) => url === '/api/lists/1' && init?.method === 'DELETE',
      ...deleteResponse,
    },
    {
      match: (url, init) => url === '/api/items' && init?.method === 'POST',
      status: 201,
      body: { id: 99, title: 'Scarf', received: false, rating: null, quantity: 1, list_id: 1 },
    },
    {
      match: (url) => url.startsWith('/api/items'),
      body: items,
    },
    {
      match: (url) => url === '/api/settings',
      body: { claim_management_site_enabled: false, claim_delete_warning_skipped: false },
    },
  ])
  vi.stubGlobal('fetch', fetchMock)
  renderWithProviders(<WishlistPage currentUser={currentUser} />, { route })
  return fetchMock
}

describe('WishlistPage toolbar', () => {
  it('shows the lists in the toolbar selector and loads the gifts of the first list', async () => {
    const fetchMock = renderPage({
      items: [{ id: 11, title: 'Scarf', received: false, rating: null, quantity: 1 }],
    })

    const selector = await screen.findByRole('combobox')
    expect(selector).toHaveValue('1')
    expect(screen.getByRole('option', { name: 'Natale' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Compleanno' })).toBeInTheDocument()

    await waitFor(() => {
      expect(fetchMock.callsTo('/api/items?list_id=1')).toHaveLength(1)
    })
    expect(await screen.findByText('Scarf')).toBeInTheDocument()
  })

  it('selects the list named by the /?list=<code> URL parameter', async () => {
    const fetchMock = renderPage({
      items: [{ id: 22, title: 'Book', received: false, rating: null, quantity: 1 }],
      route: '/?list=def456',
    })

    const selector = await screen.findByRole('combobox')
    expect(selector).toHaveValue('2')
    await waitFor(() => {
      expect(fetchMock.callsTo('/api/items?list_id=2')).toHaveLength(1)
    })
    expect(await screen.findByText('Book')).toBeInTheDocument()
    expect(screen.getByTestId('location-probe')).toHaveTextContent('?list=def456')
  })

  it('opens the first list and syncs the URL when the parameter is missing or unknown', async () => {
    renderPage({ route: '/?list=unknown-code' })

    const selector = await screen.findByRole('combobox')
    expect(selector).toHaveValue('1')
    await waitFor(() => {
      expect(screen.getByTestId('location-probe')).toHaveTextContent('?list=abc123')
    })
  })

  it('creates a list from the + button input and makes it active', async () => {
    const fetchMock = renderPage()
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'New list' }))
    // the selector is replaced by the inline input
    const input = await screen.findByRole('textbox')
    await waitFor(() => {
      expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
    })

    await user.type(input, 'Viaggio')
    await user.keyboard('{Enter}')

    await waitFor(() => {
      expect(fetchMock.callsTo('/api/lists')).toHaveLength(2) // GET + POST
    })
    const post = fetchMock.lastCallTo('/api/lists')
    expect(post.init.method).toBe('POST')
    expect(JSON.parse(post.init.body)).toEqual({ name: 'Viaggio' })

    // the new list becomes active and the URL carries its code
    await waitFor(() => {
      expect(screen.getByTestId('location-probe')).toHaveTextContent('?list=ghi789')
    })
    expect(await screen.findByRole('combobox')).toHaveValue('3')
    await waitFor(() => {
      expect(fetchMock.callsTo('/api/items?list_id=3')).toHaveLength(1)
    })
  })

  it('cancels the create-list input with Escape', async () => {
    renderPage()
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'New list' }))
    await screen.findByRole('textbox')
    await user.keyboard('{Escape}')

    expect(await screen.findByRole('combobox')).toBeInTheDocument()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('renames the active list from the pencil button input', async () => {
    const fetchMock = renderPage()
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'Rename list' }))
    // the inline input is pre-filled with the current name
    const input = await screen.findByRole('textbox')
    expect(input).toHaveValue('Natale')

    await user.clear(input)
    await user.type(input, 'Natale 2026')
    await user.keyboard('{Enter}')

    await waitFor(() => {
      expect(fetchMock.callsTo('/api/lists/1')).toHaveLength(1)
    })
    const put = fetchMock.lastCallTo('/api/lists/1')
    expect(put.init.method).toBe('PUT')
    expect(JSON.parse(put.init.body)).toEqual({ name: 'Natale 2026' })

    // the selector shows the new name
    expect(await screen.findByRole('combobox')).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Natale 2026' })).toBeInTheDocument()
  })

  it('cancels the rename input with Escape and keeps the current name', async () => {
    renderPage()
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'Rename list' }))
    await screen.findByRole('textbox')
    await user.keyboard('{Escape}')

    expect(await screen.findByRole('combobox')).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Natale' })).toBeInTheDocument()
  })

  it('deletes the active list after confirming, warning about its gifts', async () => {
    const fetchMock = renderPage({ lists: lists })
    const user = userEvent.setup()
    vi.stubGlobal('confirm', vi.fn(() => true))

    await user.click(await screen.findByRole('button', { name: 'Delete list' }))
    expect(confirm).toHaveBeenCalledWith(
      expect.stringContaining('Natale'),
    )
    expect(confirm).toHaveBeenCalledWith(
      expect.stringContaining('1'),
    )

    await waitFor(() => {
      expect(fetchMock.callsTo('/api/lists/1')).toHaveLength(1)
    })
    expect(fetchMock.lastCallTo('/api/lists/1').init.method).toBe('DELETE')

    // the deleted list disappears and the first remaining list becomes active
    expect(await screen.findByRole('combobox')).toHaveValue('2')
    expect(screen.queryByRole('option', { name: 'Natale' })).not.toBeInTheDocument()
    await waitFor(() => {
      expect(fetchMock.callsTo('/api/items?list_id=2')).toHaveLength(1)
    })
  })

  it("does not delete the list when the user doesn't confirm", async () => {
    renderPage()
    const user = userEvent.setup()
    vi.stubGlobal('confirm', vi.fn(() => false))

    await user.click(await screen.findByRole('button', { name: 'Delete list' }))
    expect(confirm).toHaveBeenCalled()

    await waitFor(() => {
      expect(screen.queryByRole('option', { name: 'Natale' })).toBeInTheDocument()
    })
  })

  it("shows an error and keeps the list when it's the last one", async () => {
    const singleList = [
      { id: 1, name: "Els's wishlist", code: 'abc123', share_token: 'share-1', gift_count: 2 },
    ]
    renderPage({
      lists: singleList,
      deleteResponse: { status: 403, body: { error: "You can't delete your last list" } },
    })
    const user = userEvent.setup()
    const confirmMock = vi.fn(() => true)
    vi.stubGlobal('confirm', confirmMock)
    const alertMock = vi.fn()
    vi.stubGlobal('alert', alertMock)

    await user.click(await screen.findByRole('button', { name: 'Delete list' }))
    await waitFor(() => {
      expect(alertMock).toHaveBeenCalledWith("You can't delete your last list")
    })
    // the list is still there
    expect(await screen.findByRole('combobox')).toHaveValue('1')
  })

  it('creates a gift in the active list', async () => {
    const fetchMock = renderPage()
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'New item' }))
    const titleInput = await screen.findByLabelText(/Title/)
    await waitFor(() => {
      expect(fetchMock.callsTo('/api/items?list_id=1')).toHaveLength(1)
    })

    // fill the gift form: title and URL are enough for a minimal gift
    await user.type(titleInput, 'Scarf')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => {
      expect(fetchMock.callsTo('/api/items')).toHaveLength(1) // the POST
    })
    const post = fetchMock.lastCallTo('/api/items')
    expect(post.init.method).toBe('POST')
    const payload = JSON.parse(post.init.body)
    expect(payload.list_id).toBe(1)
    expect(payload.title).toBe('Scarf')
  })
})
