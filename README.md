# URL Health Monitor

Checks a list of websites every morning and emails you if any of them
return a 404, a server error (5xx), or fail to respond at all.

## Setup (one-time, ~5 minutes)

1. **Create a new GitHub repo** and push these files to it
   (`check_urls.py`, `urls.txt`, `requirements.txt`, `.github/workflows/check-urls.yml`).

2. **Create a Gmail App Password** (don't use your real Gmail password):
   - Turn on 2-Step Verification on your Google account, if not already on:
     https://myaccount.google.com/security
   - Go to https://myaccount.google.com/apppasswords
   - Create an app password (name it e.g. "url-monitor") and copy the 16-character code.

3. **Add repo secrets**: in your GitHub repo, go to
   `Settings -> Secrets and variables -> Actions -> New repository secret`
   and add:
   - `GMAIL_USER` = your Gmail address (the "from" address)
   - `GMAIL_APP_PASSWORD` = the 16-character app password from step 2
   - `MAIL_TO` = where alerts should go (comma-separate multiple addresses,
     e.g. `alerts@yourcompany.com,you@yourcompany.com`)

4. **Add your URLs** to `urls.txt`, one per line.

5. **Set the schedule**: open `.github/workflows/check-urls.yml` and adjust
   the `cron` line to your desired time. GitHub Actions cron is always UTC —
   for example, for 8:00 AM IST use `cron: "30 2 * * *"` (2:30 UTC).
   Use https://crontab.guru to build the expression.

That's it — GitHub will now run the check automatically every day.

## Testing it right now

You don't have to wait for tomorrow morning:
- Go to the **Actions** tab in your repo -> **Daily URL Health Check** -> **Run workflow**.
- This runs it immediately using the `workflow_dispatch` trigger already in the workflow file.
- Check the **Actions** log to see the per-URL results, and check your inbox
  if any site had a problem.

## Notes

- No email is sent when everything is healthy (keeps your inbox quiet).
  To always get a daily "all clear" email too, change `ALWAYS_NOTIFY: "false"`
  to `"true"` in the workflow file.
- Each run times out after 15 seconds per URL — slow sites aren't
  necessarily broken, just adjust `TIMEOUT_SECONDS` in `check_urls.py` if needed.
- To add/remove monitored sites, just edit `urls.txt` — no code changes needed.
