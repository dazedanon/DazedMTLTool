# Game bible - ひと夏の思い出 ("A Summer to Remember")

Developer: はちみつサンド (Hachimitsu Sand). Unity 6 / IL2CPP, 3D, R18.

## What the game is

A short, quiet three-day summer story told over 3D animated scenes, plus a large
free-viewing mode with camera, expression, voice and costume controls. The story
is small on purpose: about 45 spoken lines across three days. Everything else the
player reads is settings UI.

## The two characters

**Miu (美羽)** - the heroine, a teenage girl. She does almost all the talking.
Warm, a bit shy, teasing when she is comfortable. Her Japanese is casual spoken
register: dropped particles, trailing ～かも / ～だよね / ～なぁ, filler like えへへ.
English should read as an actual teenager speaking out loud, not as prose.
Contractions always. Fragments are fine and usually right.

**The protagonist** - the player, a teenage boy, never named. He is visiting for
the summer and goes home when it ends. He gets 15 short lines, all of them
reactive: a question back, a small reassurance. The author writes his spoken
lines inside fullwidth brackets `「 」`, and the Dialogue Database independently
marks them actor 1 / IsPlayer. **Keep the brackets and the spaces inside them
exactly as they are** - they are how the game distinguishes his voice on screen.

## The shape of the story

Three days at a house whose owners (Miu's aunt and uncle) are away.

- **Day One** - she arrives, they are alone in the house for the first time, it is
  hot, the mood is nervous and a bit transgressive ("feels like we're doing
  something bad").
- **Day Two** - she comes back, sooner and more eagerly ("I ran here").
- **Final Day** - it is cooler, summer is ending, and she says out loud what the
  whole thing has been about: he goes home, this does not continue, and that is
  what makes it what it is.

Tone: wistful, warm, small. Not melodramatic. The last day should land gently -
resist the urge to punch it up.

## Register rules

- Adult scenes are explicit and stay explicit. Match the source's bluntness. No
  euphemism, no softening, no editorialising. This is the correct localisation.
- The action buttons (`挿入する`, `中に出す`, `体位を変える`) are terse imperatives
  the player clicks. Keep them short and plain.
- No honorifics appear anywhere in the script and neither character is addressed
  by name. Do not add names, nicknames or honorifics that are not in the source.
- `キミ` is "you".

## Line-level conventions

- `……` (fullwidth ellipsis) marks hesitation. Render as `...` and keep it where
  the author put it - leading ellipsis means she is trailing into the thought.
- Lines are short and are shown one at a time. Do not merge two source lines into
  one English sentence, and do not split one into two: the line count is the
  pacing, and each line is timed against its own voice clip.
- **Length matters more than usual here.** `FacialLipSync` derives the lip-sync
  duration from the *character count* of the subtitle, so an English line much
  longer than its Japanese keeps the mouth moving after the voice has stopped.
  Stay close to the source's length. Shorter is safer than longer.

## UI voice

Terse product English. Sentence case. No trailing period on a button or a
setting label. Prefer the word a player already knows from other games:
`全画面表示` is "Fullscreen", `垂直同期` is "V-Sync", `被写界深度` is "Depth of
Field", `フレームレート` is "Frame rate".

The settings screen is dense and the labels sit in fixed-width rows, so a label
that grows a lot will collide with its control. Keep UI strings at or below the
Japanese width where you can.
