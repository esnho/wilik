import { useLocation } from 'react-router-dom'

// dumps the router's current query string so tests can observe the URL seam
export default function LocationProbe() {
  const { search } = useLocation()
  return <span data-testid="location-probe">{search}</span>
}
