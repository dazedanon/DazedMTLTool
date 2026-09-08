var tmp_view_x = x;
var tmp_view_y = y;
draw_sprite(spr_option, -1, tmp_view_x, tmp_view_y);
for (var tmp_i = 1; tmp_i <= 3; tmp_i += 1)
{
    draw_sprite(spr_option_a, -1, tmp_view_x + geo_x[tmp_i], tmp_view_y + 30 + (40 * tmp_i));
    if (geo_mouse_num == tmp_i || geo_click == tmp_i)
    {
        draw_set_alpha(0.2);
        if (geo_click == tmp_i)
        {
            draw_set_alpha(0.4);
        }
        gpu_set_fog(1, c_white, 0, 0);
        draw_sprite(spr_option_a, -1, tmp_view_x + geo_x[tmp_i], tmp_view_y + 30 + (40 * tmp_i));
        gpu_set_fog(0, c_white, 0, 0);
        draw_set_alpha(1);
    }
}
draw_set_font(font_b1);
draw_set_color(#D9C2BD);
draw_set_halign(fa_left);
draw_text(tmp_view_x + 333, tmp_view_y + 44, string(ceil(global.bgm * 100)));
draw_text(tmp_view_x + 333, tmp_view_y + 84, string(ceil(global.se * 100)));
draw_text(tmp_view_x + 333, tmp_view_y + 124, string(ceil(global.voice * 100)));
var tmp_str = "";
draw_set_halign(fa_center);
switch (global.god_size)
{
    case 1:
        tmp_str = "1366*768";
        break;
    case 2:
        tmp_str = "1600*900";
        break;
    case 3:
        tmp_str = "1920*1080";
        break;
}
draw_text(tmp_view_x + 296, tmp_view_y + 213, tmp_str);
var tmp_spr = spr_option_button;
if (global.god_full)
{
    tmp_spr = spr_option_button_1;
}
scr_button_draw(tmp_spr, tmp_view_x + 283, tmp_view_y + 259);
tmp_spr = spr_option_button;
if (global.h_speed)
{
    tmp_spr = spr_option_button_1;
}
scr_button_draw(tmp_spr, tmp_view_x + 283, tmp_view_y + 299);
if (global.god_full == 0)
{
    if (global.god_size != 1)
    {
        scr_button_draw(spr_ui_left_8, x + 196, y + 228);
    }
    if (global.god_size != 3)
    {
        scr_button_draw(spr_ui_left_9, x + 382, y + 228);
    }
}
tmp_spr = spr_option_back_0;
if (room == room_0)
{
    tmp_spr = spr_option_back_1;
}
else if (room != room_title)
{
    tmp_spr = spr_option_back_2;
}
scr_button_draw(tmp_spr, tmp_view_x + 106, tmp_view_y + 371);
var tmp_x = 1717;
var tmp_y = 975;
if (room == room_title)
{
    tmp_x = 0;
    tmp_y = 1080;
}
if (room == room_1 || room == room_2 || room == room_3)
{
    tmp_x = 1765;
    tmp_y = 943;
}
draw_sprite(spr_tip_3, -1, tmp_x, tmp_y);
