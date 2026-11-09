"""Shared display-name rules for the booking page board."""

BOARD_DISPLAY_NAME = "Q Club Player"


def board_display_name(partner, viewer_is_public):
    """Return a display name without exposing contact or account fields."""
    if viewer_is_public:
        return BOARD_DISPLAY_NAME
    name = (partner.name or "").strip()
    if not name or "@" in name or sum(char.isdigit() for char in name) >= 7:
        return BOARD_DISPLAY_NAME
    return name
