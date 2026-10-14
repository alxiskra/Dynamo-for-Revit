# -*- coding: utf-8 -*-
# _______________________________________________________________________
# Описание: Интерактивный аудит и НЕМОДАЛЬНЫЙ дашборд заполненности параметров
#           элементов (Экземпляр и Тип) на 3D-виде, плане или в спецификации
# Особенности версии v2.0 (Modeless):
#   - Дашборд открывается в немодальном режиме (form.Show()) и НЕ блокирует Revit!
#   - Можно выделять элементы из таблицы, вращать модель, нажимать HI/HR и
#     редактировать параметры в окне Свойств Revit при открытом дашборде
#   - Кнопка «Обновить дашборд» пересчитывает проценты и шкалы на лету
#   - Встроенный ExternalEvent для авто-изоляции элементов (IsolateElementsTemporary)
# Автор: Alexander Iskra (alxiskra)
# Протестировано на Revit: v2022 (IronPython 2.7)
# _______________________________________________________________________

import clr
import sys
import os
import codecs
import traceback

clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('RevitServices')
clr.AddReference('System')
clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')

from Autodesk.Revit.DB import (
    FilteredElementCollector, View, ViewType, ViewSchedule,
    StorageType, ElementId, CategoryType, BuiltInCategory, BuiltInParameter,
    Transaction, TemporaryViewMode
)
from Autodesk.Revit.UI import (
    TaskDialog, IExternalEventHandler, ExternalEvent
)

from RevitServices.Persistence import DocumentManager
from System.Collections.Generic import List

from System.Windows.Forms import (
    Form, Button, DialogResult, FormBorderStyle, FormStartPosition,
    CheckBox, Label, ComboBox, ComboBoxStyle, RadioButton, TextBox,
    Control, Keys, Panel, TrackBar, TabControl, TabPage, DataGridView,
    DataGridViewSelectionMode, DataGridViewAutoSizeColumnsMode,
    ScrollBars, SaveFileDialog, GroupBox,
    ListBox, BorderStyle, FlatStyle
)
from System.Drawing import (
    Size, Point, Font, FontStyle, Color, SolidBrush, Pen, Rectangle
)

doc = DocumentManager.Instance.CurrentDBDocument
uiapp = DocumentManager.Instance.CurrentUIApplication
uidoc = uiapp.ActiveUIDocument


# ==============================================================================
# 0. ОБРАБОТЧИК EXTERNAL EVENT ДЛЯ НЕМОДАЛЬНОГО ОКНА (ИЗОЛЯЦИЯ / ЗУМ В REVIT)
# ==============================================================================

class RevitModelessActionHandler(IExternalEventHandler):
    """
    Позволяет немодальному окну (form.Show()) безопасно выполнять транзакции
    в контексте Revit API (например, временную изоляцию элементов HI/HR).
    """
    def __init__(self):
        self.action_type = None
        self.element_ids = None
        self.status_callback = None

    def Execute(self, uiapp_ref):
        try:
            active_uidoc = uiapp_ref.ActiveUIDocument
            if not active_uidoc:
                return
            active_doc = active_uidoc.Document
            target_view = active_uidoc.ActiveGraphicalView
            if target_view is None:
                target_view = active_doc.ActiveView

            if self.action_type == "ISOLATE" and self.element_ids and self.element_ids.Count > 0:
                active_uidoc.Selection.SetElementIds(self.element_ids)
                if target_view and not isinstance(target_view, ViewSchedule):
                    t = Transaction(active_doc, u"BIM Аудит: Временная изоляция элементов")
                    t.Start()
                    target_view.IsolateElementsTemporary(self.element_ids)
                    t.Commit()
                    if self.status_callback:
                        self.status_callback(
                            u"Изолировано элементов на активном виде: {}. Окно Revit доступно для работы.".format(self.element_ids.Count),
                            Color.FromArgb(22, 101, 52)
                        )
                else:
                    if self.status_callback:
                        self.status_callback(
                            u"Элементы выделены ({} шт.). Переключитесь на 3D-вид или план для изоляции.".format(self.element_ids.Count),
                            Color.FromArgb(180, 83, 9)
                        )

            elif self.action_type == "RESET_ISOLATION":
                if target_view and not isinstance(target_view, ViewSchedule):
                    t = Transaction(active_doc, u"BIM Аудит: Сброс временной изоляции")
                    t.Start()
                    target_view.DisableTemporaryViewMode(TemporaryViewMode.TemporaryHideIsolate)
                    t.Commit()
                    if self.status_callback:
                        self.status_callback(
                            u"Временная изоляция (HI) сброшена на активном виде.",
                            Color.FromArgb(30, 64, 175)
                        )

            elif self.action_type == "SELECT_AND_ZOOM" and self.element_ids and self.element_ids.Count > 0:
                active_uidoc.Selection.SetElementIds(self.element_ids)
                try:
                    active_uidoc.ShowElements(self.element_ids)
                except:
                    pass
                if self.status_callback:
                    self.status_callback(
                        u"Показано и выделено в модели: {} шт. Вы можете сразу менять их свойства в Revit!".format(self.element_ids.Count),
                        Color.FromArgb(22, 101, 52)
                    )
        except Exception as ex:
            if self.status_callback:
                self.status_callback(u"Ошибка действия в Revit: " + unicode(ex), Color.FromArgb(185, 28, 28))

    def GetName(self):
        return "RevitParameterAuditModelessHandler"


# ==============================================================================
# 1. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ АНАЛИЗА ПАРАМЕТРОВ (ЭКЗЕМПЛЯР + ТИП)
# ==============================================================================

def ElementName(elem):
    """Безопасное получение имени элемента в IronPython 2."""
    try:
        return elem.Name
    except:
        try:
            p = elem.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
            if p and p.AsString():
                return p.AsString()
        except:
            pass
        return u"ID {}".format(elem.Id.IntegerValue)


def get_element_type_name(doc_ref, elem):
    """Возвращает строку 'Семейство : Тип' для элемента."""
    try:
        type_id = elem.GetTypeId()
        if type_id and type_id != ElementId.InvalidElementId:
            type_elem = doc_ref.GetElement(type_id)
            if type_elem:
                fam_name = getattr(type_elem, 'FamilyName', '')
                t_name = ElementName(type_elem)
                if fam_name and t_name:
                    return u"{} : {}".format(fam_name, t_name)
                elif t_name:
                    return t_name
        return ElementName(elem)
    except:
        return u"<Без имени типа>"


