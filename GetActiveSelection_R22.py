# ______________________________________________________________
# Описание: Скрипт передает в Dynamo выделенные Revit-элементы
# Протестировано на Revit: v2022
# Автор: Alexander Iskra (alxiskra)
# Лицензия: MIT
# ______________________________________________________________

import clr
clr.AddReference("RevitServices")
from RevitServices.Persistence import DocumentManager

clr.AddReference("RevitNodes")
import Revit
clr.ImportExtensions(Revit.Elements)

# Эта переменная принимает сигнал от нода Boolean. 
# Нам не важно её значение (True или False), 
# важно лишь то, что при её изменении Dynamo принудительно перезапустит этот скрипт.
refresh_signal = IN[0]

uidoc = DocumentManager.Instance.CurrentUIApplication.ActiveUIDocument
doc = uidoc.Document 

selected_ids = uidoc.Selection.GetElementIds()
OUT = [doc.GetElement(s_id).ToDSType(True) for s_id in selected_ids]
