# Vision & Idea Backlog

> A living north-star + idea inventory. Much of this came from a 6-lens creative
> panel (2026-07-16): behavioral science, wellness/physiology, game design,
> creative technology, product strategy, and a speculative "wildcard." Filed
> issues are linked; everything else is a preserved seed, not a commitment.

## North star

**From a break *reminder* → the calm layer that protects your attention, makes
rest a moment you *arrive at*, and mirrors your rhythm back as something
beautiful.** The product framing: an **Attention Sanctuary / adaptive rhythm
companion** — *"every other app wants more of your attention; this one gives it
back."*

The unfair advantage is the **local, sensor-driven event log** + a genuinely
**calm, kind design sensibility** — not the popup (everyone has a popup).

## Ethos / guardrails (apply to every idea)

- **Kind, never naggy.** No shame, no guilt-trips, no loss-aversion streaks, no
  manufactured urgency, no dark-pattern variable rewards.
- **Autonomy first.** The app *offers* and *asks*; the user always decides.
- **Absence is rest, not failure.** Time away should be welcomed, never punished.
- **The rest is sacred.** Eye/body recovery is never sacrificed to productivity
  or gamification. Any "productive" layer is opt-in and only on longer breaks.
- **Local-first & private.** On-device inference preferred; the event log never
  leaves the machine. Sensor use (camera, etc.) is opt-in with a hard off switch.
- **Everything configurable.** Sensible defaults; nothing imposed.

## What the six lenses *converged* on (the real signal)

1. **The break is a destination you arrive at, not a popup you dismiss** — the
   single highest-conviction idea (5 of 6 lenses). → #65
2. **The event log becomes a kind mirror, never a scoreboard** — weekly recap /
   rhythm reflection. → #61
3. **Adaptive timing that asks, never forces** — learn your rhythm, protect deep
   work, offer the right break at the right time. → #62
4. **Absence-safe kindness** — the app is glad when you don't need it (fresh-start
   welcomes; companions that rest rather than "die"). → #64
5. **The break as a *dose*, not just timing** — make the 15s/10min physiologically
   potent (blink, breath, posture, near/far focus).
6. **Off-screen / ambient / physical** — the kindest break gets you off the glass.
7. **Generative keepsake from your day** — the log rendered as private art.
8. **On-device intelligence** — small local models / stats; privacy as a feature.
9. **Sensor frontier** — camera blink/posture, rPPG HRV (opt-in, frames never kept).
10. **Presence without surveillance** — kind, anonymous body-doubling.

## Backlog

### Near-term wins (mostly `Tk-now`)
- **The break ritual — "arrive at the break"** (breathing pacer + micro-prompt +
  peak-end on return). → **#65**
- **Weekly Recap** (kind focus letter from the event log). → **#61**
- **Break Inbox** (GTD capture → surface one item on longer breaks). → **#63**
- **Annotate your time** — a lightweight "Work on…" focus label (**#88**) + tag what
  a break was ("lunch"/"walk", **#89**), both event-sourced (feeds #52). Two sides of
  one idea: label the *work*, label the *rest*, so the Recap/dashboard mirrors *what*
  you worked on and *how* you rested. Free-text, generic-by-default, project-capable
  for free.
- **Daily "Start" ritual + Fresh-Start re-entry**. → **#64**
- **If-then break recipes** — you pre-write, in your own words, what a break is
  *for* ("Normal Break → water + window"); the popup echoes *your* plan back.
  (Implementation intentions ~2× follow-through.) *[backlog]*
- **Temptation bundling** — a want-to-do that only appears during breaks
  (a track, a saved photo, a wishlist article). *[backlog; overlaps #63]*
- **Time-of-day adaptive breaks** — morning bright/activating, evening warm
  wind-down; content + palette + chime shift with the day. *[backlog; ties #62]*
- **Custom sounds**, **reactive hover micro-interactions**. → #55, #56

### Bigger bets (`needs-data/AI` / `needs-native`)
- **Adaptive rhythm & smart scheduling** — Golden Hours + Flow Shield +
  context-aware intervals (the "how did it know" moat). → **#62**
- **Health & Habits sync** — Apple Health steps/stand + write Mindful Minutes;
  track habits done in breaks; habit-app sync via Shortcuts. → **#66**
- **Menu-bar cockpit** — glanceable progress-to-next-break ring, "Break now",
  "push 10 min", + a Raycast/Spotlight extension and Shortcuts/App-Intents. *[backlog]*
- **On-device LLM layer** — "Slow Return" (tailor the break to what you just did)
  and a one-line "Evening Exhale" daily recap; rule-based fallback. *[backlog]*
- **Generative keepsake** — the event log rendered as private, absence-safe,
  *additive-only* art you can look back on / print: **Grove** (a world that grows
  *because* you step away), **Constellations of Rest** (name & print them),
  **Season Rings / Day-Seeded Sky**. *[backlog]*
- **Cinematic "start focus" hero moment** ("vvooom"). → #57
- **Distraction removal in focus mode**; **macOS/iOS Focus (DND) integration**. → #59, #60

### Moonshots (`needs-sensor` / `needs-hardware`)
- **Kind Camera** — on-device blink-rate + posture coach; frames processed in
  memory, never kept. *[backlog]*
- **Biofeedback break** — camera rPPG → HRV; a breath pacer that finds your
  resonance and *verifies* you downregulated. *[backlog]*
- **Physical desk companion** — a screenless object that breathes with your
  rhythm and warms/glows for a break (**Resonance** puck / **Worry Stone**). *[backlog]*
- **Circadian Co-Pilot / Weather of You** — shape the whole day to your energy
  curve (chronotype/ultradian), optionally from sleep/light signals. *[backlog]*
- **Kind body-doubling** — anonymous "someone is resting with you" presence
  (**Focus Buddies** for one friend, or a global **Breathing Bridge**). Needs a
  minimal privacy-preserving relay; hard local-only off switch. *[backlog]*
- **iPhone + Apple Watch companion** — Handoff Break: start on Mac, finish as a
  haptic breathing session on the Watch, away from the screen. → #58 (+ Watch)

### Product / business (honor the ethos)
- **First Light** — a 60-second calm first-run instead of a settings grid. *[backlog; distinct from the daily ritual in #64]*
- **Kind Pro** — free forever for the break/rest/pausing; Pro gates *depth* (long
  history of Recap + Golden Hours, sound/theme packs, Focus Buddies), never
  dignity. Single calm upsell, shown once. *[backlog]*

## Concept glossary (for the fuzzy ones)

- **If-then break recipe:** an *implementation intention* — a pre-written
  "if [trigger] then [action]" plan the user authors; the app just echoes it back
  at break time. Doubles follow-through vs. a vague goal.
- **Fresh-Start effect:** people act most on goals at temporal landmarks; and
  returning after a gap is greeted as a *fresh start*, never a *lapse* — the
  anti-streak.
- **Peak-end rule:** we remember an experience by its emotional peak and its
  ending; engineering a warm *end* to the break makes the whole thing feel good,
  which is the ethical way to build the habit.
- **Flow Shield:** defer a due break past deep work to the next natural seam
  instead of interrupting mid-thought.

## Related tracked work
Design makeover #49 · event-log audit #52 · manage breaks #53 · custom sounds #55
· reactive design #56 · start hero #57 · iPhone app #58 · distraction removal #59
· Focus/DND #60 · **Weekly Recap #61 · Adaptive rhythm #62 · Break Inbox #63 ·
Start ritual + Fresh-Start #64 · Break ritual (arrive-at) #65 · Health & Habits #66**
· Work-on label #88 · Break tag #89
