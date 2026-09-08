using System;
using System.IO;
using System.Linq;
using UndertaleModLib.Compiler;
EnsureDataLoaded();
string name = "gml_Object_obj_state_Draw_0";
if (Data.Code.Count(c => c.Name.Content == name) != 1)
    throw new Exception("Missing or duplicate stats Draw event");
var group = new CodeImportGroup(Data);
group.QueueReplace(name, File.ReadAllText(Environment.GetEnvironmentVariable("NFP_STATE_GML")));
var result = group.Import();
if (!result.Successful) throw new Exception(result.PrintAllErrors(false));
