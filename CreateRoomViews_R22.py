# _______________________________________________________________________
# Описание: Скрипт создает 3D виды под выбранные помещения, включая связи
# Протестировано на Revit: v2022
# Автор: Alexander Iskra (alxiskra)
# Лицензия: MIT
# _______________________________________________________________________

import clr

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')
clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')

from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, BuiltInParameter, 
    ViewFamilyType, ViewFamily, View3D,
    ElementId, BoundingBoxXYZ, XYZ, SubTransaction,
    RevitLinkInstance, Transform
)
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager
from System.Windows.Forms import (
    Form, CheckedListBox, Button, DialogResult, FormBorderStyle, FormStartPosition,
    TextBox, CheckState, Label, Control, Keys, Cursors, ProgressBar, Application, ProgressBarStyle
)
from System.Drawing import Size, Point, Font, FontStyle

doc = DocumentManager.Instance.CurrentDBDocument

# --- 1. Сбор документов и извлечение помещений ---
class RoomData:
    def __init__(self, room, transform, source_name):
        self.room = room
        self.transform = transform
        self.source_name = source_name
        
        num_param = room.get_Parameter(BuiltInParameter.ROOM_NUMBER)
        name_param = room.get_Parameter(BuiltInParameter.ROOM_NAME)
        self.number = num_param.AsString().strip() if num_param and num_param.AsString() else "00"
        self.name = name_param.AsString().strip() if name_param and name_param.AsString() else "Без имени"
        self.display_key = "[{}] {} - {}".format(source_name, self.number, self.name)

def collect_rooms_from_doc(target_doc, transform, source_name):
    rooms_list = []
    collector = FilteredElementCollector(target_doc)\
        .OfCategory(BuiltInCategory.OST_Rooms)\
        .WhereElementIsNotElementType()\
        .ToElements()
        
    for r in collector:
        area_param = r.get_Parameter(BuiltInParameter.ROOM_AREA)
        if area_param and area_param.AsDouble() > 0 and r.Location is not None:
            rooms_list.append(RoomData(r, transform, source_name))
    return rooms_list

sources_dict = {}
link_docs_info = {}

sources_dict["Текущий файл"] = collect_rooms_from_doc(doc, Transform.Identity, "Текущий файл")

link_instances = FilteredElementCollector(doc).OfClass(RevitLinkInstance).ToElements()
for link in link_instances:
    link_doc = link.GetLinkDocument()
    if link_doc:
        link_name = link_doc.Title
        source_title = "Связь: " + link_name
        transform = link.GetTotalTransform()
        link_docs_info[source_title] = (link_doc, transform, link_name)

