function scr_newline(arg0, arg1)
{
    var tl_result = "";
    var tl_line = "";
    var tl_word = "";
    var tl_length = string_length(arg0);
    for (var tl_i = 1; tl_i <= tl_length + 1; tl_i += 1)
    {
        var tl_char = "";
        if (tl_i <= tl_length)
            tl_char = string_copy(arg0, tl_i, 1);
        if (tl_char == " " || tl_char == "\n" || tl_i > tl_length)
        {
            if (tl_word != "")
            {
                var tl_candidate = tl_word;
                if (tl_line != "")
                    tl_candidate = tl_line + " " + tl_word;
                if (tl_line != "" && string_width(tl_candidate) > arg1)
                {
                    tl_result += tl_line + "\n";
                    tl_line = tl_word;
                }
                else
                    tl_line = tl_candidate;
                tl_word = "";
            }
            if (tl_char == "\n")
            {
                tl_result += tl_line + "\n";
                tl_line = "";
            }
        }
        else
            tl_word += tl_char;
    }
    return tl_result + tl_line;
}
