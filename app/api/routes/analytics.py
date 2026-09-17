"""Read-only aggregate endpoints, built for the React dashboard (Step 9).

Deliberately unauthenticated, like the other GET endpoints (see
STUDY_NOTES.md §24.1): these return aggregate platform statistics, not
per-advertiser private data, and keeping them open avoids the genuinely
worse anti-pattern of embedding a secret API key in browser JavaScript
where anyone can read it.

Every query here is a deliberate aggregate computed in SQL rather than by
loading rows into Python - see §28 for the index work these queries
finally made necessary, which §19's Finding 5 predicted would be needed
"the moment you write that query".
"""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.analytics import CampaignPerformance, InterestWeightSample, PlatformSummary

router = APIRouter()


@router.get("/summary", response_model=PlatformSummary)
def platform_summary(db: Session = Depends(get_db)):
    """Headline totals across the whole platform.

    One round trip, not eight: every count is a scalar subquery inside a
    single SELECT, so the dashboard's top row costs one query rather than
    one per statistic.
    """
    row = db.execute(text("""
        SELECT
            (SELECT count(*) FROM advertisers)                        AS advertisers,
            (SELECT count(*) FROM campaigns)                          AS campaigns,
            (SELECT count(*) FROM campaigns WHERE status = 'active')  AS active_campaigns,
            (SELECT count(*) FROM impressions)                        AS impressions,
            (SELECT count(*) FROM clicks)                             AS clicks,
            (SELECT count(*) FROM conversions)                        AS conversions,
            (SELECT count(*) FROM clicks WHERE suspicious)            AS suspicious_clicks,
            (SELECT coalesce(sum(spent), 0) FROM campaigns)           AS total_spend
    """)).one()

    return PlatformSummary(
        advertisers=row.advertisers,
        campaigns=row.campaigns,
        active_campaigns=row.active_campaigns,
        impressions=row.impressions,
        clicks=row.clicks,
        conversions=row.conversions,
        suspicious_clicks=row.suspicious_clicks,
        # Guarded against division by zero rather than assuming there's
        # always traffic - a freshly-seeded database has impressions but
        # no clicks at all.
        click_through_rate=(row.clicks / row.impressions) if row.impressions else 0.0,
        conversion_rate=(row.conversions / row.clicks) if row.clicks else 0.0,
        total_spend=float(row.total_spend),
    )


@router.get("/campaigns/top", response_model=list[CampaignPerformance])
def top_campaigns(limit: int = 10, db: Session = Depends(get_db)):
    """The campaigns with the most impressions, with their click-through
    rates and spend.

    The LEFT JOINs are onto pre-aggregated subqueries rather than joining
    the raw impressions/clicks tables directly: joining first and grouping
    afterwards would multiply every impression row by that campaign's
    click rows before collapsing them again, inflating the counts and
    doing far more work. Aggregate first, then join the small results.
    """
    rows = db.execute(text("""
        SELECT
            c.id            AS campaign_id,
            a.name          AS advertiser_name,
            c.status        AS status,
            c.budget        AS budget,
            c.spent         AS spent,
            coalesce(i.impressions, 0) AS impressions,
            coalesce(cl.clicks, 0)     AS clicks
        FROM campaigns c
        JOIN advertisers a ON a.id = c.advertiser_id
        LEFT JOIN (
            SELECT campaign_id, count(*) AS impressions
            FROM impressions GROUP BY campaign_id
        ) i ON i.campaign_id = c.id
        LEFT JOIN (
            SELECT i2.campaign_id, count(*) AS clicks
            FROM clicks cl2 JOIN impressions i2 ON i2.id = cl2.impression_id
            GROUP BY i2.campaign_id
        ) cl ON cl.campaign_id = c.id
        WHERE coalesce(i.impressions, 0) > 0
        ORDER BY impressions DESC
        LIMIT :limit
    """), {"limit": limit}).all()

    return [
        CampaignPerformance(
            campaign_id=r.campaign_id,
            advertiser_name=r.advertiser_name,
            status=r.status,
            budget=float(r.budget),
            spent=float(r.spent),
            impressions=r.impressions,
            clicks=r.clicks,
            click_through_rate=(r.clicks / r.impressions) if r.impressions else 0.0,
        )
        for r in rows
    ]


@router.get("/interests/weights", response_model=list[InterestWeightSample])
def interest_weights(limit: int = 12, db: Session = Depends(get_db)):
    """Average learned interest weight across all users, per interest.

    This is the Step 8b preference learning (§21/§22) made visible: every
    interest starts at a flat 1.0 for every user, so any interest whose
    average has drifted above or below 1.0 has done so purely because of
    real click behaviour nudging it.
    """
    rows = db.execute(text("""
        SELECT i.name AS interest, avg(ui.weight) AS average_weight, count(*) AS users
        FROM user_interests ui
        JOIN interests i ON i.id = ui.interest_id
        GROUP BY i.name
        ORDER BY average_weight DESC
        LIMIT :limit
    """), {"limit": limit}).all()

    return [
        InterestWeightSample(
            interest=r.interest, average_weight=float(r.average_weight), users=r.users
        )
        for r in rows
    ]
