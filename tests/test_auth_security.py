import sys
import os

# Add project root to path for testing
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backend.services.auth_service as auth

def test_password_hashing_security():
    """Verifies that passwords are hashed securely and not stored in plaintext."""
    password = "GovernmentGradeSecurity2026!"
    hashed = auth.hash_password(password)

    # 1. Ensure it's not plaintext
    assert hashed != password, "FAIL: Password stored in plaintext!"

    # 2. Ensure it uses bcrypt (passlib format: $2b$<rounds>$...)
    assert hashed.startswith("$2b$"), "FAIL: Incorrect hashing scheme — expected bcrypt ($2b$)!"

    # 3. Ensure verification works
    assert auth.verify_password(password, hashed), "FAIL: Verification failed for valid password!"

    # 4. Ensure salt works (different hashes for same password)
    hashed_2 = auth.hash_password(password)
    assert hashed != hashed_2, "FAIL: Salt is not being used (hashes are identical)!"

    print("✅ Password Hashing Security: PASSED (bcrypt + Unique Salts)")


def test_legacy_pbkdf2_verification():
    """Verifies that legacy PBKDF2-SHA256 hashes are still verifiable (migration path)."""
    import hashlib, base64, secrets as _secrets

    password = "LegacyPassword123!"
    salt = _secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200000)
    legacy_hash = (
        f"pbkdf2_sha256$200000$"
        f"{base64.b64encode(salt).decode()}$"
        f"{base64.b64encode(digest).decode()}"
    )

    assert auth.verify_password(password, legacy_hash), \
        "FAIL: Legacy PBKDF2 hash verification failed — existing accounts would be locked out!"
    assert not auth.verify_password("WrongPassword!", legacy_hash), \
        "FAIL: Legacy PBKDF2 accepted wrong password!"

    print("✅ Legacy PBKDF2 Verification: PASSED (migration path intact)")

def test_rbac_logic():
    """Verifies that Role-Based Access Control is functioning."""
    admin_user = {"username": "admin_test", "role": "admin"}
    cashier_user = {"username": "cashier_test", "role": "cashier"}
    
    # Admin should have full access
    assert auth.has_permission(admin_user, "backup_restore"), "FAIL: Admin missing permissions!"
    assert auth.has_permission(admin_user, "manage_users"), "FAIL: Admin missing permissions!"
    
    # Cashier should be restricted
    assert not auth.has_permission(cashier_user, "manage_users"), "FAIL: Cashier has unauthorized access!"
    assert auth.has_permission(cashier_user, "receipt_generate"), "FAIL: Cashier missing vital permissions!"
    
    print("✅ RBAC Permission Logic: PASSED")

if __name__ == "__main__":
    print("🏛️ MTO ENTERPRISE SECURITY TEST SUITE")
    print("-" * 40)
    try:
        test_password_hashing_security()
        test_legacy_pbkdf2_verification()
        test_rbac_logic()
        print("-" * 40)
        print("🏆 ALL SECURITY TESTS PASSED: SYSTEM IS HARDENED")
    except AssertionError as e:
        print(f"❌ SECURITY TEST FAILED: {str(e)}")
        sys.exit(1)