# --- 2. Окно выбора ---
class RoomSelectorForm(Form):
    def __init__(self, sources_data, links_info):
        self.Text = "Выбор помещений (включая связи) для 3D видов"
        self.Size = Size(520, 680)
        self.StartPosition = FormStartPosition.CenterScreen
        self.FormBorderStyle = FormBorderStyle.FixedDialog
        self.MaximizeBox = False
        self.MinimizeBox = False

        self.sources_data = sources_data
        self.links_info = links_info
        self._is_updating = False
        self.last_clicked_index = -1
        
        self.room_states = {}
        for room_list in self.sources_data.values():
            for r_data in room_list:
                self.room_states[r_data.display_key] = False

        lbl_links = Label()
        lbl_links.Text = "1. Источники моделей (связи):"
        lbl_links.Font = Font(lbl_links.Font, FontStyle.Bold)
        lbl_links.Location = Point(15, 12)
        lbl_links.Size = Size(470, 20)
        self.Controls.Add(lbl_links)

        self.clb_links = CheckedListBox()
        self.clb_links.Location = Point(15, 35)
        self.clb_links.Size = Size(470, 85)
        self.clb_links.CheckOnClick = True
        self.Controls.Add(self.clb_links)

        self.clb_links.Items.Add("Текущий файл", True)
        for src_name in sorted(self.links_info.keys()):
            self.clb_links.Items.Add(src_name, False)

        self.clb_links.ItemCheck += self.on_link_check

        lbl_rooms = Label()
        lbl_rooms.Text = "2. Выберите помещ. (Поиск. Shift+клик — диапазон):"
        lbl_rooms.Font = Font(lbl_rooms.Font, FontStyle.Bold)
        lbl_rooms.Location = Point(15, 130)
        lbl_rooms.Size = Size(470, 20)
        self.Controls.Add(lbl_rooms)

        self.tb_search = TextBox()
        self.tb_search.Location = Point(15, 155)
        self.tb_search.Size = Size(470, 22)
        self.tb_search.TextChanged += self.on_search_changed
        self.Controls.Add(self.tb_search)

        self.clb_rooms = CheckedListBox()
        self.clb_rooms.Location = Point(15, 185)
        self.clb_rooms.Size = Size(470, 390)
        self.clb_rooms.CheckOnClick = False 
        self.clb_rooms.MouseClick += self.on_mouse_click
        self.Controls.Add(self.clb_rooms)

        self.btn_all = Button(Text="Выбрать все", Location=Point(15, 590), Size=Size(90, 32))
        self.btn_all.Click += self.on_select_all
        self.Controls.Add(self.btn_all)

        self.btn_none = Button(Text="Снять выбор", Location=Point(115, 590), Size=Size(90, 32))
        self.btn_none.Click += self.on_select_none
        self.Controls.Add(self.btn_none)

        self.btn_ok = Button(Text="Создать виды", Location=Point(255, 590), Size=Size(120, 32), DialogResult=DialogResult.OK)
        self.Controls.Add(self.btn_ok)

        self.btn_cancel = Button(Text="Отмена", Location=Point(385, 590), Size=Size(100, 32), DialogResult=DialogResult.Cancel)
        self.Controls.Add(self.btn_cancel)

        self.AcceptButton = self.btn_ok
        self.CancelButton = self.btn_cancel

        self.refresh_rooms_list()

    def get_active_source_names(self):
        return [self.clb_links.Items[i] for i in range(self.clb_links.Items.Count) if self.clb_links.GetItemChecked(i)]

    def load_link_if_needed(self, link_title):
        if link_title in self.sources_data: return
        if link_title in self.links_info:
            self.Cursor = Cursors.WaitCursor
            try:
                l_doc, l_transform, l_name = self.links_info[link_title]
                loaded_rooms = collect_rooms_from_doc(l_doc, l_transform, l_name)
                self.sources_data[link_title] = loaded_rooms if loaded_rooms else []
                for r_data in self.sources_data[link_title]:
                    if r_data.display_key not in self.room_states:
                        self.room_states[r_data.display_key] = False
            finally:
                self.Cursor = Cursors.Default

    def refresh_rooms_list(self, active_sources=None):
        self._is_updating = True
        self.clb_rooms.Items.Clear()
        if active_sources is None: active_sources = self.get_active_source_names()
        filter_text = self.tb_search.Text.lower().strip()
        for src in active_sources:
            if src in self.sources_data:
                for r_data in self.sources_data[src]:
                    if filter_text == "" or filter_text in r_data.display_key.lower():
                        is_checked = self.room_states.get(r_data.display_key, False)
                        self.clb_rooms.Items.Add(r_data.display_key, is_checked)
        self.last_clicked_index = -1 
        self._is_updating = False

    def on_link_check(self, sender, event):
        item_name = self.clb_links.Items[event.Index]
        is_checking = (event.NewValue == CheckState.Checked)
        if is_checking: self.load_link_if_needed(item_name)
        active_sources = []
        for i in range(self.clb_links.Items.Count):
            if i == event.Index:
                if is_checking: active_sources.append(self.clb_links.Items[i])
            else:
                if self.clb_links.GetItemChecked(i): active_sources.append(self.clb_links.Items[i])
        self.refresh_rooms_list(active_sources)

    def on_search_changed(self, sender, event): self.refresh_rooms_list()

    def on_mouse_click(self, sender, event):
        index = self.clb_rooms.IndexFromPoint(event.Location)
        if index == -1: return
        is_shift_pressed = (Control.ModifierKeys == Keys.Shift)
        current_state = self.clb_rooms.GetItemChecked(index)
        new_state = not current_state
        if is_shift_pressed and self.last_clicked_index != -1:
            start, end = min(self.last_clicked_index, index), max(self.last_clicked_index, index)
            for i in range(start, end + 1):
                self.clb_rooms.SetItemChecked(i, new_state)
                self.room_states[self.clb_rooms.Items[i]] = new_state
        else:
            self.clb_rooms.SetItemChecked(index, new_state)
            self.room_states[self.clb_rooms.Items[index]] = new_state
        self.last_clicked_index = index

    def on_select_all(self, sender, event):
        for i in range(self.clb_rooms.Items.Count):
            self.clb_rooms.SetItemChecked(i, True)
            self.room_states[self.clb_rooms.Items[i]] = True

    def on_select_none(self, sender, event):
        for i in range(self.clb_rooms.Items.Count):
            self.clb_rooms.SetItemChecked(i, False)
            self.room_states[self.clb_rooms.Items[i]] = False

    def get_selected_room_keys(self):
        return [key for key, checked in self.room_states.items() if checked]

