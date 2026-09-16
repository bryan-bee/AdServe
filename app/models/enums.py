import enum


class DeviceType(str, enum.Enum):
    """Shared enum used by both User (a device a person uses) and
    AudienceTargeting (a device a campaign targets) - kept in its own
    module so neither model has to import the other to reuse it."""


    DESKTOP = "desktop"
    MOBILE = "mobile"
    TABLET = "tablet"