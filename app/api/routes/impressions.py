import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.idempotency import claim_or_replay, idempotency_key_header, store_response
from app.core.metrics import idempotent_replays_total, suspicious_clicks_total
from app.db.session import get_db
from app.models.impression import Impression
from app.schemas.click import ClickRead
from app.services.events import publish_event

router = APIRouter()

# A click landing sooner than this after its own impression is treated as
# implausible for a human who actually saw an ad and decided to click it.
# Deliberately conservative - see STUDY_NOTES.md §27 for why this flags
# rather than blocks, and why the threshold is set low enough to be
# obviously-bot territory rather than merely "fast".
MIN_PLAUSIBLE_CLICK_DELAY_SECONDS = 0.5


@router.post("/{impression_id}/clicks", response_model=ClickRead, status_code=201)
def record_click(
    impression_id: uuid.UUID,
    db: Session = Depends(get_db),
    idempotency_key: str | None = Depends(idempotency_key_header),
):
    """Record that a specific impression was clicked.

    Publishes a "click" event to Kafka and returns immediately - a separate
    consumer process (scripts/consume_events.py) does the actual Postgres
    insert. See STUDY_NOTES.md §20 for that pipeline and the
    eventual-consistency window it opens.

    Supports an optional `Idempotency-Key` header. Without one, a client
    that retries after a dropped connection produces a second, genuinely
    distinct click event (new `id`) and double-counts the click - the
    consumer's own deduplication can't catch that, because from its point
    of view these are two different events. With one, the retry replays the
    original response and publishes nothing. See §26.

    Also applies a timing-based click-fraud heuristic (§27): a click
    arriving implausibly soon after its impression is flagged - counted in
    `adserve_suspicious_clicks_total` and marked on the published event -
    but still recorded, deliberately, rather than rejected.

    Args:
        impression_id: The impression that was clicked.

    Returns:
        The click that was just queued for recording - `id` is generated
        here, before the event is published, so the caller gets it back
        immediately without waiting on Kafka or Postgres.

    Raises:
        HTTPException: 404 if the impression doesn't exist, or 409 if
            another request with the same Idempotency-Key is in flight.
    """
    replayed = claim_or_replay("click", idempotency_key)
    if replayed is not None:
        idempotent_replays_total.labels(endpoint="clicks").inc()
        return ClickRead(**replayed)

    impression = db.get(Impression, impression_id)
    if impression is None:
        raise HTTPException(status_code=404, detail="Impression not found")

    click_id = uuid.uuid4()
    occurred_at = datetime.now(timezone.utc)

    # The impression row is written synchronously by record_win (§20.11),
    # so its timestamp is always available here without waiting on the
    # event pipeline - which is what makes this check possible at request
    # time at all.
    elapsed = (occurred_at - impression.occurred_at).total_seconds()
    suspicious = elapsed < MIN_PLAUSIBLE_CLICK_DELAY_SECONDS
    if suspicious:
        suspicious_clicks_total.inc()

    publish_event(
        {
            "event_type": "click",
            "id": str(click_id),
            "impression_id": str(impression_id),
            "occurred_at": occurred_at.isoformat(),
            "suspicious": suspicious,
        },
        # Keyed on the click's own id, not the impression's - a conversion
        # event also keys on this same click_id, which is what guarantees
        # Kafka places a click and the conversion(s) referencing it on the
        # same partition, in produce order (§20.5).
        key=str(click_id),
    )

    response = ClickRead(id=click_id, impression_id=impression_id, occurred_at=occurred_at)
    store_response("click", idempotency_key, response.model_dump(mode="json"))
    return response
