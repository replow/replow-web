"""Regression checks for password strength and verified password change."""
import unittest
from unittest.mock import Mock
from app.core.password_policy import valid_new_password
from app.schemas.auth import PasswordChangeRequest
from app.services.account import AccountService, AccountError
from pydantic import ValidationError

class PasswordSecurityTests(unittest.TestCase):
    def test_password_requires_three_of_four_groups(self):
        allowed = ["Abc123", "Abc12!", "ABC12!", "abc12!", "Aa!aaa", "AA11!!", "aa11!!"]
        denied = ["Aa1", "abc123", "ABC123", "abc!!", "123456", "abcdef", "ABCDEF", "A1!"]
        for password in allowed:
            with self.subTest(allowed=password):
                self.assertTrue(valid_new_password(password))
        for password in denied:
            with self.subTest(denied=password):
                self.assertFalse(valid_new_password(password))

    def test_verification_code_is_required(self):
        PasswordChangeRequest(new_password="Abc123", code="123456")
        for code in ["", "12345", "1234567"]:
            with self.subTest(code=code), self.assertRaises(ValidationError):
                PasswordChangeRequest(new_password="Abc123", code=code)

    def test_change_uses_stored_email_not_caller_email(self):
        service = AccountService.__new__(AccountService)
        users = Mock()
        users.get_by_id.return_value = {"uid": 123, "email": "owner@example.org", "status": "active"}
        users.update_password.return_value = True
        service.users = users
        service._verify_code = Mock()
        service.issue_tokens = Mock(return_value={"success": True})
        user = {"uid": 123, "email": "substituted@example.org"}
        service.change_password(user=user, new_password="Abc123", code="123456")
        service._verify_code.assert_called_once_with("owner@example.org", "reset", "123456")
        users.update_password.assert_called_once()

    def test_wrong_code_cannot_modify_password(self):
        service = AccountService.__new__(AccountService)
        users = Mock()
        users.get_by_id.return_value = {"uid": 123, "email": "owner@example.org", "status": "active"}
        service.users = users
        service._verify_code = Mock(side_effect=AccountError("verification_code_invalid", 422))
        with self.assertRaises(AccountError):
            service.change_password(user={"uid": 123}, new_password="Abc123", code="000000")
        users.update_password.assert_not_called()

    def test_weak_password_does_not_consume_code(self):
        service = AccountService.__new__(AccountService)
        service.users = Mock()
        service._verify_code = Mock()
        with self.assertRaises(AccountError):
            service.change_password(user={"uid": 123}, new_password="abc123", code="123456")
        service._verify_code.assert_not_called()

if __name__ == "__main__":
    unittest.main()
