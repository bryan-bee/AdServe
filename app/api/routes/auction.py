from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.core.metrics import auction_no_fill_total, auction_wins_total
from app.core.rate_limit import auction_rate_limit
from app.db.session import get_db
from app.models.user import User
from app.schemas.auction import AuctionRequest, AuctionResponse
from app.services.auction import filter_eligible_campaigns, get_user_interest_weights, pick_winner, record_win

router = APIRouter()


@router.post("", response_model=AuctionResponse, dependencies=[Depends(auction_rate_limit)])
def run_auction(payload: AuctionRequest, db: Session = Depends(get_db)):
    """Run an ad auction for a user.

    Looks up the user, filters campaigns down to those eligible for them,
    and picks a winner via popularity-weighted random selection. On a win,
    increments the winning campaign's spend.

    Args:
        payload: The user to run the auction for.

    Returns:
        The winning campaign's id, advertiser id, and the id of the
        impression that was just logged for it.

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
    # Fetched ONCE per request, then reused for both winner selection and
    # the score persisted below - see get_user_interest_weights and
    # record_win's docstring for why the same dict has to feed both.
    user_interest_weights = get_user_interest_weights(db, user.id)
    winner = pick_winner(eligible, user, user_interest_weights)

    if winner is None:
        auction_no_fill_total.inc()
        return Response(status_code=204)

    auction_wins_total.inc()
    impression = record_win(db, winner, user, user_interest_weights)
    return AuctionResponse(
        campaign_id=winner.id,
        advertiser_id=winner.advertiser_id,
        impression_id=impression.id,
    )