def resolve_parameter_value(doc_ref, elem, param_name):
    """
    Ищет параметр сначала у Экземпляра, затем у Типа элемента.
    Возвращает кортеж: (is_filled, value_str, scope_str)
    """
    param = elem.LookupParameter(param_name)
    scope_str = u"Экземпляр"

    if param is None:
        type_id = elem.GetTypeId()
        if type_id and type_id != ElementId.InvalidElementId:
            type_elem = doc_ref.GetElement(type_id)
            if type_elem:
                param = type_elem.LookupParameter(param_name)
                if param is not None:
                    scope_str = u"Тип"

    if param is None:
        return (False, u"<Нет параметра>", u"Отсутствует")

    if not param.HasValue:
        return (False, u"<Пусто>", scope_str)

    st = param.StorageType
    if st == StorageType.String:
        raw_val = param.AsString()
        if raw_val is None:
            raw_val = param.AsValueString()
        if raw_val is None or raw_val.strip() == u"":
            return (False, u"<Пусто>", scope_str)
        return (True, raw_val.strip(), scope_str)

    elif st == StorageType.ElementId:
        eid = param.AsElementId()
        if eid is None or eid == ElementId.InvalidElementId or eid.IntegerValue <= 0:
            val_str = param.AsValueString()
            if val_str and val_str.strip() != u"" and val_str.strip().lower() not in [u"нет", u"none"]:
                return (True, val_str.strip(), scope_str)
            return (False, u"<Не назначено>", scope_str)
        val_str = param.AsValueString()
        if not val_str:
            target_el = doc_ref.GetElement(eid)
            val_str = ElementName(target_el) if target_el else unicode(eid.IntegerValue)
        return (True, val_str, scope_str)

    elif st == StorageType.Integer:
        val_str = param.AsValueString()
        if not val_str:
            val_str = unicode(param.AsInteger())
        return (True, val_str, scope_str)

    elif st == StorageType.Double:
        val_str = param.AsValueString()
        if not val_str:
            val_str = unicode(round(param.AsDouble(), 4))
        return (True, val_str, scope_str)

    return (False, u"<Пусто>", scope_str)


def collect_elements_from_view(doc_ref, view_elem):
    """
    Собирает модельные элементы из 3D-вида, плана, разреза или спецификации.
    Исключает камеры, границы 3D-вида и служебные объекты.
    """
    raw_elements = FilteredElementCollector(doc_ref, view_elem.Id).WhereElementIsNotElementType().ToElements()
    valid_elements = []

    ignored_bic = set([
        int(BuiltInCategory.OST_Cameras),
        int(BuiltInCategory.OST_SectionBox),
        int(BuiltInCategory.OST_Viewers),
        int(BuiltInCategory.OST_SharedBasePoint),
        int(BuiltInCategory.OST_ProjectBasePoint),
        int(BuiltInCategory.OST_IOSModelGroups)
    ])

    for el in raw_elements:
        try:
            cat = el.Category
            if cat is None:
                continue
            if cat.CategoryType != CategoryType.Model:
                continue
            if cat.Id.IntegerValue in ignored_bic:
                continue
            valid_elements.append(el)
        except:
            continue

    return valid_elements


# ==============================================================================
# 2. ОКНО НАСТРОЙКИ ПРОВЕРКИ (МОДАЛЬНОЕ — ВЫБОР ВИДА + ВВОД ПАРАМЕТРОВ)
# ==============================================================================

