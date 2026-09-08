"""One-time, source-evidenced glossary seed. Refuses to erase completed entries."""
import project as p

fixed={'お鈴':'Orin','甜瓜':'Meron','姫乃':'Himeno','凛風':'Rinfa','ハク':'Haku','初音':'Hatsune','ホクサイ':'Hokusai','高尾':'Takao','お松':'Omatsu','？？？':'???'}
generic={'夜見世客':'Nighttime Customer','男Ａ':'Man A','男Ｂ':'Man B','男':'Man','鬼の遊女':'Oni Courtesan','蜘蛛の遊女':'Spider Courtesan','遊女':'Courtesan','客':'Customer','なじみ客':'Regular Customer','使い':'Messenger','お好み焼き屋':'Okonomiyaki Vendor','まんじゅう屋':'Manju Vendor','ラーメン屋':'Ramen Vendor','雑貨屋':'General Store Owner','男妖怪':'Male Yokai','女妖怪':'Female Yokai','飴屋':'Candy Vendor','占い屋':'Fortune Teller','楼主':'Brothel Owner','トクガワ家使い':'Tokugawa Messenger','遊女Ａ':'Courtesan A','遊女Ｂ':'Courtesan B','店員':'Shopkeeper','行灯売り':'Lantern Vendor','泥棒':'Thief','町人':'Townsman','女':'Woman','補陀落の下女':'Fudaraku Maid','禿':'Kamuro','女Ａ':'Woman A','女Ｂ':'Woman B','補陀落浄土の使い':'Fudaraku Pure Land Messenger','かんざし屋':'Hairpin Vendor'}
_,units=p.load_catalog(False)
old=p.read_json(p.ROOT/'glossary.json') if (p.ROOT/'glossary.json').exists() else {'names':{}}
rows={}
for u in units:
    if u.kind!='name':continue
    name=u.src;base=name.removeprefix('m_');en=fixed.get(base,generic.get(base))
    if name.startswith('m_') and en:en='m_'+en
    prior=old['names'].get(name,{})
    rows[name]={'en':prior.get('en') or en,'gender':'female' if base in ['お鈴','甜瓜','姫乃','凛風','ハク','初音','高尾','お松'] else 'unknown',
               'role':'principal character' if base in fixed else 'literal speaker label',
               'register':'follow the source scene','aliases':[],
               'evidence':'main/1_1.ks registration IDs; char_all_list.ks roster. Minor readings remain unresolved.'}
p.write_json(p.ROOT/'glossary.json',{'meta':{'game':'Yume Yoshiwara no Ayakashi Giro','status':'seeded; minor readings need names pass'},'names':rows,
    'terms':{'夢吉原':'Yume Yoshiwara','妖怪':'yokai','妓楼':'brothel','両':'ryo'},
    'do_not_translate':['projectID','package.name','character IDs','state keys','asset paths','jump labels']})
print('Seeded:',len(rows),'Unresolved:',[k for k,v in rows.items() if not v['en']])
