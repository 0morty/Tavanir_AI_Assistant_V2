---
trigger: always_on
---

# No Automatic Git Commits

- Never execute `git commit`, `git merge`, `git rebase`, or `git push` autonomously.
- Do not stage files (`git add`) for the purpose of creating a commit unless explicitly asked by the user.
- Leave all modified files uncommitted in the working tree for the user to review.
- Only create commits when the user gives an explicit command to do so.
