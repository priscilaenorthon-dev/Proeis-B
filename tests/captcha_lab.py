from __future__ import annotations

from dataclasses import dataclass

from proeis_http import is_valid_captcha_answer, normalize_captcha_answer


@dataclass(frozen=True)
class CaptchaAttempt:
    answer: str
    ready_after_seconds: float


@dataclass(frozen=True)
class CaptchaPlanResult:
    answer: str
    elapsed_seconds: float
    submitted: int
    solved: bool
    refreshes: int = 0


def first_valid_answer(answers: list[str]) -> str:
    for answer in answers:
        if is_valid_captcha_answer(answer):
            return normalize_captcha_answer(answer)
    return ""


def sequential_plan(attempts: list[CaptchaAttempt], max_submissions: int) -> CaptchaPlanResult:
    elapsed = 0.0
    submitted = 0
    for attempt in attempts[:max_submissions]:
        submitted += 1
        elapsed += attempt.ready_after_seconds
        if is_valid_captcha_answer(attempt.answer):
            return CaptchaPlanResult(normalize_captcha_answer(attempt.answer), elapsed, submitted, True)
    return CaptchaPlanResult("", elapsed, submitted, False)


def parallel_batch_plan(attempts: list[CaptchaAttempt], batch_size: int, max_submissions: int) -> CaptchaPlanResult:
    if batch_size < 1:
        raise ValueError("batch_size deve ser 1 ou maior")

    elapsed = 0.0
    submitted = 0
    cursor = 0

    while submitted < max_submissions and cursor < len(attempts):
        batch = attempts[cursor : cursor + min(batch_size, max_submissions - submitted)]
        cursor += len(batch)
        submitted += len(batch)

        valid = [attempt for attempt in batch if is_valid_captcha_answer(attempt.answer)]
        if valid:
            winner = min(valid, key=lambda attempt: attempt.ready_after_seconds)
            elapsed += winner.ready_after_seconds
            return CaptchaPlanResult(normalize_captcha_answer(winner.answer), elapsed, submitted, True)

        elapsed += max((attempt.ready_after_seconds for attempt in batch), default=0.0)

    return CaptchaPlanResult("", elapsed, submitted, False)


def refresh_after_invalids_plan(
    attempts: list[CaptchaAttempt],
    max_submissions: int,
    invalids_before_refresh: int = 2,
    refresh_cost_seconds: float = 1.0,
) -> CaptchaPlanResult:
    if invalids_before_refresh < 1:
        raise ValueError("invalids_before_refresh deve ser 1 ou maior")

    elapsed = 0.0
    submitted = 0
    invalid_streak = 0
    refreshes = 0

    for attempt in attempts[:max_submissions]:
        submitted += 1
        elapsed += attempt.ready_after_seconds
        if is_valid_captcha_answer(attempt.answer):
            return CaptchaPlanResult(normalize_captcha_answer(attempt.answer), elapsed, submitted, True, refreshes)

        invalid_streak += 1
        if invalid_streak >= invalids_before_refresh and submitted < max_submissions:
            elapsed += refresh_cost_seconds
            refreshes += 1
            invalid_streak = 0

    return CaptchaPlanResult("", elapsed, submitted, False, refreshes)
