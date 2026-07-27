from src.affiliates.validation import is_placeholder, mask_secret

from .models import PilotConfigurationStatus


def validate_pilot_config(config, pipeline_threshold=90):
    reasons = []
    if not config.enabled:
        state = "DISABLED"
    elif not config.group_id:
        state = "CONFIGURATION_REQUIRED"
        reasons.append("PILOT_GROUP_ID_MISSING")
    else:
        state = "READY"
    if config.group_id and is_placeholder(config.group_id):
        reasons.append("PILOT_GROUP_ID_INVALID")
    if not config.require_manual_confirmation:
        reasons.append("MANUAL_CONFIRMATION_REQUIRED")
    if config.max_messages < 1:
        reasons.append("INVALID_MESSAGE_LIMIT")
    if config.minimum_score < pipeline_threshold:
        reasons.append("PILOT_SCORE_BELOW_PIPELINE_THRESHOLD")
    if not config.allowed_stores:
        reasons.append("ALLOWED_STORES_MISSING")
    valid = state == "READY" and not reasons
    if config.enabled and reasons:
        state = "CONFIGURATION_REQUIRED"
    return PilotConfigurationStatus(
        state=state,
        valid=valid,
        reasons=tuple(reasons),
        masked_group=mask_secret(config.group_id),
        details={
            "enabled": config.enabled,
            "group_configured": bool(config.group_id),
            "manual_confirmation": config.require_manual_confirmation,
            "max_messages": config.max_messages,
            "allowed_stores": list(config.allowed_stores),
            "minimum_score": config.minimum_score,
            "cooldown_minutes": config.cooldown_minutes,
            "auto_stop_on_error": config.auto_stop_on_error,
        },
    )
