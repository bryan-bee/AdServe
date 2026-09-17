const NUMBER = new Intl.NumberFormat('en-US')

export default function InterestWeights({ interests }) {
  if (!interests?.length) return <p className="empty">No interest data yet.</p>

  // Every interest starts at exactly 1.0 for every user, so 1.0 is the
  // meaningful baseline, not zero - a bar chart anchored at zero would
  // render every bar at ~100% and show nothing. These are scaled by their
  // DRIFT from 1.0 instead, which is the only part that carries signal.
  const drifts = interests.map((i) => Math.abs(i.average_weight - 1))
  const maxDrift = Math.max(...drifts, Number.EPSILON)

  return (
    <div className="weights">
      <p className="weights__note">
        Learned from real click behaviour. Every interest starts at a flat{' '}
        <code>1.0</code>; bars show drift from that baseline.
      </p>
      {interests.map((interest) => {
        const drift = interest.average_weight - 1
        const width = (Math.abs(drift) / maxDrift) * 100
        return (
          <div className="weight" key={interest.interest}>
            <span className="weight__name">{interest.interest}</span>
            <div className="weight__track">
              <div
                className={`weight__bar${drift < 0 ? ' weight__bar--down' : ''}`}
                style={{ width: `${width}%` }}
              />
            </div>
            <span className="weight__value">{interest.average_weight.toFixed(6)}</span>
            <span className="weight__users">{NUMBER.format(interest.users)} users</span>
          </div>
        )
      })}
    </div>
  )
}
