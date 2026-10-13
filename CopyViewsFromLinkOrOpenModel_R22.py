# _______________________________________________________________________
# Описание: Скрипт копирует Чертежные виды и Легенды из открытых проектов или связей
# Проверка на дубликаты: Включена (предупреждает и пропускает существующие)
# Автор: Alexander Iskra (alxiskra)
# Протестировано на Revit: v2022
# _______________________________________________________________________

import clr
import traceback

clr.AddReference('RevitAPI')
# ИСПРАВЛЕНИЕ: Добавляем библиотеку UI Revit для красивого окошка-предупреждения
clr.AddReference('RevitAPIUI') 
clr.AddReference('RevitServices')
clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')

from Autodesk.Revit.DB import (
    FilteredElementCollector, View, ViewType, 
    ElementTransformUtils, Transform, CopyPasteOptions, ElementId,
    RevitLinkInstance
)
from Autodesk.Revit.UI import TaskDialog # Импортируем окно Revit

from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager
from System.Collections.Generic import List

from System.Windows.Forms import (
    Form, CheckedListBox, Button, DialogResult, FormBorderStyle, FormStartPosition,
    CheckBox, Label, ComboBox, Application, ComboBoxStyle, RadioButton, TextBox,
    Control, Keys
)
from System.Drawing import Size, Point, Font, FontStyle

# Текущий документ (целевой)
doc = DocumentManager.Instance.CurrentDBDocument
app = DocumentManager.Instance.CurrentUIApplication.Application

# Сбор открытых проектов
open_docs = [d for d in app.Documents if not d.IsLinked and d.Title != doc.Title]

# Сбор подгруженных связей (Revit Links)
link_docs = []
link_instances = FilteredElementCollector(doc).OfClass(RevitLinkInstance).ToElements()
for link in link_instances:
    link_doc = link.GetLinkDocument()
    if link_doc and link_doc.Title not in [d.Title for d in link_docs]:
        link_docs.append(link_doc)

