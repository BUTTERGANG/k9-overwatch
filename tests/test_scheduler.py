from datetime import timedelta

from k9overwatch.scheduler.runner import ScraperScheduler


def test_scraper_intervals_and_startup_stagger_match_documented_cadence():
    scheduler = ScraperScheduler().build()
    jobs = {job.id: job for job in scheduler.get_jobs()}
    matching_start = jobs["matching_pass"].next_run_time

    expected = {
        "indy_lost_pet_alert": (15, 0),
        "petconnect24": (30, 1),
        "pawboost": (35, 4),
        "petfbi": (40, 7),
        "lostmydoggie": (45, 10),
    }
    for job_id, (minutes, offset) in expected.items():
        job = jobs[job_id]
        assert job.trigger.interval == timedelta(minutes=minutes)
        assert job.max_instances == 1
        assert job.coalesce is True
        assert job.next_run_time is not None
        assert (job.next_run_time - matching_start).total_seconds() == (offset - 20) * 60

    assert jobs["matching_pass"].trigger.interval == timedelta(minutes=30)
    assert jobs["matching_pass"].max_instances == 1
    assert jobs["matching_pass"].coalesce is True
    if scheduler.running:
        scheduler.shutdown(wait=False)
