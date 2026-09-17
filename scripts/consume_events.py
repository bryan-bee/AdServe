"""Consumer side of AdServe's event pipeline (Step 8), plus heuristic
preference learning on top of it (Step 8b).

Subscribes to the adserve.events topic and writes each event to Postgres -
the actual persistence step that record_click/record_conversion
(app/api/routes/impressions.py, app/api/routes/clicks.py) no longer do
themselves. Also nudges a user's interest weights based on click behavior
(nudge_interests_from_click) - the "heuristic version first" of user
preference learning from ROADMAP.md. Run this as its own long-lived
process, separate from the API server:

    python -m scripts.consume_events

See STUDY_NOTES.md §20 for the event-pipeline concepts (what a consumer
group is, why offsets are committed manually here, and why every insert
below has to tolerate being run twice on the same message) and §21 for the
preference-learning design specifically.
"""
import json
import uuid
from datetime import datetime

from confluent_kafka import Consumer, KafkaError
from sqlalchemy import text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.db.session import SessionLocal

# Every model needs importing here, not just Click/Conversion - SQLAlchemy
# only knows about a table's foreign keys once the model that maps it has
# actually been imported somewhere. Click has a foreign key to impressions;
# without importing Impression too, committing a Click fails with
# NoReferencedTableError the first time SQLAlchemy tries to sort tables by
# FK dependency during flush. Same gotcha, same fix, as tests/conftest.py.
from app.models.advertiser import Advertiser  # noqa: F401
from app.models.audience_targeting import AudienceTargeting  # noqa: F401
from app.models.campaign import Campaign  # noqa: F401
from app.models.interest import Interest  # noqa: F401
from app.models.user import User, user_interests
from app.models.impression import Impression  # noqa: F401
from app.models.click import Click
from app.models.conversion import Conversion

CONSUMER_GROUP = "adserve-event-writer"

# Step 8b (heuristic preference learning - see STUDY_NOTES.md §21):
# deliberately simple, tunable constants, not learned or configurable yet
# ("no ML yet, just a scoring rule", per ROADMAP.md). +1.0 mirrors
# score_campaign's existing "+1 per matched interest" convention. 0.95
# means an interest that stops earning clicks loses ~5% of its weight on
# every OTHER click this same user makes elsewhere - roughly halved after
# ~14 such clicks, a slow drift rather than a sharp cutoff.
INTEREST_NUDGE_INCREMENT = 1.0
INTEREST_DECAY_FACTOR = 0.95


def nudge_interests_from_click(db, impression_id: uuid.UUID) -> None:
    """Heuristic preference learning: a click is evidence this user is
    interested in whatever the campaign was targeting, so bump the
    weight of those interests for this user - creating a brand new
    user_interests row, at a starter weight, if the campaign targeted an
    interest the user didn't already have. Every OTHER interest this user
    already has gets a small multiplicative decay, so an interest that
    stops earning clicks fades out over time instead of staying inflated
    forever from one early click.

    Deliberately keys off the FULL set of interests the campaign
    targeted, not just the subset that already overlapped with this
    user's existing interests (the set that made the campaign eligible in
    the first place - see filter_eligible_campaigns/matches_targeting in
    app/services/auction.py). A click can be evidence of a genuinely NEW
    interest, not just reinforcement of an already-known one - that's the
    actual point of preference *learning*, not just preference
    confirmation. See STUDY_NOTES.md §21 for the full design discussion,
    including why there's no equivalent explicit "down" signal from an
    impression that was shown but never clicked.
    """
    # impressions are still written synchronously by record_win (§20.11) -
    # by the time a click event for this impression_id can even exist,
    # the impression endpoint has already confirmed this row exists
    # (app/api/routes/impressions.py's 404 check). .one() trusts that
    # invariant rather than defensively handling "zero rows" here.
    impression = db.execute(
        text("SELECT user_id, campaign_id FROM impressions WHERE id = :id"),
        {"id": impression_id},
    ).one()

    matched_interest_ids = [
        row[0]
        for row in db.execute(
            text(
                "SELECT ti.interest_id FROM audience_targeting a "
                "JOIN targeting_interests ti ON ti.targeting_id = a.id "
                "WHERE a.campaign_id = :campaign_id"
            ),
            {"campaign_id": impression.campaign_id},
        ).all()
    ]
    if not matched_interest_ids:
        # Untargeted campaign, or targeted with no specific interests -
        # nothing to credit this click to, so nothing to nudge either way.
        return

    for interest_id in matched_interest_ids:
        # INSERT ... ON CONFLICT DO UPDATE (Postgres's upsert): one atomic,
        # database-side statement instead of "SELECT to check if a row
        # exists, then INSERT or UPDATE in Python" - the same read-modify-
        # write race that §19's Finding 3 fixed for campaign.spent, avoided
        # here by construction rather than fixed after the fact. Two
        # concurrent clicks nudging the same brand-new (user, interest)
        # pair can't both "win" an INSERT and silently drop the other's
        # increment - Postgres serializes them on the row itself.
        stmt = (
            pg_insert(user_interests)
            .values(user_id=impression.user_id, interest_id=interest_id, weight=INTEREST_NUDGE_INCREMENT)
            .on_conflict_do_update(
                index_elements=["user_id", "interest_id"],
                set_={"weight": user_interests.c.weight + INTEREST_NUDGE_INCREMENT},
            )
        )
        db.execute(stmt)

    db.execute(
        update(user_interests)
        .where(user_interests.c.user_id == impression.user_id)
        .where(user_interests.c.interest_id.not_in(matched_interest_ids))
        .values(weight=user_interests.c.weight * INTEREST_DECAY_FACTOR)
    )


