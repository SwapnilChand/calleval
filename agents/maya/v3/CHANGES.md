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

(A hypothesis until re-run. Status: not verified. A first same-model re-run on 3 comparable cases showed no difference between v2 and v3: doctor-branch pass/pass, language-switch fail/fail, tool-failure void/void. Needs more runs.)