class ParameterAuditConfigForm(Form):
    def __init__(self, doc_ref):
        self.doc = doc_ref
        self.Text = u"BIM Аудит параметров модели (Revit 2022)"
        self.Size = Size(540, 740)
        self.StartPosition = FormStartPosition.CenterScreen
        self.FormBorderStyle = FormBorderStyle.FixedDialog
        self.MaximizeBox = False
        self.MinimizeBox = False
        self.BackColor = Color.FromArgb(245, 247, 250)

        self.selected_view = None
        self.selected_params = []
        self.available_views_dict = {}
        self.dynamic_textboxes = []

        self.default_params = [
            u"MR_Корпус",
            u"MR_Комплект",
            u"MR_Этаж",
            u"MR_Код по классификатору"
        ]

        # --- ШАПКА ---
        pnl_header = Panel(Location=Point(0, 0), Size=Size(540, 52), BackColor=Color.FromArgb(30, 41, 59))
        lbl_title = Label(
            Text=u"Проверка заполненности обязательных параметров",
            Location=Point(15, 8), Size=Size(500, 22),
            ForeColor=Color.White, Font=Font("Segoe UI", 11, FontStyle.Bold)
        )
        lbl_sub = Label(
            Text=u"Поддержка параметров Экземпляра и Типа | 3D-виды, Планы и Спецификации",
            Location=Point(15, 30), Size=Size(500, 18),
            ForeColor=Color.FromArgb(148, 163, 184), Font=Font("Segoe UI", 8.5, FontStyle.Regular)
        )
        pnl_header.Controls.Add(lbl_title)
        pnl_header.Controls.Add(lbl_sub)
        self.Controls.Add(pnl_header)

        # --- БЛОК 1: ВЫБОР ВИДА ИЛИ СПЕЦИФИКАЦИИ ---
        grp_view = GroupBox(
            Text=u"1. Источник элементов (3D-вид, План или Спецификация)",
            Location=Point(15, 62), Size=Size(495, 255),
            Font=Font("Segoe UI", 9, FontStyle.Bold)
        )

        self.chk_3d = CheckBox(
            Text=u"3D-виды", Location=Point(15, 22), Size=Size(95, 20),
            Checked=True, Font=Font("Segoe UI", 8.5, FontStyle.Regular)
        )
        self.chk_3d.CheckedChanged += self.refresh_views_list
        grp_view.Controls.Add(self.chk_3d)

        self.chk_sched = CheckBox(
            Text=u"Спецификации", Location=Point(115, 22), Size=Size(125, 20),
            Checked=True, Font=Font("Segoe UI", 8.5, FontStyle.Regular)
        )
        self.chk_sched.CheckedChanged += self.refresh_views_list
        grp_view.Controls.Add(self.chk_sched)

        self.chk_plans = CheckBox(
            Text=u"Планы / Разрезы", Location=Point(245, 22), Size=Size(135, 20),
            Checked=False, Font=Font("Segoe UI", 8.5, FontStyle.Regular)
        )
        self.chk_plans.CheckedChanged += self.refresh_views_list
        grp_view.Controls.Add(self.chk_plans)

        self.btn_active_view = Button(
            Text=u"Активный вид", Location=Point(382, 19), Size=Size(98, 24),
            Font=Font("Segoe UI", 8, FontStyle.Regular), BackColor=Color.White
        )
        self.btn_active_view.Click += self.on_select_active_view
        grp_view.Controls.Add(self.btn_active_view)

        lbl_search = Label(
            Text=u"Поиск или точное имя вида:", Location=Point(15, 50), Size=Size(465, 18),
            Font=Font("Segoe UI", 8.5, FontStyle.Regular)
        )
        grp_view.Controls.Add(lbl_search)

        self.tb_view_search = TextBox(
            Location=Point(15, 70), Size=Size(465, 22),
            Font=Font("Segoe UI", 9, FontStyle.Regular)
        )
        self.tb_view_search.TextChanged += self.refresh_views_list
        grp_view.Controls.Add(self.tb_view_search)

        self.lb_views = ListBox(
            Location=Point(15, 98), Size=Size(465, 145),
            Font=Font("Segoe UI", 9, FontStyle.Regular)
        )
        grp_view.Controls.Add(self.lb_views)

        self.Controls.Add(grp_view)

        # --- БЛОК 2: СПОСОБ ВВОДА ПАРАМЕТРОВ ---
        grp_params = GroupBox(
            Text=u"2. Обязательные параметры для анализа (Экземпляр или Тип)",
            Location=Point(15, 325), Size=Size(495, 315),
            Font=Font("Segoe UI", 9, FontStyle.Bold)
        )

        self.rb_semicolon = RadioButton(
            Text=u"Ввод строкой через разделитель «;»",
            Location=Point(15, 24), Size=Size(250, 20),
            Checked=True, Font=Font("Segoe UI", 8.5, FontStyle.Bold)
        )
        self.rb_semicolon.CheckedChanged += self.on_param_mode_changed
        grp_params.Controls.Add(self.rb_semicolon)

        self.rb_slider = RadioButton(
            Text=u"Поля с ползунком (кол-во параметров)",
            Location=Point(265, 24), Size=Size(220, 20),
            Checked=False, Font=Font("Segoe UI", 8.5, FontStyle.Bold)
        )
        self.rb_slider.CheckedChanged += self.on_param_mode_changed
        grp_params.Controls.Add(self.rb_slider)

        # Панель режима 1: Ввод через ";"
        self.pnl_semicolon = Panel(Location=Point(12, 50), Size=Size(470, 250))
        lbl_semi_hint = Label(
            Text=u"Введите имена параметров через точку с запятой (;).\nСкрипт сам проверит параметры Экземпляра и Типа:",
            Location=Point(3, 2), Size=Size(460, 34),
            Font=Font("Segoe UI", 8.5, FontStyle.Regular)
        )
        self.pnl_semicolon.Controls.Add(lbl_semi_hint)

        self.tb_semicolon = TextBox(
            Location=Point(3, 40), Size=Size(460, 55),
            Multiline=True, ScrollBars=ScrollBars.Vertical,
            Font=Font("Segoe UI", 9.5, FontStyle.Regular),
            Text=u";".join(self.default_params)
        )
        self.pnl_semicolon.Controls.Add(self.tb_semicolon)

        lbl_presets = Label(
            Text=u"Быстрая вставка типовых параметров в строку:",
            Location=Point(3, 108), Size=Size(460, 18),
            Font=Font("Segoe UI", 8.5, FontStyle.Regular), ForeColor=Color.FromArgb(71, 85, 105)
        )
        self.pnl_semicolon.Controls.Add(lbl_presets)

        preset_y = 130
        for p_name in self.default_params:
            btn_p = Button(
                Text=u"+ " + p_name,
                Location=Point(3, preset_y), Size=Size(225, 25),
                Font=Font("Segoe UI", 8, FontStyle.Regular), BackColor=Color.White
            )
            btn_p.Tag = p_name
            btn_p.Click += self.on_add_preset_param
            self.pnl_semicolon.Controls.Add(btn_p)
            preset_y += 28

        btn_reset_defaults = Button(
            Text=u"Сбросить к набору MR_*",
            Location=Point(240, 130), Size=Size(220, 28),
            Font=Font("Segoe UI", 8.5, FontStyle.Regular), BackColor=Color.White
        )
        btn_reset_defaults.Click += self.on_reset_defaults
        self.pnl_semicolon.Controls.Add(btn_reset_defaults)

        grp_params.Controls.Add(self.pnl_semicolon)

        # Панель режима 2: Ползунок TrackBar + динамические поля
        self.pnl_slider = Panel(Location=Point(12, 50), Size=Size(470, 250), Visible=False)

        self.lbl_slider_count = Label(
            Text=u"Количество параметров для проверки: 4",
            Location=Point(3, 4), Size=Size(260, 20),
            Font=Font("Segoe UI", 8.5, FontStyle.Bold)
        )
        self.pnl_slider.Controls.Add(self.lbl_slider_count)

        self.track_count = TrackBar(
            Location=Point(260, 0), Size=Size(205, 32),
            Minimum=1, Maximum=12, Value=4, TickFrequency=1
        )
        self.track_count.Scroll += self.on_slider_scroll
        self.pnl_slider.Controls.Add(self.track_count)

        self.pnl_fields_container = Panel(
            Location=Point(3, 38), Size=Size(462, 205),
            AutoScroll=True, BorderStyle=BorderStyle.FixedSingle,
            BackColor=Color.White
        )
        self.pnl_slider.Controls.Add(self.pnl_fields_container)

        grp_params.Controls.Add(self.pnl_slider)
        self.Controls.Add(grp_params)

        # --- КНОПКИ ЗАПУСКА ---
        self.btn_run = Button(
            Text=u"Запустить анализ и открыть Дашборд",
            Location=Point(195, 650), Size=Size(215, 38),
            Font=Font("Segoe UI", 9, FontStyle.Bold),
            BackColor=Color.FromArgb(37, 99, 235), ForeColor=Color.White,
            FlatStyle=FlatStyle.Flat
        )
        self.btn_run.Click += self.on_run_click
        self.Controls.Add(self.btn_run)

        self.btn_cancel = Button(
            Text=u"Отмена",
            Location=Point(420, 650), Size=Size(90, 38),
            Font=Font("Segoe UI", 9, FontStyle.Regular),
            BackColor=Color.White, DialogResult=DialogResult.Cancel
        )
        self.Controls.Add(self.btn_cancel)

        self.AcceptButton = self.btn_run
        self.CancelButton = self.btn_cancel

        self.rebuild_dynamic_fields(self.default_params)
        self.refresh_views_list()
        self.select_initial_active_view()

    def get_view_prefix(self, v):
        vt = v.ViewType
        if vt == ViewType.ThreeD:
            return u"[3D Вид] "
        elif vt == ViewType.Schedule:
            return u"[Спецификация] "
        elif vt in [ViewType.FloorPlan, ViewType.CeilingPlan, ViewType.EngineeringPlan, ViewType.AreaPlan]:
            return u"[План] "
        elif vt in [ViewType.Section, ViewType.Elevation]:
            return u"[Разрез/Фасад] "
        return u"[Вид] "

    def refresh_views_list(self, sender=None, event=None):
        self.lb_views.Items.Clear()
        self.available_views_dict.clear()

        search_q = self.tb_view_search.Text.strip().lower()
        collector = FilteredElementCollector(self.doc).OfClass(View).ToElements()

        display_items = []
        for v in collector:
            try:
                if v.IsTemplate:
                    continue
                vt = v.ViewType
                is_3d = (vt == ViewType.ThreeD)
                is_sched = (
                    vt == ViewType.Schedule and
                    not getattr(v, 'IsInternalKeynoteSchedule', False) and
                    not getattr(v, 'IsTitleblockRevisionSchedule', False)
                )
                is_plan_sec = (vt in [
                    ViewType.FloorPlan, ViewType.CeilingPlan,
                    ViewType.EngineeringPlan, ViewType.Section, ViewType.Elevation
                ])

                allowed = (
                    (self.chk_3d.Checked and is_3d) or
                    (self.chk_sched.Checked and is_sched) or
                    (self.chk_plans.Checked and is_plan_sec)
                )
                if not allowed:
                    continue

                v_name = ElementName(v)
                disp = self.get_view_prefix(v) + v_name
                if search_q == u"" or (search_q in disp.lower()) or (search_q in v_name.lower()):
                    self.available_views_dict[disp] = v
                    display_items.append(disp)
            except:
                continue

        for item in sorted(display_items):
            self.lb_views.Items.Add(item)

        if self.lb_views.Items.Count > 0:
            self.lb_views.SelectedIndex = 0

    def select_initial_active_view(self):
        try:
            active_v = self.doc.ActiveView
            if active_v:
                target_disp = self.get_view_prefix(active_v) + ElementName(active_v)
                for i in range(self.lb_views.Items.Count):
                    if self.lb_views.Items[i] == target_disp:
                        self.lb_views.SelectedIndex = i
                        return
        except:
            pass

    def on_select_active_view(self, sender, event):
        try:
            active_v = self.doc.ActiveView
            if not active_v:
                return
            self.chk_3d.Checked = True
            self.chk_sched.Checked = True
            self.chk_plans.Checked = True
            self.tb_view_search.Text = ElementName(active_v)
            self.refresh_views_list()
        except:
            pass

    def on_add_preset_param(self, sender, event):
        p_name = sender.Tag
        current_items = [x.strip() for x in self.tb_semicolon.Text.split(u";") if x.strip()]
        if p_name not in current_items:
            current_items.append(p_name)
            self.tb_semicolon.Text = u";".join(current_items)

    def on_reset_defaults(self, sender, event):
        self.tb_semicolon.Text = u";".join(self.default_params)

    def on_param_mode_changed(self, sender, event):
        if self.rb_semicolon.Checked:
            vals = [tb.Text.strip() for tb in self.dynamic_textboxes if tb.Text.strip()]
            if vals:
                self.tb_semicolon.Text = u";".join(vals)
            self.pnl_semicolon.Visible = True
            self.pnl_slider.Visible = False
        else:
            raw_clean = self.tb_semicolon.Text.replace(u"\r", u"").replace(u"\n", u";")
            vals = [x.strip() for x in raw_clean.split(u";") if x.strip()]
            if not vals:
                vals = list(self.default_params)
            cnt = max(1, min(12, len(vals)))
            self.track_count.Value = cnt
            self.lbl_slider_count.Text = u"Количество параметров для проверки: {}".format(cnt)
            self.rebuild_dynamic_fields(vals)
            self.pnl_semicolon.Visible = False
            self.pnl_slider.Visible = True

    def on_slider_scroll(self, sender, event):
        cnt = self.track_count.Value
        self.lbl_slider_count.Text = u"Количество параметров для проверки: {}".format(cnt)
        current_vals = [tb.Text for tb in self.dynamic_textboxes]
        self.rebuild_dynamic_fields(current_vals, target_count=cnt)

    def rebuild_dynamic_fields(self, seed_values, target_count=None):
        if target_count is None:
            target_count = len(seed_values) if seed_values else 4
        target_count = max(1, min(12, target_count))

        self.pnl_fields_container.Controls.Clear()
        self.dynamic_textboxes = []

        for idx in range(target_count):
            y_pos = 8 + idx * 30
            lbl = Label(
                Text=u"Параметр #{}:".format(idx + 1),
                Location=Point(8, y_pos + 3), Size=Size(95, 20),
                Font=Font("Segoe UI", 8.5, FontStyle.Regular)
            )
            tb = TextBox(
                Location=Point(108, y_pos), Size=Size(325, 23),
                Font=Font("Segoe UI", 9, FontStyle.Regular)
            )
            if idx < len(seed_values):
                tb.Text = seed_values[idx]
            elif idx < len(self.default_params):
                tb.Text = self.default_params[idx]

            self.pnl_fields_container.Controls.Add(lbl)
            self.pnl_fields_container.Controls.Add(tb)
            self.dynamic_textboxes.append(tb)

    def on_run_click(self, sender, event):
        chosen_view = None
        if self.lb_views.SelectedItem and self.lb_views.SelectedItem in self.available_views_dict:
            chosen_view = self.available_views_dict[self.lb_views.SelectedItem]
        else:
            typed_name = self.tb_view_search.Text.strip().lower()
            if typed_name:
                for disp, v_obj in self.available_views_dict.items():
                    if ElementName(v_obj).lower() == typed_name:
                        chosen_view = v_obj
                        break

        if chosen_view is None:
            TaskDialog.Show(u"Ошибка выбора вида", u"Пожалуйста, выберите 3D-вид, план или спецификацию из списка.")
            return

        if self.rb_semicolon.Checked:
            raw_text = self.tb_semicolon.Text.replace(u"\r", u"").replace(u"\n", u";")
            params = [x.strip() for x in raw_text.split(u";") if x.strip()]
        else:
            params = [tb.Text.strip() for tb in self.dynamic_textboxes if tb.Text.strip()]

        unique_params = []
        for p in params:
            if p not in unique_params:
                unique_params.append(p)

        if not unique_params:
            TaskDialog.Show(u"Ошибка параметров", u"Укажите хотя бы один параметр для анализа.")
            return

        self.selected_view = chosen_view
        self.selected_params = unique_params
        self.DialogResult = DialogResult.OK
        self.Close()


