const NUMBER = new Intl.NumberFormat('en-US')
const MONEY = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })
const PERCENT = new Intl.NumberFormat('en-US', { style: 'percent', maximumFractionDigits: 3 })

export default function SummaryCards({ summary }) {
  if (!summary) return null

  const cards = [
    { label: 'Impressions', value: NUMBER.format(summary.impressions) },
    { label: 'Clicks', value: NUMBER.format(summary.clicks) },
    { label: 'Click-through rate', value: PERCENT.format(summary.click_through_rate) },
    { label: 'Conversions', value: NUMBER.format(summary.conversions) },
    { label: 'Conversion rate', value: PERCENT.format(summary.conversion_rate) },
    { label: 'Total spend', value: MONEY.format(summary.total_spend) },
    {
      label: 'Active campaigns',
      value: NUMBER.format(summary.active_campaigns),
      sub: `of ${NUMBER.format(summary.campaigns)} total`,
    },
    {
      label: 'Suspicious clicks',
      value: NUMBER.format(summary.suspicious_clicks),
      // Given its own visual state rather than being just another number:
      // this is the one card that means "something needs a human's
      // attention", and only when it's non-zero.
      tone: summary.suspicious_clicks > 0 ? 'warn' : 'ok',
      sub: 'flagged by timing heuristic',
    },
  ]

  return (
    <div className="cards">
      {cards.map((card) => (
        <div key={card.label} className={`card${card.tone ? ` card--${card.tone}` : ''}`}>
          <span className="card__label">{card.label}</span>
          <span className="card__value">{card.value}</span>
          {card.sub && <span className="card__sub">{card.sub}</span>}
        </div>
      ))}
    </div>
  )
}
