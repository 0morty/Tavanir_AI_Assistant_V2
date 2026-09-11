from typing import Any

SCALAR_CONFIGURATION: dict[str, Any] = {
    # Core UI & Layout Settings
    "show_sidebar": True,
    "hide_client_button": False,
    "hide_test_request_button": False,
    "hide_models": False,
    "hide_search": False,
    "hide_dark_mode_toggle": False,
    "with_default_fonts": True,
    "show_developer_tools": "localhost",
    # API Behavior Settings
    "default_open_all_tags": True,
    "expand_all_model_sections": False,
    "expand_all_responses": False,
    "order_required_properties_first": True,
    "persist_auth": False,
    # Privacy & Telemetry
    "telemetry": False,
    "integration": "fastapi",
    # UI Overrides
    "overrides": {
        "showToolbar": "localhost",
        "operationTitleSource": "summary",
        "isEditable": False,
        "isLoading": False,
        "showOperationId": False,
        "orderSchemaPropertiesBy": "alpha",
        "default": False,
        "slug": "api-1",
    },
}