# ==============================================================================
# 3. НЕМОДАЛЬНЫЙ ГРАФИЧЕСКИЙ ДАШБОРД (НЕ БЛОКИРУЕТ ОКНО REVIT!)
# ==============================================================================

class AuditDashboardForm(Form):
    def __init__(self, doc_ref, uidoc_ref, view_elem, param_names, audit_data):
        self.doc = doc_ref
        self.uidoc = uidoc_ref
        self.view_elem = view_elem
        self.view_name = ElementName(view_elem)
        self.param_names = param_names
        self.audit_data = audit_data

        # Инициализируем ExternalEvent для безопасных транзакций из немодального окна
        self.ext_handler = RevitModelessActionHandler()
        self.ext_handler.status_callback = self.set_status_message
        self.ext_event = None
        try:
            self.ext_event = ExternalEvent.Create(self.ext_handler)
        except:
            self.ext_event = None

        self.Text = u"Дашборд BIM-аудита (Немодальный режим — окно Revit активно) — Вид: {}".format(self.view_name)
        self.Size = Size(1020, 755)
        self.StartPosition = FormStartPosition.CenterScreen
        self.FormBorderStyle = FormBorderStyle.FixedSingle
        self.MaximizeBox = False
        self.MinimizeBox = True
        self.TopMost = True  # Поверх Revit, чтобы окно не пряталось при клике в модель
        self.BackColor = Color.FromArgb(241, 245, 249)

        # --- ВЕРХНЯЯ ПАНЕЛЬ KPI + ОБЩИЙ ПРОГРЕСС-БАР ---
        self.pnl_top = Panel(Location=Point(12, 10), Size=Size(980, 115), BackColor=Color.White)
        self.pnl_top.Paint += self.on_paint_top_kpi

        # Галочка "Поверх окон" и кнопка "Обновить дашборд" прямо в шапке
        self.chk_topmost = CheckBox(
            Text=u"Поверх окна Revit",
            Location=Point(700, 8), Size=Size(135, 22),
            Checked=True, Font=Font("Segoe UI", 8.5, FontStyle.Bold),
            ForeColor=Color.FromArgb(30, 58, 138)
        )
        self.chk_topmost.CheckedChanged += self.on_toggle_topmost
        self.pnl_top.Controls.Add(self.chk_topmost)

        self.btn_refresh = Button(
            Text=u"Обновить данные",
            Location=Point(840, 5), Size=Size(130, 26),
            Font=Font("Segoe UI", 8.5, FontStyle.Bold),
            BackColor=Color.FromArgb(239, 246, 255), ForeColor=Color.FromArgb(29, 78, 216),
            FlatStyle=FlatStyle.Flat
        )
        self.btn_refresh.Click += self.on_refresh_audit
        self.pnl_top.Controls.Add(self.btn_refresh)

        self.Controls.Add(self.pnl_top)

        # --- ВКЛАДКИ ДАШБОРДА ---
        self.tabs = TabControl(Location=Point(12, 132), Size=Size(980, 490), Font=Font("Segoe UI", 9, FontStyle.Regular))

        # Вкладка 1: Визуальная шкала по параметрам и уникальные значения
        self.tab_visual = TabPage(Text=u"1. Графический дашборд по параметрам")
        self.tab_visual.BackColor = Color.White
        self.pnl_bars = Panel(Location=Point(10, 10), Size=Size(952, 440), AutoScroll=True, BackColor=Color.White)
        self.pnl_bars.Paint += self.on_paint_param_bars
        self.tab_visual.Controls.Add(self.pnl_bars)
        self.tabs.TabPages.Add(self.tab_visual)

        # Вкладка 2: Сводка по категориям
        self.tab_cats = TabPage(Text=u"2. Сводка по категориям")
        self.tab_cats.BackColor = Color.White
        self.dgv_cats = self.create_styled_grid(Point(10, 10), Size(952, 440))
        self.populate_categories_grid()
        self.tab_cats.Controls.Add(self.dgv_cats)
        self.tabs.TabPages.Add(self.tab_cats)

        # Вкладка 3: Поэлементная ведомость
        self.tab_elems = TabPage(Text=u"3. Поэлементный список (Ведомость)")
        self.tab_elems.BackColor = Color.White

        self.chk_only_failed = CheckBox(
            Text=u"Показать только проблемные элементы (с незаполненными параметрами)",
            Location=Point(12, 10), Size=Size(510, 22),
            Checked=False, Font=Font("Segoe UI", 9, FontStyle.Bold),
            ForeColor=Color.FromArgb(185, 28, 28)
        )
        self.chk_only_failed.CheckedChanged += self.on_filter_elements_changed
        self.tab_elems.Controls.Add(self.chk_only_failed)

        self.chk_auto_zoom = CheckBox(
            Text=u"Приближать в модели (Zoom)",
            Location=Point(525, 10), Size=Size(195, 22),
            Checked=True, Font=Font("Segoe UI", 8.5, FontStyle.Regular)
        )
        self.tab_elems.Controls.Add(self.chk_auto_zoom)

        lbl_el_search = Label(Text=u"Поиск:", Location=Point(725, 12), Size=Size(50, 20))
        self.tab_elems.Controls.Add(lbl_el_search)

        self.tb_el_filter = TextBox(Location=Point(778, 9), Size=Size(184, 22))
        self.tb_el_filter.TextChanged += self.on_filter_elements_changed
        self.tab_elems.Controls.Add(self.tb_el_filter)

        self.dgv_elems = self.create_styled_grid(Point(10, 38), Size(952, 412))
        self.populate_elements_grid()
        self.tab_elems.Controls.Add(self.dgv_elems)
        self.tabs.TabPages.Add(self.tab_elems)

        self.Controls.Add(self.tabs)

        # --- СТРОКА ЖИВОГО СТАТУСА (ВМЕСТО БЛОКИРУЮЩИХ TASKDIALOG) ---
        self.lbl_status = Label(
            Text=u"✓ Немодальный режим активен: окно Revit разблокировано! Выделяйте элементы кнопками ниже и сразу редактируйте их в Revit.",
            Location=Point(14, 628), Size=Size(976, 22),
            Font=Font("Segoe UI", 9, FontStyle.Bold),
            ForeColor=Color.FromArgb(22, 101, 52)
        )
        self.Controls.Add(self.lbl_status)

        # --- НИЖНЯЯ ПАНЕЛЬ ИНТЕРАКТИВНЫХ ДЕЙСТВИЙ ---
        btn_sel_rows = Button(
            Text=u"Выделить выбранные строки",
            Location=Point(12, 656), Size=Size(195, 38),
            Font=Font("Segoe UI", 8.5, FontStyle.Bold),
            BackColor=Color.FromArgb(30, 64, 175), ForeColor=Color.White,
            FlatStyle=FlatStyle.Flat
        )
        btn_sel_rows.Click += self.on_select_highlighted_in_revit
        self.Controls.Add(btn_sel_rows)

        self.btn_sel_failed = Button(
            Text=u"Выделить ВСЕ проблемные ({})".format(len(self.audit_data['failed_element_ids'])),
            Location=Point(214, 656), Size=Size(215, 38),
            Font=Font("Segoe UI", 8.5, FontStyle.Bold),
            BackColor=Color.FromArgb(180, 83, 9), ForeColor=Color.White,
            FlatStyle=FlatStyle.Flat
        )
        self.btn_sel_failed.Click += self.on_select_all_failed_in_revit
        self.Controls.Add(self.btn_sel_failed)

        btn_iso_failed = Button(
            Text=u"Изолировать на виде (Авто-HI)",
            Location=Point(436, 656), Size=Size(205, 38),
            Font=Font("Segoe UI", 8.5, FontStyle.Bold),
            BackColor=Color.FromArgb(109, 40, 217), ForeColor=Color.White,
            FlatStyle=FlatStyle.Flat
        )
        btn_iso_failed.Click += self.on_isolate_in_revit
        self.Controls.Add(btn_iso_failed)

        btn_reset_iso = Button(
            Text=u"Сброс изоляции (HR)",
            Location=Point(648, 656), Size=Size(135, 38),
            Font=Font("Segoe UI", 8.5, FontStyle.Regular),
            BackColor=Color.White
        )
        btn_reset_iso.Click += self.on_reset_isolation_in_revit
        self.Controls.Add(btn_reset_iso)

        btn_csv = Button(
            Text=u"Экспорт CSV",
            Location=Point(790, 656), Size=Size(100, 38),
            Font=Font("Segoe UI", 8.5, FontStyle.Regular),
            BackColor=Color.White
        )
        btn_csv.Click += self.on_export_csv
        self.Controls.Add(btn_csv)

        btn_close = Button(
            Text=u"Закрыть",
            Location=Point(897, 656), Size=Size(95, 38),
            Font=Font("Segoe UI", 8.5, FontStyle.Bold),
            BackColor=Color.FromArgb(22, 101, 52), ForeColor=Color.White,
            FlatStyle=FlatStyle.Flat
        )
        btn_close.Click += self.on_close_click
        self.Controls.Add(btn_close)

    def set_status_message(self, text_msg, color_obj):
        try:
            self.lbl_status.Text = text_msg
            self.lbl_status.ForeColor = color_obj
        except:
            pass

    def on_toggle_topmost(self, sender, event):
        self.TopMost = self.chk_topmost.Checked

    def on_refresh_audit(self, sender, event):
        """Пересчитывает заполненность параметров после правок пользователя в Revit."""
        try:
            self.audit_data = run_parameter_audit(self.doc, self.view_elem, self.param_names)
            self.btn_sel_failed.Text = u"Выделить ВСЕ проблемные ({})".format(len(self.audit_data['failed_element_ids']))
            self.pnl_top.Invalidate()
            self.pnl_bars.Invalidate()
            self.populate_categories_grid()
            self.populate_elements_grid()
            self.set_status_message(
                u"✓ Данные обновлены! Общий индекс заполненности: {:.1f}% (проблемных элементов: {}).".format(
                    self.audit_data['overall_pct'], len(self.audit_data['failed_element_ids'])
                ),
                Color.FromArgb(22, 101, 52)
            )
        except Exception as ex:
            self.set_status_message(u"Ошибка при обновлении: " + unicode(ex), Color.FromArgb(185, 28, 28))

    def on_close_click(self, sender, event):
        self.Close()

    def create_styled_grid(self, loc, sz):
        dgv = DataGridView(Location=loc, Size=sz)
        dgv.AllowUserToAddRows = False
        dgv.AllowUserToDeleteRows = False
        dgv.ReadOnly = True
        dgv.SelectionMode = DataGridViewSelectionMode.FullRowSelect
        dgv.AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.Fill
        dgv.BackgroundColor = Color.White
        dgv.RowHeadersVisible = False
        dgv.Font = Font("Segoe UI", 8.5, FontStyle.Regular)
        return dgv

    def get_status_color(self, pct):
        if pct >= 90.0:
            return Color.FromArgb(22, 163, 74)
        elif pct >= 60.0:
            return Color.FromArgb(217, 119, 6)
        else:
            return Color.FromArgb(220, 38, 38)

    def on_paint_top_kpi(self, sender, event):
        g = event.Graphics
        d = self.audit_data
        total_el = d['total_elements']
        passed_el = d['fully_filled_elements']
        failed_el = d['failed_elements_count']
        overall_pct = d['overall_pct']

        f_title = Font("Segoe UI", 10.5, FontStyle.Bold)
        f_kpi_num = Font("Segoe UI", 16, FontStyle.Bold)
        f_kpi_lbl = Font("Segoe UI", 8.5, FontStyle.Regular)

        g.DrawString(
            u"Вид: {}  |  Категорий: {}  |  Параметров: {}".format(
                self.view_name, len(d['category_stats']), len(self.param_names)
            ),
            f_title, SolidBrush(Color.FromArgb(15, 23, 42)), 15, 10
        )

        cards = [
            (u"Всего элементов", unicode(total_el), Color.FromArgb(30, 58, 138), 15),
            (u"Заполнены на 100%", unicode(passed_el), Color.FromArgb(22, 101, 52), 185),
            (u"Требуют внимания", unicode(failed_el), Color.FromArgb(185, 28, 28), 355),
            (u"Общий индекс BIM-качества", u"{:.1f}%".format(overall_pct), self.get_status_color(overall_pct), 525)
        ]

        for title, val, col, x_pos in cards:
            rect = Rectangle(x_pos, 40, 158, 62)
            g.FillRectangle(SolidBrush(Color.FromArgb(248, 250, 252)), rect)
            g.DrawRectangle(Pen(Color.FromArgb(226, 232, 240), 1), rect)
            g.DrawString(title, f_kpi_lbl, SolidBrush(Color.FromArgb(100, 116, 139)), x_pos + 10, 46)
            g.DrawString(val, f_kpi_num, SolidBrush(col), x_pos + 10, 64)

        bar_x = 700
        bar_y = 54
        bar_w = 260
        bar_h = 24
        g.DrawString(u"Шкала заполненности модели:", f_kpi_lbl, SolidBrush(Color.FromArgb(71, 85, 105)), bar_x, 36)
        g.FillRectangle(SolidBrush(Color.FromArgb(226, 232, 240)), Rectangle(bar_x, bar_y, bar_w, bar_h))
        fill_w = int(bar_w * (overall_pct / 100.0))
        if fill_w > 0:
            g.FillRectangle(SolidBrush(self.get_status_color(overall_pct)), Rectangle(bar_x, bar_y, fill_w, bar_h))
        g.DrawRectangle(Pen(Color.FromArgb(148, 163, 184), 1), Rectangle(bar_x, bar_y, bar_w, bar_h))
        g.DrawString(
            u"Заполнено ячеек: {} из {}".format(d['total_filled_cells'], d['total_cells']),
            f_kpi_lbl, SolidBrush(Color.FromArgb(71, 85, 105)), bar_x, 83
        )

    def on_paint_param_bars(self, sender, event):
        g = event.Graphics
        p_stats = self.audit_data['param_stats']

        f_param = Font("Segoe UI", 10, FontStyle.Bold)
        f_meta = Font("Segoe UI", 8.5, FontStyle.Regular)
        f_pct = Font("Segoe UI", 9.5, FontStyle.Bold)

        y = 12
        for p_name in self.param_names:
            st = p_stats[p_name]
            pct = st['pct']
            filled = st['filled']
            total = st['total']
            scopes = u"/".join(sorted(st['scopes'])) if st['scopes'] else u"Не найден"
            uniq_cnt = len(st['value_counts'])

            sorted_vals = sorted(st['value_counts'].items(), key=lambda kv: kv[1], reverse=True)[:5]
            top_vals_str = u", ".join([u"{} ({} шт.)".format(k, v) for k, v in sorted_vals])
            if not top_vals_str:
                top_vals_str = u"Нет заполненных значений"

            card_rect = Rectangle(10, y, 910, 88)
            g.FillRectangle(SolidBrush(Color.FromArgb(248, 250, 252)), card_rect)
            g.DrawRectangle(Pen(Color.FromArgb(203, 213, 225), 1), card_rect)

            g.DrawString(
                u"{}   [{}]".format(p_name, scopes),
                f_param, SolidBrush(Color.FromArgb(15, 23, 42)), 22, y + 10
            )

            g.DrawString(
                u"Заполнено: {} из {} ({:.1f}%)   |   Уникальных значений: {}".format(filled, total, pct, uniq_cnt),
                f_pct, SolidBrush(self.get_status_color(pct)), 440, y + 10
            )

            bx, by, bw, bh = 22, y + 36, 880, 20
            g.FillRectangle(SolidBrush(Color.FromArgb(226, 232, 240)), Rectangle(bx, by, bw, bh))
            fw = int(bw * (pct / 100.0))
            if fw > 0:
                g.FillRectangle(SolidBrush(self.get_status_color(pct)), Rectangle(bx, by, fw, bh))
            g.DrawRectangle(Pen(Color.FromArgb(148, 163, 184), 1), Rectangle(bx, by, bw, bh))

            g.DrawString(
                u"Примеры значений: " + top_vals_str,
                f_meta, SolidBrush(Color.FromArgb(71, 85, 105)), 22, y + 62
            )

            y += 98

        self.pnl_bars.AutoScrollMinSize = Size(920, y + 20)

    def populate_categories_grid(self):
        self.dgv_cats.Columns.Clear()
        self.dgv_cats.Rows.Clear()

        self.dgv_cats.Columns.Add("CatName", u"Категория")
        self.dgv_cats.Columns.Add("TotalEl", u"Элементов (шт.)")
        self.dgv_cats.Columns.Add("ReadyPct", u"Общий %")

        for p_name in self.param_names:
            self.dgv_cats.Columns.Add("P_" + p_name, p_name)

        for cat_name in sorted(self.audit_data['category_stats'].keys()):
            c_info = self.audit_data['category_stats'][cat_name]
            row_vals = [
                cat_name,
                unicode(c_info['count']),
                u"{:.1f}%".format(c_info['pct'])
            ]
            for p_name in self.param_names:
                p_filled = c_info['param_filled'].get(p_name, 0)
                p_pct = (100.0 * p_filled / c_info['count']) if c_info['count'] > 0 else 0.0
                row_vals.append(u"{}/{} ({:.0f}%)".format(p_filled, c_info['count'], p_pct))

            row_idx = self.dgv_cats.Rows.Add(*row_vals)
            row_obj = self.dgv_cats.Rows[row_idx]
            if c_info['pct'] < 60.0:
                row_obj.DefaultCellStyle.BackColor = Color.FromArgb(254, 242, 242)
            elif c_info['pct'] < 100.0:
                row_obj.DefaultCellStyle.BackColor = Color.FromArgb(254, 252, 232)
            else:
                row_obj.DefaultCellStyle.BackColor = Color.FromArgb(240, 253, 244)

    def populate_elements_grid(self):
        self.dgv_elems.Columns.Clear()
        self.dgv_elems.Rows.Clear()

        self.dgv_elems.Columns.Add("ElId", u"ID элемента")
        self.dgv_elems.Columns.Add("Cat", u"Категория")
        self.dgv_elems.Columns.Add("FamType", u"Семейство и Тип")
        self.dgv_elems.Columns.Add("Status", u"Статус")

        for p_name in self.param_names:
            self.dgv_elems.Columns.Add("Val_" + p_name, p_name)

        only_failed = self.chk_only_failed.Checked
        q = self.tb_el_filter.Text.strip().lower()

        for item in self.audit_data['element_rows']:
            if only_failed and item['is_ok']:
                continue

            search_blob = (u"{} {} {} ".format(item['id_int'], item['category'], item['fam_type']) + u" ".join(item['values_list'])).lower()
            if q and (q not in search_blob):
                continue

            status_txt = u"ОК (100%)" if item['is_ok'] else u"Не заполнено ({}/{})".format(item['filled_cnt'], len(self.param_names))
            row_vals = [
                unicode(item['id_int']),
                item['category'],
                item['fam_type'],
                status_txt
            ] + item['values_list']

            r_idx = self.dgv_elems.Rows.Add(*row_vals)
            r_obj = self.dgv_elems.Rows[r_idx]
            if not item['is_ok']:
                r_obj.DefaultCellStyle.BackColor = Color.FromArgb(254, 242, 242)

    def on_filter_elements_changed(self, sender, event):
        self.populate_elements_grid()

    def get_target_ids_from_grid_or_failed(self, use_selected_rows=True):
        ids_list = List[ElementId]()
        if use_selected_rows:
            sel_rows = self.dgv_elems.SelectedRows
            for i in range(sel_rows.Count):
                try:
                    id_str = sel_rows[i].Cells[0].Value
                    ids_list.Add(ElementId(int(id_str)))
                except:
                    pass
        else:
            for eid in self.audit_data['failed_element_ids']:
                ids_list.Add(eid)
        return ids_list

    def select_ids_non_blocking(self, ids_list):
        """Выделяет элементы в Revit без блокирующих всплывающих окон."""
        if ids_list.Count == 0:
            return
        try:
            self.uidoc.Selection.SetElementIds(ids_list)
            if self.chk_auto_zoom.Checked and ids_list.Count <= 50:
                try:
                    self.uidoc.ShowElements(ids_list)
                except:
                    pass
            self.set_status_message(
                u"✓ Выделено в Revit: {} шт. Окно Revit активно — можете нажать HI или сразу заполнить параметры в Свойствах!".format(ids_list.Count),
                Color.FromArgb(22, 101, 52)
            )
        except:
            if self.ext_event:
                self.ext_handler.action_type = "SELECT_AND_ZOOM"
                self.ext_handler.element_ids = ids_list
                self.ext_event.Raise()

    def on_select_highlighted_in_revit(self, sender, event):
        if self.tabs.SelectedTab != self.tab_elems:
            self.tabs.SelectedTab = self.tab_elems
        ids_list = self.get_target_ids_from_grid_or_failed(use_selected_rows=True)
        if ids_list.Count == 0:
            self.set_status_message(
                u"Выберите одну или несколько строк в таблице на вкладке «3. Поэлементный список».",
                Color.FromArgb(180, 83, 9)
            )
            return
        self.select_ids_non_blocking(ids_list)

    def on_select_all_failed_in_revit(self, sender, event):
        ids_list = self.get_target_ids_from_grid_or_failed(use_selected_rows=False)
        if ids_list.Count == 0:
            self.set_status_message(
                u"✓ Все проверенные элементы заполнены на 100%! Проблемных элементов нет.",
                Color.FromArgb(22, 101, 52)
            )
            return
        self.select_ids_non_blocking(ids_list)

    def on_isolate_in_revit(self, sender, event):
        """Временно изолирует выбранные строки (или все проблемные элементы) через ExternalEvent."""
        ids_list = self.get_target_ids_from_grid_or_failed(use_selected_rows=True)
        if ids_list.Count == 0:
            ids_list = self.get_target_ids_from_grid_or_failed(use_selected_rows=False)

        if ids_list.Count == 0:
            self.set_status_message(u"Нет проблемных или выбранных элементов для изоляции.", Color.FromArgb(22, 101, 52))
            return

        if self.ext_event:
            self.ext_handler.action_type = "ISOLATE"
            self.ext_handler.element_ids = ids_list
            self.ext_event.Raise()
            self.set_status_message(
                u"Запрос на изоляцию {} элементов отправлен в Revit (переведите курсор в окно модели)...".format(ids_list.Count),
                Color.FromArgb(109, 40, 217)
            )
        else:
            self.select_ids_non_blocking(ids_list)
            self.set_status_message(
                u"Элементы выделены ({} шт.). Кликните в окно Revit и нажмите клавиши HI.".format(ids_list.Count),
                Color.FromArgb(109, 40, 217)
            )

    def on_reset_isolation_in_revit(self, sender, event):
        if self.ext_event:
            self.ext_handler.action_type = "RESET_ISOLATION"
            self.ext_event.Raise()
            self.set_status_message(
                u"Запрос на сброс изоляции отправлен (переведите курсор в окно модели Revit)...",
                Color.FromArgb(30, 64, 175)
            )
        else:
            self.set_status_message(u"Кликните в окно Revit и нажмите клавиши HR для сброса изоляции.", Color.FromArgb(30, 64, 175))

    def on_export_csv(self, sender, event):
        sfd = SaveFileDialog()
        sfd.Title = u"Сохранить отчет проверки параметров (CSV для Excel)"
        sfd.Filter = "CSV files (*.csv)|*.csv"
        sfd.FileName = u"Аудит_параметров_{}.csv".format(self.view_name.replace(u":", u"_").replace(u"/", u"_"))

        if sfd.ShowDialog() == DialogResult.OK:
            try:
                with codecs.open(sfd.FileName, mode='w', encoding='utf-8-sig') as f:
                    headers = [u"ID элемента", u"Категория", u"Семейство и Тип", u"Статус", u"Заполнено параметров"] + self.param_names
                    f.write(u";".join([u'"{}"'.format(h.replace(u'"', u'""')) for h in headers]) + u"\r\n")

                    for item in self.audit_data['element_rows']:
                        st = u"ОК" if item['is_ok'] else u"ОШИБКА"
                        ratio = u"{}/{}".format(item['filled_cnt'], len(self.param_names))
                        row = [unicode(item['id_int']), item['category'], item['fam_type'], st, ratio] + item['values_list']
                        f.write(u";".join([u'"{}"'.format(unicode(c).replace(u'"', u'""')) for c in row]) + u"\r\n")

                self.set_status_message(u"✓ Отчет CSV успешно сохранен: " + sfd.FileName, Color.FromArgb(22, 101, 52))
            except Exception as ex:
                self.set_status_message(u"Ошибка сохранения CSV: " + unicode(ex), Color.FromArgb(185, 28, 28))


