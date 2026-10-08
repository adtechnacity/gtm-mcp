"""Tests for fastmcp_gtm_helpers validation, consent, and status helpers."""
import pytest

from fastmcp_gtm_helpers import (
    _validate_gtm_id,
    _validate_ids,
    _validate_consent_params,
    _build_consent_settings,
    _upsert_parameters,
    _validate_trigger_filters,
    _filter_tuples_to_conditions,
    _fingerprint_to_iso,
    _summarize_version,
    _diff_entity_dicts,
    _diff_versions,
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
# _validate_trigger_filters
# ---------------------------------------------------------------------------

class TestValidateTriggerFilters:
    def test_empty_list_is_valid(self):
        assert _validate_trigger_filters([]) is None

    def test_valid_single_condition(self):
        cond = [{
            "type": "matchRegex",
            "parameter": [
                {"type": "template", "key": "arg0", "value": "{{Page Path}}"},
                {"type": "template", "key": "arg1", "value": "/create"},
            ],
        }]
        assert _validate_trigger_filters(cond) is None

    def test_rejects_non_list(self):
        assert "must be a list" in _validate_trigger_filters({"type": "equals"})

    def test_rejects_non_dict_item(self):
        assert "must be a dict" in _validate_trigger_filters(["not-a-dict"])

    def test_rejects_missing_type(self):
        assert "type" in _validate_trigger_filters([{"parameter": [{"key": "arg0", "value": "x", "type": "template"}]}])

    def test_rejects_empty_parameter_list(self):
        assert "parameter" in _validate_trigger_filters([{"type": "equals", "parameter": []}])

    def test_rejects_parameter_missing_key(self):
        cond = [{"type": "equals", "parameter": [{"value": "x", "type": "template"}]}]
        assert "key/value/type" in _validate_trigger_filters(cond)


# ---------------------------------------------------------------------------
# _filter_tuples_to_conditions
# ---------------------------------------------------------------------------

class TestFilterTuplesToConditions:
    def test_builds_single_condition(self):
        result = _filter_tuples_to_conditions([
            {"operator": "matchRegex", "lhs": "{{Page Path}}", "rhs": "/create"},
        ])
        assert result == [{
            "type": "matchRegex",
            "parameter": [
                {"type": "template", "key": "arg0", "value": "{{Page Path}}"},
                {"type": "template", "key": "arg1", "value": "/create"},
            ],
        }]

    def test_builds_multiple_conditions(self):
        result = _filter_tuples_to_conditions([
            {"operator": "equals", "lhs": "{{utm_source}}", "rhs": "google"},
            {"operator": "contains", "lhs": "{{Page Path}}", "rhs": "/cart"},
        ])
        assert len(result) == 2
        assert result[0]["type"] == "equals"
        assert result[1]["type"] == "contains"

    def test_rejects_empty_list(self):
        with pytest.raises(ValueError, match="non-empty"):
            _filter_tuples_to_conditions([])

    def test_rejects_non_list(self):
        with pytest.raises(ValueError, match="non-empty"):
            _filter_tuples_to_conditions({"operator": "equals"})

    def test_rejects_missing_operator(self):
        with pytest.raises(ValueError, match="operator"):
            _filter_tuples_to_conditions([{"lhs": "x", "rhs": "y"}])

    def test_rejects_missing_lhs(self):
        with pytest.raises(ValueError, match="lhs"):
            _filter_tuples_to_conditions([{"operator": "equals", "rhs": "y"}])

    def test_rejects_non_string_rhs(self):
        with pytest.raises(ValueError, match="rhs"):
            _filter_tuples_to_conditions([{"operator": "equals", "lhs": "x", "rhs": 123}])

    def test_rejects_empty_string_value(self):
        with pytest.raises(ValueError, match="lhs"):
            _filter_tuples_to_conditions([{"operator": "equals", "lhs": "", "rhs": "y"}])


# ---------------------------------------------------------------------------
# _fingerprint_to_iso
# ---------------------------------------------------------------------------

class TestFingerprintToIso:
    def test_valid_ms_string(self):
        # 1700000000000 ms = 2023-11-14T22:13:20 UTC
        assert _fingerprint_to_iso("1700000000000") == "2023-11-14T22:13:20Z"

    def test_epoch_zero(self):
        assert _fingerprint_to_iso("0") == "1970-01-01T00:00:00Z"

    def test_accepts_int(self):
        assert _fingerprint_to_iso(1700000000000) == "2023-11-14T22:13:20Z"

    def test_strips_whitespace(self):
        assert _fingerprint_to_iso(" 1700000000000 ") == "2023-11-14T22:13:20Z"

    def test_result_is_utc_z_suffixed(self):
        result = _fingerprint_to_iso("1700000000000")
        assert result.endswith("Z")
        assert "+00:00" not in result

    def test_none_returns_none(self):
        assert _fingerprint_to_iso(None) is None

    def test_empty_string_returns_none(self):
        assert _fingerprint_to_iso("") is None

    def test_non_numeric_returns_none(self):
        assert _fingerprint_to_iso("not-a-number") is None

    def test_float_string_returns_none(self):
        assert _fingerprint_to_iso("1700000000000.5") is None

    def test_bool_returns_none(self):
        assert _fingerprint_to_iso(True) is None

    def test_absurdly_large_returns_none(self):
        assert _fingerprint_to_iso("9" * 30) is None


# ---------------------------------------------------------------------------
# _summarize_version
# ---------------------------------------------------------------------------

def _sample_version():
    return {
        "containerVersionId": "42",
        "name": "Release 42",
        "description": "Adds checkout tracking",
        "fingerprint": "1700000000000",
        "tagManagerUrl": "https://tagmanager.google.com/#/versions/42",
        "deleted": False,
        "accountId": "123",
        "containerId": "456",
        "tag": [
            {
                "tagId": "1",
                "name": "GA4 Config",
                "type": "gtagjs",
                "paused": True,
                "firingTriggerId": ["10"],
                "blockingTriggerId": ["11"],
                "consentSettings": {"consentStatus": "needed"},
                "parameter": [{"key": "tagId", "type": "template", "value": "G-X"}],
            },
            {"tagId": "2", "name": "Pixel", "type": "html"},
        ],
        "trigger": [
            {"triggerId": "10", "name": "All Pages", "type": "pageview", "filter": []},
        ],
        "variable": [
            {"variableId": "20", "name": "DLV - item", "type": "v"},
        ],
        "builtInVariable": [
            {"name": "Page Path", "type": "pagePath"},
            {"name": "Click ID", "type": "clickId"},
        ],
    }


class TestSummarizeVersion:
    def test_identity_fields(self):
        summary = _summarize_version(_sample_version())
        assert summary["containerVersionId"] == "42"
        assert summary["name"] == "Release 42"
        assert summary["description"] == "Adds checkout tracking"
        assert summary["fingerprint"] == "1700000000000"
        assert summary["fingerprint_datetime"] == "2023-11-14T22:13:20Z"
        assert summary["tagManagerUrl"] == "https://tagmanager.google.com/#/versions/42"
        assert summary["deleted"] is False

    def test_counts(self):
        summary = _summarize_version(_sample_version())
        assert summary["counts"] == {
            "tags": 2, "triggers": 1, "variables": 1, "builtInVariables": 2,
        }

    def test_tag_entries_slim_shape(self):
        summary = _summarize_version(_sample_version())
        tag = summary["tags"][0]
        assert tag == {
            "tagId": "1",
            "name": "GA4 Config",
            "type": "gtagjs",
            "paused": True,
            "firingTriggerId": ["10"],
            "blockingTriggerId": ["11"],
            "consentSettings": {"consentStatus": "needed"},
        }
        assert "parameter" not in tag

    def test_tag_defaults_when_fields_missing(self):
        summary = _summarize_version(_sample_version())
        tag = summary["tags"][1]
        assert tag["paused"] is False
        assert tag["firingTriggerId"] == []
        assert tag["blockingTriggerId"] == []
        assert tag["consentSettings"] == {}

    def test_trigger_and_variable_entries(self):
        summary = _summarize_version(_sample_version())
        assert summary["triggers"] == [{"triggerId": "10", "name": "All Pages", "type": "pageview"}]
        assert summary["variables"] == [{"variableId": "20", "name": "DLV - item", "type": "v"}]

    def test_built_in_variables_are_names(self):
        summary = _summarize_version(_sample_version())
        assert summary["builtInVariables"] == ["Page Path", "Click ID"]

    def test_empty_version_does_not_crash(self):
        summary = _summarize_version({})
        assert summary["containerVersionId"] is None
        assert summary["fingerprint_datetime"] is None
        assert summary["description"] == ""
        assert summary["deleted"] is False
        assert summary["counts"] == {
            "tags": 0, "triggers": 0, "variables": 0, "builtInVariables": 0,
        }
        assert summary["tags"] == []
        assert summary["triggers"] == []
        assert summary["variables"] == []
        assert summary["builtInVariables"] == []


# ---------------------------------------------------------------------------
# _diff_entity_dicts
# ---------------------------------------------------------------------------

class TestDiffEntityDicts:
    def test_identical_dicts_no_changes(self):
        entity = {"tagId": "1", "name": "GA4", "parameter": [{"key": "a", "type": "template", "value": "x"}]}
        assert _diff_entity_dicts(entity, dict(entity)) == []

    def test_changed_scalar_field(self):
        changes = _diff_entity_dicts({"name": "Old"}, {"name": "New"})
        assert changes == [{"field": "name", "from": "Old", "to": "New"}]

    def test_added_field_reports_from_none(self):
        changes = _diff_entity_dicts({}, {"notes": "hi"})
        assert changes == [{"field": "notes", "from": None, "to": "hi"}]

    def test_removed_field_reports_to_none(self):
        changes = _diff_entity_dicts({"notes": "hi"}, {})
        assert changes == [{"field": "notes", "from": "hi", "to": None}]

    def test_ignored_keys_produce_no_changes(self):
        old = {"fingerprint": "1", "path": "a/b", "tagManagerUrl": "u1",
               "accountId": "1", "containerId": "2", "workspaceId": "3"}
        new = {"fingerprint": "2", "path": "c/d", "tagManagerUrl": "u2",
               "accountId": "9", "containerId": "8", "workspaceId": "7"}
        assert _diff_entity_dicts(old, new) == []

    def test_nested_dict_uses_dotted_path(self):
        old = {"consentSettings": {"consentStatus": "notSet"}}
        new = {"consentSettings": {"consentStatus": "needed"}}
        changes = _diff_entity_dicts(old, new)
        assert changes == [{"field": "consentSettings.consentStatus", "from": "notSet", "to": "needed"}]

    def test_parameter_changed_value_matched_by_key(self):
        old = {"parameter": [{"key": "eventName", "type": "template", "value": "purchase"}]}
        new = {"parameter": [{"key": "eventName", "type": "template", "value": "refund"}]}
        changes = _diff_entity_dicts(old, new)
        assert changes == [{"field": "parameter[eventName].value", "from": "purchase", "to": "refund"}]

    def test_parameter_key_matching_ignores_order(self):
        old = {"parameter": [
            {"key": "a", "type": "template", "value": "1"},
            {"key": "b", "type": "template", "value": "2"},
        ]}
        new = {"parameter": [
            {"key": "b", "type": "template", "value": "2"},
            {"key": "a", "type": "template", "value": "1"},
        ]}
        assert _diff_entity_dicts(old, new) == []

    def test_parameter_added_reports_from_none(self):
        old = {"parameter": [{"key": "a", "type": "template", "value": "1"}]}
        new = {"parameter": [
            {"key": "a", "type": "template", "value": "1"},
            {"key": "b", "type": "template", "value": "2"},
        ]}
        changes = _diff_entity_dicts(old, new)
        assert changes == [{
            "field": "parameter[b]",
            "from": None,
            "to": {"key": "b", "type": "template", "value": "2"},
        }]

    def test_parameter_removed_reports_to_none(self):
        old = {"parameter": [
            {"key": "a", "type": "template", "value": "1"},
            {"key": "b", "type": "template", "value": "2"},
        ]}
        new = {"parameter": [{"key": "a", "type": "template", "value": "1"}]}
        changes = _diff_entity_dicts(old, new)
        assert changes == [{
            "field": "parameter[b]",
            "from": {"key": "b", "type": "template", "value": "2"},
            "to": None,
        }]

    def test_nested_map_entries_matched_by_key(self):
        old = {"parameter": [{
            "key": "eventParameters", "type": "list",
            "list": [{"type": "map", "map": [
                {"key": "name", "type": "template", "value": "item_id"},
                {"key": "value", "type": "template", "value": "sku-1"},
            ]}],
        }]}
        new = {"parameter": [{
            "key": "eventParameters", "type": "list",
            "list": [{"type": "map", "map": [
                {"key": "name", "type": "template", "value": "item_id"},
                {"key": "value", "type": "template", "value": "sku-2"},
            ]}],
        }]}
        changes = _diff_entity_dicts(old, new)
        assert changes == [{
            "field": "parameter[eventParameters].list[0].map[value].value",
            "from": "sku-1",
            "to": "sku-2",
        }]

    def test_unkeyed_list_falls_back_to_index(self):
        old = {"firingTriggerId": ["10", "11"]}
        new = {"firingTriggerId": ["10", "12", "13"]}
        changes = _diff_entity_dicts(old, new)
        assert changes == [
            {"field": "firingTriggerId[1]", "from": "11", "to": "12"},
            {"field": "firingTriggerId[2]", "from": None, "to": "13"},
        ]

    def test_duplicate_keys_fall_back_to_index_and_report_change(self):
        # Key-matching would collapse the duplicates last-wins and report
        # "no change" — duplicate keys must force the indexed fallback.
        old = {"parameter": [
            {"key": "a", "type": "template", "value": "1"},
            {"key": "a", "type": "template", "value": "2"},
        ]}
        new = {"parameter": [{"key": "a", "type": "template", "value": "2"}]}
        changes = _diff_entity_dicts(old, new)
        assert changes == [
            {"field": "parameter[0].value", "from": "1", "to": "2"},
            {"field": "parameter[1]", "from": {"key": "a", "type": "template", "value": "2"}, "to": None},
        ]

    def test_non_string_key_falls_back_to_index_without_raising(self):
        old = {"parameter": [{"key": ["x"], "type": "template", "value": "1"}]}
        new = {"parameter": [{"key": ["x"], "type": "template", "value": "2"}]}
        changes = _diff_entity_dicts(old, new)
        assert changes == [{"field": "parameter[0].value", "from": "1", "to": "2"}]

    def test_long_string_truncated(self):
        old = {"parameter": [{"key": "html", "type": "template", "value": "<div>" + "x" * 500}]}
        new = {"parameter": [{"key": "html", "type": "template", "value": "<span>" + "y" * 500}]}
        changes = _diff_entity_dicts(old, new)
        assert len(changes) == 1
        assert changes[0]["field"] == "parameter[html].value"
        assert changes[0]["from"].endswith("… [truncated]")
        assert changes[0]["to"].endswith("… [truncated]")
        assert len(changes[0]["from"]) == 300 + len("… [truncated]")

    def test_short_string_not_truncated(self):
        changes = _diff_entity_dicts({"name": "a" * 300}, {"name": "b" * 300})
        assert changes[0]["from"] == "a" * 300
        assert changes[0]["to"] == "b" * 300

    def test_truncation_applies_inside_removed_parameter(self):
        huge = "<script>" + "z" * 1000
        old = {"parameter": [{"key": "html", "type": "template", "value": huge}]}
        new = {"parameter": []}
        changes = _diff_entity_dicts(old, new)
        assert changes == [{
            "field": "parameter[html]",
            "from": {"key": "html", "type": "template", "value": huge[:300] + "… [truncated]"},
            "to": None,
        }]

    def test_prefix_is_prepended(self):
        changes = _diff_entity_dicts({"name": "a"}, {"name": "b"}, prefix="tag.")
        assert changes[0]["field"] == "tag.name"


# ---------------------------------------------------------------------------
# _diff_versions
# ---------------------------------------------------------------------------

class TestDiffVersions:
    def test_identical_versions_all_empty(self):
        version = _sample_version()
        diff = _diff_versions(version, _sample_version())
        assert diff["summary"] == {
            "tags": {"added": 0, "removed": 0, "changed": 0},
            "triggers": {"added": 0, "removed": 0, "changed": 0},
            "variables": {"added": 0, "removed": 0, "changed": 0},
            "builtInVariables": {"added": 0, "removed": 0},
        }
        assert diff["tags"] == {"added": [], "removed": [], "changed": []}

    def test_added_tag(self):
        old = {"tag": []}
        new = {"tag": [{"tagId": "5", "name": "New Tag", "type": "html"}]}
        diff = _diff_versions(old, new)
        assert diff["tags"]["added"] == [{"tagId": "5", "name": "New Tag", "type": "html"}]
        assert diff["summary"]["tags"] == {"added": 1, "removed": 0, "changed": 0}

    def test_removed_trigger(self):
        old = {"trigger": [{"triggerId": "7", "name": "Old Trigger", "type": "pageview"}]}
        new = {}
        diff = _diff_versions(old, new)
        assert diff["triggers"]["removed"] == [{"triggerId": "7", "name": "Old Trigger", "type": "pageview"}]
        assert diff["summary"]["triggers"] == {"added": 0, "removed": 1, "changed": 0}

    def test_changed_variable_carries_field_changes(self):
        old = {"variable": [{"variableId": "20", "name": "DLV - item", "type": "v",
                             "parameter": [{"key": "name", "type": "template", "value": "item"}]}]}
        new = {"variable": [{"variableId": "20", "name": "DLV - item", "type": "v",
                             "parameter": [{"key": "name", "type": "template", "value": "item_id"}]}]}
        diff = _diff_versions(old, new)
        assert diff["variables"]["changed"] == [{
            "variableId": "20",
            "name": "DLV - item",
            "type": "v",
            "changes": [{"field": "parameter[name].value", "from": "item", "to": "item_id"}],
        }]
        assert diff["summary"]["variables"] == {"added": 0, "removed": 0, "changed": 1}

    def test_changed_entry_uses_new_name(self):
        old = {"tag": [{"tagId": "1", "name": "Old Name", "type": "html"}]}
        new = {"tag": [{"tagId": "1", "name": "New Name", "type": "html"}]}
        diff = _diff_versions(old, new)
        assert diff["tags"]["changed"][0]["name"] == "New Name"

    def test_entities_matched_by_id_not_position(self):
        old = {"tag": [
            {"tagId": "1", "name": "A", "type": "html"},
            {"tagId": "2", "name": "B", "type": "html"},
        ]}
        new = {"tag": [
            {"tagId": "2", "name": "B", "type": "html"},
            {"tagId": "1", "name": "A", "type": "html"},
        ]}
        diff = _diff_versions(old, new)
        assert diff["summary"]["tags"] == {"added": 0, "removed": 0, "changed": 0}

    def test_ignored_keys_do_not_mark_entity_changed(self):
        old = {"tag": [{"tagId": "1", "name": "A", "type": "html", "fingerprint": "100", "path": "x"}]}
        new = {"tag": [{"tagId": "1", "name": "A", "type": "html", "fingerprint": "200", "path": "y"}]}
        diff = _diff_versions(old, new)
        assert diff["tags"]["changed"] == []

    def test_built_in_variables_by_name(self):
        old = {"builtInVariable": [{"name": "Page Path"}, {"name": "Click ID"}]}
        new = {"builtInVariable": [{"name": "Page Path"}, {"name": "Event"}]}
        diff = _diff_versions(old, new)
        assert diff["builtInVariables"] == {"added": ["Event"], "removed": ["Click ID"]}
        assert diff["summary"]["builtInVariables"] == {"added": 1, "removed": 1}

    def test_changes_capped_with_truncation_marker(self):
        old = {"tag": [{"tagId": "1", "name": "A", "type": "html",
                        **{f"field{i:02d}": "old" for i in range(45)}}]}
        new = {"tag": [{"tagId": "1", "name": "A", "type": "html",
                        **{f"field{i:02d}": "new" for i in range(45)}}]}
        diff = _diff_versions(old, new)
        changes = diff["tags"]["changed"][0]["changes"]
        assert len(changes) == 41
        assert changes[-1] == {"field": "_truncated", "from": None, "to": "5 more changes omitted"}
        assert all(c["field"] != "_truncated" for c in changes[:40])

    def test_exactly_at_cap_not_truncated(self):
        old = {"tag": [{"tagId": "1", "name": "A", "type": "html",
                        **{f"field{i:02d}": "old" for i in range(40)}}]}
        new = {"tag": [{"tagId": "1", "name": "A", "type": "html",
                        **{f"field{i:02d}": "new" for i in range(40)}}]}
        diff = _diff_versions(old, new)
        changes = diff["tags"]["changed"][0]["changes"]
        assert len(changes) == 40
        assert all(c["field"] != "_truncated" for c in changes)

    def test_empty_versions_do_not_crash(self):
        diff = _diff_versions({}, {})
        assert diff["summary"]["tags"] == {"added": 0, "removed": 0, "changed": 0}
        assert diff["builtInVariables"] == {"added": [], "removed": []}

    def test_results_sorted_numerically_by_id(self):
        old = {"tag": []}
        new = {"tag": [
            {"tagId": "10", "name": "Ten", "type": "html"},
            {"tagId": "2", "name": "Two", "type": "html"},
        ]}
        diff = _diff_versions(old, new)
        assert [t["tagId"] for t in diff["tags"]["added"]] == ["2", "10"]

    def test_live_has_no_special_meaning(self):
        # The pure helpers treat "live" as just another string — only the
        # server tools resolve it to versions.live.
        old = {"containerVersionId": "live", "tag": [{"tagId": "live", "name": "A", "type": "html"}]}
        new = {"containerVersionId": "live", "tag": [{"tagId": "live", "name": "B", "type": "html"}]}
        diff = _diff_versions(old, new)
        assert diff["tags"]["changed"][0]["tagId"] == "live"
        assert diff["tags"]["changed"][0]["changes"] == [{"field": "name", "from": "A", "to": "B"}]
        summary = _summarize_version(old)
        assert summary["containerVersionId"] == "live"
        assert summary["fingerprint_datetime"] is None


# ---------------------------------------------------------------------------
# MAX_BATCH_SIZE
# ---------------------------------------------------------------------------

def test_max_batch_size_is_positive():
    assert MAX_BATCH_SIZE > 0
    assert MAX_BATCH_SIZE == 50
