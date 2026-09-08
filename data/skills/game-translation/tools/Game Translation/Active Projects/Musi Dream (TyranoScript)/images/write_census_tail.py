"""Persist manual visual classification of contact sheets 10--18."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parent
inventory = json.loads((ROOT/'inventory.json').read_text(encoding='utf-8'))
candidate_ids = {343,345,346,356,357,358,359,402,403,404,410,411,412,413,414,415,416,417,418,419,420,421,422,471}
english_ids = set(range(268,287)) | {349,350,351,352,355} | set(range(363,387)) | {390,391,392,395,396,398,399,400,401,405,406,409} | set(range(423,441)) | {453,456,457,458,459,460,461,462,463,464,465,466,482,484,486,487,488,489} | set(range(492,502)) | {505,506,507,508,509}
transcriptions = {
 343: ['★お気に入り','虫を大量に産んでアヘってしまいました'],
 345: ['挿入ゲーム','ヒマリィの顔を見て、','「挿れる」か「止まる」か判断せよ！','判断ミスが続くとゲームオーバー！','８割以上挿入できてたらクリア！','リロード','挿れる','止まる','キケン','ヘタレ'],
 346: ['ミッション','ネットの海に漂っている、ヒマリィの産卵動画を見つけてください。'],
 356: ['虫をクリックして 尻を割れ目に擦ろう'],
 357: ['ヒマリィを起こさず 服を脱がそう 服をクリック'],
 358: ['キケン'], 359: ['ヘタレ'],
 402: ['CG鑑賞モード'],403: ['コンフィグ'],404: ['回想モード'],
 410: ['CGモード'],411: ['コンフィグ'],412: ['つづきから'],413: ['回想モード'],414: ['はじめから'],
 415: ['はやい'],416: ['ふつう'],417: ['挿れる'],418: ['つづきから'],419: ['はじめから'],420: ['止まる'],421: ['ゆっくり'],
 422: ['個別画像表示・消去 プラグイン'],
 471: ['ガイド','一括テーマ変換です。','どこで生れたかとんと見当がつかぬ。何でも薄暗いじめじめした所でニャーニャー泣いていた事だけは記憶している。','ガイド：一括テーマ変換です。','まだ、保存されているデータがありません。'],
}
rows=[]
for item in inventory:
 if item['id']<266: continue
 k=item['id']; representative=item['representative_id']
 row={'id':k,'path':item['path'],'sha256':item['sha256'],'representative_id':representative}
 if representative!=k:
  row.update(classification='duplicate_inherit',review_status='reviewed_duplicate',notes='Exact SHA-256 duplicate; classification follows representative.')
 else:
  row['classification']='needs_translation' if k in candidate_ids else ('already_english' if k in english_ids else 'no_translatable_text')
  row['review_status']='visually_reviewed'
  row['evidence']='Contact sheets 10--18; native/3x candidate crops under census_zoom.'
  if 268<=k<=286 or k in {349,350,351,352}: row['notes']="Shirt is Latin 'Kiwi' beside a bird drawing; retain unchanged. Native chest crops 268/271/276 independently inspected."
  if k in transcriptions: row['source_blocks']=transcriptions[k]
  if item['frames']>1: row['animation_review']={'frames_reviewed':item['frames'],'result':'Only hearts, musical notes, or next-page dots; no text in any frame.'}
 rows.append(row)
report={'reviewer':'manual offline visual audit','scope':'Contact sheets 10--18, inventory IDs 266--516. Exact duplicates inherit their representatives.','unique_images_visually_reviewed':sum(r['representative_id']==r['id'] for r in rows),'candidate_unique_count':len(candidate_ids),'rows':rows}
(ROOT/'census_tail.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(f"Wrote {len(rows)} records; {report['unique_images_visually_reviewed']} unique; {len(candidate_ids)} text candidates.")
