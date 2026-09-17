import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from app.core.idempotency import claim_or_replay, idempotency_key_header, store_response
from app.core.metrics import idempotent_replays_total
from app.schemas.conversion import ConversionRead
from app.services.events import publish_event

router = APIRouter()


@router.post("/{click_id}/conversions", response_model=ConversionRead, status_code=201)
def record_conversion(
    click_id: uuid.UUID,
    idempotency_key: str | None = Depends(idempotency_key_header),
):
    """Record that a specific click led to a conversion.

    Touches Postgres not at all - not even to read. The click-existence
    check this endpoint used to perform stopped being safe once clicks
    became events rather than synchronous writes (§20.7): a conversion can
    legitimately arrive before the consumer has persisted the click it
    refers to, and 404ing in that window would reject a valid conversion.
    `click_id` is trusted as given; the consumer's foreign key is what
    eventually catches a bogus one.

    Supports an optional `Idempotency-Key` header, for the same reason
    record_click does (§26) - and it matters more here, since a conversion
    is the event most directly tied to money.

    Args:
        click_id: The click that converted.

    Returns:
        The conversion that was just queued for recording.

    Raises:
        HTTPException: 409 if another request with the same
            Idempotency-Key is currently in flight.
    """
    replayed = claim_or_replay("conversion", idempotency_key)
    if replayed is not None:
        idempotent_replays_total.labels(endpoint="conversions").inc()
        return ConversionRead(**replayed)

    conversion_id = uuid.uuid4()
    occurred_at = datetime.now(timezone.utc)

    publish_event(
        {
            "event_type": "conversion",
            "id": str(conversion_id),
            "click_id": str(click_id),
            "occurred_at": occurred_at.isoformat(),
        },
        # Same key as the click event it references, so both land on the
        # same partition and a consumer always sees the click first (§20.5).
        key=str(click_id),
    )

    response = ConversionRead(id=conversion_id, click_id=click_id, occurred_at=occurred_at)
    store_response("conversion", idempotency_key, response.model_dump(mode="json"))
    return response
