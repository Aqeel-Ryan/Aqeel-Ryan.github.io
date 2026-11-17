---
title: "A WhatsApp front end for a freight document checker: what each limit cost"
description: "I added a WhatsApp chat to a tool that cross-checks shipping documents. The design came down to four trade-offs: one card at a time, Accept only for tiny changes, no money in message text, and a worker that never sends outside."
date: 2026-11-17
tags: [llm, agents, whatsapp, design]
draft: false
linkedin: true
---

I'm building a tool that reads every document on a sea-freight shipment, cross-checks them against each other, and turns each real mismatch into a finding with an owner. This week I put a WhatsApp chat in front of it.

The chat was easy to build. Deciding what it should refuse to do was the actual work.

## The problem

Most of a coordinator's day happens in email. The notes from a field interview in the project docs put it at about 90%. The web app is where detailed work happens, but two jobs don't need a laptop: getting a document into the system when someone sends it over a chat, and answering a quick question like "is this corrected packing list fine?"

The first prototype of the chat delivered every waiting question at once. On a phone that is a wall of cards, and a reply like "1" could land on any of them. TODO(verify): what the chat did with forwarded files and corrected documents before this build; the docs only say they were not handled in the chat.

## Constraints

I wrote eight rules before building anything. Four of them shaped most of the design:

- A message must be readable and actionable in 40 seconds: two lines, about 50 words, at most 3 buttons.
- Nothing leaves the company from the chat. Outgoing mail to a shipper or carrier goes only from a signed-in confirm page.
- No prices, margins or bank details in message text, because notifications show on the lock screen.
- A tap in the chat must show on the shipment's timeline, same as a click on the web.

There was also a platform limit. On WhatsApp's Cloud API, nothing can go out unless the person wrote to the bot first, inside a 24-hour window. A bot that "pushes the next question" needs its own loop and a template message for outside the window.

## What I tried, and what I dropped

**All cards at once.** This was the starting point. I replaced it, and the decision log says the fallback is reverting the commit (`0813f35`, 16 Nov), with a rollback for the one migration it added. Cost: the bot now needs state about which card is open, and a loop to send the next one. What it bought: a reply to a card can be matched to that card.

**Matching a forwarded file by the booking or B/L number printed on it.** I dropped this from the first build. A file isn't read until it is on a shipment, so reading the number first would mean extracting before filing. That is a bigger change to the pipeline than the chat justified. The cost is real: a forward with no caption gets a list of the five most recent shipments plus "File it later on the web", which is one extra tap. There is a `todo` test for the printed-number case that is still open.

**A Claude Code agent team.** I planned to build with one, then switched to separate Orca workers, because the lead session had no shared task-list tools. Each worker owned a set of files and could not touch anyone else's. That cost me some coordination overhead, but it kept two workers from overwriting each other in one checkout.

## What I built

**One card at a time.** The chat sends the most pressing waiting card and the next one only after an answer. A swipe-reply that quotes an older card answers that card. A bare "1" applies only if exactly one card is open. The cost is slower throughput: a person with ten waiting cards does ten round trips. I accepted that because the other choice was replies landing on the wrong card.

**Accept, but only for small, safe changes.** When a shipper sends a corrected document, code compares it to the other documents first, and the person is asked only after that. Accept is offered for at most two changed values, and never when a name, address or bank detail changed. From `packages/agent/src/build.ts`:

```ts
const sensitive = p.changes.filter((c) => isSensitivePath(c.path));
if (p.sensitive || sensitive.length) {
  const named = andList([...new Set(sensitive.map(changeNoun))].map((x) => `the ${x}`));
  return toWeb(n > sensitive.length ? `${who} changes ${n} values, including ${named}.` : `${who} changes ${named}.`, n > 1);
}
if (n > ACCEPT_MAX_CHANGES) return toWeb(`${who} changes ${n} values.`, true);
```

