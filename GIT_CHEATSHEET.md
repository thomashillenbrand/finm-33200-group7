# Git Cheat Sheet — Group 7

A one-pager for working on this repo. The main branch is **`master`**, the remote is **`origin`** (GitHub), and we do significant work on **branches** that get **merged back via pull requests**.

> First time on a new machine? Clone it:
> `git clone git@github.com:thomashillenbrand/finm-33200-group7.git`

---

## The everyday loop

```bash
# 1. START every session by getting the latest from GitHub
git checkout master        # make sure you're on master
git pull                   # download + merge everyone else's changes

# 2. Make a branch for your work (don't work directly on master)
git checkout -b my-feature # creates the branch AND switches to it

# 3. ... edit files ...

# 4. See what you changed
git status                 # which files changed / are staged
git diff                   # the actual line-by-line changes

# 5. Stage + commit
git add <file1> <file2>    # stage specific files, OR
git add -A                 # stage everything you changed
git commit -m "Short, clear message about what you did"

# 6. Push your branch to GitHub
git push -u origin my-feature   # first push of a new branch
git push                        # every push after that
```

Then open a **Pull Request** on GitHub to merge `my-feature` into `master` (see below).

---

## Branching

| Goal | Command |
|------|---------|
| See all branches | `git branch -a` |
| Create + switch to a new branch | `git checkout -b my-feature` |
| Switch to an existing branch | `git checkout my-feature` |
| Switch back to master | `git checkout master` |
| Delete a local branch (after it's merged) | `git branch -d my-feature` |

**Naming:** use a descriptive name, e.g. `feature/gold-set-loader` or `fix/horizon-resolver`.

---

## Committing well

- Commit **small, logical chunks** — not your whole day in one commit.
- Write a **clear message**: `git commit -m "Add Compustat loader for numerical guidance"` beats `"stuff"`.
- Made a typo in the message of the commit you *just* made (and haven't pushed)?
  `git commit --amend -m "Better message"`

---

## Pull Requests (how work gets into `master`)

1. Push your branch: `git push -u origin my-feature`
2. Go to the repo on GitHub — it'll offer a **"Compare & pull request"** button.
3. Add a short description of what changed and why, then **Create pull request**.
4. A teammate reviews, then it gets **merged** into `master`.
5. Afterwards, locally: `git checkout master && git pull` to pick up the merged work.

> Why PRs instead of pushing to master directly? They give teammates a chance to see changes, and keep `master` stable so everyone can pull from it safely.

---

## Keeping your branch up to date

If `master` moved while you were working and you want those changes on your branch:

```bash
git checkout master
git pull                   # get latest master
git checkout my-feature
git merge master           # bring master's changes into your branch
```

---

## "Help, I messed up" recovery

| Situation | Fix |
|-----------|-----|
| Discard changes to one file (not yet committed) | `git checkout -- <file>` |
| Unstage a file (keep the edits) | `git restore --staged <file>` |
| Undo the last commit but **keep** your changes | `git reset --soft HEAD~1` |
| See recent commits | `git log --oneline -10` |
| See who changed a line and when | `git blame <file>` |
| I'm lost — what state am I in? | `git status` (run it often!) |

**When in doubt, run `git status` and stop before doing anything destructive.** If something looks scary, ask a teammate before running it — it's almost always recoverable, but easier to fix before you pile more on top.

---

## Merge conflicts (don't panic)

A conflict happens when two people changed the same lines. Git marks them in the file:

```
<<<<<<< HEAD
your version
=======
their version
>>>>>>> master
```

Edit the file to keep what you want, delete the `<<<`, `===`, `>>>` markers, then:

```bash
git add <file>
git commit          # completes the merge
```

---

## Glossary

- **repo** — the project folder tracked by git.
- **commit** — a saved snapshot of your changes, with a message.
- **branch** — an independent line of work; `master` is the shared one.
- **origin** — our remote on GitHub.
- **push / pull** — upload your commits / download everyone else's.
- **merge** — combine one branch's work into another.
- **PR (pull request)** — a GitHub request to merge a branch, with review.
