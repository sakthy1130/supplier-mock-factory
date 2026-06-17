# Session Starter Prompts — Smart Booking Automation

Reference file. When you open a **new Claude Code session**, open it rooted at
`supplier-mock-factory` (add `qaBackend_Enigma` as an extra working directory for
the Java side), then **paste one of the prompts below** as your first message.

The memory (`sb-automation-handoff`) and `qaBackend_Enigma/docs/SB_HANDOFF.md`
load automatically — you don't need to re-explain the background.

---

## ▶️ Continue the SB work (primary — copy this)

```
Read the sb-automation-handoff memory and docs/SB_HANDOFF.md, then continue the Smart Booking automation. We're on branch cowork-smartbooking-wip (SMF) and ENIGMA-5856 (qaBackend_Enigma). Tell me where we left off before doing anything.
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
- Branches in play (local, not pushed):
  - `supplier-mock-factory` → `cowork-smartbooking-wip`
  - `qaBackend_Enigma` → `ENIGMA-5856`
- Reminder for Java runs: `export JAVA_HOME=/opt/homebrew/Cellar/openjdk@21/21.0.11/libexec/openjdk.jdk/Contents/Home`