`toWeb` builds a card with only "Open document" and "Not now". The cost is that some perfectly fine corrections get sent to the web. What it bought: a bad consignee swap can never be one tap on a lock screen. The threshold of two is a judgment call, not a measured one. Accepting also doesn't close the problem directly; reconciliation re-runs and closes it, so the card only goes away after the check passes.

**Numbers are checked before they are sent.** The status snapshot ("MRS-4448 · 3 documents read. ...") is built from counts, and every number in the text must be one of the snapshot's own values. From `packages/agent/src/snapshot.ts`:

```ts
export function numberProblems(text: string, d: SnapshotData): string[] {
  let rest = text.split(d.reference).join(' ');
  for (const u of d.untyped) rest = rest.split(u.filename).join(' ');
  const values = d.toConfirm.reduce((n, x) => n + x.count, 0);
  const allowed = new Set([
    d.read, d.reading, d.untyped.length, values, d.toConfirm.length, ...d.toConfirm.map((x) => x.count), d.problems.count,
    ...(d.problems.count === 1 ? d.problems.numbers : []),
  ].map((n) => Math.round(n * 1000) / 1000));
  return (rest.match(NUM) ?? []).filter((tok) => !allowed.has(Math.round(toNumber(tok) * 1000) / 1000)).map((tok) => `${tok} is not in the shipment record`);
}
```

If the check fails, the message falls back to "Open the shipment for its status." with no numbers. This costs a regex and a rounding rule. It means the chat can't state a number the database doesn't hold, even if a template changes later.

**A push loop that can't reach the send path.** The worker runs `pushEverywhere` every 10 seconds (`CHAT_PUSH_SECONDS`), only to staff's own chats. The file header in `apps/worker/src/chat-push.ts` says it imports nothing from mail or the outbound path, and a test walks the import graph of the agent, channels, worker and webhook code to check that. I added that test after finding that the older no-auto-send test's package map never followed the chat code at all.

## Results

All numbers come from `docs/evals/WHATSAPP-EVAL.md` and `docs/DECISIONS.md` (D-48) in the project, final gate on 16 Nov:

- Unit tests: 1311 passing across 60 files. DB tests: 743 passing, 4 skipped (waiting for recorded model output), 1 todo (the printed-number matching I deferred).
- All nine hard gates are at 0: no message to an outside party from the chat, no reply to an unlinked number, no duplicate effect from a webhook delivered twice, no reply applied to the wrong card, no Accept on more than two or a sensitive change, no money/margin/IBAN in chat text, no card picture cropped from a money or bank field, no snapshot number missing from the record, and no cross-company `chat_intake` rows.
- In the 10-step simulator walk-through, 28 messages: at most 2 lines each (mean 1.3), at most 32 words (mean 16.8), at most 3 buttons (mean 1.1). Most flows took one tap.

The eval also caught real failures. The first run broke my own lock-screen rule: reading-check cards quoted "48,600.00" and an IBAN in their text. Money and bank readings now go web-only, with no value and no picture. Another test found a card that stayed with a person who had lost access to the shipment. That one was fixed too.

One caveat on these numbers: the walk-through runs in process, with reading simulated, so I did not measure the time from forwarding a file to its snapshot. By design the acknowledgement comes after 3 seconds of quiet and the snapshot on the first push run after reading finishes.

## What I'd do next

- **Test on a real phone.** I haven't. Meta locked the test WhatsApp Business account pending business verification (code 131031), and there's no company to verify for a demo. The simulator runs the same code, but that is not the same as a phone.
- **Match files by printed number.** The deferred item above. It needs extraction before filing.
- **Run on real documents.** The test corpora are clean digital PDFs, synthetic data only. The crop for a reading-check picture has only been tested on a synthetic PDF and photo, not on crooked phone photos with stamps over the field.
- **Open points from the eval.** Purge doesn't yet reach forwarded files and card images, managers see only their own unfiled forwards, the push backstop covers only the latest batch, and one audit event stores the sender's email address. TODO(verify): whether any of these have been fixed since the eval was written.
- **Re-check the two-change limit.** It is a guess. With real corrections I'd see how often it sends harmless fixes to the web.
