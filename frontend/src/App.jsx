import { useCallback, useEffect, useState } from 'react'
import { fetchInterestWeights, fetchSummary, fetchTopCampaigns } from './api'
import SummaryCards from './components/SummaryCards'
import CampaignTable from './components/CampaignTable'
import InterestWeights from './components/InterestWeights'

const REFRESH_MS = 5000

export default function App() {
  const [data, setData] = useState({ summary: null, campaigns: [], interests: [] })
  const [error, setError] = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)

  const load = useCallback(async () => {
    try {
      // Fetched in parallel, not sequentially: three independent endpoints
      // that don't depend on each other, so awaiting them one at a time
      // would make the dashboard three round trips slow for no reason.
      const [summary, campaigns, interests] = await Promise.all([
        fetchSummary(),
        fetchTopCampaigns(8),
        fetchInterestWeights(10),
      ])
      setData({ summary, campaigns, interests })
      setLastUpdated(new Date())
      setError(null)
    } catch (err) {
      // Deliberately keeps the last good data on screen rather than
      // blanking the dashboard: a transient failed poll shouldn't destroy
      // what the viewer was already reading.
      setError(err.message)
    }
  }, [])

  useEffect(() => {
    load()
    const timer = setInterval(load, REFRESH_MS)
    return () => clearInterval(timer)
  }, [load])

  return (
    <div className="app">
      <header className="header">
        <div>
          <h1>AdServe</h1>
          <p className="subtitle">Real-time ad platform operations</p>
        </div>
        <div className="status">
          {error ? (
            <span className="status__error">Update failed: {error}</span>
          ) : (
            <span className="status__live">
              <span className="dot" /> Live
            </span>
          )}
          {lastUpdated && (
            <span className="status__time">
              Updated {lastUpdated.toLocaleTimeString()}
            </span>
          )}
        </div>
      </header>

      {!data.summary && !error && <p className="empty">Loading…</p>}

      <SummaryCards summary={data.summary} />

      <section className="panel">
        <h2>Top campaigns by impressions</h2>
        <CampaignTable campaigns={data.campaigns} />
      </section>

      <section className="panel">
        <h2>Learned interest weights</h2>
        <InterestWeights interests={data.interests} />
      </section>
    </div>
  )
}
