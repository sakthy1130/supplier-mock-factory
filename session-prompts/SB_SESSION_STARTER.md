# Session Starter Prompts — Smart Booking Automation

Reference file. When you open a **new Claude Code session**, open it rooted at
`supplier-mock-factory` (add `qaBackend_Enigma` as an extra working directory for
the Java side), then **paste one of the prompts below** as your first message.

The memory (`sb-automation-handoff`) and `qaBackend_Enigma/docs/SB_HANDOFF.md`
load automatically — you don't need to re-explain the background.

> **Worktree note — important.** The SMF SB work lives on **`origin/smartBooking`**
> (remote). The local `cowork-smartbooking-wip` branch is checked out in the MAIN
> worktree and CANNOT be checked out again in another worktree. If a new session
> starts in a fresh worktree based on old `main`/`abda852`, it will be missing the
> SB commits. Fix it by basing on the remote:
> ```bash
> git fetch origin && git merge origin/smartBooking   # bring SB work into this worktree
> ```
> (or `git checkout -b <new-branch> origin/smartBooking`). Do NOT start from `main`.

---

## ▶️ Continue the SB work (primary — copy this)

```
Read the sb-automation-handoff memory and docs/SB_HANDOFF.md, then continue the Smart Booking automation. The SMF work is on origin/smartBooking (fetch + merge it into this worktree if it's missing); qaBackend_Enigma is on ENIGMA-5856. Tell me where we left off before doing anything.
```

---

## 🔎 Just get oriented first

```
Read the SB automation handoff and summarize the current state — branches, what's fixed, what's left.
```

---

## ⚡ Minimal version

```
Continue the SB automation — check the handoff memory first.
```

---

## Notes
- Asking it to **"tell me where we left off before doing anything"** is the safest
  opener — Claude confirms its understanding before touching code, so you catch
  any drift early.
- Branches in play:
  - `supplier-mock-factory` → **`origin/smartBooking`** (PUSHED; local
    `cowork-smartbooking-wip` is the same work, locked to the main worktree)
  - `qaBackend_Enigma` → `ENIGMA-5856` (local, not pushed)
- Reminder for Java runs: `export JAVA_HOME=/opt/homebrew/Cellar/openjdk@21/21.0.11/libexec/openjdk.jdk/Contents/Home`