# --- 1. Окно выбора ---
class ViewCopierForm(Form):
    def __init__(self, open_docs, link_docs):
        self.Text = "Копирование видов: Проекты и Связи"
        self.Size = Size(450, 680) 
        self.StartPosition = FormStartPosition.CenterScreen
        self.FormBorderStyle = FormBorderStyle.FixedDialog
        self.MaximizeBox = False
        self.MinimizeBox = False

        self.dict_open = {d.Title: d for d in open_docs}
        self.dict_link = {d.Title: d for d in link_docs}
        
        self.current_source_doc = None
        self.available_views_dict = {} 
        self.selected_views = []
        self.last_clicked_index = -1

        # 1. Выбор источника: Открытые проекты
        self.rb_open = RadioButton()
        self.rb_open.Text = "Из открытого проекта:"
        self.rb_open.Font = Font(self.rb_open.Font, FontStyle.Bold)
        self.rb_open.Location = Point(15, 12)
        self.rb_open.Size = Size(400, 20)
        self.rb_open.CheckedChanged += self.on_radio_changed
        self.Controls.Add(self.rb_open)

        self.cb_open = ComboBox()
        self.cb_open.Location = Point(15, 35)
        self.cb_open.Size = Size(400, 25)
        self.cb_open.DropDownStyle = ComboBoxStyle.DropDownList
        for title in sorted(self.dict_open.keys()):
            self.cb_open.Items.Add(title)
        self.cb_open.SelectedIndexChanged += self.on_doc_changed
        self.Controls.Add(self.cb_open)

        # 2. Выбор источника: Связи
        self.rb_link = RadioButton()
        self.rb_link.Text = "Из подгруженной связи (Revit Link):"
        self.rb_link.Font = Font(self.rb_link.Font, FontStyle.Bold)
        self.rb_link.Location = Point(15, 70)
        self.rb_link.Size = Size(400, 20)
        self.rb_link.CheckedChanged += self.on_radio_changed
        self.Controls.Add(self.rb_link)

        self.cb_link = ComboBox()
        self.cb_link.Location = Point(15, 93)
        self.cb_link.Size = Size(400, 25)
        self.cb_link.DropDownStyle = ComboBoxStyle.DropDownList
        for title in sorted(self.dict_link.keys()):
            self.cb_link.Items.Add(title)
        self.cb_link.SelectedIndexChanged += self.on_doc_changed
        self.Controls.Add(self.cb_link)

        # 3. Фильтры
        lbl_filter = Label()
        lbl_filter.Text = "Фильтр типов видов:"
        lbl_filter.Font = Font(lbl_filter.Font, FontStyle.Bold)
        lbl_filter.Location = Point(15, 135)
        lbl_filter.Size = Size(400, 20)
        self.Controls.Add(lbl_filter)

        self.chk_drafting = CheckBox()
        self.chk_drafting.Text = "Чертежные виды"
        self.chk_drafting.Location = Point(15, 155)
        self.chk_drafting.Size = Size(150, 20)
        self.chk_drafting.Checked = True
        self.chk_drafting.CheckedChanged += self.refresh_views_list
        self.Controls.Add(self.chk_drafting)

        self.chk_legends = CheckBox()
        self.chk_legends.Text = "Легенды"
        self.chk_legends.Location = Point(175, 155)
        self.chk_legends.Size = Size(150, 20)
        self.chk_legends.Checked = True
        self.chk_legends.CheckedChanged += self.refresh_views_list
        self.Controls.Add(self.chk_legends)

        # 4. Список видов и Поиск
        lbl_views = Label()
        lbl_views.Text = "Выберите виды (Shift+клик для диапазона):"
        lbl_views.Font = Font(lbl_views.Font, FontStyle.Bold)
        lbl_views.Location = Point(15, 190)
        lbl_views.Size = Size(400, 20)
        self.Controls.Add(lbl_views)

        self.tb_search = TextBox()
        self.tb_search.Location = Point(15, 215)
        self.tb_search.Size = Size(400, 22)
        self.tb_search.TextChanged += self.refresh_views_list
        self.Controls.Add(self.tb_search)

        self.clb_views = CheckedListBox()
        self.clb_views.Location = Point(15, 245) 
        self.clb_views.Size = Size(400, 270) 
        self.clb_views.CheckOnClick = False 
        self.clb_views.MouseClick += self.on_mouse_click
        self.Controls.Add(self.clb_views)

        # Кнопки управления списком
        self.btn_all = Button(Text="Выбрать все", Location=Point(15, 525), Size=Size(90, 30))
        self.btn_all.Click += self.on_select_all
        self.Controls.Add(self.btn_all)

        self.btn_none = Button(Text="Снять выбор", Location=Point(115, 525), Size=Size(90, 30))
        self.btn_none.Click += self.on_select_none
        self.Controls.Add(self.btn_none)

        # Главные кнопки
        self.btn_ok = Button(Text="Копировать", Location=Point(215, 560), Size=Size(100, 35), DialogResult=DialogResult.OK)
        self.btn_ok.Click += self.on_ok_click
        self.Controls.Add(self.btn_ok)

        self.btn_cancel = Button(Text="Отмена", Location=Point(325, 560), Size=Size(90, 35), DialogResult=DialogResult.Cancel)
        self.Controls.Add(self.btn_cancel)

        self.AcceptButton = self.btn_ok
        self.CancelButton = self.btn_cancel
        
        # Установка начальных состояний
        if open_docs:
            self.rb_open.Checked = True
            if self.cb_open.Items.Count > 0: self.cb_open.SelectedIndex = 0
        else:
            self.rb_open.Enabled = False
            self.rb_link.Checked = True

        if not link_docs:
            self.rb_link.Enabled = False
            
        if link_docs and self.cb_link.Items.Count > 0:
            self.cb_link.SelectedIndex = 0
            
        self.update_current_doc()

    def on_mouse_click(self, sender, event):
        index = self.clb_views.IndexFromPoint(event.Location)
        if index == -1: return
        
        is_shift_pressed = (Control.ModifierKeys == Keys.Shift)
        current_state = self.clb_views.GetItemChecked(index)
        new_state = not current_state
        
        if is_shift_pressed and self.last_clicked_index != -1:
            start = min(self.last_clicked_index, index)
            end = max(self.last_clicked_index, index)
            for i in range(start, end + 1):
                self.clb_views.SetItemChecked(i, new_state)
        else:
            self.clb_views.SetItemChecked(index, new_state)
            
        self.last_clicked_index = index

    def on_radio_changed(self, sender, event):
        if self.rb_open.Checked:
            self.cb_open.Enabled = True
            self.cb_link.Enabled = False
        else:
            self.cb_open.Enabled = False
            self.cb_link.Enabled = True
        self.update_current_doc()

    def on_doc_changed(self, sender, event):
        self.update_current_doc()

    def update_current_doc(self):
        if not hasattr(self, 'clb_views'): return 

        self.current_source_doc = None
        if self.rb_open.Checked and self.cb_open.SelectedItem:
            self.current_source_doc = self.dict_open.get(self.cb_open.SelectedItem)
        elif self.rb_link.Checked and self.cb_link.SelectedItem:
            self.current_source_doc = self.dict_link.get(self.cb_link.SelectedItem)
            
        self.refresh_views_list()

    def refresh_views_list(self, sender=None, event=None):
        if not hasattr(self, 'clb_views'): return 

        self.clb_views.Items.Clear()
        self.available_views_dict.Clear()
        self.last_clicked_index = -1 
        
        if not self.current_source_doc: return

        search_text = self.tb_search.Text.lower()

        collector = FilteredElementCollector(self.current_source_doc).OfClass(View).ToElements()
        
        for v in collector:
            if v.IsTemplate: continue 
            
            is_drafting = (v.ViewType == ViewType.DraftingView)
            is_legend = (v.ViewType == ViewType.Legend)
            
            if (self.chk_drafting.Checked and is_drafting) or (self.chk_legends.Checked and is_legend):
                prefix = "[Чертежный вид] " if is_drafting else "[Легенда] "
                display_name = prefix + v.Name
                
                if search_text == "" or search_text in display_name.lower():
                    self.available_views_dict[display_name] = v
                    self.clb_views.Items.Add(display_name, False)

    def on_select_all(self, sender, event):
        for i in range(self.clb_views.Items.Count):
            self.clb_views.SetItemChecked(i, True)

    def on_select_none(self, sender, event):
        for i in range(self.clb_views.Items.Count):
            self.clb_views.SetItemChecked(i, False)

    def on_ok_click(self, sender, event):
        for i in range(self.clb_views.Items.Count):
            if self.clb_views.GetItemChecked(i):
                display_name = self.clb_views.Items[i]
                self.selected_views.append(self.available_views_dict[display_name])


