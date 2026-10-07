"""Pure publication-result presentation: an upload acknowledgment is not proof."""


def publication_feedback(result):
    verified = result.get("verification") or {}
    success = (
        result.get("status") == "VERIFIED"
        and verified.get("http_readiness") is True
        and verified.get("publication_identity_matches") is True
        and verified.get("checksum_readback_verified") is True
        and verified.get("expanded_bytes_readback_verified") is True
    )
    if success:
        records = int(result.get("record_count") or 0)
        checksum = str(result.get("checksum") or "")[:12]
        return {
            "outcome": "success",
            "accent": "#10b981",
            "title": "Website Publication Verified",
            "status_text": f"Portal publish: verified | {records:,} records | checksum {checksum}",
            "detail": f"The website checksum and exact snapshot bytes were verified.\n\nRecords: {records:,}\nChecksum: {checksum}\nPublished: {result.get('published_at') or 'Unknown'}",
        }
    if result.get("uploaded") is True or result.get("status") == "uploaded":
        return {
            "outcome": "warning",
            "accent": "#f59e0b",
            "title": "Upload Not Yet Verified",
            "status_text": "Portal publish: upload acknowledged; verification required",
            "detail": "An upload was acknowledged, but hosted checksum and exact-byte verification were not confirmed.\n\nDo not submit another upload. Ask the administrator to review the saved publication evidence.",
        }
    return {
        "outcome": "error",
        "accent": "#ef4444",
        "title": "Portal Publication Blocked",
        "status_text": "Portal publish: blocked; existing website data retained",
        "detail": f"Publication was not verified. Keep the existing evidence; do not repeatedly click Publish.\n\nReason: {result.get('reason_code') or 'PUBLICATION_NOT_VERIFIED'}\nStage: {result.get('network_stage') or 'approval / connectivity check'}\n\nNo billing repair or restore is needed for an upload error.",
    }
