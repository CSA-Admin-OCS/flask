import unittest

from api.github_id_validation import is_student_id_used_as_github_id


class GithubIdValidationTest(unittest.TestCase):
    def test_rejects_exactly_seven_digits(self):
        self.assertTrue(is_student_id_used_as_github_id("1234567"))
        self.assertTrue(is_student_id_used_as_github_id(" 1234567 "))

    def test_allows_other_github_id_values(self):
        allowed_values = ["123456", "12345678", "123456a", "octocat", None]

        for value in allowed_values:
            with self.subTest(value=value):
                self.assertFalse(is_student_id_used_as_github_id(value))


if __name__ == "__main__":
    unittest.main()
