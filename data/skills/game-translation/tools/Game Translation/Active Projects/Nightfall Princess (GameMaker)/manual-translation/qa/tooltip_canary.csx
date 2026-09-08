using System;
using System.IO;
using System.Linq;
using Newtonsoft.Json.Linq;
using UndertaleModLib.Compiler;
EnsureDataLoaded();
var request = JObject.Parse(File.ReadAllText(Environment.GetEnvironmentVariable("NFP_TOOLTIP_CANARY")));
string[] allowed = {"gml_Object_obj_title_Create_0", "gml_Object_obj_title_Step_0", "gml_Object_obj_title_Draw_0"};
var group = new CodeImportGroup(Data);
foreach(var change in (JArray)request["changes"])
{
    string name=(string)change["name"];
    if(!allowed.Contains(name))throw new Exception("Unexpected canary event");
    group.QueueReplace(name,File.ReadAllText((string)change["source"]));
}
var result=group.Import();
if(!result.Successful)throw new Exception(result.PrintAllErrors(false));
