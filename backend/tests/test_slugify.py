"""Unit tests for shared slug/id generation."""

from backend.slugify import slugify, unique_slug


def test_slugify_lowercases_and_hyphenates():
    assert slugify("The Futurist", fallback="item") == "the-futurist"


def test_slugify_strips_punctuation():
    assert slugify("O'Brien!", fallback="item") == "o-brien"


def test_slugify_blank_name_uses_fallback():
    assert slugify("   ", fallback="item") == "item"


def test_unique_slug_returns_base_slug_when_no_collision():
    assert unique_slug("Sarah", [], fallback="item") == "sarah"


def test_unique_slug_suffixes_on_collision():
    assert unique_slug("Sarah", ["sarah"], fallback="item") == "sarah-2"


def test_unique_slug_keeps_incrementing_past_multiple_collisions():
    assert unique_slug("Sarah", ["sarah", "sarah-2", "sarah-3"], fallback="item") == "sarah-4"


def test_unique_slug_blank_name_uses_fallback_then_suffixes():
    assert unique_slug("", [], fallback="item") == "item"
    assert unique_slug("", ["item"], fallback="item") == "item-2"
