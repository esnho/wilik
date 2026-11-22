import { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import GiftCard from '../components/GiftCard'
import GiftForm from '../components/GiftForm'
import { PlusIcon, PencilIcon, TrashIcon, SparkleIcon, GripIcon, SpinnerIcon } from '../components/Icons'
import { sortGifts } from '../sortGifts'
import { useI18n } from '../i18n'

const API_BASE = '/api'
const API_URL = `${API_BASE}/items`

function WishlistPage({ currentUser }) {
  const { t } = useI18n()
  const [searchParams, setSearchParams] = useSearchParams()
  const [lists, setLists] = useState(null)
  const [activeListId, setActiveListId] = useState(null)
  const [items, setItems] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  const [isAdding, setIsAdding] = useState(false)
  const [claimManagementSiteEnabled, setClaimManagementSiteEnabled] = useState(false)
  const [claimDeleteWarningSkipped, setClaimDeleteWarningSkipped] = useState(false)
  const [dragState, setDragState] = useState({
    draggedId: null,
    draggedRating: undefined,
    overId: null,
    x: 0,
    y: 0,
  })
  const [editingList, setEditingList] = useState(null) // null | 'new' | 'rename'

  useEffect(() => {
    fetch(`${API_BASE}/lists`, { credentials: 'include' })
      .then((response) => response.json())
      .then((data) => {
        setLists(data)
        const requested = data.find((list) => list.code === searchParams.get('list'))
        if (requested) {
          setActiveListId(requested.id)
        } else if (data.length > 0) {
          // open the first list and make the URL match, so bookmarks made right now
          // keep working (the code is stable; see docs/piano-liste-multiple.md)
          setActiveListId(data[0].id)
          setSearchParams({ list: data[0].code }, { replace: true })
        }
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (activeListId == null) return
    fetch(`${API_URL}?list_id=${activeListId}`, { credentials: 'include' })
      .then((response) => response.json())
      .then((data) => setItems(data))
      .finally(() => setIsLoading(false))
  }, [activeListId])

  useEffect(() => {
    fetch(`${API_BASE}/settings`)
      .then((response) => response.json())
      .then((data) => {
        setClaimManagementSiteEnabled(data.claim_management_site_enabled)
        setClaimDeleteWarningSkipped(data.claim_delete_warning_skipped)
      })
  }, [])

  const claimManagementEnabled = currentUser.claim_management_enabled && claimManagementSiteEnabled

  function handleRatingChange(id, rating) {
    fetch(`${API_URL}/${id}/rating`, {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rating }),
    })
      .then((response) => response.json())
      .then((updatedGift) => {
        setItems((current) =>
          current.map((item) => (item.id === updatedGift.id ? updatedGift : item))
        )
      })
  }

  function handleCreate(values) {
    fetch(API_URL, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...values, list_id: activeListId }),
    })
      .then((response) => response.json())
      .then((newGift) => {
        setItems((current) => [...current, newGift])
        setIsAdding(false)
      })
  }

  function handleUpdate(id, values) {
    fetch(`${API_URL}/${id}`, {
      method: 'PUT',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(values),
    })
      .then((response) => response.json())
      .then((updatedGift) => {
        setItems((current) =>
          current.map((item) => (item.id === updatedGift.id ? updatedGift : item))
        )
      })
  }

  function handleDelete(id) {
    fetch(`${API_URL}/${id}`, { method: 'DELETE', credentials: 'include' }).then(() => {
      setItems((current) => current.filter((item) => item.id !== id))
    })
  }

  function handleReceivedChange(id, received) {
    fetch(`${API_URL}/${id}/received`, {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ received }),
    })
      .then((response) => response.json())
      .then((updatedGift) => {
        setItems((current) => current.map((item) => (item.id === updatedGift.id ? updatedGift : item)))
      })
  }

  function handleClaimsReset(updatedGift) {
    setItems((current) => current.map((item) => (item.id === updatedGift.id ? updatedGift : item)))
  }

  function handleReorder(draggedId, targetId) {
    const dragged = items.find((item) => item.id === draggedId)
    const target = items.find((item) => item.id === targetId)
    if (!dragged || !target) return
    if (dragged.rating !== target.rating) {
      alert(t('Gifts can only be reordered within the same star rating.'))
      return
    }

    const group = sortGifts(items).filter((item) => item.rating === dragged.rating)
    const withoutDragged = group.filter((item) => item.id !== draggedId)
    const targetIndex = withoutDragged.findIndex((item) => item.id === targetId)
    withoutDragged.splice(targetIndex, 0, dragged)

    const reordered = withoutDragged.map((item, index) => ({ id: item.id, sort_order: index }))

    setItems((current) =>
      current.map((item) => {
        const match = reordered.find((r) => r.id === item.id)
        return match ? { ...item, sort_order: match.sort_order } : item
      })
    )

    reordered.forEach(({ id, sort_order }) => {
      fetch(`${API_URL}/${id}`, {
        method: 'PUT',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sort_order }),
      })
    })
  }

  function handleDragStart(id, rating) {
    setDragState((current) => ({ ...current, draggedId: id, draggedRating: rating, overId: null }))
  }

  function handleDragMove(x, y) {
    setDragState((current) => ({ ...current, x, y }))
  }

  function handleDragEnter(id) {
    setDragState((current) => ({ ...current, overId: id }))
  }

  function handleDragEnd() {
    setDragState({ draggedId: null, draggedRating: undefined, overId: null, x: 0, y: 0 })
  }

  const draggedItem = dragState.draggedId != null ? items.find((item) => item.id === dragState.draggedId) : null

  const activeItems = items.filter((item) => !item.received)

  const activeList = lists?.find((list) => list.id === activeListId)

  function handleListNameSubmit(name) {
    const trimmed = name.trim()
    if (!trimmed) {
      setEditingList(null)
      return
    }
    if (editingList === 'new') {
      fetch(`${API_BASE}/lists`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: trimmed }),
      })
        .then((response) => response.json())
        .then((created) => {
          setLists((current) => [...current, created])
          setActiveListId(created.id)
          setSearchParams({ list: created.code }, { replace: true })
        })
    } else {
      fetch(`${API_BASE}/lists/${activeListId}`, {
        method: 'PUT',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: trimmed }),
      })
        .then((response) => response.json())
        .then((updated) => {
          setLists((current) => current.map((list) => (list.id === updated.id ? updated : list)))
        })
    }
    setEditingList(null)
  }

  function handleDeleteList() {
    const proceed = confirm(
      t('Delete "{name}"? This will also delete its {count} gifts, including received ones.', {
        name: activeList.name,
        count: activeList.gift_count,
      }),
    )
    if (!proceed) return
    fetch(`${API_BASE}/lists/${activeListId}`, { method: 'DELETE', credentials: 'include' }).then(
      (response) => {
        if (!response.ok) {
          response.json().then((data) => alert(t(data.error)))
          return
        }
        const remaining = lists.filter((list) => list.id !== activeListId)
        const next = remaining[0]
        setLists(remaining)
        setActiveListId(next.id)
        setSearchParams({ list: next.code }, { replace: true })
      },
    )
  }

  return (
    <>
      <div className="wishlist-toolbar">
        {editingList ? (
          <ListNameInput
            initialName={editingList === 'rename' ? activeList?.name : ''}
            onSubmit={handleListNameSubmit}
            onCancel={() => setEditingList(null)}
            label={editingList === 'new' ? t('New list') : t('Rename list')}
          />
        ) : (
          <>
            <select
              className="wishlist-toolbar__title"
              value={activeListId ?? ''}
              onChange={(event) => {
                const selected = lists.find((list) => list.id === Number(event.target.value))
                setActiveListId(selected.id)
                setSearchParams({ list: selected.code }, { replace: true })
              }}
              aria-label={t('Active list')}
            >
              {(lists ?? []).map((list) => (
                <option key={list.id} value={list.id}>
                  {list.name}
                </option>
              ))}
            </select>
            <button
              type="button"
              aria-label={t('New list')}
              onClick={() => setEditingList('new')}
            >
              <PlusIcon width={16} height={16} strokeWidth={3} />
            </button>
            <button
              type="button"
              aria-label={t('Rename list')}
              disabled={!activeList}
              onClick={() => setEditingList('rename')}
            >
              <PencilIcon width={16} height={16} />
            </button>
            <button
              type="button"
              aria-label={t('Delete list')}
              disabled={!activeList}
              onClick={handleDeleteList}
            >
              <TrashIcon width={16} height={16} />
            </button>
          </>
        )}
        <button
          className={isAdding ? undefined : 'btn-primary'}
          type="button"
          onClick={() => setIsAdding((current) => !current)}
        >
          {isAdding ? (
            t('Cancel')
          ) : (
            <>
              <PlusIcon width={14} height={14} strokeWidth={3} /> {t('New item')}
            </>
          )}
        </button>
      </div>
      <main>
        <div className="gift-grid">
          {isAdding && (
            <GiftForm
              defaultCurrency={currentUser.currency}
              onSubmit={handleCreate}
              onCancel={() => setIsAdding(false)}
            />
          )}
          {!isAdding && isLoading && (
            <div className="empty-state">
              <SpinnerIcon width={32} height={32} />
              <p>{t('Loading your wishlist…')}</p>
            </div>
          )}
          {!isAdding && !isLoading && activeItems.length === 0 && (
            <div className="empty-state">
              <SparkleIcon />
              <h3>{t('Your wishlist is empty')}</h3>
              <p>{t('Add your first gift idea to get started')}</p>
              <button className="btn-primary" type="button" onClick={() => setIsAdding(true)}>
                <PlusIcon width={14} height={14} strokeWidth={3} /> {t('New item')}
              </button>
            </div>
          )}
          {sortGifts(activeItems).map((item) => (
            <GiftCard
              key={item.id}
              gift={item}
              currency={currentUser.currency}
              decimalSeparator={currentUser.decimal_separator}
              showImagePlaceholder={currentUser.show_image_placeholder}
              showBackgroundPattern={currentUser.show_background_pattern}
              claimManagementEnabled={claimManagementEnabled}
              lockIconClaimedOnly={currentUser.lock_icon_claimed_only}
              claimDeleteWarningSkipped={claimDeleteWarningSkipped}
              onRatingChange={handleRatingChange}
              onUpdate={handleUpdate}
              onDelete={handleDelete}
              onReorder={handleReorder}
              onReceivedChange={handleReceivedChange}
              onClaimsReset={handleClaimsReset}
              dragState={dragState}
              onDragStart={handleDragStart}
              onDragMove={handleDragMove}
              onDragEnter={handleDragEnter}
              onDragEnd={handleDragEnd}
            />
          ))}
        </div>
      </main>
      {draggedItem && (
        <div
          className="gift-card__drag-ghost"
          style={{ left: dragState.x, top: dragState.y }}
        >
          <GripIcon />
          <span className="gift-card__drag-ghost-title">{draggedItem.title}</span>
        </div>
      )}
    </>
  )
}

function ListNameInput({ initialName, onSubmit, onCancel, label }) {
  const [name, setName] = useState(initialName)
  return (
    <input
      type="text"
      className="wishlist-toolbar__title wishlist-toolbar__title-input"
      value={name}
      aria-label={label}
      autoFocus
      maxLength={100}
      onChange={(event) => setName(event.target.value)}
      onKeyDown={(event) => {
        if (event.key === 'Enter') onSubmit(name)
        if (event.key === 'Escape') onCancel()
      }}
      onBlur={() => onCancel()}
    />
  )
}

export default WishlistPage
