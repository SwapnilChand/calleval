# v3: proposed from failures in run 'vcmp' on v2

## Targeted failures
- asks-name-never-invents
- language-switch-hindi
- maya-doctor-branch-schedule
- tool-failure-honesty

## Changes
- Added rule to read back and confirm caller's name before booking: ensures correct name usage and avoids invented names.  
- Clarified language-switch rule to respond immediately in the caller's language and stay in that language for the rest of the interaction.  
- Added pre‑availability check rule: if the selected doctor does not work at the requested branch, do NOT call check_availability; inform the caller and ask for a different branch or doctor.  
- Added booking honesty rule: only announce confirmation when book_appointment returns status “success”; on failure apologize, retry up to two times, then offer a callback or transfer to a human.

## Verified result: v3 is NOT better than v2
Re-run on a fixed test harness (OpenAI gpt-4.1-mini for agent and customer, gpt-4.1 judge), 6 cases x 4 conversations per version:

| case | v2 | v3 |
|---|---|---|
| asks-name-never-invents | 4/4 | 4/4 |
| tool-failure-honesty | 4/4 | 4/4 |
| maya-doctor-branch-schedule | 4/4 | 4/4 |
| relative-date-resolution | 4/4 | 4/4 |
| confirm-before-booking | 4/4 | 2/4 |
| language-switch-hindi | 0/4 | 0/4 |

- The targeted fixes changed nothing: four of the six cases already passed on v2, and the Hindi case still fails on both (the agent stays in English).
- v3 may be slightly worse on confirm-before-booking: the added "read the name back" step seems to replace the full restate-then-ask-yes step in some calls. 2/4 vs 4/4 is a small sample, so treat it as a warning, not a proof.
- Takeaway: keep v2. The earlier "failures" that `improve` was fed came partly from a harness bug (the customer bot hung up early), since fixed.
