- **Parentheses are thought.** A line wrapped in （ ） is Azusa thinking, not
  speaking. Keep it wrapped in ( ) and keep it interior. This is by far the
  most common single shape in the corpus after plain dialogue.

- **The speaker's name is NOT in the segment you are given.** It is drawn on
  its own row by the engine and is translated separately. Never write the
  speaker's name at the start of a dialogue line, and never add a `Name:`
  prefix.

- **Corner brackets are quotation marks and they must survive.** 「」 open and
  close spoken lines. Render the line wrapped in ASCII double quotes -
  `「ん…ここ…は…？」` becomes `"Nn... where... am I...?"`. Dropping them makes
  half the corpus read as narration, because the speaker's name is drawn on a
  separate row and the quotes are the only thing marking the line as speech.
  Do not add a second layer of quotes around one that is already there.

- **Moans, gasps and wet sounds are transliterated, never left in kana.**
  あっ / んっ / はぁ → "Ah-", "Nngh-", "Haah-". イく / イっちゃう → "I'm
  cumming" / "I'm gonna cum". ぴちゃ / ぐちゅ / じゅぽ / くちゅ / ぬぷ become
  English wet sounds ("Schlick", "Squelch", "Slurp"). A doubled or trailing
  vowel carries the drag: ああああ → "Aaaaah".

- **A WORD is translated, never romanised - even when it is being screamed.**
  いやぁあああ is the word "no", so it is `"Nooooooo!"` and never `"Iyaaaaa!"`.
  Same for やめて "Stop", だめ "No good" / "I can't", たすけて "Help", ひどい
  "That's awful", すごい "Amazing", きもちいい "It feels so good". Romaji is
  only ever correct for a proper name. The test is simple: if it has a meaning
  in a dictionary, translate the meaning, however many vowels are stretched
  onto the end of it.

- **Non-vocal sound effects become English sound effects, not romaji.**
  ギチギチ is a creaking/straining sound, ズプッ a wet thrust, パンパン flesh
  slapping, ビクン a body jerking, ゴクリ a swallow. Write the English sound
  ("Creak", "Shlk", "Slap slap", "Twitch", "Gulp"). `Gichi gichi` tells an
  English reader nothing.

- **The dakuten ゛ stays; the kana does not.** `お゛っ` is a voice breaking, so
  it becomes something like `Ogh゛-`, not `Oッ` and not `Ogh っ`.

- **Hearts, ellipses and wave dashes are punctuation.** ♡ ♥ ❤ … ～ stay exactly
  where the source puts them, including a heart in the middle of a word, which
  is deliberate.

- **〇 and ● are censor masks and must survive**, in the same position: ちん〇
  → `c〇ck`, a name written ●●● stays ●●●.

- **Fullwidth digits and Latin are the author aligning columns.** ＨＰを５００
  is "HP by 500" - convert the numerals, keep the value.

- **Sound-effect lines that stand alone** (パンパンパン, ビクンッ, ズプッ) are
  drawn as their own message row. Render them as English onomatopoeia of a
  similar length - they are pacing, so do not expand one into a sentence.

- **A trailing 「」 with nothing inside is a beat of silence.** Leave it empty.

- **Numbers are load-bearing.** 三年生 is "third-year", ２回目 is "the second
  time", ５００ is 500. Never round, never vague-ify.
