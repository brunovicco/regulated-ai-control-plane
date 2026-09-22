"""Package smoke tests."""


def test_package_is_importable() -> None:
    """Ensure the generated package is importable."""
    import regulated_ai  # noqa: F401
