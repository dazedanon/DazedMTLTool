draw_set_alpha(geo_alpha);
draw_sprite(spr_talent_bg, -1, x, y);
for (var tmp_i = 1; tmp_i <= 3; tmp_i += 1)
{
    for (var tmp_j = 1; tmp_j <= 9; tmp_j += 1)
    {
        if (geo_line_r[tmp_i][tmp_j] == 1)
        {
            draw_sprite(spr_talent_line, -1, x + 85 + (80 * (tmp_i - 1)), y + 50 + (80 * (tmp_j - 1)));
        }
    }
}
for (var tmp_i = 1; tmp_i <= 4; tmp_i += 1)
{
    for (var tmp_j = 1; tmp_j <= 8; tmp_j += 1)
    {
        if (geo_line_d[tmp_i][tmp_j] == 1)
        {
            draw_sprite(spr_talent_line_2, -1, x + 45 + (80 * (tmp_i - 1)), y + 90 + (80 * (tmp_j - 1)));
        }
    }
}
for (var tmp_i = 1; tmp_i <= 4; tmp_i += 1)
{
    for (var tmp_j = 1; tmp_j <= 9; tmp_j += 1)
    {
        if (geo_talent[tmp_i][tmp_j] > 0)
        {
            var tmp_spr;
            if (geo_talent[tmp_i][tmp_j] <= 9)
            {
                tmp_spr = asset_get_index("spr_talent_" + string(geo_talent[tmp_i][tmp_j]));
            }
            else
            {
                if (geo_talent[tmp_i][tmp_j] == 11)
                {
                    tmp_spr = asset_get_index("spr_skill_" + string(geo_skill[1]));
                }
                if (geo_talent[tmp_i][tmp_j] == 12)
                {
                    tmp_spr = asset_get_index("spr_skill_" + string(geo_skill[2]));
                }
                if (geo_talent[tmp_i][tmp_j] == 13)
                {
                    tmp_spr = asset_get_index("spr_skill_" + string(geo_skill[3]));
                }
            }
            draw_sprite(spr_talent_0, -1, x + 45 + (80 * (tmp_i - 1)), y + 50 + (80 * (tmp_j - 1)));
            if (geo_talent[tmp_i][tmp_j] < 10)
            {
                gpu_set_fog(1, #392722, 0, 0);
            }
            if (geo_talent[tmp_i][tmp_j] == 11 || geo_talent[tmp_i][tmp_j] == 12)
            {
                gpu_set_fog(1, #4975F0, 0, 0);
            }
            if (geo_talent[tmp_i][tmp_j] == 13)
            {
                gpu_set_fog(1, #C312E3, 0, 0);
            }
            draw_sprite(tmp_spr, -1, x + 45 + (80 * (tmp_i - 1)), y + 50 + (80 * (tmp_j - 1)));
            gpu_set_fog(0, c_white, 0, 0);
            if (geo_talent_can[tmp_i][tmp_j] < 2)
            {
                gpu_set_fog(1, c_black, 0, 0);
                draw_sprite_ext(spr_talent_0, -1, x + 45 + (80 * (tmp_i - 1)), y + 50 + (80 * (tmp_j - 1)), 1, 1, 0, -1, 0.4 * geo_alpha);
                gpu_set_fog(0, c_white, 0, 0);
            }
            if (geo_talent_can[tmp_i][tmp_j] == 1 && geo_now == 1 && global.role_point > 0 && !(geo_mouse_x == tmp_i && geo_mouse_y == tmp_j))
            {
                draw_sprite_ext(spr_talent_can, -1, x + 45 + (80 * (tmp_i - 1)), y + 50 + (80 * (tmp_j - 1)), 1, 1, 0, -1, geo_can_alpha);
            }
            if (geo_talent_can[tmp_i][tmp_j] == 1 && geo_now == 0 && !(geo_mouse_x == tmp_i && geo_mouse_y == tmp_j))
            {
                draw_sprite_ext(spr_talent_can, -1, x + 45 + (80 * (tmp_i - 1)), y + 50 + (80 * (tmp_j - 1)), 1, 1, 0, -1, 0.75);
            }
        }
    }
}
if (geo_mouse == 1)
{
    gpu_set_fog(1, c_white, 0, 0);
    draw_sprite_ext(spr_talent_bg, -1, x, y, 1, 1, 0, -1, 0.2);
    gpu_set_fog(0, c_white, 0, 0);
}
if (geo_now != -1 && geo_mouse_x > 0 && geo_mouse_y > 0 && geo_talent[geo_mouse_x][geo_mouse_y] > 0)
{
    draw_sprite(spr_talent_mouse, -1, x + 45 + (80 * (geo_mouse_x - 1)), y + 50 + (80 * (geo_mouse_y - 1)));
    var tmp_x = x + 17 + (80 * (geo_mouse_x - 1));
    var tmp_y = y + 78 + (80 * (geo_mouse_y - 1));
    if (tmp_x > 1638)
    {
        tmp_x = 1638;
    }
    draw_sprite(spr_talent_bg_2, -1, tmp_x, tmp_y);
    var tmp_spr = spr_no;
    if (geo_talent[geo_mouse_x][geo_mouse_y] <= 9)
    {
        tmp_spr = asset_get_index("spr_talent_" + string(geo_talent[geo_mouse_x][geo_mouse_y]));
    }
    else
    {
        if (geo_talent[geo_mouse_x][geo_mouse_y] == 11)
        {
            tmp_spr = asset_get_index("spr_skill_" + string(geo_skill[1]));
        }
        if (geo_talent[geo_mouse_x][geo_mouse_y] == 12)
        {
            tmp_spr = asset_get_index("spr_skill_" + string(geo_skill[2]));
        }
        if (geo_talent[geo_mouse_x][geo_mouse_y] == 13)
        {
            tmp_spr = asset_get_index("spr_skill_" + string(geo_skill[3]));
        }
    }
    gpu_set_fog(1, c_white, 0, 0);
    if (geo_talent[geo_mouse_x][geo_mouse_y] == 11 || geo_talent[geo_mouse_x][geo_mouse_y] == 12)
    {
        gpu_set_fog(1, #4975F0, 0, 0);
    }
    if (geo_talent[geo_mouse_x][geo_mouse_y] == 13)
    {
        gpu_set_fog(1, #C312E3, 0, 0);
    }
    draw_sprite(tmp_spr, -1, tmp_x + 32, tmp_y + 32);
    gpu_set_fog(0, c_white, 0, 0);
    if (geo_talent[geo_mouse_x][geo_mouse_y] <= 9)
    {
        draw_set_font(font_b1);
        draw_text(tmp_x + 66, tmp_y + 7, scr_name_talent(geo_talent[geo_mouse_x][geo_mouse_y]));
        draw_set_font(font_b2);
        var tmp_str = scr_text_talent(geo_talent[geo_mouse_x][geo_mouse_y]);
        draw_text_ext(tmp_x + 18, tmp_y + 56, scr_newline(tmp_str, 280), 27, 310);
    }
    else
    {
        draw_set_font(font_b1);
        var tmp_title = scr_name_skill(geo_skill[geo_talent[geo_mouse_x][geo_mouse_y] - 10]);
        var tmp_title_width = sprite_get_width(spr_talent_bg_2) - 70 - 14;
        var tmp_title_scale = min(1, tmp_title_width / max(1, string_width(tmp_title)));
        var tmp_title_y = tmp_y + 7 + ((1 - tmp_title_scale) * string_height(tmp_title) * 0.5);
        draw_text_transformed(tmp_x + 70, tmp_title_y, tmp_title, tmp_title_scale, tmp_title_scale, 0);
        draw_set_font(font_b2);
        var tmp_n = geo_skill[geo_talent[geo_mouse_x][geo_mouse_y] - 10];
        var tmp_lv = 1;
        if (geo_talent[geo_mouse_x][geo_mouse_y] == 13)
        {
            tmp_lv = 2;
        }
        var tmp_str = scr_text_skill(tmp_n, tmp_lv);
        draw_text_ext(tmp_x + 18, tmp_y + 56, scr_newline(tmp_str, 280), 27, 310);
        var tmp_down = scr_text_talent_down(tmp_str);
        var tmp_d_num = string_count("\n", tmp_down);
        var tmp_d_y = 994;
        switch (tmp_d_num)
        {
            case 1:
                draw_sprite(spr_talent_down_1, -1, 688, 1128);
                tmp_d_y = 1087;
                break;
            case 2:
                draw_sprite(spr_talent_down_2, -1, 688, 1128);
                tmp_d_y = 1060;
                break;
            case 3:
                draw_sprite(spr_talent_down_3, -1, 688, 1128);
                tmp_d_y = 1031;
                break;
        }
        if (tmp_d_num > 0)
        {
            global.talent_cover = 1;
            draw_text_ext(695, tmp_d_y, tmp_down, 26, 999);
        }
    }
}
draw_set_alpha(1);
