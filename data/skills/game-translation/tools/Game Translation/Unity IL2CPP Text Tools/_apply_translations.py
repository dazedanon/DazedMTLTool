#!/usr/bin/env python3
"""
One-shot helper to apply the hand-written EN translations into the existing
dialogues.json / texts.json files. Preserves key order and the raw key bytes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PLUGIN_TL = Path(r"C:\Users\sw\Desktop\Projects\SheepClickerTL\translations")

# All translation values use real newlines (\n). The runtime Normalize() in
# TranslationStore handles literal "\\n" vs newline differences between key
# and lookup, so values just need to render correctly when set on TMP.

DIALOGUES_EN: dict[str, str] = {
    # cast / speaker labels
    "巫女": "Maiden",
    "教主": "Master",
    "官僚": "Bureaucrat",
    "狂信者": "Fanatic",
    "宣教師": "Missionary",
    # interjections / single-syllable
    "おお": "Oh.",
    "・・・": "...",
    "・・・？": "...?",
    "おおっと": "Whoa there.",
    "ふぁい・・・": "Yesh...",
    "んぐっ・・・（なんでこんなことに・・・）": "Mmnh... (Why is this happening to me...)",
    "ん？ああそうだな": "Hm? Yeah, true enough.",
    "はいっ！": "Yes, sir!",
    "オーッ！": "Yeah!",
    "！": "!",
    "はい！": "Yes!",
    "あ・・・": "Ah...",
    "なんだ": "What is it.",
    "もちろんでございます！": "Of course, Master!",
    "ふん": "Hmph.",
    "んぉっ！": "Nngh!",
    "おう": "Yeah.",
    "ああ": "Yeah.",
    "はあ・・・": "Haah...",
    "ね": "Hey...",
    "んっ": "Mn.",
    "うん・・・": "Mhm...",
    "そっかそっか": "I see, I see.",
    "はいっ": "Yes!",
    "んぁ・・・": "Nahh...",
    "ありがとう・・・": "Thank you...",
    "わかった": "Understood.",
    "さあ": "Who knows.",
    "そうですね・・・": "Indeed...",
    "！": "!",
    "はっ": "Tch.",
    "・・・！": "...!",
    "おい": "Oi.",
    "んぐっ": "Mmnh.",
    "んぇ・・・": "Nnh...",
    "返事": "Answer me.",
    "はい・・・！": "Yes, Master...!",
    "よし": "Good.",
    "・・・チッ": "...Tch.",
    "おらっ": "Take it.",
    "クソが・・・！": "Damn it...!",
    "ああっ・・・！": "Ahhn...!",

    # opening / Maiden + Master setting up the cult
    "教主様ご準備はよろしいですか？": "Master, are you ready to begin?",
    "ああ　大丈夫だ": "Yeah, I'm fine.",
    "お世辞にも良い場所とは言い難いが": "I can't honestly call this place much to look at, but...",
    "贅沢も言ってられないな": "Can't afford to be picky right now.",
    "申し訳ありません": "I'm sorry, Master.",
    "いや大丈夫だ": "No, it's fine.",
    "ここから始めよう": "We'll start from here.",
    "はい・・・": "Yes...",

    # ending — election won
    "教主様　私たちの立候補者が選挙で当選しました。": "Master — our candidate has won the election.",
    "他の立候補者も順調みたいです": "The other candidates are doing well too.",
    "なにが政教分離だ　こんなものか": "So much for separation of church and state. That was easy.",
    "これからどういたしましょう": "What shall we do from here?",
    "そうだなー": "Hmm, well...",
    "扇子持って踊るくらいしかやりたいことないな": "About all I feel like doing is dancing around with a folding fan.",
    "教主様　そんなことしてる暇があったら仕事を続けてください": "Master — if you have time for that, please get back to work.",
    "そのうち神様が目覚めて様子を見に来るかもしれませんよ": "One of these days God might wake up and come check on us, you know.",
    "はは　お前も冗談を言うんだな": "Hah. So even you tell jokes.",
    "おい、官僚": "Oi, bureaucrat.",
    "もっと奥まで咥えろ": "Take it deeper.",
    "今後も我らが神の教えを広めていきましょうね": "Let's keep spreading our god's teachings, hm?",
    "じゃあー今日も気張っていくぞー": "Right then — let's give it everything again today.",

    # GovernmentOffice 1 — first tax collection
    "うわ\n本当に何かやってる・・・": "Whoa,\nthey really are running something here...",
    "おや・・・\n入信希望者ですか？": "Oh my...\nA prospective convert?",
    "ああー\n違います": "Ahh —\nno, that's not it.",
    "このカルト教団　届け出とか出してませんよね": "This cult of yours — you haven't filed any official paperwork, have you.",
    "ああ\nそれとここはピラティス教室だ\n教団ではない": "Right.\nAlso, this is a Pilates studio,\nnot a cult.",
    "冗談はよしてくださいよ": "Please, spare me the jokes.",
    "活動実態も調べさせてもらってます": "We've already looked into what you actually do here.",
    "端的にいうと税金払ってませんよね\n占めて<color=#FF0000>100万円</color>": "Plain and simple — you haven't paid your taxes.\nGrand total: <color=#FF0000>1,000,000 yen</color>.",
    "・・・正気か？": "...Are you serious?",
    "ここは法治国家です\nあなたこそ正気ですか？": "This is a country governed by law.\nAre *you* the one being serious?",
    "教主様ここは従いましょう": "Master, let's just comply for now.",
    "・・・ほら\n持っていけ": "...Here.\nTake it.",
    "げ、現ナマっすか・・・\nまあいいですけど、確かに受け取りました": "C-cash, huh...\nWhatever. Receipt confirmed.",
    "ではまた・・・(もう来たくねー)": "Until next time... (Don't wanna come back here.)",
    "教主様　国家に目を付けられてしまいましたね": "Master — the state has its eye on us now.",
    "わかった　気を付けよう": "Understood. We'll be careful.",
    "にしても気に食わないやつだな": "Still, that guy gets on my nerves.",
    "巫女よ　政界に入り込むために必要な資産を教えてくれ": "Maiden — tell me how much wealth we'd need to break into politics.",
    "大体10億円ほどあれば政界進出は可能かと思われます": "Around one billion yen should be enough to enter politics.",
    "よし　目下の目標はそれだ": "Good. That's our immediate target.",
    "クソ役人どもの鼻を明かしてやろう": "We'll wipe the smug grins off those bureaucrats' faces.",

    # Master + Maiden bedroom scene (post-Office 1)
    "よし、じゃあ景気付けに一発種付けしてやる": "Right then. To celebrate, I'll plant my seed in you as a kickoff.",
    "巫女　横になれ": "Maiden. Lie down.",
    "はい　承知いたしました・・・": "Yes — as you wish...",
    "教主様・・・": "Master...",
    "お慕いしております・・・": "I adore you...",
    "分かっている": "I know.",
    "ずいぶん濡れているな": "You're awfully wet.",
    "は、はい・・・その・・・\nう、うれしくて・・・つい・・・": "Y-yes... it's just...\nI-I'm so happy I... can't help it...",
    "バカにでかい胸しやがってからに": "Look at those ridiculously huge tits of yours.",
    "これも神の思し召しか？": "Is this also by God's design?",
    "は、はい・・・教主様に癒しを齎すため\n我らが神がお与えになったものだと思っております": "Y-yes... I believe our god gave them to me\nso that I might bring you comfort, Master.",
    "その通りだ、お前は俺のために生きている\nそうだろ？": "Exactly. You exist for me.\nIsn't that right?",
    "ふん、では子種をくれてやる": "Hmph. Then I'll give you my seed.",
    "ありがとうございます！": "Thank you, Master!",
    "よ　よろしくお願いします・・・教主様": "P-please use me well... Master.",
    "ふぁ・・・ありがとうございます\nありがとうございます！": "Hahh... thank you, Master,\nthank you!",
    "私めはこのためにいきております\n教主様から恩寵を賜るために・・・！": "I live for this — \nto receive your grace, Master...!",
    "そら！出すぞ！": "There — I'm coming!",
    "ああっ・・・出ております\n私めの膣内で\n教主様の子種・・・": "Ahh... it's spilling out\ninside me —\nMaster's seed...",
    "一滴たりとも無駄にするなよ\n今後はまんこに封でもしておけ": "Don't waste a single drop.\nGo plug your pussy up afterward.",
    "はい　教主様・・・\nありがとうございました": "Yes, Master...\nThank you, truly.",

    # GovernmentOffice 2 — second visit
    "ごきげんよう\n政府の犬": "Good day to you,\ngovernment lapdog.",
    "・・・はい\nごきげんようございます": "...Yes.\nGood day to you as well.",
    "税金の徴収です": "I'm here to collect taxes.",
    "<color=#FF0000>1000万円</color>ほど徴収します。": "I'll be collecting <color=#FF0000>10,000,000 yen</color>.",
    "いい度胸だな": "You've got nerve.",
    "これも仕事なので　できれば穏便に済ませたいのですが・・・": "It's just my job. I'd rather settle this quietly...",
    "くれてやるさ": "Fine. Take it.",
    "ご協力感謝します": "Thank you for your cooperation.",
    "まだなにか？": "Anything else?",
    "このところあなた方教団の発展はめざましいものがありますね": "Your organization's growth lately has been remarkable.",
    "どのような活動をされているのか具体的に伺ってもよろしいでしょうか": "Mind walking me through what you actually do here, in concrete terms?",
    "ただのピラティス教室ですが・・・": "We're just a Pilates studio...",
    "貴方も興味がありますか？": "Are you interested too?",
    "お疲れのようだ　くまもひどい\nストレス解消にも効果てきめんですよ": "You look exhausted — the bags under your eyes are awful.\nIt's wonderfully effective for stress relief, you know.",
    "チッ・・・（誰のせいだか）": "Tch... (Whose fault is that.)",
    "いえお気持ちだけ\nでは　これで・・・": "No, the thought's enough.\nWell then, I'll be off...",
    "はい　道中お気をつけて": "Yes — take care on your way.",
    "・・・（クソったれが）": "...(Bastard.)",
    "寝室に来い": "Come to the bedroom.",
    "承知致しました。": "As you wish.",

    # Master + Fanatic bedroom scene
    "きょ、教主様・・・これは・・・": "M-Master... what is this...?",
    "なんだ　文句でもあるのか？": "What. Got a problem?",
    "い　いえ滅相もございません": "N-no, of course not.",
    "・・・舐めろ": "...Lick.",
    "(どうにか官僚を取り込めないか・・・）": "(Maybe I can rope this bureaucrat in somehow...)",
    "れろ・・・れろ・・・": "Lap... lap...",
    "はい　なんでしょうか": "Yes — what is it?",
    "官僚の動きをマークしてくれ\nあいつに何か弱みがないか知りたい": "Keep tabs on that bureaucrat for me.\nI want to know if he's got any weak spots.",
    "あ　あの・・・教主様？": "U-um... Master?",
    "ぐぁ・・・\n教　主　さ　ま　・・・": "Guhh...\nM... a... s... t... e... r...",
    "お前こういうの好きだろ　ほら": "You like this kind of thing, don't you. Here.",
    "あ　あり　がとう　ござ　い・・・": "Th... thank... y... you...",
    "んっ・・・！\nはあ　はあ": "Nngh...!\nHaa, haa...",
    "礼はどうした": "Where's your thanks?",
    "申し訳ありません！ありがとうございます！！": "I'm sorry! Thank you, Master!!",
    "あっありがとうございます！ありがとうございます！": "Ah, thank you! Thank you!",
    "恩寵を、私にも・・・！": "Bestow your grace on me too...!",
    "ありがとうございます\nお子種、拝領させていただきました": "Thank you, Master.\nI have humbly received your seed.",
    "お前が献身的に働いているのは分かっている\nこれからも俺のために尽くしてくれ": "I know how devotedly you serve me.\nKeep giving yourself to me from here on, too.",
    "はい・・・はい・・・！\n教主様・・・！": "Yes... yes...!\nMaster...!",

    # GovernmentOffice 3 — Master flips the table on the bureaucrat
    "また来たか": "Back again?",
    "おまえ・・・・・・": "You...",
    "また徴収か\nご苦労なことだな": "Another shake-down, huh.\nMust be hard work.",
    "これでお金をもらっていますので・・・": "It's what they pay me for...",
    "今回は5000万円になります": "This round it's 50,000,000 yen.",
    "・・・そうだな": "...I see.",
    "1200万円だな": "Twelve million, then.",
    "お前　俺がキャッシュで渡すのをいいことにピンハネしてるだろ": "You've been skimming off the top — taking advantage of the fact I pay in cash.",
    "・・・知りませんね": "...I wouldn't know.",
    "もしそうだとしても違法性が高いのはあなたたちです": "Even if I were, the bigger crime is on your side.",
    "それだけの資産　どのようにして得たのですか？": "How exactly did you come by that kind of wealth?",
    "そこの女が何をしているのかわかっているのですか？": "Do you have any idea what that woman over there is doing?",
    "狂信者　下がれ": "Fanatic. Stand down.",
    "お前は今　俺にすまないことをしたなという気持ちがある": "Right now, you feel like you've done me wrong.",
    "それはここが法治国家であることよりも　もっとプリミティブな感情だ": "That feeling is more primitive than any rule of law.",
    "なにがいいたいんですか": "What are you trying to say?",
    "協力しろ": "Cooperate.",
    "俺達にはお前を恨む理由ができた\nお前はそれを理解した": "We now have reason to hold a grudge against you.\nAnd you understand that.",
    "お前に贖罪の権利を与えてやろうというのだ": "I'm offering you the chance to atone.",
    "金が欲しいんだろ？\n<color=#FF0000>1億円くれてやる</color>": "You want money, don't you.\n<color=#FF0000>I'll give you 100,000,000 yen.</color>",
    "税金を支払ったらここに来い": "Once you've paid the taxes, come back here.",
    "返事はどうした": "Where's your answer?",
    "わかりました": "Understood.",
    "教主様　これを狙ってキャッシュで税金を払っていたのですか？": "Master — were you paying in cash all along, aiming for this?",
    "ん？　あー　そうだな": "Hm? Ahh, that's right.",
    "流石です　偉大なる教主": "As expected, my great Master.",

    # JoinFanatic
    "狂信の座\n拝命致しました": "I have been entrusted\nwith the Seat of Fanaticism.",
    "我らが神に逆らう不善のモノは\n私が浄化しましょう": "Any wicked soul who defies our god\nshall be purified by my hand.",
    "彼女は信者の数に応じた寄付金を瞬時に得ることができます": "She can instantly produce donations scaled to your number of followers.",
    "戻ったら彼女も拠点に来ていると思いますので、キャラ切替をして確認してみてください": "She should be at the hideout when you return — try switching characters to check.",
    "いよいよ大詰めです": "We're entering the home stretch.",
    "私たちの教義を国教に押し上げましょうね": "Let's elevate our doctrine to the state religion.",
    "彼女はアクティブな信者を一人選び\n資産に変換することができます": "She can pick one active follower\nand convert them into wealth.",
    "選んだ信者は復活しないので、執務室で補充するのをお忘れなきよう": "The chosen follower won't revive, so don't forget to replenish them in the Office.",
    "Rキー、または私の上のボタンを押してキャラを切り替えてみてください": "Press R, or the button above me, to switch characters.",
    "しかし彼女はどうやって資産に変換しているのだ": "But how exactly is she turning them into wealth?",

    # JoinMissionary
    "布教の座\n拝命致しました！": "I have been entrusted\nwith the Seat of Evangelism!",
    "世界中すべての人に配給しましょう！\n奇跡のような教えを教えのような奇跡を！": "Let's deliver it to everyone in the world!\nTeachings like miracles, miracles like teachings!",
    "なんですかそれは": "What's that supposed to mean?",
    "彼女は資産の何割かを用いて信者を得ることができます": "She can spend a portion of your wealth to gain new followers.",
    "信者が多いほど得られる寄付金も多くなります。積極的に活用しましょう。": "The more followers you have, the bigger the donations. Make active use of her.",
    "なんかいい感じに適当にやります！": "I'll just wing it and make it work somehow!",
    "あ　ああ\nよろしく頼んだ": "A-ah, right.\nI'm counting on you.",

    # Master + Missionary bedroom scene
    "教主・・・いる？": "Master... you in there?",
    "ん？ああいるぞ　どうした": "Hm? Yeah, I'm here. What is it?",
    "いや　どうって": "Nothing in particular.",
    "最近元気にされてますか？": "Have you been holding up okay lately?",
    "あんだけ景気よく種付け種付け仕事仕事で疲れたりしてないかなーってね": "Just wondering whether all that breeding-breeding-working-working hasn't worn you out, you know.",
    "・・・大丈夫だ": "...I'm fine.",
    "うそだ": "Liar.",
    "なんのつもりだ": "What are you doing?",
    "好きでしょ？\n遠慮しなくてもいいですよ": "You like this, don't you?\nNo need to hold back.",
    "よしよし　教主様いっぱい頑張ってるよ": "There, there. Master's been working so hard.",
    "私見てるからね・・・": "I've been watching you, you know...",
    "私はお金のためにがんばってるだけだから\n大丈夫　強がんなくてもいいんだよ": "I'm only in this for the money, after all —\nso it's okay. You don't have to put on a brave face.",
    "おちんちん辛くない？": "Isn't your cock aching?",
    "ほら、出して・・・": "Come on now, let it out...",
    "よいしょっと　んっ": "Heave-ho... mn.",
    "どう？": "How's that?",
    "（刺激は弱いが、何故かとても幸せに感じる）": "(The stimulation is gentle, but somehow it feels wonderfully blissful.)",
    "いい・・・": "Feels good...",
    "そ・・・": "I see...",
    "ツユが垂れちゃってる\nもうしちゃおっか・・・": "Your precum is dripping out...\nLet's just go ahead and do it, hm...",
    "私が動いたげるから、楽にしてていいよ": "I'll do the moving, so just relax.",
    "あんっ　もう・・・": "Ahn — geez...",
    "そんなにおっぱい好き？": "You like boobs that much?",
    "動くね・・・": "I'm going to start moving...",
    "んっ　ふっ・・・\nどう？きもちい？": "Mn, fuh...\nHow is it? Feel good?",
    "ああ・・・きもちいい": "Yeah... feels great.",
    "よしよし　我慢しなくてもいいよ\n好きな時に出して": "There, there. No need to hold it in.\nCome whenever you like.",
    "びゅーーーーーーっ": "Spuuuuurt!",
    "ぜーんぶだして\nほら　だして": "Let it aaaall out.\nCome on now — give me everything.",
    "よしよし　元気に射精できたね\nえらいぞー": "There, there. You came so hard.\nGood boy.",
    "疲れたらおいで　疲れてなくてもおいで\nいつでも歓迎だよ": "Come by when you're tired. Come by even when you're not.\nYou're welcome any time.",
}

TEXTS_EN: dict[str, str] = {
    "Config\n\nBGM\n・魔王魂\nhttps://maou.audio/\n\nSE\n・効果音ラボ\nhttps://soundeffect-lab.info/agreement/\n\n製作者\n・てぶなん\nhttps://x.com/3_on_2":
        "Config\n\nBGM\n・Maou Soul\nhttps://maou.audio/\n\nSE\n・Sound Effect Lab\nhttps://soundeffect-lab.info/agreement/\n\nCreator\n・Tebunan\nhttps://x.com/3_on_2",
    "ゲームを終了しますか？": "Quit the game?",
    "ジャンプする": "Jump",
    "キャンセル": "Cancel",
    "ゲームをプレイしてくださってありがとうございます。\nバグ、感想等ございましたらマシュマロ、レビューいただけると幸いです。\n\n制作と関係のないツイートが多いですが、フォローしていただけると励みになります。":
        "Thank you for playing!\nIf you find any bugs or have thoughts to share, I'd love a marshmallow message or a review.\n\nMost of my posts aren't dev-related, but a follow would really encourage me.",
    "作者　TwitterLink": "Author Twitter Link",
    "作者　Twitter(現 X)にジャンプします。\n引き返すなら今ですが大丈夫ですか？":
        "This will take you to the author's Twitter (now X).\nLast chance to turn back — are you sure?",
    "終了する": "Quit",
    "宣教師": "Missionary",
    "もどる": "Back",
    "はい": "Yes",
    "巫女": "Maiden",
    "官僚強化": "Bureaucrat Upgrade",
    "信徒勧誘": "Recruit Followers",
    "回想": "Recollection",
    "執務室": "Office",
    "信者追加(Shift）": "Add Follower (Shift)",
    "宣教師強化": "Missionary Upgrade",
    "巫女強化": "Maiden Upgrade",
    "狂信者強化": "Fanatic Upgrade",
    "調伏自動化3": "Auto-Subdue 3",
    "WASD:カーソル移動 Space:決定/調伏 Shift:信者導入 Q:寝室 E:ショップ F:スキルチャージ R:キャラ変更 テンキー:アイテム使用 ESC:戻る":
        "WASD: Move Cursor   Space: Confirm/Subdue   Shift: Send Follower   Q: Bedroom   E: Shop   F: Charge Skill   R: Switch Character   Numpad: Use Item   ESC: Back",
    "戻る": "Back",
    "調伏自動化2": "Auto-Subdue 2",
    "調伏自動化1": "Auto-Subdue 1",
    "～信仰値ボーナス～": "～ Faith Bonus ～",
    "狂信者": "Fanatic",
    "調伏自動化4": "Auto-Subdue 4",
    "寝室": "Bedroom",
}


def normalize(s: str) -> str:
    # collapse "\\n" (literal backslash-n, 2 chars) to actual newline; strip CR
    return s.replace("\r", "").replace("\\n", "\n").strip()


def apply(json_path: Path, mapping: dict[str, str]) -> None:
    original = json.loads(json_path.read_text(encoding="utf-8"))
    norm_map = {normalize(k): v for k, v in mapping.items()}
    out: dict[str, str] = {}
    missing: list[str] = []
    for k in original:
        en = norm_map.get(normalize(k), "")
        out[k] = en
        if not en:
            missing.append(k)
    extra = [k for k in mapping if normalize(k) not in {normalize(x) for x in original}]
    if missing:
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
        print(f"  WARN {json_path.name}: {len(missing)} key(s) missing translation:")
        for k in missing[:10]:
            print(f"    - {k!r}")
    if extra:
        print(f"  WARN {json_path.name}: {len(extra)} mapping key(s) not in source:")
        for k in extra[:10]:
            print(f"    - {k!r}")
    json_path.write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"  wrote {json_path} ({sum(1 for v in out.values() if v)}/{len(out)} translated)")


IL2CPP_EN: dict[str, str] = {
    # screenshot strings
    "-信仰値 {0}/{1}": "-Faith {0}/{1}",
    "-信者   {0}人": "-Followers   {0}",
    "-資産   ": "-Wealth   ",
    "信仰値": "Faith",
    "信仰値{0}": "Faith {0}",
    "信徒": "Follower",
    "信者 {0}/{1}  費用:{2}": "Followers {0}/{1}  Cost: {2}",
    "信者 {0}/{1} (MAX)": "Followers {0}/{1} (MAX)",
    "信者　{0}人": "Followers　{0}",
    "寄付金": "Donations",
    "資産　": "Wealth　",

    # color-tagged inline labels
    "\n<size=80%><color=red>コスト: ": "\n<size=80%><color=red>Cost: ",
    "<color=#87CEEB>信徒+{0}</color>": "<color=#87CEEB>Followers +{0}</color>",
    "<color=#FFD700>信仰+{0}</color>": "<color=#FFD700>Faith +{0}</color>",
    "<color=green>+{0}円</color>": "<color=green>+{0} yen</color>",
    "<color=red>お金が足りません</color>": "<color=red>Not enough money</color>",
    "<color=red>費用　": "<color=red>Cost　",
    "<color=yellow>【マイルストーン到達】</color> ": "<color=yellow>[Milestone Reached]</color> ",
    "/体</color>\n": " ea.</color>\n",
    "/回</color>\n": " / use</color>\n",
    "</color>/体\n": "</color> ea.\n",
    "</color>/回\n": "</color> / use\n",
    "</color>獲得": "</color> gained",

    # event / unlock messages
    "EVENT1再生後に解放": "Unlocks after EVENT1",
    "EVENT2再生後に解放": "Unlocks after EVENT2",
    "EVENT3再生後に解放": "Unlocks after EVENT3",
    "が利用可能になりました": " is now available",
    "ショップで購入できるものがあります！": "New items available in the shop!",
    "ショップを閉じる": "Close shop",
    "ストーリーを再生しますか？": "Play this story?",
    "回想するストーリーを\n選んでください。": "Select a story\nto recall.",
    "未解放": "Locked",

    # currency / units. JP numbers split at 4-digit (万) and 8-digit (億)
    # boundaries, e.g. 1万8860円 = "1" + "8860 yen" = 18,860 yen. Dropping
    # the unit lets digits concatenate naturally so the runtime composite
    # reads as a normal English number.
    "{0}万": "{0}",
    "{0}億": "{0}",
    "{0}円": "{0} yen",
    "円": "yen",
    "秒": "sec",
    "分": "min",
    "時": "hr",
    "月": "mo",
    "年": "yr",
    "日": "day",

    # skill-bracket effect names
    "【信仰継続】信仰値の20%を受け取る (+{0})": "[Sustained Faith] Receive 20% of Faith (+{0})",
    "【信者拡大】信徒数+{0}人": "[Follower Expansion] Followers +{0}",
    "【初回アンロック】官僚のスキルを解放する\n税収スキルが使用可能になる\n税収：<color=green>":
        "[First Unlock] Unlock Bureaucrat's skill\nTax-Collection becomes available\nRevenue: <color=green>",
    "【初回アンロック】宣教師のスキルを解放する\n":
        "[First Unlock] Unlock Missionary's skill\n",
    "【初回アンロック】狂信者のスキルを解放する\n殺戮スキルが使用可能になる\n報酬：<color=green>":
        "[First Unlock] Unlock Fanatic's skill\nSlaughter becomes available\nReward: <color=green>",
    "【調伏強化Lv{0}】Idle2調伏が1/30確率で2倍":
        "[Subdue Boost Lv{0}] 1/30 chance for Idle2 subdue to deal 2×",
    "【魂の取引】<color=green>{0:F0}秒間 収入{1:F0}倍</color>\n<color=red>信徒が{2}人減少</color>":
        "[Soul Bargain] <color=green>{1:F0}× income for {0:F0}s</color>\n<color=red>{2} followers lost</color>",

    # core game actions
    "代償：資産の<color=red>{0:0.#}%</color>を消費\n":
        "Cost: spend <color=red>{0:0.#}%</color> of wealth\n",
    "信者を増やす（数値のみ）\n現在：{0} / {1}人\n<color=green>追加後：{2}人</color>\n<color=red>費用　{3}</color>":
        "Add followers (count only)\nCurrent: {0} / {1}\n<color=green>After: {2}</color>\n<color=red>Cost　{3}</color>",
    "信者を追加する（画面に出現）\n現在：{0} / {1}人\n<color=green>追加後：{2}人</color>\n<color=red>費用　{3}</color>":
        "Add follower (spawned on screen)\nCurrent: {0} / {1}\n<color=green>After: {2}</color>\n<color=red>Cost　{3}</color>",
    "信者数の<color=green>{0:0.#}%</color>を即時獲得\n":
        "Instantly gain <color=green>{0:0.#}%</color> of follower count\n",
    "倍額報酬 Lv.{0}　<color=green>{1}%</color>の確率で報酬2倍":
        "Double Reward Lv.{0}　<color=green>{1}%</color> chance for 2× reward",
    "回想": "Recollection",
    "報酬": "Reward",
    "報酬：": "Reward: ",
    "夜伽を行う": "Spend the night",
    "大量勧誘　信者<color=green>+{0}</color>人　資産<color=red>-{1}</color>":
        "Mass Recruitment　Followers <color=green>+{0}</color>　Wealth <color=red>-{1}</color>",

    # role skills
    "官僚のスキルを強化する\n": "Upgrade Bureaucrat's skill\n",
    "官僚の働きにより 資産<color=green>{0}</color>を獲得 信者<color=red>-{1}</color>人":
        "Bureaucrat collected <color=green>{0}</color> wealth, costing <color=red>{1}</color> followers",
    "官僚の訪問": "Bureaucrat's Visit",
    "宣教師のスキルを強化する\n": "Upgrade Missionary's skill\n",
    "宣教師の働きにより 信徒を<color=green>{0}</color>人獲得　資産<color=red>-{1}</color>":
        "Missionary recruited <color=green>{0}</color> followers　Wealth <color=red>-{1}</color>",
    "宣教師の賢者時間　資産の10%を消費　信者数の<color=green>{0:0.#}%</color>を獲得":
        "Missionary's Refractory　Spend 10% wealth　Gain <color=green>{0:0.#}%</color> of follower count",
    "巫女のスキルを強化する\n": "Upgrade Maiden's skill\n",
    "巫女の賢者時間　残り<color=red>{0}</color>秒　得られる寄付金と信仰値が<color=green>{1:0.##}</color>倍":
        "Maiden's Refractory　<color=red>{0}</color>s left　Donations & Faith ×<color=green>{1:0.##}</color>",
    "教義の緩和\n信仰値を<color=green>{0}下げる</color>\n<color=red>費用　{1}</color>":
        "Soften Doctrine\nReduce Faith by <color=green>{0}</color>\n<color=red>Cost　{1}</color>",
    "狂信の祝福により 信徒が<color=green>{0}</color>人に増加(+{1}) 資産が<color=red>{2}</color>減少":
        "Fanatic's Blessing raises followers to <color=green>{0}</color> (+{1}); wealth -<color=red>{2}</color>",
    "狂信者のスキルを強化する\n": "Upgrade Fanatic's skill\n",
    "狂信者の働きにより 信徒が<color=red>1</color>人減少 資産を<color=green>":
        "Fanatic's work: -<color=red>1</color> follower, +<color=green>",
    "狂信者の賢者時間　あと<color=red>{0}</color>人　信者を選び<color=green>{1}</color>に変換\n累計処理数:<color=yellow>{2}</color> 信仰値ボーナス:<color=green>+{3:0.#}%</color>":
        "Fanatic's Refractory　<color=red>{0}</color> left　Pick a follower → <color=green>{1}</color>\nProcessed: <color=yellow>{2}</color> Faith bonus: <color=green>+{3:0.#}%</color>",
    "獲物数：<color=green>{0}体</color>\n": "Prey: <color=green>{0}</color>\n",
    "税収：": "Revenue: ",
    "自動搾取装置\n信者を選択して自動搾取モードに変換します":
        "Auto-Harvest Device\nSelect a follower to convert into auto-harvest mode",
    "自動搾取装置({0})はロックされています\n{1}再生後に解除":
        "Auto-Harvest Device ({0}) is locked\nUnlocks after {1}",
    "自動搾取装置({0})をLv.{1}に強化しました":
        "Upgraded Auto-Harvest Device ({0}) to Lv.{1}",
    "調伏強化 Lv.{0}　Idle2で1/30確率2倍":
        "Subdue Boost Lv.{0}　Idle2: 1/30 chance for 2×",
    "魂の取引により <color=green>{0:F0}秒間収入{1:F0}倍</color> 信徒が<color=red>{2}</color>人減少":
        "Soul Bargain: <color=green>{1:F0}× income for {0:F0}s</color>; -<color=red>{2}</color> followers",

    # asset-load warnings (probably not user visible, but harmless)
    "' に対応するAnimationClipが見つかりません": "' has no matching AnimationClip",
    "' に対応するAudioClipが見つかりません": "' has no matching AudioClip",

    # the giant skill-upgrade panel format string
    "自動搾取装置({0})を強化する\n効果：{1}を獲得\n{2} → <color=green>Lv.{3}</color>\nCD：{4:F1}s → <color=green>{5:F1}s</color>\n倍率：×{6:F2} → <color=green>×{7:F2}</color>\n<color=yellow>※調伏・殺戮でゲージをチャージ可能</color>\n<color=red>費用　{8}</color>":
        "Upgrade Auto-Harvest Device ({0})\nEffect: gain {1}\n{2} → <color=green>Lv.{3}</color>\nCD: {4:F1}s → <color=green>{5:F1}s</color>\nMultiplier: ×{6:F2} → <color=green>×{7:F2}</color>\n<color=yellow>※ Subdue/slaughter charges the gauge</color>\n<color=red>Cost　{8}</color>",

    # MAX-level variant of the same panel
    "自動搾取装置({0})　<color=yellow>Lv.MAX</color>\n効果：{1}を獲得\nCD：{2:F1}秒　倍率：×{3:F2}\n<color=yellow>※調伏・殺戮でゲージをチャージ可能</color>":
        "Auto-Harvest Device ({0})　<color=yellow>Lv.MAX</color>\nEffect: gain {1}\nCD: {2:F1}s　Multiplier: ×{3:F2}\n<color=yellow>※ Subdue/slaughter charges the gauge</color>",

    # other skill-bracket effects (with placeholders)
    "【幸運の加護Lv{0}】調伏報酬が2倍になる確率：{1}% → <color=green>{2}%</color>":
        "[Luck's Blessing Lv{0}] Chance to double subdue reward: {1}% → <color=green>{2}%</color>",
    "【狂信の祝福】信徒{0} → <color=green>{1}人(+{2})</color>\n<color=red>資産が{3}減少</color>":
        "[Fanatic's Blessing] Followers {0} → <color=green>{1} (+{2})</color>\n<color=red>Wealth -{3}</color>",

    # role-specific multiplier and refractory line endings
    "お金倍率：×{0:F1} → <color=green>×{1:F1}</color>\n":
        "Money multiplier: ×{0:F1} → <color=green>×{1:F1}</color>\n",
    "信仰倍率：×{0:F1} → <color=green>×{1:F1}</color>\n":
        "Faith multiplier: ×{0:F1} → <color=green>×{1:F1}</color>\n",
    "チャージ：{0:F1}s → <color=green>{1:F1}s</color>\n":
        "Charge: {0:F1}s → <color=green>{1:F1}s</color>\n",
    "持続時間：{0:F0}s → <color=green>{1:F0}s</color>\n":
        "Duration: {0:F0}s → <color=green>{1:F0}s</color>\n",
    "獲物数：{0}体 → <color=green>{1}体</color>\n":
        "Prey count: {0} → <color=green>{1}</color>\n",
    "信者数の{0:0.#}% → <color=green>{1:0.#}%</color>を即時獲得\n":
        "Instantly gain {0:0.#}% → <color=green>{1:0.#}%</color> of follower count\n",

    # composite recruitment / donation breakdown
    "信者の寄付　<color=green>+{0}</color>\n信徒{1}×寄付率{2}×倍率{3:0.##}×Lv{4}":
        "Follower donations　<color=green>+{0}</color>\nFollowers {1} × rate {2} × multiplier {3:0.##} × Lv{4}",
    "日常的な勧誘　信徒<color=green>+{0}</color>人\n基礎{1}×ボーナス{2:0.##}×加速{3:0.##}×Lv{4}":
        "Routine recruitment　Followers <color=green>+{0}</color>\nBase {1} × bonus {2:0.##} × accel {3:0.##} × Lv{4}",
    "官僚の賢者時間　徴税<color=green>{0}</color>　信者{1}人×税率{2:0.##}":
        "Bureaucrat's Refractory　Tax <color=green>{0}</color>　Followers {1} × rate {2:0.##}",

    # tooltip-cost concat fragments — patterns ending in "費用 "
    "<color=yellow>※他スキルと同時発動で倍率が乗算</color>\n<color=red>費用　":
        "<color=yellow>※ Multipliers stack when used with other skills</color>\n<color=red>Cost　",
    "<color=yellow>※殺害時に自動化装置のゲージをチャージ</color>\n<color=red>費用　":
        "<color=yellow>※ Killing charges the auto-device gauge</color>\n<color=red>Cost　",

    # ASCII-only format strings the dumper skipped because they have no JP.
    # These are line snippets the game appends to character skill panels.
    "Lv.{0} → <color=green>Lv.{1}</color>\n":
        "Lv.{0} → <color=green>Lv.{1}</color>\n",

    # cost-line wrapper used after each character upgrade panel
    "<color=red>費用　{0}</color>": "<color=red>Cost　{0}</color>",
}

# Strings that have no Japanese characters get filtered out by the dumper.
# Add them here and apply will inject them into il2cpp_strings.json.
IL2CPP_INJECT: list[str] = [
    "Lv.{0} → <color=green>Lv.{1}</color>\n",
    "<color=red>費用　{0}</color>",
]


MESSAGES_EN: dict[str, str] = {
    # idle banter (bubbleMessages)
    "たこ焼きはソースがない方があっさりしていて美味しいですね":
        "Takoyaki is lighter and tastier without sauce, don't you think.",
    "寄付金は信者の数に比例して増加します\n積極的に信者を増やしていきましょうね":
        "Donations grow in proportion to follower count.\nLet's actively recruit more.",
    "調伏を行うと自動搾取装置のクールタイムを短縮できます\nガンガン種付けしていきましょう":
        "Subduing reduces the auto-harvest cooldown.\nLet's keep planting seed at full tilt.",
    "本日も張り切っていきましょう": "Let's give it our all again today.",
    "教主様　調子は如何でしょうか": "Master — how are you faring?",
    "おらー金よこせーい": "Oi — hand over the money!",
    "うんうん　みんな頑張ってんね！\nあっ　教主さまもね":
        "Mhm-hm. Everyone's working so hard!\nOh — and Master too, of course.",
    "あくまで監視ですから\n監視・・・":
        "I'm strictly here to observe.\nObserving...",
    "なにもせずにこんなにお金をもらって・・・\n良い御身分ですね":
        "Pulling in this kind of money without lifting a finger...\nMust be nice.",

    # skill charge bubbles (Master interrupts each follower)
    "あっ・・・教主様\nこんなところで・・・っ":
        "Ah... Master,\nright here..!",
    "ああっ・・・教主\nどうぞ望みのまま・・・":
        "Ahh... Master,\ndo as you please...",
    "あぅ・・・\nもっと乱暴しても大丈夫だよ・・・":
        "Mm...\nyou can be rougher, it's okay...",
    "ちょっと・・・\nもう・・・":
        "Hey...\ngeez...",

    # skill action bubbles
    "教主様の・・・\nアツい・・・・・・":
        "Master's... is so hot...",
    "んっ・・・\nああこれが祝福・・・":
        "Mn...\nahh, so this is His grace...",
    "んおー\nいっぱい出とるね\nきもちい？":
        "Mmh —\nyou're letting out a lot.\nFeel good?",
    "んっ・・・（きも）": "Mn... (gross.)",

    # event start prompts
    "イベント1を再生しますか？\n必要資産<color=#FF0000>100万円</color>":
        "Play Event 1?\nRequired wealth: <color=#FF0000>1,000,000 yen</color>",
    "イベント2を再生しますか\n必要資産<color=#FF0000>1000万円</color>":
        "Play Event 2?\nRequired wealth: <color=#FF0000>10,000,000 yen</color>",
    "イベント3を再生しますか\n必要資産<color=#FF0000>1億円</color>":
        "Play Event 3?\nRequired wealth: <color=#FF0000>100,000,000 yen</color>",
    "最終イベントを再生しますか\n必要資産<color=#FF0000>10億円</color>":
        "Play the final event?\nRequired wealth: <color=#FF0000>1,000,000,000 yen</color>",

    # event 0 — Maiden (devout, formal)
    "どうか私めに\n恩寵をお与えください・・・":
        "Please...\nbestow your grace upon me...",
    "どうぞ　ご自由に\n使ってくださいませ・・・":
        "Please —\nuse me freely...",
    "あっ　そこは・・・": "Ah... not there...",
    "あんっ・・・": "Ahn...",
    "んっ・・・": "Mn...",
    "あうっ・・・\nどうぞ　もっと・・・！":
        "Ahhn...\nplease — more...!",
    "あっ・・・　教主様\n出てますよ・・・・・・":
        "Ah... Master,\nit's coming out......",
    "さあ教主様・・・\nこちらにどうぞ・・・":
        "Master, this way...\nplease, come closer...",

    # event 1 — Fanatic (begs to be punished)
    "ああどうか\n罰をお与えください・・・":
        "Please...\npunish me...",
    "おぐっ・・・\nんぉ・・・・・・っ":
        "Gugh...\nnnh......!",
    "んぎっ・・・\nぁあ・・・":
        "Nngh...\nahhh...",
    "が・・・っ・・・\nヒュー・・・ヒュー・・・":
        "G...gh...\nwheeze... wheeze...",
    "ああっ！申し訳ありませんっ！\nありがとうございますっ！":
        "Ahh! I'm so sorry!\nThank you, Master!",
    "んああ・・っ！\nありがとうございます！もっと、もっと・・・！":
        "Nyaah..!\nThank you! More, more...!",
    "んぉ・・・\n・・・・・・っっ！\nはぁ　はぁ・・・":
        "Nnh...\n......!\nHaa, haa...",
    "教主様どうか・・・\n私めに罰を・・・恩寵を・・・":
        "Master, please...\npunish me... grace me...",

    # event 2 — Missionary (motherly, comforting)
    "んっ\nおいで・・・": "Mn —\ncome here...",
    "遠慮しなくてもいいんだよ": "You don't have to hold back.",
    "いいんだよー\n好きなだけ触んな？":
        "It's okay —\ntouch as much as you like, hm?",
    "おー\nよちよち": "Aww —\nthere, there.",
    "いいこ　いいこ": "Good boy, good boy.",
    "んっ・・・\nそんなに好きなん？":
        "Mn...\nyou like them that much?",
    "いいんだよ\n力抜いて・・・":
        "It's okay,\nrelax now...",
    "んっ　きもちい？\nそう・・・":
        "Mn — feel good?\nThat's right...",
    "イキそう？\nいいよ　ほら\n・・・っ！　ふう・・・":
        "About to come?\nIt's okay, here...\n...!  Whew...",
    "つかれたねえ・・・\nいいよ、こっちおいで・・・":
        "Tired, hm?\nIt's okay, come over here...",

    # short interjections
    "あぅ・・・ありがとうございます": "Mm... thank you, Master.",
    "うぁ・・・": "Wahh...",
    "あ　ありがとうございます！": "Th-thank you, Master!",
    "ぐっ・・・": "Ngh...",
    "どう・・・して・・・": "Why... why...",
}


def main() -> None:
    for base in (ROOT, PLUGIN_TL):
        d = base / "dialogues.json"
        t = base / "texts.json"
        i = base / "il2cpp_strings.json"
        m = base / "messages.json"
        if d.exists():
            print(f"applying dialogues -> {d}")
            apply(d, DIALOGUES_EN)
        if t.exists():
            print(f"applying texts -> {t}")
            apply(t, TEXTS_EN)
        if i.exists():
            print(f"applying il2cpp -> {i}")
            # ensure injected ASCII-only format strings exist as keys in the
            # source JSON before applying translations
            try:
                src = json.loads(i.read_text(encoding="utf-8"))
            except Exception:
                src = {}
            changed = False
            for k in IL2CPP_INJECT:
                if k not in src:
                    src[k] = ""
                    changed = True
            if changed:
                i.write_text(
                    json.dumps(src, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            apply(i, IL2CPP_EN)
        if m.exists():
            print(f"applying messages -> {m}")
            # supplement messages.json with anything we already translated in
            # dialogues.json (many bubble/event lines duplicate dialogue keys)
            combined = dict(MESSAGES_EN)
            for k, v in DIALOGUES_EN.items():
                combined.setdefault(k, v)
            for k, v in TEXTS_EN.items():
                combined.setdefault(k, v)
            apply(m, combined)


if __name__ == "__main__":
    main()
