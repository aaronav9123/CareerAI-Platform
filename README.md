# CareerAI - Full Platform

## Run
```
pip install -r requirements.txt
copy .env.example .env      (Windows)   |   cp .env.example .env   (Mac/Linux)
python app.py
```
Open http://127.0.0.1:5000.

The app uses MySQL (WAMP). Start WAMP (tray icon green), set `DB_*` in `.env`
(defaults: root / empty password / port 3306). The `careerai` database and all
tables are created automatically on first start.

## New features and where they live
| Feature | Page | Code |
|---|---|---|
| Prediction history + dashboard timeline | /dashboard | `db.py` (predictions table), `app.py` |
| Admin panel | /admin | `app.py` (`admin_*`), `templates/admin.html` |
| Email verification, forgot/reset password | /register, /forgot-password | `app.py`, `mailer.py` |
| Job description matcher | /jd-match | `ats_scorer.score_against_jd` |
| Progress tracker (roadmap checkboxes, learned skills) | /roadmap, /skill-gap | `app.py`, `skill_gap.py` |
| Semantic skill matching | used everywhere | `semantic.py` |
| Resume improvement suggestions | /resume-improve | `resume_improver.py`, `llm.py` |
| Mock interview | /interview | `interview.py`, `data/interview_questions.json` |
| Live job listings | /jobs | `live_jobs.py` (Adzuna) |
| Market trend insights | /market-trends | `market_trends.py`, `data/market_trends.json` |

## Configuration (.env) - everything is optional
- **Admin**: the login is hard-coded at the top of `app.py` (`ADMIN_EMAIL`, `ADMIN_PASSWORD`) - change them there. Log in on the normal /login page. The admin can only open the Admin Panel, Market Trends and Logout.
- **Email**: set `SMTP_*`. Without SMTP, verification/reset links are printed in the terminal
  and shown on screen *only when you browse from localhost*. `REQUIRE_EMAIL_VERIFICATION=false` skips verification.
- **LLM** (resume rewrites, interview questions + scoring): `ANTHROPIC_API_KEY`, or any OpenAI-compatible
  API via `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` (Groq and Gemini have free tiers). Without a key the
  pages use rule-based fallbacks and say so.
- **Live jobs**: free keys from https://developer.adzuna.com -> `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `ADZUNA_COUNTRY=in`.
  Without keys (or if the API is down) the Jobs page shows the sample listings.
- **SBERT**: `pip install sentence-transformers`; first run downloads a ~90 MB model. `SEMANTIC_BACKEND=lite` forces the built-in matcher.

## Notes
- `data/market_trends.json` holds indicative estimates, not official statistics - replace with cited data before quoting in a report.
- Resume text is now stored in the database instead of the cookie session (a cookie can't hold a full resume).
- All forms are CSRF-protected; set a long random `SECRET_KEY` before deploying.
