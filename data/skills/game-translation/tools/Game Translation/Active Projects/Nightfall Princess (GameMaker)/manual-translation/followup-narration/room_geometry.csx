using System;
using System.IO;
using System.Linq;
using Newtonsoft.Json;
EnsureDataLoaded();
var rows=Data.Rooms.Select(room=>new {
    name=room.Name.Content,
    dimensions=room.GetType().GetProperties().Where(p=>p.Name=="Width"||p.Name=="Height"||p.Name=="Flags").ToDictionary(p=>p.Name,p=>p.GetValue(room)?.ToString()),
    views=room.Views.Select(view=>view.GetType().GetProperties().Where(p=>p.PropertyType.IsPrimitive).ToDictionary(p=>p.Name,p=>p.GetValue(view)?.ToString())).ToArray()
}).ToArray();
File.WriteAllText(Environment.GetEnvironmentVariable("NFP_ROOM_REPORT"),JsonConvert.SerializeObject(rows,Formatting.Indented));
