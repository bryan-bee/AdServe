from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness check.

    Returns:
        `{"status": "ok"}` if the app is up and able to respond to requests.
    """
    return {"status": "ok"}
