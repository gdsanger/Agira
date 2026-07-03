"""
GitHub webhook signature verification.

GitHub signs every webhook delivery with HMAC-SHA256 over the raw request
body, keyed with the secret configured for that webhook. Since the Agira
endpoint is publicly reachable and state-changing (it can move an item from
Working to Testing), this signature is the only thing distinguishing a real
GitHub event from a forged one.
"""
import hmac
import hashlib

SIGNATURE_PREFIX = 'sha256='


def verify_signature(secret: str, payload_body: bytes, signature_header: str) -> bool:
    """
    Verify a GitHub webhook's `X-Hub-Signature-256` header.

    Args:
        secret: The webhook secret configured for the repository
        payload_body: The raw (undecoded) request body GitHub signed
        signature_header: Value of the `X-Hub-Signature-256` header

    Returns:
        True if the header is present, well-formed, and matches; False otherwise
    """
    if not secret or not signature_header:
        return False

    if not signature_header.startswith(SIGNATURE_PREFIX):
        return False

    expected = hmac.new(secret.encode('utf-8'), payload_body, hashlib.sha256).hexdigest()
    provided = signature_header[len(SIGNATURE_PREFIX):]

    return hmac.compare_digest(expected, provided)
