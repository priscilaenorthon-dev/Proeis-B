import unittest

from tests.captcha_lab import (
    CaptchaAttempt,
    first_valid_answer,
    parallel_batch_plan,
    refresh_after_invalids_plan,
    sequential_plan,
)


class CaptchaLabTests(unittest.TestCase):
    def test_first_valid_answer_rejects_short_2captcha_answers(self):
        self.assertEqual(first_valid_answer(["B", "8", "9C277", "7212FD"]), "7212FD")

    def test_parallel_batch_can_be_faster_than_sequential_invalid_retries(self):
        attempts = [
            CaptchaAttempt("B", 20.0),
            CaptchaAttempt("8", 22.0),
            CaptchaAttempt("7212FD", 24.0),
        ]

        sequential = sequential_plan(attempts, max_submissions=3)
        parallel = parallel_batch_plan(attempts, batch_size=3, max_submissions=3)

        self.assertTrue(sequential.solved)
        self.assertTrue(parallel.solved)
        self.assertEqual(sequential.answer, "7212FD")
        self.assertEqual(parallel.answer, "7212FD")
        self.assertLess(parallel.elapsed_seconds, sequential.elapsed_seconds)

    def test_parallel_batch_spends_more_submissions_for_speed(self):
        attempts = [
            CaptchaAttempt("B", 20.0),
            CaptchaAttempt("7212FD", 24.0),
        ]

        sequential = sequential_plan(attempts, max_submissions=2)
        parallel = parallel_batch_plan(attempts, batch_size=2, max_submissions=2)

        self.assertEqual(sequential.submitted, 2)
        self.assertEqual(parallel.submitted, 2)
        self.assertLess(parallel.elapsed_seconds, sequential.elapsed_seconds)

    def test_unsolved_when_all_answers_are_invalid(self):
        attempts = [
            CaptchaAttempt("B", 20.0),
            CaptchaAttempt("8", 22.0),
            CaptchaAttempt("9C277", 24.0),
        ]

        result = parallel_batch_plan(attempts, batch_size=2, max_submissions=3)

        self.assertFalse(result.solved)
        self.assertEqual(result.answer, "")

    def test_refresh_after_two_invalids_tracks_new_captcha_generation(self):
        attempts = [
            CaptchaAttempt("B", 20.0),
            CaptchaAttempt("8", 20.0),
            CaptchaAttempt("7212FD", 20.0),
        ]

        result = refresh_after_invalids_plan(
            attempts,
            max_submissions=3,
            invalids_before_refresh=2,
            refresh_cost_seconds=1.0,
        )

        self.assertTrue(result.solved)
        self.assertEqual(result.answer, "7212FD")
        self.assertEqual(result.refreshes, 1)
        self.assertEqual(result.submitted, 3)


if __name__ == "__main__":
    unittest.main()
