const NUMBER = new Intl.NumberFormat('en-US')
const MONEY = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })
const PERCENT = new Intl.NumberFormat('en-US', { style: 'percent', maximumFractionDigits: 2 })

export default function CampaignTable({ campaigns }) {
  if (!campaigns?.length) {
    return <p className="empty">No campaigns have served impressions yet.</p>
  }

  return (
    <table className="table">
      <thead>
        <tr>
          <th>Advertiser</th>
          <th>Status</th>
          <th className="num">Impressions</th>
          <th className="num">Clicks</th>
          <th className="num">CTR</th>
          <th className="num">Spend</th>
          <th>Budget used</th>
        </tr>
      </thead>
      <tbody>
        {campaigns.map((c) => {
          const used = c.budget > 0 ? c.spent / c.budget : 0
          return (
            <tr key={c.campaign_id}>
              <td>
                <span className="advertiser">{c.advertiser_name}</span>
                {/* The campaign id is what you'd actually need to look a row
                    up in psql or the API, so it's shown rather than hidden. */}
                <span className="mono-id">{c.campaign_id.slice(0, 8)}</span>
              </td>
              <td>
                <span className={`pill pill--${c.status}`}>{c.status}</span>
              </td>
              <td className="num">{NUMBER.format(c.impressions)}</td>
              <td className="num">{NUMBER.format(c.clicks)}</td>
              <td className="num">{PERCENT.format(c.click_through_rate)}</td>
              <td className="num">{MONEY.format(c.spent)}</td>
              <td>
                {/* Budget consumption reads faster as a bar than as a second
                    number next to spend - the question is "how close to the
                    cap", which is a proportion, not a value. The percentage
                    is shown alongside because real usage here sits around
                    4%, which as a bar alone is an unreadable nub. */}
                <div
                  className="budget"
                  title={`${MONEY.format(c.spent)} of ${MONEY.format(c.budget)}`}
                >
                  <div className="meter">
                    <div
                      className="meter__fill"
                      style={{ width: `${Math.max(Math.min(used * 100, 100), 1.5)}%` }}
                    />
                  </div>
                  <span className="budget__pct">{PERCENT.format(used)}</span>
                </div>
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
