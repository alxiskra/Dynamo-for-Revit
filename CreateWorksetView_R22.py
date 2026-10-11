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
    Form, CheckedListBox, Button, DialogResult, FormBorderStyle, FormStartPosition,
    TextBox, CheckState, Control, Keys, Label
)
from System.Drawing import Size, Point

doc = DocumentManager.Instance.CurrentDBDocument

# Получаем все пользовательские рабочие наборы
worksets = list(FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset))
workset_dict = {ws.Name: ws for ws in worksets}

# Окно выбора рабочих наборов с поиском, поддержкой SHIFT и видимыми кнопками
class WorksetSelectorForm(Form):
    def __init__(self, names):
        self.Text = "Выбор рабочих наборов для 3D видов"
        self.Size = Size(450, 620) # Увеличена высота окна
        self.StartPosition = FormStartPosition.CenterScreen
        self.FormBorderStyle = FormBorderStyle.FixedDialog
        self.MaximizeBox = False
        self.MinimizeBox = False

        self.all_names = sorted(names)
        self.item_states = {name: False for name in self.all_names}
        self.last_clicked_index = -1

        self.lbl = Label()
        self.lbl.Text = "Поиск по имени. Shift+клик — отметить диапазон."
        self.lbl.Location = Point(15, 10)
        self.lbl.Size = Size(405, 20)
        self.Controls.Add(self.lbl)

        self.tb_search = TextBox()
        self.tb_search.Location = Point(15, 35)
        self.tb_search.Size = Size(405, 20)
        self.tb_search.TextChanged += self.on_text_changed
        self.Controls.Add(self.tb_search)

        self.clb = CheckedListBox()
        self.clb.Location = Point(15, 65)
        self.clb.Size = Size(405, 435) # Скорректирован размер списка
        self.clb.CheckOnClick = False 
        self.clb.MouseClick += self.on_mouse_click
        self.Controls.Add(self.clb)

        # Кнопки быстрого выбора (слева внизу)
        self.btn_all = Button()
        self.btn_all.Text = "Выбрать все"
        self.btn_all.Location = Point(15, 515)
        self.btn_all.Size = Size(100, 30)
        self.btn_all.Click += self.on_select_all
        self.Controls.Add(self.btn_all)

        self.btn_none = Button()
        self.btn_none.Text = "Снять выбор"
        self.btn_none.Location = Point(120, 515)
        self.btn_none.Size = Size(100, 30)
        self.btn_none.Click += self.on_select_none
        self.Controls.Add(self.btn_none)

        # Кнопки ОК / Отмена (справа внизу)
        self.btn_ok = Button()
        self.btn_ok.Text = "Создать виды"
        self.btn_ok.Location = Point(225, 515)
        self.btn_ok.Size = Size(95, 30)
        self.btn_ok.DialogResult = DialogResult.OK
        self.Controls.Add(self.btn_ok)

        self.btn_cancel = Button()
        self.btn_cancel.Text = "Отмена"
        self.btn_cancel.Location = Point(325, 515)
        self.btn_cancel.Size = Size(95, 30)
        self.btn_cancel.DialogResult = DialogResult.Cancel
        self.Controls.Add(self.btn_cancel)

        self.AcceptButton = self.btn_ok
        self.CancelButton = self.btn_cancel

        self.update_list("")

    def update_list(self, filter_text):
        self.clb.Items.Clear()
        filter_text = filter_text.lower()
        for name in self.all_names:
            if filter_text in name.lower():
                self.clb.Items.Add(name, self.item_states[name])
        self.last_clicked_index = -1 

    def on_text_changed(self, sender, event):
        self.update_list(sender.Text)

    def on_select_all(self, sender, event):
        for i in range(self.clb.Items.Count):
            name = self.clb.Items[i]
            self.clb.SetItemChecked(i, True)
            self.item_states[name] = True

    def on_select_none(self, sender, event):
        for i in range(self.clb.Items.Count):
            name = self.clb.Items[i]
            self.clb.SetItemChecked(i, False)
            self.item_states[name] = False

    def on_mouse_click(self, sender, event):
        index = self.clb.IndexFromPoint(event.Location)
        if index == -1: return

        is_shift_pressed = (Control.ModifierKeys == Keys.Shift)
        current_state = self.clb.GetItemChecked(index)
        new_state = not current_state

        if is_shift_pressed and self.last_clicked_index != -1:
            start = min(self.last_clicked_index, index)
            end = max(self.last_clicked_index, index)
            for i in range(start, end + 1):
                self.clb.SetItemChecked(i, new_state)
                item_name = self.clb.Items[i]
                self.item_states[item_name] = new_state
        else:
            self.clb.SetItemChecked(index, new_state)
            item_name = self.clb.Items[index]
            self.item_states[item_name] = new_state
            
        self.last_clicked_index = index

    def get_selected_items(self):
        return [name for name, is_checked in self.item_states.items() if is_checked]

# Отображаем форму
form = WorksetSelectorForm(workset_dict.keys())
dialog_result = form.ShowDialog()

selected_worksets = []
if dialog_result == DialogResult.OK:
    for item in form.get_selected_items():
        selected_worksets.append(workset_dict[item])

created_views = []

if selected_worksets:
    view_types = FilteredElementCollector(doc).OfClass(ViewFamilyType).ToElements()
    view_3d_type = next((vt for vt in view_types if vt.ViewFamily == ViewFamily.ThreeDimensional), None)

    existing_views = {v.Name: v.Id for v in FilteredElementCollector(doc).OfClass(View3D).ToElements()}

    TransactionManager.Instance.ForceCloseTransaction()

    trans = Transaction(doc, "DYN_Create workset view")
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
        new_view.DisplayStyle = DisplayStyle.FlatColors
        new_view.DetailLevel = ViewDetailLevel.Fine
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
