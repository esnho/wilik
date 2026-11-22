import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { I18nContext } from '../i18n'
import { vi } from 'vitest'
import LocationProbe from './LocationProbe'

// English keys are the exact English text (see I18nProvider.jsx), so t(key) -> key is
// what the app shows under its default language; {placeholders} are interpolated like
// the real t() does
const i18nDefaults = {
  t: (key, values = {}) =>
    typeof key === 'string'
      ? key.replace(/\{(\w+)\}/g, (_, name) => String(values[name] ?? `{${name}}`))
      : key,
  languageOptions: [],
  languages: { en: { name: 'English' }, it: { name: 'Italiano' }, nl: { name: 'Nederlands' } },
  applyInstanceSettings: () => {},
  activePreference: 'en',
  languageMenuVisible: false,
  setLanguagePreference: () => {},
  setShowLanguageMenu: () => {},
  setPreviewPreference: () => {},
  setPreviewShowLanguageMenu: () => {},
  clearLanguagePreview: () => {},
}

// fetch mock at the HTTP boundary: routes are [{match, status, body}] where match(url)
// says which one answers. Requests with no matching route fail the test instead of
// silently returning nothing.
export function createFetchMock(routes) {
  const calls = []
  const mock = vi.fn((url, init) => {
    calls.push({ url: String(url), init })
    const route = routes.find((route) => route.match(String(url), init))
    if (!route) return Promise.reject(new Error(`No route mocked for ${url}`))
    const { status = 200, body = {} } = route
    // a 204 response must not carry a body (the Response constructor rejects it)
    const bodyless = status === 204 || status === 304
    return Promise.resolve(
      bodyless
        ? new Response(null, { status })
        : new Response(JSON.stringify(body), { status }),
    )
  })
  mock.lastCall = () => calls[calls.length - 1]
  mock.lastCallTo = (url) => [...calls].reverse().find((call) => call.url === url)
  mock.callsTo = (url) => calls.filter((call) => call.url === url)
  return mock
}

export function renderWithProviders(ui, { route = '/', ...options } = {}) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <I18nContext.Provider value={{ ...i18nDefaults, ...options.i18nValue }}>
        {ui}
        <LocationProbe />
      </I18nContext.Provider>
    </MemoryRouter>,
    options,
  )
}

// dumps the router's current query string so tests can observe the URL seam
