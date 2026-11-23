import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import GiftDirectory from './GiftDirectory'
import { createFetchMock, renderWithProviders } from '../test/helpers'

const lists = [
  { list_name: 'Compleanno', username: 'els', share_token: 'share-1', theme_color: null },
  { list_name: 'Natale', username: 'els', share_token: 'share-2', theme_color: null },
  { list_name: 'Viaggio', username: 'joost', share_token: 'share-3', theme_color: null },
  { list_name: 'Casa', username: 'joost', share_token: 'share-4', theme_color: null },
]

function renderDirectory(body) {
  const fetchMock = createFetchMock([{ match: (url) => url === '/api/public/directory', body }])
  vi.stubGlobal('fetch', fetchMock)
  renderWithProviders(<GiftDirectory />)
  return fetchMock
}

function expectNothingShown() {
  expect(screen.queryByText("Looking for someone's wishlist?")).not.toBeInTheDocument()
}

describe('GiftDirectory on the guest homepage', () => {
  it('shows nothing while the directory is turned off', async () => {
    const fetchMock = renderDirectory({ enabled: false, lists })
    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    expectNothingShown()
  })

  it('shows nothing when there are no public wishlists', async () => {
    const fetchMock = renderDirectory({ enabled: true, lists: [] })
    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    expectNothingShown()
  })

  it('lists the public wishlists directly, without a browse-all link for three lists', async () => {
    renderDirectory({ enabled: true, lists: lists.slice(0, 3) })

    const link = await screen.findByRole('link', { name: /Compleanno/ })
    expect(link).toHaveAttribute('href', '/list/share-1')
    expect(screen.getAllByRole('listitem')).toHaveLength(3)
    expect(screen.getByText('joost')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Browse wishlists' })).not.toBeInTheDocument()
  })

  it('caps the inline list at three and links to the full directory for more', async () => {
    renderDirectory({ enabled: true, lists })

    const browseAll = await screen.findByRole('link', { name: 'Browse wishlists' })
    expect(browseAll).toHaveAttribute('href', '/directory')
    expect(screen.getAllByRole('listitem')).toHaveLength(3)
    expect(screen.queryByText('Casa')).not.toBeInTheDocument()
  })
})