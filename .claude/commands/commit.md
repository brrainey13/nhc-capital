# /commit

Review all staged and unstaged changes. Group related changes into logical conventional commits.
Use `scripts/committer` to commit — never `git add .`.
Format: `type: short description` (feat|fix|refactor|build|ci|chore|docs|style|perf|test).

After committing, push to GitLab and open a merge request:
```bash
git push -u gitlab feat/your-branch
gh pr create --title "type: description"
```
**Never push directly to main.** Branch protection will reject it.
