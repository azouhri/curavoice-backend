"""
Unit tests for Retell webhook signature verification.

Tests the HMAC-SHA256 signature verification used to secure webhooks.
"""

import pytest
import time
import hmac
import hashlib
from app.routers.retell import verify_retell_signature


class TestRetellSignatureVerification:
    """Test suite for Retell signature verification"""
    
    def test_valid_signature(self):
        """Test that a valid signature passes verification"""
        api_key = "test_api_key_12345"
        body = b'{"call_id": "12345", "from_number": "+1234567890"}'
        timestamp = int(time.time())
        
        # Generate valid signature
        signed_payload = f"{timestamp}.{body.decode('utf-8')}"
        signature = hmac.new(
            api_key.encode('utf-8'),
            signed_payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        retell_signature = f"t={timestamp},v={signature}"
        
        result = verify_retell_signature(body, retell_signature, api_key)
        assert result is True
    
    def test_invalid_signature(self):
        """Test that an invalid signature fails verification"""
        api_key = "test_api_key_12345"
        body = b'{"call_id": "12345", "from_number": "+1234567890"}'
        timestamp = int(time.time())
        
        # Use wrong signature
        retell_signature = f"t={timestamp},v=invalid_signature_hash"
        
        result = verify_retell_signature(body, retell_signature, api_key)
        assert result is False
    
    def test_expired_timestamp(self):
        """Test that an expired timestamp fails verification"""
        api_key = "test_api_key_12345"
        body = b'{"call_id": "12345", "from_number": "+1234567890"}'
        timestamp = int(time.time()) - 400  # 400 seconds ago (> 5 min threshold)
        
        # Generate valid signature but with old timestamp
        signed_payload = f"{timestamp}.{body.decode('utf-8')}"
        signature = hmac.new(
            api_key.encode('utf-8'),
            signed_payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        retell_signature = f"t={timestamp},v={signature}"
        
        result = verify_retell_signature(body, retell_signature, api_key)
        assert result is False
    
    def test_missing_signature(self):
        """Test that missing signature fails verification"""
        api_key = "test_api_key_12345"
        body = b'{"call_id": "12345"}'
        
        result = verify_retell_signature(body, "", api_key)
        assert result is False
        
        result = verify_retell_signature(body, None, api_key)
        assert result is False
    
    def test_missing_api_key(self):
        """Test that missing API key fails verification"""
        body = b'{"call_id": "12345"}'
        timestamp = int(time.time())
        retell_signature = f"t={timestamp},v=some_signature"
        
        result = verify_retell_signature(body, retell_signature, "")
        assert result is False
        
        result = verify_retell_signature(body, retell_signature, None)
        assert result is False
    
    def test_malformed_signature_format(self):
        """Test that malformed signature format fails verification"""
        api_key = "test_api_key_12345"
        body = b'{"call_id": "12345"}'
        
        # Missing v= part
        result = verify_retell_signature(body, f"t={int(time.time())}", api_key)
        assert result is False
        
        # Wrong format
        result = verify_retell_signature(body, "invalid_format", api_key)
        assert result is False
        
        # Missing timestamp
        result = verify_retell_signature(body, "v=signature", api_key)
        assert result is False
    
    def test_tampered_body(self):
        """Test that a tampered body fails verification"""
        api_key = "test_api_key_12345"
        original_body = b'{"call_id": "12345", "from_number": "+1234567890"}'
        timestamp = int(time.time())
        
        # Generate signature for original body
        signed_payload = f"{timestamp}.{original_body.decode('utf-8')}"
        signature = hmac.new(
            api_key.encode('utf-8'),
            signed_payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        retell_signature = f"t={timestamp},v={signature}"
        
        # Try to verify with tampered body
        tampered_body = b'{"call_id": "99999", "from_number": "+1234567890"}'
        result = verify_retell_signature(tampered_body, retell_signature, api_key)
        assert result is False
    
    def test_replay_attack_prevention(self):
        """Test that old signatures are rejected (replay attack prevention)"""
        api_key = "test_api_key_12345"
        body = b'{"call_id": "12345"}'
        
        # Signature from 10 minutes ago
        old_timestamp = int(time.time()) - 600
        signed_payload = f"{old_timestamp}.{body.decode('utf-8')}"
        signature = hmac.new(
            api_key.encode('utf-8'),
            signed_payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        retell_signature = f"t={old_timestamp},v={signature}"
        
        result = verify_retell_signature(body, retell_signature, api_key)
        assert result is False
    
    def test_future_timestamp(self):
        """Test that future timestamps are rejected"""
        api_key = "test_api_key_12345"
        body = b'{"call_id": "12345"}'
        
        # Timestamp from future (10 minutes ahead)
        future_timestamp = int(time.time()) + 600
        signed_payload = f"{future_timestamp}.{body.decode('utf-8')}"
        signature = hmac.new(
            api_key.encode('utf-8'),
            signed_payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        retell_signature = f"t={future_timestamp},v={signature}"
        
        result = verify_retell_signature(body, retell_signature, api_key)
        assert result is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

