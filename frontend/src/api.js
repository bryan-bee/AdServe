// All backend access lives here rather than being scattered through
// components, so the base path, error handling and response shape are
// defined once. Requests go to /api/*, which vite.config.js proxies to the
// FastAPI server (see the comment there for why a proxy beats CORS in dev).

const BASE = '/api'

async function get(path) {
  const response = await fetch(`${BASE}${path}`)
  if (!response.ok) {
    // Surfacing the status matters: a 429 from the rate limiter and a 500
    // from a broken query are very different problems, and a dashboard
    // that renders both as a blank panel hides that.
    throw new Error(`${response.status} ${response.statusText}`)
  }
  return response.json()
}

export const fetchSummary = () => get('/analytics/summary')
export const fetchTopCampaigns = (limit = 8) => get(`/analytics/campaigns/top?limit=${limit}`)
export const fetchInterestWeights = (limit = 10) => get(`/analytics/interests/weights?limit=${limit}`)
