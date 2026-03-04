"""Tests for fastmcp_gtm_helpers validation, consent, and status helpers."""
import pytest

from fastmcp_gtm_helpers import (
    _validate_gtm_id,
    _validate_ids,
    _validate_consent_params,
    _build_consent_settings,
    MAX_BATCH_SIZE,
)


# ---------------------------------------------------------------------------
# _validate_gtm_id
# ---------------------------------------------------------------------------

class TestValidateGtmId:
    def test_valid_numeric(self):
        assert _validate_gtm_id("123") is None

    def test_valid_long_numeric(self):
        assert _validate_gtm_id("9876543210") is None

    def test_rejects_alpha(self):
        assert _validate_gtm_id("abc") is not None

    def test_rejects_alphanumeric(self):
        assert _validate_gtm_id("123abc") is not None

    def test_rejects_empty(self):
        assert _validate_gtm_id("") is not None

    def test_rejects_none(self):
        assert _validate_gtm_id(None) is not None

    def test_rejects_spaces(self):
        assert _validate_gtm_id("   ") is not None

    def test_rejects_path_traversal(self):
        assert _validate_gtm_id("../123") is not None

    def test_custom_name_in_message(self):
        error = _validate_gtm_id("bad", "account_id")
        assert "account_id" in error


# ---------------------------------------------------------------------------
# _validate_ids
# ---------------------------------------------------------------------------

class TestValidateIds:
    def test_all_valid(self):
        assert _validate_ids(account_id="123", container_id="456") is None

    def test_first_invalid(self):
        error = _validate_ids(account_id="bad", container_id="456")
        assert "account_id" in error

    def test_second_invalid(self):
        error = _validate_ids(account_id="123", container_id="bad")
        assert "container_id" in error

    def test_empty_dict(self):
        assert _validate_ids() is None

    def test_single_valid(self):
        assert _validate_ids(workspace_id="1") is None


# ---------------------------------------------------------------------------
# _validate_consent_params
# ---------------------------------------------------------------------------

class TestValidateConsentParams:
    def test_valid_not_set(self):
        assert _validate_consent_params("notSet", None) is None

    def test_valid_not_needed(self):
        assert _validate_consent_params("notNeeded", None) is None

    def test_valid_needed_with_types(self):
        assert _validate_consent_params("needed", ["ad_storage"]) is None

    def test_invalid_status(self):
        error = _validate_consent_params("invalid", None)
        assert "Invalid consent_status" in error

    def test_needed_without_types(self):
        error = _validate_consent_params("needed", None)
        assert "consent_types is required" in error

    def test_needed_with_empty_list(self):
        error = _validate_consent_params("needed", [])
        assert "consent_types is required" in error


# ---------------------------------------------------------------------------
# _build_consent_settings
# ---------------------------------------------------------------------------

class TestBuildConsentSettings:
    def test_not_set(self):
        result = _build_consent_settings("notSet", None)
        assert result == {"consentStatus": "notSet"}

    def test_not_needed(self):
        result = _build_consent_settings("notNeeded", None)
        assert result == {"consentStatus": "notNeeded"}

    def test_needed_with_types(self):
        result = _build_consent_settings("needed", ["ad_storage", "analytics_storage"])
        assert result["consentStatus"] == "needed"
        assert result["consentType"]["type"] == "list"
        items = result["consentType"]["list"]
        assert len(items) == 2
        assert items[0] == {"type": "template", "value": "ad_storage"}
        assert items[1] == {"type": "template", "value": "analytics_storage"}

    def test_needed_without_types_no_consent_type_key(self):
        result = _build_consent_settings("needed", None)
        assert "consentType" not in result


# ---------------------------------------------------------------------------
# MAX_BATCH_SIZE
# ---------------------------------------------------------------------------

def test_max_batch_size_is_positive():
    assert MAX_BATCH_SIZE > 0
    assert MAX_BATCH_SIZE == 50