# ==============================================================================
# 4. ОСНОВНАЯ ЛОГИКА ВЫПОЛНЕНИЯ И ФОРМИРОВАНИЯ ВЫХОДОВ DYNAMO (OUT)
# ==============================================================================

def run_parameter_audit(doc_ref, view_elem, param_names):
    elements = collect_elements_from_view(doc_ref, view_elem)
    total_elements = len(elements)
    num_params = len(param_names)
    total_cells = total_elements * num_params
    total_filled_cells = 0
    fully_filled_elements = 0

    param_stats = {}
    for p in param_names:
        param_stats[p] = {
            'filled': 0,
            'total': total_elements,
            'pct': 0.0,
            'scopes': set(),
            'value_counts': {}
        }

    category_stats = {}
    element_rows = []
    failed_elements = []
    failed_element_ids = []

    for el in elements:
        cat_name = el.Category.Name if el.Category else u"<Без категории>"
        if cat_name not in category_stats:
            category_stats[cat_name] = {
                'count': 0,
                'filled_cells': 0,
                'total_cells': 0,
                'pct': 0.0,
                'param_filled': {p: 0 for p in param_names}
            }

        cat_entry = category_stats[cat_name]
        cat_entry['count'] += 1
        cat_entry['total_cells'] += num_params

        fam_type = get_element_type_name(doc_ref, el)
        el_values = []
        el_filled_cnt = 0

        for p_name in param_names:
            is_filled, val_str, scope_str = resolve_parameter_value(doc_ref, el, p_name)
            p_entry = param_stats[p_name]

            if scope_str != u"Отсутствует":
                p_entry['scopes'].add(scope_str)

            if is_filled:
                el_filled_cnt += 1
                total_filled_cells += 1
                p_entry['filled'] += 1
                cat_entry['filled_cells'] += 1
                cat_entry['param_filled'][p_name] += 1
                p_entry['value_counts'][val_str] = p_entry['value_counts'].get(val_str, 0) + 1
                el_values.append(u"{} [{}]".format(val_str, scope_str[0]))
            else:
                el_values.append(val_str)

        is_ok = (el_filled_cnt == num_params)
        if is_ok:
            fully_filled_elements += 1
        else:
            failed_elements.append(el)
            failed_element_ids.append(el.Id)

        element_rows.append({
            'id_int': el.Id.IntegerValue,
            'category': cat_name,
            'fam_type': fam_type,
            'filled_cnt': el_filled_cnt,
            'is_ok': is_ok,
            'values_list': el_values
        })

    for p_name in param_names:
        st = param_stats[p_name]
        st['pct'] = (100.0 * st['filled'] / total_elements) if total_elements > 0 else 0.0

    for cat_name, c_entry in category_stats.items():
        c_entry['pct'] = (100.0 * c_entry['filled_cells'] / c_entry['total_cells']) if c_entry['total_cells'] > 0 else 0.0

    overall_pct = (100.0 * total_filled_cells / total_cells) if total_cells > 0 else 0.0

    return {
        'total_elements': total_elements,
        'total_cells': total_cells,
        'total_filled_cells': total_filled_cells,
        'fully_filled_elements': fully_filled_elements,
        'failed_elements_count': len(failed_elements),
        'overall_pct': overall_pct,
        'param_stats': param_stats,
        'category_stats': category_stats,
        'element_rows': element_rows,
        'failed_elements': failed_elements,
        'failed_element_ids': failed_element_ids
    }


