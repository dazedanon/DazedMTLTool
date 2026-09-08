"""Check the reward/header reservation in the shared quest/equipment panel."""
import re
import build_catalog as bc

OLD_TEXT = ("A monster in the cave can turn people to stone, making it impossible "
            "for ordinary people to approach. The fairy saint's help is needed to "
            "collect materials there. Do not meet the monster's gaze.")

def audit(measurements):
    from layout_audit import wrap
    code = (bc.PROJECT/'source/gml/gml_Object_obj_shop_Draw_0.gml').read_text(encoding='utf-8')
    sprite_y = int(re.search(r'draw_sprite\(spr_ui_shop, -1, \d+, (\d+)\)', code)[1])
    assert 'draw_set_font(font_2);' in code
    body_y, width, pitch = map(int, re.search(
        r'draw_text_ext\(836, (\d+), scr_newline\(scr_text_quest\(.*\), (\d+)\), (\d+), 999\)', code).groups())
    assert 'draw_text_ext(836, 714, scr_newline(geo_down_text, 900), 39, 999);' in code
    reward_y = int(re.search(r'draw_text\(836, (\d+), tmp_str\)', code)[1])
    sprite = next(r for r in bc.read(bc.ROOT/'images/source/manifest.json') if r['sprite']=='spr_ui_shop')
    # Inspected frame: sprite-local y=732 is the top of the lower border.
    # Reserve two more pixels above that border for the font line box.
    bottom = sprite_y - sprite['origin'][1] + sprite['sprite_size'][1] - 20
    font = next(f for f in bc.read(bc.PROJECT/'source/snapshot.json')['fonts'] if f['name']=='font_2')
    line_height = font['line_height']
    capacity = 1 + (bottom-body_y-line_height)//pitch
    assert (reward_y,body_y,width,pitch,bottom,line_height,capacity)==(675,714,900,39,830,38,3)
    assert reward_y + line_height <= body_y
    old_lines = wrap(OLD_TEXT,width,font)
    assert len(old_lines)==4 and body_y+(len(old_lines)-1)*pitch+line_height>bottom
    rows = [r for r in measurements if r['context'] in ('quest','shop')]
    assert sum(r['context']=='quest' for r in rows)==17
    assert sum(r['context']=='shop' for r in rows)==231
    for row in rows:
        assert row['font']=='font_2' and row['width']==width
        assert row['rows']<=capacity
        assert body_y+(row['rows']-1)*pitch+line_height<=bottom
    report = {'quest_descriptions':17,'shop_equipment_rank_forms':231,
              'reward_y':reward_y,'body_y':body_y,'line_pitch':pitch,
              'font_line_height':line_height,'body_bottom':bottom,'body_capacity':capacity,
              'old_petrifying_gaze_rows':len(old_lines),'known_overflow_detected':True,
              'remaining_overflows':0,'rows':rows}
    bc.write(bc.ROOT/'build/quest-layout-audit.json',report)
    return report
