from hik_video_download.updater import is_newer


def test_equal_versions_are_not_newer() -> None:
    assert is_newer("0.1.0", "0.1.0") is False


def test_patch_higher_is_newer() -> None:
    assert is_newer("0.1.0", "0.1.1") is True


def test_patch_lower_is_not_newer() -> None:
    assert is_newer("0.1.0", "0.0.9") is False


def test_minor_higher_is_newer() -> None:
    assert is_newer("0.1.0", "0.2.0") is True


def test_major_higher_is_newer() -> None:
    assert is_newer("1.9.9", "2.0.0") is True


def test_extra_digits_padded_with_zero() -> None:
    assert is_newer("0.1", "0.1.1") is True
    assert is_newer("0.1.1", "0.1") is False


def test_v_prefix_stripped() -> None:
    assert is_newer("v0.1.0", "v0.1.1") is True


def test_empty_latest_is_not_newer() -> None:
    assert is_newer("0.1.0", "") is False
    assert is_newer("0.1.0", None) is False  # type: ignore[arg-type]


def test_empty_current_treated_as_zero() -> None:
    assert is_newer("", "0.0.1") is True
    assert is_newer("", "0") is False