# ==============================================================================
# 5. ТОЧКА ВХОДА СКРИПТА
# ==============================================================================

try:
    config_form = ParameterAuditConfigForm(doc)
    res = config_form.ShowDialog()

    if res != DialogResult.OK:
        OUT = [u"Операция отменена пользователем."]
    else:
        target_view = config_form.selected_view
        target_params = config_form.selected_params
        view_title = ElementName(target_view)
        config_form.Dispose()

        audit_result = run_parameter_audit(doc, target_view, target_params)

        if audit_result['total_elements'] == 0:
            TaskDialog.Show(
                u"Нет элементов",
                u"На выбранном виде «{}» не найдено модельных элементов для анализа.".format(view_title)
            )
            OUT = [u"На виде '{}' не найдено модельных элементов.".format(view_title)]
        else:
            # КЛЮЧЕВОЕ ОТЛИЧИЕ: открываем дашборд через .Show() (НЕМОДАЛЬНО!),
            # чтобы Dynamo сразу завершил скрипт и разблокировал окно Revit!
            dash_form = AuditDashboardForm(doc, uidoc, target_view, target_params, audit_result)
            dash_form.Show()

            # Формируем структурированные списки для выходов нода Python в Dynamo
            summary_report = []
            summary_report.append(u"=== СВОДНЫЙ ОТЧЕТ АУДИТА ПАРАМЕТРОВ ===")
            summary_report.append(u"Вид / Спецификация: {}".format(view_title))
            summary_report.append(u"Проверено элементов: {}".format(audit_result['total_elements']))
            summary_report.append(u"Полностью заполнены (без ошибок): {} ({:.1f}%)".format(
                audit_result['fully_filled_elements'],
                100.0 * audit_result['fully_filled_elements'] / audit_result['total_elements']
            ))
            summary_report.append(u"Требуют доработки: {}".format(audit_result['failed_elements_count']))
            summary_report.append(u"Общий индекс заполненности ячеек: {:.1f}% ({} из {})".format(
                audit_result['overall_pct'],
                audit_result['total_filled_cells'],
                audit_result['total_cells']
            ))
            summary_report.append(u"")
            summary_report.append(u"--- ДЕТАЛИЗАЦИЯ ПО ПАРАМЕТРАМ И КОЛИЧЕСТВУ ЗНАЧЕНИЙ ---")

            for p_name in target_params:
                st = audit_result['param_stats'][p_name]
                scopes_str = u"/".join(sorted(st['scopes'])) if st['scopes'] else u"Параметр отсутствует"
                summary_report.append(
                    u"• {} [{}] -> Заполнено: {}/{} ({:.1f}%) | Уникальных значений: {}".format(
                        p_name, scopes_str, st['filled'], st['total'], st['pct'], len(st['value_counts'])
                    )
                )
                for val_k, val_cnt in sorted(st['value_counts'].items(), key=lambda kv: kv[1], reverse=True):
                    summary_report.append(u"    - Значение «{}»: {} шт.".format(val_k, val_cnt))

            category_report = []
            for cat_name in sorted(audit_result['category_stats'].keys()):
                c_st = audit_result['category_stats'][cat_name]
                p_details = u", ".join([
                    u"{}: {}/{}".format(p, c_st['param_filled'][p], c_st['count'])
                    for p in target_params
                ])
                category_report.append(
                    u"[{}] Элементов: {} | Заполненность: {:.1f}% | ({})".format(
                        cat_name, c_st['count'], c_st['pct'], p_details
                    )
                )

            element_report = []
            for r in audit_result['element_rows']:
                status_tag = u"[OK]" if r['is_ok'] else u"[НЕ ЗАПОЛНЕН]"
                vals_joined = u" | ".join([
                    u"{}={}".format(target_params[i], r['values_list'][i])
                    for i in range(len(target_params))
                ])
                element_report.append(
                    u"{} ID {} | {} | {} -> {}".format(
                        status_tag, r['id_int'], r['category'], r['fam_type'], vals_joined
                    )
                )

            OUT = [
                summary_report,
                category_report,
                element_report,
                audit_result['failed_elements']
            ]

except Exception as e:
    OUT = [u"Ошибка выполнения скрипта:\n" + traceback.format_exc()]
