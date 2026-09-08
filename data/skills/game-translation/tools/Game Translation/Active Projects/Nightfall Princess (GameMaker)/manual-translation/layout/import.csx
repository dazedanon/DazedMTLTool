using System;
using System.IO;
using System.Linq;
using Newtonsoft.Json.Linq;
using UndertaleModLib.Compiler;

EnsureDataLoaded();
var request = JObject.Parse(File.ReadAllText(Environment.GetEnvironmentVariable("NFP_LAYOUT_REQUEST")));
string[] allowed = { "gml_GlobalScript_scr_newline", "gml_Object_obj_dialog_Step_0", "gml_Object_obj_option_Draw_0", "gml_Object_obj_talent_Draw_0" };
var group = new CodeImportGroup(Data);
foreach (var change in (JArray)request["changes"])
{
    string name = (string)change["name"];
    if (!allowed.Contains(name)) throw new Exception("Unexpected layout code: " + name);
    if (Data.Code.Count(c => c.Name.Content == name) != 1) throw new Exception("Missing or duplicate code: " + name);
    group.QueueReplace(name, File.ReadAllText((string)change["source"]));
}
var result = group.Import();
if (!result.Successful) throw new Exception(result.PrintAllErrors(false));
File.WriteAllText((string)request["receipt"], "Compiled English wrapping and context-specific options label.\n");
