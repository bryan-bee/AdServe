from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User
from app.schemas.auction import AuctionRequest, AuctionResponse
from app.services.auction import filter_eligible_campaigns, pick_winner, record_win

router = APIRouter()


@router.post("", response_model=AuctionResponse)
def run_auction(payload: AuctionRequest, db: Session = Depends(get_db)):
    """Run an ad auction for a user.

    Looks up the user, filters campaigns down to those eligible for them,
    and picks a winner via popularity-weighted random selection. On a win,
    increments the winning campaign's spend.

    Args:
        payload: The user to run the auction for.

    Returns:
        The winning campaign's id and advertiser id.

    Raises:
        HTTPException: 404 if `payload.user_id` doesn't match an existing user.

    Note:
        Returns 204 No Content (no body) if no campaign is eligible for
        this user - a "no fill", not an error.
    """
    user = db.get(User, payload.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    eligible = filter_eligible_campaigns(db, user)
    winner = pick_winner(eligible, user)

    if winner is None:
        return Response(status_code=204)

    record_win(db, winner)
    return AuctionResponse(campaign_id=winner.id, advertiser_id=winner.advertiser_id)
