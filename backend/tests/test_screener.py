"""Unit tests for the High School Internship Screener rules."""

from app.screener import screen_posting


def test_explicit_high_school_internship_is_eligible():
    res = screen_posting(
        title="Summer High School Software Engineering Intern",
        description=(
            "<p>Join our engineering outreach team for 8 weeks.</p>"
            "<ul><li>Open to current high school juniors and seniors (grades 11-12), ages 16+.</li>"
            "<li>Paid $22/hr, hybrid in Austin, TX.</li></ul>"
        ),
        location="Austin, TX",
    )
    assert res.eligibility_status == "eligible"
    assert res.eligibility_score >= 50
    assert res.compensation == "paid"
    assert res.work_mode == "hybrid"
    assert "grades 11-12" in res.grade_or_age.lower() or "16+" in res.grade_or_age
    assert "high school" in res.evidence_quote.lower()


def test_accepts_high_school_and_undergrad_together():
    res = screen_posting(
        title="STEM Research Intern",
        description=(
            "This paid internship is open to high school students and undergraduate students "
            "interested in robotics. Stipend of $1,500 provided."
        ),
        location="Boston, MA",
    )
    assert res.eligibility_status == "eligible"
    assert res.compensation == "stipend"


def test_rejects_internal_and_international_word_false_positives():
    res1 = screen_posting(
        title="International Operations Manager",
        description="Manage global logistics with 5+ years of experience.",
        location="New York, NY",
    )
    res2 = screen_posting(
        title="Engineering Manager, Internal Tools",
        description="Lead a team of backend engineers.",
        location="San Francisco, CA",
    )
    assert res1.eligibility_status == "rejected"
    assert res2.eligibility_status == "rejected"


def test_rejects_high_school_diploma_adult_job_trap():
    res = screen_posting(
        title="Warehouse Associate",
        description="Full-time role. High school diploma or GED required. 2+ years experience preferred.",
        location="Dallas, TX",
    )
    assert res.eligibility_status == "rejected"
    assert "not an internship" in res.rejection_reason.lower() or "diploma" in res.rejection_reason.lower()


def test_rejects_college_only_and_phd_internships():
    college_res = screen_posting(
        title="Software Engineer Intern (Summer 2027)",
        description="Must be currently enrolled in a Bachelor's or Master's degree in Computer Science.",
        location="Seattle, WA",
    )
    phd_res = screen_posting(
        title="PhD Intern, Machine Learning",
        description="Work on cutting-edge research models.",
        location="San Francisco, CA",
    )
    assert college_res.eligibility_status == "rejected"
    assert "college" in college_res.rejection_reason.lower() or "degree" in college_res.rejection_reason.lower()
    assert phd_res.eligibility_status == "rejected"


def test_rejects_pursuing_degree_and_graduating_with_degree_wording():
    res1 = screen_posting(
        title="Software Engineer Intern (2027)",
        description="<ul><li>Currently pursuing a degree in Computer Science.</li></ul>",
    )
    res2 = screen_posting(
        title="Data Science Intern",
        description="You will graduate in fall 2027 or spring 2028 with a Master's or PhD degree.",
    )
    res3 = screen_posting(
        title="Year at Company - Intern",
        description="Open to freshmen and sophomores, as well as juniors and seniors in college.",
    )
    assert res1.eligibility_status == "rejected"
    assert res2.eligibility_status == "rejected"
    assert res3.eligibility_status == "rejected"


def test_possible_when_internship_has_no_degree_restriction():
    res = screen_posting(
        title="Community Media Summer Intern",
        description="Help produce local video stories and manage social calendars. Remote friendly. Unpaid academic credit.",
        location="Remote",
    )
    assert res.eligibility_status == "possible"
    assert res.work_mode == "remote"
    assert res.compensation == "unpaid"


def test_directory_explainer_internship_passes_and_tuition_bootcamp_rejects():
    nybg = screen_posting(
        title="High School Explainer Program",
        description="The High School Explainer Program is a tiered internship for high school students.",
        location="New York",
        source_type="standoutsearch",
    )
    assert nybg.eligibility_status == "eligible"

    bootcamp = screen_posting(
        title="AI Scholars Live Online",
        description="Online AI program for high school students in grades 9 to 12. It is a 10-session bootcamp.",
        location="Remote",
        source_type="standoutsearch",
    )
    assert bootcamp.eligibility_status == "rejected"
    assert "tuition" in bootcamp.rejection_reason.lower() or "bootcamp" in bootcamp.rejection_reason.lower()
