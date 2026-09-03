#!/usr/bin/env python3
"""
Checks a list of URLs and emails a report if any return 404, 5xx,
or fail to connect (timeout, DNS error, connection refused, etc).

Config via environment variables (set as GitHub Actions secrets):
    GMAIL_USER          - the Gmail address to send FROM
    GMAIL_APP_PASSWORD  - a Gmail App Password (not your normal password)
    MAIL_TO             - comma-separated recipient address(es)
    ALWAYS_NOTIFY       - optional, "true" to get an email every run even
                          when everything is healthy (default: "false")
"""

import os
import re
import smtplib
import sys
from datetime import datetime, timezone
from email.mime.text import MIMEText
from urllib.parse import urlparse

import requests

URLS_FILE = "urls.txt"
TIMEOUT_SECONDS = 15
HEADERS = {
    # A browser-like UA cuts down on false "403 Forbidden" results from
    # bot-protection systems (Cloudflare etc.) that block generic/bot UAs.
    # It won't help with WAFs that block on IP range alone (GitHub Actions
    # runners use known datacenter IPs) — see the 403 message below.
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Below this many characters of visible (tag-stripped) text, a 200 OK page
# is treated as blank rather than healthy.
MIN_VISIBLE_TEXT_CHARS = 30

# Phrases that show up on pages a server still answers with 200 OK for, but
# that are actually broken: CMS fatal errors, hosting-suspension parking
# pages, exposed directory listings, expired-domain placeholders, etc.
BROKEN_PAGE_SIGNATURES = [
    "fatal error",
    "there has been a critical error",
    "database connection error",
    "error establishing a database connection",
    "parse error: syntax error",
    "notice: undefined variable",
    "warning: mysql",
    "index of /",
    "account suspended",
    "this account has been suspended",
    "domain has expired",
    "this domain is not configured",
    "website coming soon",
    "default web page",
]

# Terms commonly injected by site defacements / SEO spam hacks. Kept short
# and specific to avoid flagging legitimate pages that just mention them once.
HACK_INDICATOR_KEYWORDS = [
    "hacked by",
    "this site has been hacked",
    "cialis",
    "viagra",
    "sildenafil",
    "judi slot",
    "situs slot",
    "bandar togel",
]


def same_site(host_a, host_b):
    """Rough check: do two hostnames share their last two labels?

    Not a full public-suffix-list lookup, just enough to tell "our own
    domain redirecting www -> apex" apart from "redirected to a totally
    different domain", which is the interesting signal here.
    """
    if not host_a or not host_b:
        return host_a == host_b
    return host_a.split(".")[-2:] == host_b.split(".")[-2:]


def inspect_page_content(url, resp):
    """Returns None if the page content looks fine, otherwise a problem
    description. Only meaningful for successful (2xx/3xx) responses."""
    final_host = urlparse(resp.url).hostname
    original_host = urlparse(url).hostname
    if not same_site(original_host, final_host):
        return f"Unexpected redirect to a different domain ({resp.url})"

    text = resp.text[:500_000]
    visible_text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()
    if len(visible_text) < MIN_VISIBLE_TEXT_CHARS:
        return f"Blank or near-empty page ({len(visible_text)} chars of visible text)"

    lower_text = text.lower()
    for signature in BROKEN_PAGE_SIGNATURES:
        if signature in lower_text:
            return f"Broken page detected (found: \"{signature}\")"

    for keyword in HACK_INDICATOR_KEYWORDS:
        # Word-boundary match: a plain substring check would flag "cialis"
        # inside ordinary words like "specialist" or "commercialise".
        if re.search(rf"\b{re.escape(keyword)}\b", lower_text):
            return f"Possible hack/spam injection detected (found: \"{keyword}\")"

    return None


def load_urls(path):
    urls = []
    seen = set()
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", line):
                    line = f"https://{line}"
                if line not in seen:
                    seen.add(line)
                    urls.append(line)
    return urls


def check_url(url):
    """Returns None if healthy, otherwise a short problem description."""
    try:
        resp = requests.get(
            url, timeout=TIMEOUT_SECONDS, allow_redirects=True, headers=HEADERS
        )
        if resp.status_code == 404:
            return "404 Not Found"
        if resp.status_code >= 500:
            return f"Server error ({resp.status_code})"
        if resp.status_code == 403:
            return (
                "403 Forbidden (often a false alarm: bot/WAF protection "
                "blocking the automated check itself, not a real outage — "
                "verify in a browser before assuming the site is down)"
            )
        if resp.status_code >= 400:
            return f"Client error ({resp.status_code})"
        return inspect_page_content(url, resp)
    except requests.exceptions.Timeout:
        return "Timed out (no response)"
    except requests.exceptions.ConnectionError:
        return "Connection failed (site unreachable/DNS error)"
    except requests.exceptions.RequestException as e:
        return f"Request failed ({e.__class__.__name__})"


def send_email(subject, body):
    gmail_user = os.environ["GMAIL_USER"]
    gmail_password = os.environ["GMAIL_APP_PASSWORD"]
    mail_to = [addr.strip() for addr in os.environ["MAIL_TO"].split(",")]

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = ", ".join(mail_to)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_password)
        server.sendmail(gmail_user, mail_to, msg.as_string())


def main():
    always_notify = os.environ.get("ALWAYS_NOTIFY", "false").lower() == "true"

    urls = load_urls(URLS_FILE)
    if not urls:
        print("No URLs found in urls.txt")
        return

    problems = []
    healthy = []

    for url in urls:
        issue = check_url(url)
        if issue:
            problems.append((url, issue))
            print(f"[ISSUE] {url} -> {issue}")
        else:
            healthy.append(url)
            print(f"[OK]    {url}")

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if problems:
        lines = [f"URL check run: {timestamp}", "", "Problems found:", ""]
        for url, issue in problems:
            lines.append(f"  - {url}\n    -> {issue}")
        if healthy:
            lines.append("")
            lines.append(f"Healthy ({len(healthy)}): " + ", ".join(healthy))
        body = "\n".join(lines)
        subject = f"[URL Monitor] {len(problems)} site(s) need attention"
        send_email(subject, body)
        print("Notification email sent.")
    elif always_notify:
        body = f"URL check run: {timestamp}\n\nAll {len(healthy)} site(s) healthy:\n" + "\n".join(
            f"  - {u}" for u in healthy
        )
        send_email("[URL Monitor] All sites healthy", body)
        print("All-clear email sent.")
    else:
        print("All sites healthy. No email sent.")


if __name__ == "__main__":
    sys.exit(main())
