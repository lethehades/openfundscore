# Security Policy

## Supported status

OpenFundScore is a research preview. Security and data-rights reports are
accepted for the current `main` branch; no production service or hosted ranking
is currently operated.

## Report privately

Do not open a public issue containing credentials, private holdings, personal
identifiers, restricted provider data or an exploitable vulnerability. Use
GitHub private vulnerability reporting when enabled for the repository owner.
If that channel is unavailable, open a minimal issue requesting a private
contact channel without including sensitive details.

## Credential and data rules

- Never commit API keys, passwords, cookies, SMS codes or payment credentials.
- Provider secrets remain user-local and must be redacted from logs.
- Do not bypass login, CAPTCHA, anti-bot or platform access controls.
- Third-party data rights are not granted by the Apache-2.0 code licence.
- Manager records contain relevant public professional evidence only.
- Private holdings and suitability profiles remain local by default.

Security fixes must include a regression test when behavior is testable and must
not expose the original secret or private dataset in commits, issues or CI logs.
