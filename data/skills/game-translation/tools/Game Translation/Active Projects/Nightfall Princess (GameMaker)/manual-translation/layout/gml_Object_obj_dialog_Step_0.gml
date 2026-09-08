if (geo_text_new == 1)
{
    geo_text = 1;
    geo_text_new = 0;
    geo_text_y += 1;
    geo_text_n = "";
    draw_set_font(font_2);
    geo_text_max = scr_newline(geo_story[geo_text_y], 510);
    geo_text_l_max = string_length(geo_text_max);
    geo_text_command = 0;
    geo_text_name = "";
    if (geo_text_y == 4)
    {
        geo_text = 0;
        geo_text_x = 0;
        geo_text_y = 0;
        geo_text_now = "";
        geo_text_max = "";
        geo_text_n = "";
        geo_text_l = 0;
        geo_text_l_max = 0;
        geo_text_new = 0;
        geo_text_cd = 0;
        geo_text_command = 0;
        geo_text_name = "";
        instance_destroy();
        obj_npc.geo_open = 1;
    }
    if (geo_text_command == 0)
    {
        geo_text_now = "";
        geo_text_l = 0;
    }
}
if (geo_text == 1 && geo_text_command == 0)
{
    if (geo_text_cd < 3)
    {
        geo_text_cd += 1;
    }
    if (geo_text_cd >= 1 && geo_text_l < geo_text_l_max)
    {
        geo_text_cd = 0;
        geo_text_l += 1;
        geo_text_now += string_copy(geo_text_max, geo_text_l, 1);
        geo_text_n += string_copy(geo_text_max, geo_text_l, 1);
        if (string_width(geo_text_n) > 520)
        {
            geo_text_now += "\n";
            geo_text_n = "";
        }
    }
    if (keyboard_check_pressed(ord("S")) || keyboard_check_pressed(vk_enter))
    {
        if (geo_text_l >= geo_text_l_max)
        {
            geo_text_new = 1;
        }
        else
        {
            geo_text_cd = 0;
            while (geo_text_l < geo_text_l_max)
            {
                geo_text_l += 1;
                geo_text_now += string_copy(geo_text_max, geo_text_l, 1);
                geo_text_n += string_copy(geo_text_max, geo_text_l, 1);
                if (string_width(geo_text_n) > 520)
                {
                    geo_text_now += "\n";
                    geo_text_n = "";
                }
            }
        }
    }
}
geo_f += 1;
if (geo_f >= 25.5)
{
    geo_f -= 25.5;
}
