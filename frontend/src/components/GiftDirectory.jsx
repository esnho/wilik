import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { UserIcon } from './Icons'
import { useI18n } from '../i18n'

const API_BASE = '/api'
const HOMEPAGE_LIST_LIMIT = 3

function GiftDirectory() {
  const { t } = useI18n()
  const [lists, setLists] = useState([]) // empty until the directory answers (or when it's off)

  useEffect(() => {
    fetch(`${API_BASE}/public/directory`)
      .then((response) => response.json())
      .then((data) => setLists(data.enabled ? data.lists : []))
  }, [])

  if (lists.length === 0) return null

  const preview = lists.slice(0, HOMEPAGE_LIST_LIMIT)

  return (
    <div className="gift-directory">
      <h3>{t("Looking for someone's wishlist?")}</h3>
      <ul className="gift-directory__list gift-directory__list--compact">
        {preview.map((list) => (
          <li key={list.share_token}>
            <Link to={`/list/${list.share_token}`}>
              <span className="gift-directory__item-name">{list.list_name}</span>
              <span className="gift-directory__badge">
                <UserIcon /> {list.username}
              </span>
            </Link>
          </li>
        ))}
      </ul>
      {lists.length > HOMEPAGE_LIST_LIMIT && (
        <Link to="/directory" className="gift-directory__more">
          {t('Browse wishlists')}
        </Link>
      )}
    </div>
  )
}

export default GiftDirectory
