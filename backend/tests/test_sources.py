"""Tests for RSS/Google Alerts and public ATS source adapters."""

import httpx

from app.sources.ats import fetch_ashby, fetch_greenhouse, fetch_lever
from app.sources.github_markdown import parse_github_markdown_tables
from app.sources.nichable import parse_nichable_cards, parse_nichable_detail
from app.sources.pathwaystoscience import (
    parse_pathwaystoscience_detail,
    parse_pathwaystoscience_list,
)
from app.sources.remotive import fetch_remotive
from app.sources.rss import parse_feed_xml, unwrap_google_alert_url
from app.sources.standoutsearch import parse_standoutsearch_html
from app.sources.studentresearchnyc import parse_srmc_programs_html


def test_unwrap_google_alerts_redirect():
    wrapped = (
        "https://www.google.com/url?rct=j&sa=t&url="
        "https%3A%2F%2Fwww.linkedin.com%2Fjobs%2Fview%2F123456&ct=ga"
    )
    assert unwrap_google_alert_url(wrapped) == "https://www.linkedin.com/jobs/view/123456"


def test_parse_google_alerts_atom_feed():
    atom_xml = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Google Alert - LinkedIn HS Intern</title>
  <entry>
    <title type="html">City Hall &lt;b&gt;High School&lt;/b&gt; Youth Intern - City of Austin | LinkedIn</title>
    <link href="https://www.google.com/url?rct=j&amp;sa=t&amp;url=https%3A%2F%2Fwww.linkedin.com%2Fjobs%2Fview%2F777888&amp;ct=ga"/>
    <published>2026-11-10T12:00:00Z</published>
    <content type="html">Open to &lt;b&gt;high school&lt;/b&gt; students in Austin, TX. Paid $17/hr.</content>
  </entry>
</feed>
"""
    postings = parse_feed_xml(atom_xml, source_name="Austin LinkedIn Alert", area_hint="Austin, TX")
    assert len(postings) == 1
    p = postings[0]
    assert p.apply_url == "https://www.linkedin.com/jobs/view/777888"
    assert p.company == "City of Austin"
    assert "Austin, TX" in p.location
    assert "LinkedIn" in p.source_label


def test_greenhouse_lever_ashby_and_remotive_adapters():
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "boards-api.greenhouse.io" in url:
            return httpx.Response(
                200,
                json={
                    "jobs": [
                        {
                            "id": 1,
                            "title": "High School Engineering Intern",
                            "company_name": "Acme Civic",
                            "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
                            "location": {"name": "Austin, TX"},
                            "content": "<p>Open to high school students grades 11-12.</p>",
                        },
                        {
                            "id": 2,
                            "title": "Internal Audit Director",
                            "absolute_url": "https://boards.greenhouse.io/acme/jobs/2",
                            "location": {"name": "Austin, TX"},
                            "content": "<p>10 years experience.</p>",
                        },
                    ]
                },
            )
        if "api.lever.co" in url:
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "lev-1",
                        "text": "Summer Youth Intern",
                        "hostedUrl": "https://jobs.lever.co/beta/lev-1",
                        "categories": {"location": "Chicago, IL"},
                        "workplaceType": "onsite",
                        "descriptionPlain": "High school teens welcome.",
                    }
                ],
            )
        if "api.ashbyhq.com" in url:
            return httpx.Response(
                200,
                json={
                    "jobs": [
                        {
                            "id": "ash-1",
                            "title": "Pre-College Design Intern",
                            "location": "Remote",
                            "isRemote": True,
                            "jobUrl": "https://jobs.ashbyhq.com/gamma/ash-1",
                            "descriptionPlain": "Open to high schoolers.",
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 99,
                        "url": "https://remotive.com/remote-jobs/software-dev/hs-intern-99",
                        "title": "Junior High School Coding Intern",
                        "company_name": "RemoteEd",
                        "candidate_required_location": "USA Only",
                        "description": "Remote high school student internship.",
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    gh = fetch_greenhouse("acme", "Acme", client=client)
    lv = fetch_lever("beta", "Beta", client=client)
    ash = fetch_ashby("gamma", "Gamma", client=client)
    rem = fetch_remotive("intern", "Remotive", client=client)
    client.close()

    assert len(gh) == 1 and gh[0].title == "High School Engineering Intern"
    assert len(lv) == 1 and lv[0].location == "Chicago, IL"
    assert len(ash) == 1 and ash[0].work_mode_hint == "remote"
    assert len(rem) == 1 and rem[0].source_url.startswith("https://remotive.com/")


def test_parse_standoutsearch_html():
    html_snippet = """
    <div class="body">
      <p class="org">New York Botanical Garden</p>
      <h3 class="title"><a class="title-link" href="/opportunities/nybg-explainer">High School Explainer Program</a></h3>
      <p class="blurb">A tiered internship for high school students teaching visitors.</p>
      <div class="meta">
        <span class="place"><span data-place="New York">New York</span></span>
        <span class="deadline" data-deadline='{"dates":[{"date":"2026-11-14"}]}'>Deadline: Nov 14</span>
      </div>
    </div>
    """
    items = parse_standoutsearch_html(html_snippet)
    assert len(items) == 1
    assert items[0].company == "New York Botanical Garden"
    assert items[0].location == "New York"
    assert items[0].deadline == "2026-11-14"
    assert items[0].apply_url == "https://www.standoutsearch.com/opportunities/nybg-explainer"


def test_parse_pathwaystoscience_list_and_detail():
    list_html = """
    <div class="progigert">
      <a href="programhub.aspx?sort=HSC-ASEE-ONRSEAP">Office of Naval Research SEAP</a>
      <div>Competitive research internships for high school students ...read more</div>
    </div>
    """
    entries = parse_pathwaystoscience_list(list_html)
    assert len(entries) == 1
    assert entries[0]["title"] == "Office of Naval Research SEAP"

    detail_html = """
    <html><body>
      <img src="images/nationwide.gif" alt="icon indicating a nationwide program"/>
      <a href="https://navalsteminterns.us/seap/">Click Here to Learn More and Apply!</a>
      <div>Description:</div>
      <div>Eight-week paid research internships at Navy labs for high school students.</div>
      <div>Participating Institution(s):</div>
      <a href="Institution.aspx?sort=Institution&subsort=ASEE">ASEE</a>
    </body></html>
    """
    parsed = parse_pathwaystoscience_detail(detail_html, entries[0]["detail_url"])
    assert parsed["apply_url"] == "https://navalsteminterns.us/seap/"
    assert parsed["company"] == "ASEE"
    assert parsed["location"] == "Across the US"
    assert "high school students" in parsed["description"].lower()


def test_parse_github_markdown_tables_skips_competitions():
    md = """
