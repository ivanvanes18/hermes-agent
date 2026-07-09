# Problems: hermes-upstream-20260710

No open problems after final targeted verification.

Known caveats, not blockers for this merge branch:
- Branch is not pushed or activated in the live gateway.
- Distribution metadata is now synced to `hermes-agent 0.18.2` in this checkout venv.
- Full test suite was not run; targeted suite passed.

## Current activation blocker

The update branch and venv are ready, and prod-targeted tests passed on rerun.

The only remaining blocker is live process restart: `hermes gateway restart` is blocked from inside the serving gateway process by Hermes safety guardrail. Use Telegram `/restart` or run `hermes gateway restart` from an external local shell.