# --- 3. Окно прогресса загрузки с кнопкой отмены ---
class ProgressForm(Form):
    def __init__(self, max_value):
        self.Text = "Создание 3D видов..."
        self.Size = Size(400, 150)
        self.StartPosition = FormStartPosition.CenterScreen
        self.FormBorderStyle = FormBorderStyle.FixedToolWindow
        self.ControlBox = False 
        self.TopMost = True     
        
        self.is_cancelled = False

        self.lbl_status = Label()
        self.lbl_status.Text = "Инициализация..."
        self.lbl_status.Location = Point(15, 15)
        self.lbl_status.Size = Size(350, 20)
        self.Controls.Add(self.lbl_status)

        self.progress_bar = ProgressBar()
        self.progress_bar.Location = Point(15, 40)
        self.progress_bar.Size = Size(350, 25)
        self.progress_bar.Minimum = 0
        self.progress_bar.Maximum = max_value
        self.progress_bar.Value = 0
        self.progress_bar.Style = ProgressBarStyle.Continuous
        self.Controls.Add(self.progress_bar)

        self.btn_cancel = Button()
        self.btn_cancel.Text = "Отмена"
        self.btn_cancel.Location = Point(140, 75)
        self.btn_cancel.Size = Size(100, 30)
        self.btn_cancel.Click += self.on_cancel_click
        self.Controls.Add(self.btn_cancel)

    def on_cancel_click(self, sender, event):
        self.is_cancelled = True
        self.lbl_status.Text = "Отмена операции... Очистка данных."
        self.btn_cancel.Enabled = False
        Application.DoEvents() 

    def update_progress(self, current, total, room_name):
        if not self.is_cancelled:
            self.progress_bar.Value = current
            self.lbl_status.Text = "Создание вида {} из {}: {}".format(current, total, room_name)
        Application.DoEvents() 


# --- 4. Трансформация BoundingBox ---
def get_transformed_section_box(room, transform, offset=1.0):
    bb = room.get_BoundingBox(None)
    if not bb: return None

    new_bb = BoundingBoxXYZ()
    new_bb.Transform = transform.Multiply(bb.Transform)
    
    v_offset = XYZ(offset, offset, offset)
    new_bb.Min = bb.Min - v_offset
    new_bb.Max = bb.Max + v_offset
    
    return new_bb

# --- 5. Запуск формы и транзакции ---
form = RoomSelectorForm(sources_dict, link_docs_info)
dialog_result = form.ShowDialog()
form.Dispose()

created_views = []
OUT = "Операция отменена пользователем."

if dialog_result == DialogResult.OK:
    selected_keys = set(form.get_selected_room_keys())
    
    selected_room_data = []
    for room_list in form.sources_data.values():
        for r_data in room_list:
            if r_data.display_key in selected_keys:
                selected_room_data.append(r_data)

    total_rooms = len(selected_room_data)

    if total_rooms > 0:
        view_types = FilteredElementCollector(doc).OfClass(ViewFamilyType).ToElements()
        view_3d_type = next((vt for vt in view_types if vt.ViewFamily == ViewFamily.ThreeDimensional), None)
        existing_views = {v.Name: v.Id for v in FilteredElementCollector(doc).OfClass(View3D).ToElements()}

        progress_form = ProgressForm(total_rooms)
        progress_form.Show()

        # ИСПОЛЬЗУЕМ БЕЗОПАСНЫЕ ТРАНЗАКЦИИ DYNAMO
        TransactionManager.Instance.EnsureInTransaction(doc)
        
        # Запускаем SubTransaction (подтранзакцию) — её откат работает безупречно
        sub_trans = SubTransaction(doc)
        sub_trans.Start()

        try:
            for index, r_data in enumerate(selected_room_data):
                # Обновляем интерфейс ДО начала работы с элементом
                progress_form.update_progress(index + 1, total_rooms, r_data.name)

                # Мгновенно прерываем цикл, если поймали отмену
                if progress_form.is_cancelled:
                    break
                    
                prefix = "" if r_data.source_name == "Текущий файл" else r_data.source_name + "_"
                view_name = "3D_Room_{}{}_{}".format(prefix, r_data.number, r_data.name)

                for bad_char in ['\\', ':', '{', '}', '[', ']', '|', ';', '<', '>', '?', '`', '~']:
                    view_name = view_name.replace(bad_char, '_')

                if view_name in existing_views:
                    new_view = doc.GetElement(existing_views[view_name])
                else:
                    new_view = View3D.CreateIsometric(doc, view_3d_type.Id)
                    new_view.Name = view_name

                new_view.ViewTemplateId = ElementId.InvalidElementId

                new_bb = get_transformed_section_box(r_data.room, r_data.transform, offset=1.0)
                if new_bb:
                    new_view.IsSectionBoxActive = True
                    new_view.SetSectionBox(new_bb)

                created_views.append(view_name)

            # Проверяем, как завершился цикл
            if progress_form.is_cancelled:
                sub_trans.RollBack() # Стирает все виды, созданные с момента sub_trans.Start()
                OUT = "Создание видов прервано. Изменения откачены."
            else:
                sub_trans.Commit()
                OUT = created_views
                
        except Exception as e:
            sub_trans.RollBack()
            OUT = "Ошибка скрипта: " + str(e)
            
        finally:
            TransactionManager.Instance.TransactionTaskDone()
            progress_form.Close()
            progress_form.Dispose()
