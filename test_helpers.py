"""Tests for fastmcp_gtm_helpers validation, consent, and status helpers."""
import pytest

from fastmcp_gtm_helpers import (
    _validate_gtm_id,
    _validate_ids,
    _validate_consent_params,
    _build_consent_settings,
    _upsert_parameters,
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
# _upsert_parameters
# ---------------------------------------------------------------------------

class TestUpsertParameters:
    def test_appends_when_key_absent(self):
        existing = [{"key": "eventName", "type": "template", "value": "purchase"}]
        updates = [{"key": "measurementIdOverride", "type": "template", "value": "G-ABC"}]
        result = _upsert_parameters(existing, updates)
        assert len(result) == 2
        assert result[0] == existing[0]
        assert result[1] == updates[0]

    def test_replaces_when_key_present(self):
        existing = [{"key": "eventName", "type": "template", "value": "purchase"}]
        updates = [{"key": "eventName", "type": "template", "value": "refund"}]
        result = _upsert_parameters(existing, updates)
        assert result == [{"key": "eventName", "type": "template", "value": "refund"}]

    def test_mixed_replace_and_append_preserves_order(self):
        existing = [
            {"key": "eventName", "type": "template", "value": "purchase"},
            {"key": "sendEcommerceData", "type": "boolean", "value": "false"},
        ]
        updates = [
            {"key": "sendEcommerceData", "type": "boolean", "value": "true"},
            {"key": "measurementIdOverride", "type": "template", "value": "G-NEW"},
        ]
        result = _upsert_parameters(existing, updates)
        assert [p["key"] for p in result] == ["eventName", "sendEcommerceData", "measurementIdOverride"]
        assert result[1]["value"] == "true"

    def test_handles_empty_existing(self):
        updates = [{"key": "eventName", "type": "template", "value": "purchase"}]
        assert _upsert_parameters([], updates) == updates
        assert _upsert_parameters(None, updates) == updates

    def test_does_not_mutate_inputs(self):
        existing = [{"key": "eventName", "type": "template", "value": "purchase"}]
        updates = [{"key": "eventName", "type": "template", "value": "refund"}]
        existing_copy = [dict(p) for p in existing]
        updates_copy = [dict(p) for p in updates]
        _upsert_parameters(existing, updates)
        assert existing == existing_copy
        assert updates == updates_copy

    def test_result_does_not_alias_updates(self):
        nested_update = {
            "key": "eventParameters",
            "type": "list",
            "list": [{"type": "map", "map": [
                {"key": "name", "type": "template", "value": "item_id"},
            ]}],
        }
        result = _upsert_parameters([], [nested_update])
        result[0]["list"][0]["map"][0]["value"] = "MUTATED"
        assert nested_update["list"][0]["map"][0]["value"] == "item_id"

    def test_supports_list_typed_parameter(self):
        event_params = {
            "key": "eventParameters",
            "type": "list",
            "list": [
                {"type": "map", "map": [
                    {"key": "name", "type": "template", "value": "item_id"},
                    {"key": "value", "type": "template", "value": "sku-1"},
                ]},
            ],
        }
        result = _upsert_parameters([], [event_params])
        assert result == [event_params]

    def test_rejects_non_list_updates(self):
        with pytest.raises(ValueError, match="must be a list"):
            _upsert_parameters([], {"key": "x", "type": "template"})

    def test_rejects_non_dict_update(self):
        with pytest.raises(ValueError, match="must be a dict"):
            _upsert_parameters([], ["not a dict"])

    def test_rejects_missing_key(self):
        with pytest.raises(ValueError, match="non-empty string 'key'"):
            _upsert_parameters([], [{"type": "template", "value": "x"}])

    def test_rejects_empty_key(self):
        with pytest.raises(ValueError, match="non-empty string 'key'"):
            _upsert_parameters([], [{"key": "", "type": "template"}])

    def test_rejects_non_string_key(self):
        with pytest.raises(ValueError, match="non-empty string 'key'"):
            _upsert_parameters([], [{"key": 123, "type": "template"}])

    def test_rejects_missing_type(self):
        with pytest.raises(ValueError, match="missing 'type'"):
            _upsert_parameters([], [{"key": "eventName", "value": "x"}])

    def test_rejects_duplicate_keys_in_updates(self):
        with pytest.raises(ValueError, match="Duplicate key 'eventName'"):
            _upsert_parameters([], [
                {"key": "eventName", "type": "template", "value": "a"},
                {"key": "eventName", "type": "template", "value": "b"},
            ])


# ---------------------------------------------------------------------------
# MAX_BATCH_SIZE
# ---------------------------------------------------------------------------

def test_max_batch_size_is_positive():
    assert MAX_BATCH_SIZE > 0
    assert MAX_BATCH_SIZE == 50