## Competitions
| **Name** | **Short Description** | **Link** |
| :--- | :--- | :--- |
| **USACO** | National coding olympiad | [Link](https://usaco.org/) |

## Internships
| **Name** | **Short Description** | **Format** | **Grade Level** | **Paid?** | **Deadline** | **Link** |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: |
| **Lockheed Martin Space Internship** | High school summer engineering internship | In-person | 10-12 | $ -> | January | [Link](https://lockheedmartin.com/hs) |
"""
    items = parse_github_markdown_tables(md, source_name="HS CS Repo")
    assert len(items) == 1
    assert items[0].title == "Lockheed Martin Space Internship"
    assert items[0].apply_url == "https://lockheedmartin.com/hs"
    assert "Paid internship" in items[0].description


def test_parse_nichable_cards_and_detail_skips_scholarships():
    cards_html = """
    <div>
      <div class="rounded-lg border p-4">
        <div class="flex min-w-0 flex-col gap-0.5">
          <h3><a href="/opportunities/albany-light" title="City of Albany LIGHT Youth Employment">City of Albany LIGHT Youth Employment</a></h3>
          <span>City of Albany</span>
        </div>
        <div>Job · Paid · Albany, NY · Opening soon</div>
      </div>
      <div class="rounded-lg border p-4">
        <div class="flex min-w-0 flex-col gap-0.5">
          <h3><a href="/opportunities/elks-scholarship" title="Elks Scholarship">Elks Scholarship</a></h3>
          <span>Elks</span>
        </div>
        <div>Scholarship · Nationwide</div>
      </div>
    </div>
    """
    items = parse_nichable_cards(cards_html, source_name="Nichable Albany", base_url="https://nichable.app/local/albany")
    assert len(items) == 1
    assert items[0].title == "City of Albany LIGHT Youth Employment"
    assert items[0].company == "City of Albany"
    assert items[0].location == "Albany, NY"
    assert items[0].apply_url == "https://nichable.app/opportunities/albany-light"

    detail_html = """
    <main>
      <h1>Albany Medical College NextGen Neuroscience Summer Program</h1>
      <a href="/orgs/amc">Albany Medical College</a>
      <div>Location</div><div>Albany, NY</div>
      <div>Grade levels</div><div>Grades 10-12</div>
      <div>Cost</div><div>Unpaid</div>
      <div>About</div><div>Free six-week summer program for high school students 16 and older.</div>
    </main>
    """
    detail_item = parse_nichable_detail(
        detail_html,
        url="https://nichable.app/opportunities/amc-nextgen",
        source_name="Nichable Albany",
    )
    assert detail_item is not None
    assert detail_item.location == "Albany, NY"
    assert "Grades 10-12" in detail_item.description
    assert detail_item.company == "Albany Medical College"


def test_parse_srmc_programs_html_and_rss_company_split():
    srmc_html = """
    <div class="program-cards">
      <div class="program-card">
        <a href="/our_programs/arise/">Applied Research Innovation in Science &amp; Engineering (ARISE)</a>
        <div>NYU Tandon School of Engineering, Brooklyn</div>
      </div>
      <div class="program-card">
        <a href="/our_programs/slp/">Science Leadership Program (SLP)</a>
        <div>Hudson River Park Trust, 353 West St., Pier 40, 2nd Floor, NY, NY 10014</div>
      </div>
    </div>
    """
    srmc_items = parse_srmc_programs_html(srmc_html)
    assert len(srmc_items) == 2
    assert srmc_items[0].company == "NYU Tandon School of Engineering"
    assert srmc_items[0].location == "Brooklyn, NY"
    assert "high school" in srmc_items[0].description.lower()
    assert srmc_items[1].location == "New York, NY"

    rss_xml = """<?xml version="1.0"?>
    <rss version="2.0"><channel><title>NY Creates</title>
      <item>
        <title>Cybersecurity Intern - NY Creates</title>
        <link>http://nycreates.interviewexchange.com/jobofferdetails.jsp?JOBID=206535</link>
        <description>&lt;b&gt;Location:&lt;/b&gt; Albany, NY. Open to students.</description>
      </item>
    </channel></rss>"""
    rss_items = parse_feed_xml(rss_xml, source_name="NY CREATES RSS", area_hint="Albany, NY")
    assert len(rss_items) == 1
    assert rss_items[0].title == "Cybersecurity Intern"
    assert rss_items[0].company == "NY Creates"
    assert rss_items[0].location == "Albany, NY"
