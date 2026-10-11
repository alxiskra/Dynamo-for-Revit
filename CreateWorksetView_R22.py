# ______________________________________________________________
# Описание: Скрипт создает 3D виды под выбранные рабочие наборы
# Протестировано на Revit: v2022
# Автор: Alexander Iskra (alxiskra)
# Лицензия: MIT
# ______________________________________________________________

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')
clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')

from Autodesk.Revit.DB import (
    FilteredElementCollector, FilteredWorksetCollector,
    WorksetKind, ViewFamilyType, ViewFamily, View3D,
    WorksetVisibility, ElementId, Transaction,
    DisplayStyle, ViewDetailLevel
)
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager
from System.Windows.Forms import (
    Form, CheckedListBox, Button, DialogResult, FormBorderStyle, FormStartPosition
)
from System.Drawing import Size, Point

doc = DocumentManager.Instance.CurrentDBDocument

# Получаем все пользовательские рабочие наборы
worksets = list(FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset))
workset_dict = {ws.Name: ws for ws in worksets}

# Окно выбора рабочих наборов
class WorksetSelectorForm(Form):
    def __init__(self, names):
        self.Text = "Выбор рабочих наборов для 3D видов"
        self.Size = Size(450, 550)
        self.StartPosition = FormStartPosition.CenterScreen
        self.FormBorderStyle = FormBorderStyle.FixedDialog
        self.MaximizeBox = False
        self.MinimizeBox = False

        self.clb = CheckedListBox()
        self.clb.Location = Point(15, 15)
        self.clb.Size = Size(405, 430)
        self.clb.CheckOnClick = True
        for name in sorted(names):
            self.clb.Items.Add(name)
        self.Controls.Add(self.clb)

        self.btn_ok = Button()
        self.btn_ok.Text = "Создать виды"
        self.btn_ok.Location = Point(200, 460)
        self.btn_ok.Size = Size(120, 32)
        self.btn_ok.DialogResult = DialogResult.OK
        self.Controls.Add(self.btn_ok)

        self.btn_cancel = Button()
        self.btn_cancel.Text = "Отмена"
        self.btn_cancel.Location = Point(330, 460)
        self.btn_cancel.Size = Size(90, 32)
        self.btn_cancel.DialogResult = DialogResult.Cancel
        self.Controls.Add(self.btn_cancel)

        self.AcceptButton = self.btn_ok
        self.CancelButton = self.btn_cancel

# Отображаем форму
form = WorksetSelectorForm(workset_dict.keys())
dialog_result = form.ShowDialog()

selected_worksets = []
if dialog_result == DialogResult.OK:
    for item in form.clb.CheckedItems:
        selected_worksets.append(workset_dict[item])

created_views = []

if selected_worksets:
    view_types = FilteredElementCollector(doc).OfClass(ViewFamilyType).ToElements()
    view_3d_type = next((vt for vt in view_types if vt.ViewFamily == ViewFamily.ThreeDimensional), None)

    existing_views = {v.Name: v.Id for v in FilteredElementCollector(doc).OfClass(View3D).ToElements()}

    TransactionManager.Instance.ForceCloseTransaction()

    trans = Transaction(doc, "Dyn_Create workset view")
    trans.Start()

    for target_ws in selected_worksets:
        view_name = "00_workset_" + target_ws.Name

        if view_name in existing_views:
            new_view = doc.GetElement(existing_views[view_name])
        else:
            new_view = View3D.CreateIsometric(doc, view_3d_type.Id)
            new_view.Name = view_name

        # Отвязываем шаблон
        new_view.ViewTemplateId = ElementId.InvalidElementId

        # --- НАСТРОЙКИ ГРАФИКИ ---
        
        # 1. Визуальный стиль
        # DisplayStyle.Shading    = "Тонированный" (с тенями от освещения)
        # DisplayStyle.FlatColors = "Заливка" (сплошные цвета, он же Consistent Colors)
        # DisplayStyle.HLR        = "Скрытая линия"
        # DisplayStyle.Wireframe  = "Каркас"
        
        new_view.DisplayStyle = DisplayStyle.FlatColors # Установлена "Заливка"
        
        # 2. Уровень детализации
        # ViewDetailLevel.Coarse = "Низкий"
        # ViewDetailLevel.Medium = "Средний"
        # ViewDetailLevel.Fine   = "Высокий"
        
        new_view.DetailLevel = ViewDetailLevel.Fine
        
        # 3. Масштаб (1:100)
        new_view.Scale = 100
        # -------------------------

        for ws in worksets:
            if ws.Id == target_ws.Id:
                new_view.SetWorksetVisibility(ws.Id, WorksetVisibility.Visible)
            else:
                new_view.SetWorksetVisibility(ws.Id, WorksetVisibility.Hidden)

        created_views.append(view_name)

    trans.Commit()

OUT = created_views if created_views else "Операция отменена или наборы не выбраны"
