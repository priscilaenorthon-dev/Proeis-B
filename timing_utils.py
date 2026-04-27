def format_elapsed(seconds: float) -> str:
    total_seconds = max(0.0, float(seconds))
    whole_minutes, remaining = divmod(total_seconds, 60)
    hours, minutes = divmod(int(whole_minutes), 60)

    if hours:
        return f"{hours:02d}h{minutes:02d}m{remaining:04.1f}s"
    if minutes:
        return f"{minutes:02d}m{remaining:04.1f}s"
    return f"{remaining:.1f}s"