# --- 2. Запуск логики и проверка дубликатов ---
if not open_docs and not link_docs:
    OUT = "Ошибка: Нет ни открытых проектов, ни подгруженных связей."
else:
    form = ViewCopierForm(open_docs, link_docs)
    dialog_result = form.ShowDialog()
    
    source_doc = form.current_source_doc
    views_to_copy = form.selected_views
    form.Dispose()

    if dialog_result == DialogResult.OK:
        if not views_to_copy:
            OUT = "Отмена: Виды не были выбраны."
        else:
            # СБОР ИМЕН СУЩЕСТВУЮЩИХ ВИДОВ В ТЕКУЩЕМ ПРОЕКТЕ
            existing_views = FilteredElementCollector(doc).OfClass(View).ToElements()
            existing_names = set([v.Name for v in existing_views if not v.IsTemplate])
            
            safe_views = []
            duplicate_names = []
            
            # РАЗДЕЛЯЕМ ВЫБРАННЫЕ ВИДЫ НА БЕЗОПАСНЫЕ И ДУБЛИКАТЫ
            for v in views_to_copy:
                if v.Name in existing_names:
                    duplicate_names.append(v.Name)
                else:
                    safe_views.append(v)
            
            # ЕСЛИ ЕСТЬ ДУБЛИКАТЫ - ВЫВОДИМ ОКОШКО ПРЕДУПРЕЖДЕНИЯ
            if duplicate_names:
                msg = "Следующие виды уже существуют в текущем проекте и не будут скопированы:\n"
                for name in duplicate_names:
                    msg += "\n- " + name
                TaskDialog.Show("Внимание: Обнаружены дубликаты", msg)
            
            # ЕСЛИ БЕЗОПАСНЫХ ВИДОВ НЕ ОСТАЛОСЬ - ПРЕРЫВАЕМ
            if not safe_views:
                OUT = "Копирование отменено: Все выбранные виды уже существуют в проекте."
            else:
                view_ids = List[ElementId]()
                for v in safe_views:
                    view_ids.Add(v.Id)

                TransactionManager.Instance.EnsureInTransaction(doc)
                try:
                    options = CopyPasteOptions()
                    copied_ids = ElementTransformUtils.CopyElements(source_doc, view_ids, doc, Transform.Identity, options)
                    
                    OUT = []
                    OUT.append("Успешно скопировано элементов: {}".format(copied_ids.Count))
                    OUT.append("Скопированные виды из '{}':".format(source_doc.Title))
                    for v in safe_views:
                        OUT.append(" - " + v.Name)
                        
                    if duplicate_names:
                        OUT.append("\nПропущены (уже существуют в проекте):")
                        for name in duplicate_names:
                            OUT.append(" - " + name)
                        
                except Exception as e:
                    OUT = ["Ошибка при копировании: " + traceback.format_exc()]
                finally:
                    TransactionManager.Instance.TransactionTaskDone()
    else:
        OUT = "Операция отменена пользователем."
