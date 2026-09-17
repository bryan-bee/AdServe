from pydantic import BaseModel
from uuid import UUID


class PlatformSummary(BaseModel):
    """Headline numbers for the dashboard's top row."""

    advertisers: int
    campaigns: int
    active_campaigns: int
    impressions: int
    clicks: int
    conversions: int
    suspicious_clicks: int
    click_through_rate: float
    conversion_rate: float
    total_spend: float


class CampaignPerformance(BaseModel):
    """One row of the dashboard's campaign table."""

    campaign_id: UUID
    advertiser_name: str
    status: str
    budget: float
    spent: float
    impressions: int
    clicks: int
    click_through_rate: float


class InterestWeightSample(BaseModel):
    """One interest and how heavily users lean toward it, aggregated across
    the whole user base - the visible output of the Step 8b preference
    learning (STUDY_NOTES.md §21/§22)."""

    interest: str
    average_weight: float
    users: int
