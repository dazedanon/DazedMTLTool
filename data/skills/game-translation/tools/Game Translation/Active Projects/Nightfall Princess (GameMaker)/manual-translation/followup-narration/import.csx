using System;
using System.IO;
using System.Linq;
using Newtonsoft.Json.Linq;
using UndertaleModLib.Compiler;
EnsureDataLoaded();
var request = JObject.Parse(File.ReadAllText(Environment.GetEnvironmentVariable("NFP_NARRATION_REQUEST")));
string[] allowed = {"gml_Object_obj_hall_Draw_0", "gml_Object_obj_quest_Draw_0", "gml_Object_obj_gallery_Draw_0", "gml_Object_obj_ui_Draw_0"};
var group = new CodeImportGroup(Data);
if (((JArray)request["changes"]).Count != allowed.Length) throw new Exception("Expected all four narration renderers");
foreach (var change in (JArray)request["changes"])
{
    string name = (string)change["name"];
    if (!allowed.Contains(name) || Data.Code.Count(c => c.Name.Content == name) != 1)
        throw new Exception("Unexpected or duplicate renderer");
    group.QueueReplace(name, File.ReadAllText((string)change["source"]));
}
var result = group.Import();
if (!result.Successful) throw new Exception(result.PrintAllErrors(false));
