"""Tests for LinkedIn job alert email parsing."""

from app.email_parser import canonicalize_linkedin_job_url, parse_linkedin_alert_email


def test_canonicalize_linkedin_url_strips_tracking():
    raw = "https://www.linkedin.com/comm/jobs/view/4123456789/?trackingId=abc&trk=eml-jobs"
    assert canonicalize_linkedin_job_url(raw) == "https://www.linkedin.com/jobs/view/4123456789/"


def test_parse_html_linkedin_alert_email():
    sample_eml = """From: LinkedIn Job Alerts <jobs-noreply@linkedin.com>
Subject: "high school intern": 2 new jobs
MIME-Version: 1.0
Content-Type: text/html; charset="utf-8"

<html><body>
  <table>
    <tr>
      <td>
        <a href="https://www.linkedin.com/comm/jobs/view/99887766/?trackingId=xyz">High School Robotics Intern</a>
        <div>Civic Robotics Lab</div>
        <div>Chicago, IL (On-site)</div>
        <div>Open to high school juniors and seniors, paid $18/hr.</div>
        <a href="https://www.linkedin.com/comm/jobs/view/99887766/?trackingId=xyz">View job</a>
      </td>
    </tr>
  </table>
</body></html>
"""
    postings = parse_linkedin_alert_email(sample_eml)
    assert len(postings) == 1
    p = postings[0]
    assert p.title == "High School Robotics Intern"
    assert p.company == "Civic Robotics Lab"
    assert "Chicago, IL" in p.location
    assert p.apply_url == "https://www.linkedin.com/jobs/view/99887766/"
    assert p.source_type == "linkedin_email"


def test_parse_plain_text_linkedin_alert():
    raw = """
Summer Museum Teen Intern
City History Museum
Seattle, WA
https://www.linkedin.com/jobs/view/5544332211/?trk=share
"""
    postings = parse_linkedin_alert_email(raw)
    assert len(postings) == 1
    assert postings[0].title == "Summer Museum Teen Intern"
    assert postings[0].company == "City History Museum"
    assert postings[0].location == "Seattle, WA"
    assert postings[0].apply_url == "https://www.linkedin.com/jobs/view/5544332211/"