def handle_click(db, event: dict) -> None:
    click = Click(
        id=uuid.UUID(event["id"]),
        impression_id=uuid.UUID(event["impression_id"]),
        occurred_at=datetime.fromisoformat(event["occurred_at"]),
        # .get with a default, not event["suspicious"]: events produced
        # before the click-fraud heuristic existed (§27) are still sitting
        # in the topic and are still replayable, and they have no such
        # field. A consumer that assumed every event matches the newest
        # producer's schema would crash on its own history - schema
        # tolerance matters precisely because Kafka keeps old messages.
        suspicious=event.get("suspicious", False),
    )
    db.add(click)
    # Flushed (not committed) before doing anything else: a DUPLICATE
    # click's INSERT fails right here, before any interest-nudging work
    # runs - see process_message's docstring. Everything below only ever
    # executes the first time this exact click is actually processed, so
    # the click write and its resulting nudge share one commit (below) and
    # can never partially apply - both happen, or neither does.
    db.flush()

    nudge_interests_from_click(db, click.impression_id)

    db.commit()


def handle_conversion(db, event: dict) -> None:
    conversion = Conversion(
        id=uuid.UUID(event["id"]),
        click_id=uuid.UUID(event["click_id"]),
        occurred_at=datetime.fromisoformat(event["occurred_at"]),
    )
    db.add(conversion)
    db.commit()


HANDLERS = {"click": handle_click, "conversion": handle_conversion}


def process_message(db, msg) -> None:
    """Write one event to Postgres, tolerating a message this consumer has
    already successfully processed before.

    Kafka only ever promises "at-least-once" delivery to a consumer that
    commits offsets manually after processing (see main(), and
    STUDY_NOTES.md §20): if this process crashes or is killed after
    db.commit() succeeds but before consumer.commit() records that
    success, Kafka will hand the SAME message to this consumer group
    again after restart, because as far as Kafka knows, it was never
    acknowledged.

    That's why every event's id is used as the row's own primary key
    (generated client-side, in the endpoint that published it, not here)
    instead of leaving the database to generate a new one: reprocessing
    the same event twice now means INSERTing a row whose primary key
    already exists, which Postgres reports as an IntegrityError - a safe,
    detectable signal that this exact event was already handled, not a
    reason to treat it as new data. Catching that specific case and
    moving on (rather than crashing, or silently double-inserting) is
    what makes this consumer idempotent.
    """
    event = json.loads(msg.value())
    handler = HANDLERS.get(event.get("event_type"))
    if handler is None:
        print(f"Skipping event with unknown event_type: {event}")
        return

    try:
        handler(db, event)
        print(f"Wrote {event['event_type']} {event['id']}")
    except IntegrityError as e:
        db.rollback()
        if "duplicate key" in str(e.orig).lower():
            print(f"Already processed {event['event_type']} {event['id']} - skipping (at-least-once redelivery)")
        else:
            # Anything else (e.g. a foreign key violation - a conversion
            # naming a click_id that was never actually produced by
            # record_click) is real bad data, not a safe-to-ignore replay.
            # Logged and skipped rather than crashing the whole consumer
            # over one bad message, but worth real alerting in production.
            print(f"Failed to write {event['event_type']} {event['id']}: {e.orig}")


def main() -> None:
    consumer = Consumer({
        "bootstrap.servers": settings.kafka_bootstrap_servers,
        # Every consumer sharing this group.id divides the topic's
        # partitions between them - two processes with the SAME group.id
        # split the work (each partition still goes to only one of them),
        # which is how this scales horizontally later. A DIFFERENT
        # group.id would instead get its own full, independent copy of
        # every message - useful for an entirely separate pipeline (e.g.
        # a future CTR-logging consumer) reading the same topic without
        # interfering with this one.
        "group.id": CONSUMER_GROUP,
        # Only relevant the FIRST time this group.id ever runs (no
        # committed offset exists yet): start from the beginning of the
        # topic instead of only seeing messages produced from now on.
        "auto.offset.reset": "earliest",
        # Commit offsets ourselves, only after a message is actually
        # written to Postgres (see consumer.commit(msg) below) - the
        # mechanism that makes this "at-least-once" instead of
        # "at-most-once". The default (True) would advance the offset as
        # soon as poll() returns the message, BEFORE it's written to the
        # database - a crash in between would lose that event forever.
        "enable.auto.commit": False,
    })
    consumer.subscribe([settings.kafka_events_topic])

    db = SessionLocal()
    print(f"Consuming '{settings.kafka_events_topic}' as group '{CONSUMER_GROUP}'... Ctrl+C to stop.")
    try:
        while True:
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    # Not a real error - just "no more messages on this
                    # partition right now." Expected constantly once the
                    # consumer catches up to the live end of the topic.
                    continue
                print(f"Consumer error: {msg.error()}")
                continue

            process_message(db, msg)
            # Commits the offset for THIS message only after the line
            # above returns - i.e. only after the write is either
            # confirmed durable or confirmed already-done.
            consumer.commit(msg)
    except KeyboardInterrupt:
        print("Shutting down...")
    finally:
        db.close()
        # Leaves the consumer group cleanly, triggering an immediate
        # rebalance instead of making the group wait out this consumer's
        # session timeout before reassigning its partitions.
        consumer.close()


if __name__ == "__main__":
    main()
