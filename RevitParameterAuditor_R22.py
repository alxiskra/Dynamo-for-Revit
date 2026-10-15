# -*- coding: utf-8 -*-
# _______________________________________________________________________
# Описание: Интерактивный аудит и НЕМОДАЛЬНЫЙ дашборд заполненности параметров
#           элементов (Экземпляр и Тип) на 3D-виде, плане или в спецификации
# Версия: v3.1 (Чистая компактная структура кода без потери функционала v3.0)
# Автор: Alexander Iskra (alxiskra)
# Протестировано на Revit: v2022 (IronPython 2.7)
# _______________________________________________________________________
#
# КАРТА СТРУКТУРЫ КОДА (ДЛЯ БЫСТРОЙ НАВИГАЦИИ):
#   БЛОК 1. Базовые настройки, UI-помощники и Менеджер конфигураций JSON (AuditConfigManager)
#   БЛОК 2. Немодальный обработчик команд Revit (RevitModelessActionHandler / ExternalEvent)
#   БЛОК 3. Функции анализа модели Revit (чтение/запись параметров Экземпляра и Типа, фильтр категорий)
#   БЛОК 4. Окно 1 — Настройка проверки и каталог всех параметров (ParameterAuditConfigForm)
#   БЛОК 5. Окно 2 — Карточка редактирования параметров элемента по 2х-клику (ElementParameterEditorForm)
#   БЛОК 6. Окно 3 — Главный немодальный графический дашборд (AuditDashboardForm) + Точка входа (OUT)
# _______________________________________________________________________

import clr
import sys
import os
import json
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
    Transaction, TemporaryViewMode, TypeBinding
)
from Autodesk.Revit.UI import TaskDialog, IExternalEventHandler, ExternalEvent
from RevitServices.Persistence import DocumentManager
from System.Collections.Generic import List

from System.Windows.Forms import (
    Form, Button, DialogResult, FormBorderStyle, FormStartPosition,
    CheckBox, Label, ComboBox, ComboBoxStyle, TextBox,
    Control, Keys, MouseButtons, Panel, TabControl, TabPage, DataGridView,
    DataGridViewSelectionMode, DataGridViewAutoSizeColumnsMode,
    DataGridViewCheckBoxColumn, DataGridViewTextBoxColumn,
    ScrollBars, SaveFileDialog, OpenFileDialog, GroupBox,
    ListBox, BorderStyle, FlatStyle, AnchorStyles
)
from System.Drawing import (
    Size, Point, Font, FontStyle, Color, SolidBrush, Pen, Rectangle, ContentAlignment
)

doc = DocumentManager.Instance.CurrentDBDocument
uiapp = DocumentManager.Instance.CurrentUIApplication
uidoc = uiapp.ActiveUIDocument


# ==============================================================================
# БЛОК 1. КОНСТАНТЫ, UI-ХЕЛПЕРЫ И МЕНЕДЖЕР КОНФИГУРАЦИЙ (JSON)
# ==============================================================================

# Привязки краев элементов (чтобы окна можно было растягивать мышкой как стандартные)
ANC_TL = AnchorStyles.Top | AnchorStyles.Left
ANC_TR = AnchorStyles.Top | AnchorStyles.Right
ANC_TLR = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right
ANC_TBL = AnchorStyles.Top | AnchorStyles.Bottom | AnchorStyles.Left
ANC_BL = AnchorStyles.Bottom | AnchorStyles.Left
ANC_BR = AnchorStyles.Bottom | AnchorStyles.Right
ANC_BLR = AnchorStyles.Bottom | AnchorStyles.Left | AnchorStyles.Right
ANC_ALL = AnchorStyles.Top | AnchorStyles.Bottom | AnchorStyles.Left | AnchorStyles.Right

# Общие шрифты и цвета интерфейса
FONT_REG = Font("Segoe UI", 8.5, FontStyle.Regular)
FONT_BOLD = Font("Segoe UI", 8.5, FontStyle.Bold)
FONT_9_REG = Font("Segoe UI", 9.0, FontStyle.Regular)
FONT_9_BOLD = Font("Segoe UI", 9.0, FontStyle.Bold)
FONT_10_BOLD = Font("Segoe UI", 10.0, FontStyle.Bold)
FONT_TITLE = Font("Segoe UI", 11.0, FontStyle.Bold)

DEFAULT_PARAMS_LIST = [u"Код по классификатору"]
FALLBACK_CATALOG_PARAMS = [
    u"Код по классификатору", u"Марка", u"Комментарии",
    u"Комментарии к типоразмеру", u"Описание"
]


def ui_label(text, x, y, w, h, font=FONT_REG, color=None, align=None, anchor=None, ellipsis=False):
    """Компактное создание текстовой метки Label в одну строчку."""
    lbl = Label(Text=text, Location=Point(x, y), Size=Size(w, h), Font=font, AutoEllipsis=ellipsis)
    if color is not None:
        lbl.ForeColor = color
    if align is not None:
        lbl.TextAlign = align
    if anchor is not None:
        lbl.Anchor = anchor
    return lbl


def ui_button(text, x, y, w, h, on_click=None, font=FONT_REG, bg=None, fg=None, flat=False, anchor=None, dlg_res=None):
    """Компактное создание кнопки Button в одну строчку."""
    btn = Button(Text=text, Location=Point(x, y), Size=Size(w, h), Font=font)
    btn.BackColor = bg if bg is not None else Color.White
    if fg is not None:
        btn.ForeColor = fg
    if flat:
        btn.FlatStyle = FlatStyle.Flat
    if anchor is not None:
        btn.Anchor = anchor
    if dlg_res is not None:
        btn.DialogResult = dlg_res
    if on_click is not None:
        btn.Click += on_click
    return btn


def ui_check(text, x, y, w, h, checked=True, on_change=None, font=FONT_REG, color=None, anchor=None):
    """Компактное создание галочки CheckBox в одну строчку."""
    chk = CheckBox(Text=text, Location=Point(x, y), Size=Size(w, h), Checked=checked, Font=font)
    if color is not None:
        chk.ForeColor = color
    if anchor is not None:
        chk.Anchor = anchor
    if on_change is not None:
        chk.CheckedChanged += on_change
    return chk


def save_json_file(filepath, data_dict):
    """Сохраняет словарь настроек в читаемый UTF-8 JSON с поддержкой кириллицы."""
    try:
        raw_json = json.dumps(data_dict, ensure_ascii=False, indent=2, sort_keys=True)
        if isinstance(raw_json, str):
            raw_json = raw_json.decode('utf-8')
        with codecs.open(filepath, mode='w', encoding='utf-8') as f:
            f.write(raw_json)
        return True
    except:
        try:
            raw_json = json.dumps(data_dict, ensure_ascii=True, indent=2, sort_keys=True)
            with codecs.open(filepath, mode='w', encoding='utf-8') as f:
                f.write(unicode(raw_json))
            return True
        except:
            return False


def load_json_file(filepath):
    """Читает JSON-файл конфигурации с диска."""
    if not os.path.exists(filepath):
        return None
    for enc in ('utf-8-sig', 'utf-8'):
        try:
            with codecs.open(filepath, mode='r', encoding=enc) as f:
                return json.loads(f.read())
        except:
            pass
    return None


class AuditConfigManager(object):
    """Отвечает за автосохранение сессии, хранение профилей и импорт/экспорт .json."""
    def __init__(self):
        appdata = os.environ.get('APPDATA') or os.path.expanduser('~')
        cfg_dir = os.path.join(appdata, u"RevitParameterAuditor")
        if not os.path.exists(cfg_dir):
            try:
                os.makedirs(cfg_dir)
            except:
                pass
        self.config_path = os.path.join(cfg_dir, u"audit_configs_v30.json")
        self.store = self.load_store()

    def get_default_store(self):
        base = {u"params": list(DEFAULT_PARAMS_LIST), u"input_mode": u"semicolon", u"category_states": {}}
        return {
            u"active_profile": u"По умолчанию",
            u"last_session": dict(base),
            u"profiles": {u"По умолчанию": dict(base)}
        }

    def load_store(self):
        data = load_json_file(self.config_path)
        def_store = self.get_default_store()
        if not isinstance(data, dict):
            save_json_file(self.config_path, def_store)
            return def_store
        if not isinstance(data.get(u"profiles"), dict) or not data[u"profiles"]:
            data[u"profiles"] = def_store[u"profiles"]
        if not isinstance(data.get(u"last_session"), dict):
            data[u"last_session"] = def_store[u"last_session"]
        if data.get(u"active_profile") not in data[u"profiles"]:
            data[u"active_profile"] = sorted(data[u"profiles"].keys())[0]
        return data

    def save_store(self):
        return save_json_file(self.config_path, self.store)

    def get_profile_names(self):
        return sorted(self.store.get(u"profiles", {}).keys())

    def get_active_profile_name(self):
        return self.store.get(u"active_profile", u"По умолчанию")

    def get_last_session(self):
        return self.store.get(u"last_session", {u"params": list(DEFAULT_PARAMS_LIST), u"category_states": {}})

    def get_profile_data(self, profile_name):
        return self.store.get(u"profiles", {}).get(profile_name, self.get_last_session())

    def save_profile(self, profile_name, params_list, category_states_dict, input_mode=u"semicolon"):
        profile_name = profile_name.strip()
        if not profile_name:
            return False
        if category_states_dict is None:
            existing = self.store[u"profiles"].get(profile_name, {})
            category_states_dict = existing.get(u"category_states", dict(self.get_last_session().get(u"category_states", {})))
        prof_obj = {
            u"params": list(params_list),
            u"input_mode": unicode(input_mode),
            u"category_states": dict(category_states_dict)
        }
        self.store.setdefault(u"profiles", {})[profile_name] = prof_obj
        self.store[u"active_profile"] = profile_name
        self.store[u"last_session"] = dict(prof_obj)
        return self.save_store()

    def delete_profile(self, profile_name):
        profiles = self.store.get(u"profiles", {})
        if profile_name in profiles and len(profiles) > 1:
            del profiles[profile_name]
            self.store[u"active_profile"] = sorted(profiles.keys())[0]
            self.save_store()
            return True
        return False

    def update_last_session(self, params_list=None, category_states_dict=None, input_mode=None, also_update_active_profile=False):
        ls = self.get_last_session()
        if params_list is not None:
            ls[u"params"] = list(params_list)
        if category_states_dict is not None:
            merged = dict(ls.get(u"category_states", {}))
            for k, v in category_states_dict.items():
                merged[k] = bool(v)
            ls[u"category_states"] = merged
        if input_mode is not None:
            ls[u"input_mode"] = unicode(input_mode)
        self.store[u"last_session"] = ls

        if also_update_active_profile:
            act_name = self.get_active_profile_name()
            if act_name in self.store.get(u"profiles", {}):
                p_obj = self.store[u"profiles"][act_name]
                if params_list is not None:
                    p_obj[u"params"] = list(params_list)
                if category_states_dict is not None:
                    merged_p = dict(p_obj.get(u"category_states", {}))
                    for k, v in category_states_dict.items():
                        merged_p[k] = bool(v)
                    p_obj[u"category_states"] = merged_p
        return self.save_store()

    def export_single_config_to_file(self, filepath, profile_name, params_list, category_states_dict):
        return save_json_file(filepath, {
            u"format": u"RevitParameterAuditorConfig_v3.1",
            u"profile_name": unicode(profile_name),
            u"params": list(params_list),
            u"category_states": dict(category_states_dict) if category_states_dict else {}
        })

    def import_config_from_file(self, filepath):
        data = load_json_file(filepath)
        if not isinstance(data, dict):
            return None
        if u"params" in data:
            p_name = data.get(u"profile_name") or os.path.splitext(os.path.basename(filepath))[0]
            params = [unicode(x).strip() for x in data.get(u"params", []) if unicode(x).strip()] or list(DEFAULT_PARAMS_LIST)
            cat_states = data.get(u"category_states", {})
        elif u"last_session" in data:
            ls = data[u"last_session"]
            p_name = data.get(u"active_profile", u"Импортированный профиль")
            params = ls.get(u"params", list(DEFAULT_PARAMS_LIST))
            cat_states = ls.get(u"category_states", {})
        else:
            return None
        self.save_profile(p_name, params, cat_states)
        return {u"profile_name": p_name, u"params": params, u"category_states": cat_states}


# ==============================================================================
# БЛОК 2. ОБРАБОТЧИК EXTERNAL EVENT (ДЛЯ РАБОТЫ С REVIT ИЗ НЕМОДАЛЬНОГО ОКНА)
# ==============================================================================

class RevitModelessActionHandler(IExternalEventHandler):
    """Выполняет изоляцию элементов и запись параметров в контексте Revit API."""
    def __init__(self):
        self.action_type = None
        self.element_ids = None
        self.target_element_id_int = None
        self.params_to_set = None
        self.on_params_written_callback = None
        self.status_callback = None

    def Execute(self, uiapp_ref):
        try:
            active_uidoc = uiapp_ref.ActiveUIDocument
            if not active_uidoc:
                return
            active_doc = active_uidoc.Document
            target_view = active_uidoc.ActiveGraphicalView or active_doc.ActiveView

            if self.action_type == "ISOLATE" and self.element_ids and self.element_ids.Count > 0:
                active_uidoc.Selection.SetElementIds(self.element_ids)
                if target_view and not isinstance(target_view, ViewSchedule):
                    t = Transaction(active_doc, u"BIM Аудит: Временная изоляция элементов")
                    t.Start()
                    target_view.IsolateElementsTemporary(self.element_ids)
                    t.Commit()
                    if self.status_callback:
                        self.status_callback(u"✓ Изолировано элементов на виде: {}.".format(self.element_ids.Count), Color.FromArgb(22, 101, 52))
                elif self.status_callback:
                    self.status_callback(u"Элементы выделены ({} шт.). Переключитесь на 3D-вид для изоляции.".format(self.element_ids.Count), Color.FromArgb(180, 83, 9))

            elif self.action_type == "RESET_ISOLATION":
                if target_view and not isinstance(target_view, ViewSchedule):
                    t = Transaction(active_doc, u"BIM Аудит: Сброс временной изоляции")
                    t.Start()
                    target_view.DisableTemporaryViewMode(TemporaryViewMode.TemporaryHideIsolate)
                    t.Commit()
                    if self.status_callback:
                        self.status_callback(u"✓ Временная изоляция (HI) сброшена.", Color.FromArgb(30, 64, 175))

            elif self.action_type == "SELECT_AND_ZOOM" and self.element_ids and self.element_ids.Count > 0:
                active_uidoc.Selection.SetElementIds(self.element_ids)
                try:
                    active_uidoc.ShowElements(self.element_ids)
                except:
                    pass
                if self.status_callback:
                    self.status_callback(u"✓ Выделено в модели: {} шт.".format(self.element_ids.Count), Color.FromArgb(22, 101, 52))

            elif self.action_type == "SET_ELEMENT_PARAMS" and self.target_element_id_int is not None and self.params_to_set:
                target_el = active_doc.GetElement(ElementId(int(self.target_element_id_int)))
                if target_el is not None:
                    t = Transaction(active_doc, u"BIM Аудит: Запись значений параметров")
                    t.Start()
                    changed_cnt, errors = 0, []
                    for p_name, new_val in self.params_to_set.items():
                        ok, msg, _ = write_single_parameter_value(active_doc, target_el, p_name, new_val)
                        if ok:
                            changed_cnt += 1
                        else:
                            errors.append(u"{}: {}".format(p_name, msg))
                    t.Commit()
                    if self.on_params_written_callback:
                        self.on_params_written_callback(self.target_element_id_int, changed_cnt, errors)
        except Exception as ex:
            if self.status_callback:
                self.status_callback(u"Ошибка действия в Revit: " + unicode(ex), Color.FromArgb(185, 28, 28))

    def GetName(self):
        return "RevitParameterAuditModelessHandler"


# ==============================================================================
# БЛОК 3. ФУНКЦИИ АНАЛИЗА МОДЕЛИ REVIT (ПАРАМЕТРЫ ЭКЗЕМПЛЯРА/ТИПА И КАТЕГОРИИ)
# ==============================================================================

HARD_IGNORED_BIC_NAMES = (
    "OST_Cameras", "OST_SectionBox", "OST_Viewers", "OST_SharedBasePoint", "OST_ProjectBasePoint"
)

RARE_BIC_NAMES = (
    "OST_CurtainGrids", "OST_CurtainGridsWall", "OST_CurtainGridsSystem", "OST_CurtainGridsRoof",
    "OST_CurtainGridsCurtaSystem", "OST_Lines", "OST_SketchLines", "OST_CurveElem",
    "OST_RoomSeparationLines", "OST_AreaSchemeLines", "OST_SpaceSeparationLines",
    "OST_MEPSpaceSeparationLines", "OST_InsulationLines", "OST_Materials", "OST_ShaftOpening",
    "OST_ArcWallRectOpening", "OST_SWallRectOpening", "OST_ColumnOpening", "OST_FloorOpening",
    "OST_RoofOpening", "OST_CeilingOpening", "OST_PipingSystem", "OST_DuctSystem",
    "OST_SwitchSystem", "OST_ElectricalCircuit", "OST_DetailComponents", "OST_RasterImages",
    "OST_Mass", "OST_MassFloor", "OST_MassWall", "OST_MassRoof", "OST_MassGlazing",
    "OST_Topography", "OST_Site", "OST_Planting", "OST_Entourage", "OST_Roads", "OST_Parking",
    "OST_RvtLinks", "OST_Parts", "OST_Assemblies", "OST_IOSModelGroups", "OST_Levels",
    "OST_Grids", "OST_CLines", "OST_ScopeBoxes", "OST_ReferencePoints", "OST_HVAC_Zones",
    "OST_ZoneEquipment", "OST_AnalyticalNodes", "OST_AnalyticalMember", "OST_BeamAnalytical",
    "OST_ColumnAnalytical", "OST_FloorAnalytical", "OST_WallAnalytical",
    "OST_FoundationSlabAnalytical", "OST_IsolatedFoundationAnalytical",
    "OST_AnalyticalPipeConnections", "OST_RebarShape", "OST_FabricAreas", "OST_Coupler"
)

HARD_IGNORED_BICS = set(int(getattr(BuiltInCategory, n)) for n in HARD_IGNORED_BIC_NAMES if hasattr(BuiltInCategory, n))
RARE_BICS = set(int(getattr(BuiltInCategory, n)) for n in RARE_BIC_NAMES if hasattr(BuiltInCategory, n))

RARE_CATEGORY_KEYWORDS = (
    u"схемы разрезки", u"разрезки витраж", u"разрезка витраж", u"curtain grid", u"curtain wall grid",
    u"линии", u"lines", u"разделител", u"separation", u"материал", u"material",
    u"аналитическ", u"analytical", u"антураж", u"entourage", u"озеленени", u"planting",
    u"топограф", u"topograph", u"генплан", u"площадк", u"парковк", u"parking",
    u"проем", u"opening", u"шахт", u"shaft", u"элементы узлов", u"detail item",
    u"связанн", u"rvt link", u"группы", u"model group", u"формы", u"формообразующ", u"mass",
    u"системы воздуховодов", u"трубопроводные системы", u"цепи", u"duct system",
    u"piping system", u"electrical circuit", u"зоны", u"hvac zone", u"пространств", u"spaces",
    u"сборки", u"части", u"parts", u"assemblies", u"оси", u"уровни", u"grids", u"levels",
    u"област", u"scope box", u"растров", u"raster", u"вспомогательн", u"эскиз", u"sketch"
)


def is_rare_or_service_category(cat_name, cat_id_int=None):
    """Проверяет, относится ли категория к редким/служебным (чтобы отключить ее по умолчанию)."""
    if cat_id_int is not None and cat_id_int in RARE_BICS:
        return True
    if not cat_name:
        return True
    low = cat_name.strip().lower()
    return any(kw in low for kw in RARE_CATEGORY_KEYWORDS)


def ElementName(elem):
    """Безопасно получает имя элемента в IronPython 2."""
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
    """Возвращает строку 'Семейство : Тип' для ведомости."""
    try:
        type_id = elem.GetTypeId()
        if type_id and type_id != ElementId.InvalidElementId:
            type_elem = doc_ref.GetElement(type_id)
            if type_elem:
                fam_name = getattr(type_elem, 'FamilyName', '')
                t_name = ElementName(type_elem)
                return u"{} : {}".format(fam_name, t_name) if (fam_name and t_name) else (t_name or ElementName(elem))
        return ElementName(elem)
    except:
        return u"<Без имени типа>"


def resolve_parameter_value(doc_ref, elem, param_name):
    """Ищет параметр сначала у Экземпляра, затем у Типа. Возвращает (is_filled, value_str, scope_str)."""
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
            if val_str and val_str.strip() != u"" and val_str.strip().lower() not in (u"нет", u"none"):
                return (True, val_str.strip(), scope_str)
            return (False, u"<Не назначено>", scope_str)
        val_str = param.AsValueString()
        if not val_str:
            target_el = doc_ref.GetElement(eid)
            val_str = ElementName(target_el) if target_el else unicode(eid.IntegerValue)
        return (True, val_str, scope_str)

    elif st == StorageType.Integer:
        return (True, param.AsValueString() or unicode(param.AsInteger()), scope_str)

    elif st == StorageType.Double:
        return (True, param.AsValueString() or unicode(round(param.AsDouble(), 4)), scope_str)

    return (False, u"<Пусто>", scope_str)


def inspect_editable_parameter(doc_ref, elem, param_name):
    """Определяет метаданные параметра для карточки редактирования по двойному клику."""
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
        return {'exists': False, 'is_readonly': True, 'scope': u"Отсутствует", 'storage_type': None, 'current_val': u""}

    is_ro = bool(param.IsReadOnly) or (param.StorageType == StorageType.ElementId)
    is_filled, val_str, _ = resolve_parameter_value(doc_ref, elem, param_name)
    return {
        'exists': True,
        'is_readonly': is_ro,
        'scope': scope_str,
        'storage_type': param.StorageType,
        'current_val': val_str if is_filled else u""
    }


def write_single_parameter_value(doc_ref, elem, param_name, new_value_str):
    """Записывает новое значение в параметр Экземпляра или Типа (внутри открытой транзакции)."""
    param = elem.LookupParameter(param_name)
    is_type_param = False
    if param is None:
        type_id = elem.GetTypeId()
        if type_id and type_id != ElementId.InvalidElementId:
            type_elem = doc_ref.GetElement(type_id)
            if type_elem:
                param = type_elem.LookupParameter(param_name)
                if param is not None:
                    is_type_param = True

    if param is None:
        return (False, u"Параметр не найден", False)
    if param.IsReadOnly:
        return (False, u"Параметр только для чтения", is_type_param)

    st = param.StorageType
    val_clean = new_value_str.strip() if new_value_str is not None else u""
    try:
        if st == StorageType.String:
            param.Set(val_clean)
        elif st == StorageType.Integer:
            param.Set(0 if val_clean == u"" else int(float(val_clean.replace(u",", u"."))))
        elif st == StorageType.Double:
            if val_clean == u"":
                param.Set(0.0)
            elif not param.SetValueString(val_clean):
                param.Set(float(val_clean.replace(u",", u".")))
        else:
            return (False, u"Тип ElementId не меняется текстом", is_type_param)
        return (True, u"ОК", is_type_param)
    except Exception as ex:
        return (False, unicode(ex), is_type_param)


def collect_elements_from_view(doc_ref, view_elem):
    """Собирает все модельные элементы с выбранного вида или спецификации."""
    raw_elements = FilteredElementCollector(doc_ref, view_elem.Id).WhereElementIsNotElementType().ToElements()
    valid_elements = []
    for el in raw_elements:
        try:
            cat = el.Category
            if cat is None or cat.Id.IntegerValue in HARD_IGNORED_BICS:
                continue
            if cat.CategoryType != CategoryType.Model and not is_rare_or_service_category(cat.Name, cat.Id.IntegerValue):
                continue
            valid_elements.append(el)
        except:
            continue
    return valid_elements


def discover_available_parameters(doc_ref, view_elem=None):
    """Быстро собирает каталог всех доступных параметров (Экземпляр и Тип) для правого списка."""
    params_map = {}

    def register_p(p_name, scope_label):
        if p_name and p_name.strip():
            params_map.setdefault(p_name.strip(), set()).add(scope_label)

    if view_elem is not None:
        try:
            raw_els = FilteredElementCollector(doc_ref, view_elem.Id).WhereElementIsNotElementType().ToElements()
            seen_types, seen_cats, sampled = set(), set(), 0
            for el in raw_els:
                try:
                    cat = el.Category
                    if not cat or cat.Id.IntegerValue in HARD_IGNORED_BICS or is_rare_or_service_category(cat.Name, cat.Id.IntegerValue):
                        continue
                    c_id = cat.Id.IntegerValue
                    t_id = el.GetTypeId()
                    t_id_int = t_id.IntegerValue if t_id else -1
                    if (t_id_int != -1 and t_id_int in seen_types) and (c_id in seen_cats):
                        continue
                    seen_cats.add(c_id)
                    if t_id_int != -1:
                        seen_types.add(t_id_int)

                    for p in el.Parameters:
                        if p.Definition and p.Definition.Name:
                            register_p(p.Definition.Name, u"Экземпляр")
                    if t_id and t_id != ElementId.InvalidElementId:
                        t_elem = doc_ref.GetElement(t_id)
                        if t_elem:
                            for tp in t_elem.Parameters:
                                if tp.Definition and tp.Definition.Name:
                                    register_p(tp.Definition.Name, u"Тип")
                    sampled += 1
                    if sampled >= 120:
                        break
                except:
                    continue
        except:
            pass

    try:
        it = doc_ref.ParameterBindings.ForwardIterator()
        it.Reset()
        while it.MoveNext():
            if it.Key and it.Key.Name:
                register_p(it.Key.Name, u"Тип" if isinstance(it.Current, TypeBinding) else u"Экземпляр")
    except:
        pass
    return params_map


def build_all_revit_categories_catalog(doc_ref, view_elements, saved_category_states=None):
    """Строит полный список категорий Revit (активные на виде + серые неактивные)."""
    saved_category_states = saved_category_states or {}
    catalog = {}

    for el in view_elements:
        try:
            cat = el.Category
            if not cat or not cat.Name:
                continue
            c_name, c_id = cat.Name, cat.Id.IntegerValue
            if c_name not in catalog:
                rare_flag = is_rare_or_service_category(c_name, c_id)
                enabled_flag = bool(saved_category_states[c_name]) if (c_name in saved_category_states) else (not rare_flag)
                catalog[c_name] = {'name': c_name, 'id_int': c_id, 'count_on_view': 0, 'is_rare': rare_flag, 'enabled': enabled_flag}
            catalog[c_name]['count_on_view'] += 1
        except:
            continue

    try:
        for c in doc_ref.Settings.Categories:
            try:
                if c and c.Name and c.CategoryType == CategoryType.Model and c.Id.IntegerValue not in HARD_IGNORED_BICS:
                    if c.Name not in catalog:
                        catalog[c.Name] = {
                            'name': c.Name, 'id_int': c.Id.IntegerValue, 'count_on_view': 0,
                            'is_rare': is_rare_or_service_category(c.Name, c.Id.IntegerValue), 'enabled': False
                        }
            except:
                continue
    except:
        pass
    return catalog


def scan_raw_view_elements(doc_ref, view_elem, param_names, saved_category_states=None):
    """Однократно считывает все элементы вида в оперативную память для мгновенной фильтрации."""
    elements = collect_elements_from_view(doc_ref, view_elem)
    categories_catalog = build_all_revit_categories_catalog(doc_ref, elements, saved_category_states)
    raw_records = []
    for el in elements:
        raw_records.append({
            'element': el,
            'id': el.Id,
            'id_int': el.Id.IntegerValue,
            'category': el.Category.Name if el.Category else u"<Без категории>",
            'fam_type': get_element_type_name(doc_ref, el),
            'param_results': {p_name: resolve_parameter_value(doc_ref, el, p_name) for p_name in param_names}
        })
    return raw_records, categories_catalog


def aggregate_audit_from_records(raw_records, param_names, enabled_categories_set):
    """Пересчитывает проценты, категории и таблицы по включенным категориям из кэша в памяти."""
    filtered_records = [r for r in raw_records if r['category'] in enabled_categories_set]
    total_elements = len(filtered_records)
    num_params = len(param_names)
    total_cells = total_elements * num_params
    total_filled_cells = 0
    fully_filled_elements = 0

    param_stats = {
        p: {'filled': 0, 'total': total_elements, 'pct': 0.0, 'scopes': set(), 'value_counts': {}, 'missing_ids': []}
        for p in param_names
    }
    category_stats, element_rows, failed_elements, failed_element_ids = {}, [], [], []

    for rec in filtered_records:
        cat_name = rec['category']
        if cat_name not in category_stats:
            category_stats[cat_name] = {'count': 0, 'filled_cells': 0, 'total_cells': 0, 'pct': 0.0, 'param_filled': {p: 0 for p in param_names}}
        cat_entry = category_stats[cat_name]
        cat_entry['count'] += 1
        cat_entry['total_cells'] += num_params

        el_values, el_filled_cnt = [], 0
        for p_name in param_names:
            is_filled, val_str, scope_str = rec['param_results'][p_name]
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
            else:
                p_entry['missing_ids'].append(rec['id'])
            el_values.append(val_str)

        is_ok = (el_filled_cnt == num_params)
        if is_ok:
            fully_filled_elements += 1
        else:
            failed_elements.append(rec['element'])
            failed_element_ids.append(rec['id'])

        element_rows.append({
            'id_int': rec['id_int'], 'category': cat_name, 'fam_type': rec['fam_type'],
            'filled_cnt': el_filled_cnt, 'is_ok': is_ok, 'values_list': el_values
        })

    for st in param_stats.values():
        st['pct'] = (100.0 * st['filled'] / total_elements) if total_elements > 0 else 0.0
    for c_entry in category_stats.values():
        c_entry['pct'] = (100.0 * c_entry['filled_cells'] / c_entry['total_cells']) if c_entry['total_cells'] > 0 else 0.0

    return {
        'total_elements': total_elements, 'total_cells': total_cells, 'total_filled_cells': total_filled_cells,
        'fully_filled_elements': fully_filled_elements, 'failed_elements_count': len(failed_elements),
        'overall_pct': (100.0 * total_filled_cells / total_cells) if total_cells > 0 else 0.0,
        'param_stats': param_stats, 'category_stats': category_stats, 'element_rows': element_rows,
        'failed_elements': failed_elements, 'failed_element_ids': failed_element_ids
    }


# ==============================================================================
# БЛОК 4. ОКНО 1 — НАСТРОЙКА ПРОВЕРКИ И КАТАЛОГ ПАРАМЕТРОВ (ParameterAuditConfigForm)
# ==============================================================================

class ParameterAuditConfigForm(Form):
    """Первое окно: выбор профиля, 3D-вида/спецификации (слева) и каталог всех параметров (справа)."""
    def __init__(self, doc_ref, cfg_mgr, current_view_override=None, current_params_override=None):
        self.doc = doc_ref
        self.cfg_mgr = cfg_mgr
        self.current_view_override = current_view_override
        self.Text = u"BIM Аудит параметров модели v3.1 (Revit 2022)"
        self.Size = Size(960, 780)
        self.MinimumSize = Size(880, 640)
        self.StartPosition = FormStartPosition.CenterScreen
        self.FormBorderStyle = FormBorderStyle.Sizable
        self.MaximizeBox = True
        self.MinimizeBox = True
        self.TopMost = True
        self.BackColor = Color.FromArgb(245, 247, 250)
        self.Shown += self.on_form_shown

        self.selected_view = None
        self.selected_params = []
        self.available_views_dict = {}
        self.discovered_params_map = {}
        self._suppress_profile_change = False
        self._suppress_text_sync = False

        last_sess = self.cfg_mgr.get_last_session()
        initial_params = list(current_params_override) if current_params_override else (last_sess.get(u"params") or list(DEFAULT_PARAMS_LIST))
        self.selected_category_states = dict(last_sess.get(u"category_states", {}))

        # --- ШАПКА ---
        pnl_hdr = Panel(Location=Point(0, 0), Size=Size(944, 52), BackColor=Color.FromArgb(30, 41, 59), Anchor=ANC_TLR)
        pnl_hdr.Controls.Add(ui_label(u"Проверка заполненности обязательных параметров (v3.1)", 15, 8, 750, 22, FONT_TITLE, Color.White))
        pnl_hdr.Controls.Add(ui_label(u"Слева: выбор вида и проверяемых параметров  |  Справа: каталог всех доступных параметров модели", 15, 30, 780, 18, FONT_REG, Color.FromArgb(148, 163, 184)))
        self.chk_topmost = ui_check(u"Поверх окон", 815, 15, 115, 22, True, self.on_toggle_topmost, FONT_BOLD, Color.White, ANC_TR)
        pnl_hdr.Controls.Add(self.chk_topmost)
        self.Controls.Add(pnl_hdr)

        # --- ЛЕВАЯ КОЛОНКА: БЛОК ПРОФИЛЕЙ ---
        grp_cfg = GroupBox(Text=u"Профиль настроек (Параметры + Фильтр категорий)", Location=Point(15, 58), Size=Size(485, 86), Font=FONT_9_BOLD, Anchor=ANC_TL)
        self.cb_profiles = ComboBox(Location=Point(12, 22), Size=Size(250, 24), DropDownStyle=ComboBoxStyle.DropDown, Font=FONT_9_REG)
        self.cb_profiles.SelectedIndexChanged += self.on_profile_selected
        grp_cfg.Controls.Add(self.cb_profiles)
        grp_cfg.Controls.Add(ui_button(u"Сохранить профиль", 268, 21, 130, 26, self.on_save_profile_click, FONT_BOLD, Color.FromArgb(239, 246, 255), Color.FromArgb(30, 64, 175), True))
        grp_cfg.Controls.Add(ui_button(u"Удалить", 404, 21, 68, 26, self.on_delete_profile_click))
        grp_cfg.Controls.Add(ui_button(u"Загрузить из JSON...", 12, 53, 165, 25, self.on_import_json_click))
        grp_cfg.Controls.Add(ui_button(u"Выгрузить в JSON...", 183, 53, 165, 25, self.on_export_json_click))
        self.lbl_cfg_status = ui_label(u"Автосохранение вкл.", 352, 56, 120, 18, Font("Segoe UI", 7.5, FontStyle.Regular), Color.FromArgb(22, 101, 52), ContentAlignment.MiddleRight)
        grp_cfg.Controls.Add(self.lbl_cfg_status)
        self.Controls.Add(grp_cfg)

        # --- ЛЕВАЯ КОЛОНКА: БЛОК 1 (ВЫБОР ВИДА) ---
        grp_view = GroupBox(Text=u"1. Источник элементов (3D-вид, План или Спецификация)", Location=Point(15, 150), Size=Size(485, 235), Font=FONT_9_BOLD, Anchor=ANC_TL)
        self.chk_3d = ui_check(u"3D-виды", 12, 22, 85, 20, True, self.refresh_views_list)
        self.chk_sched = ui_check(u"Спецификации", 102, 22, 118, 20, True, self.refresh_views_list)
        self.chk_plans = ui_check(u"Планы / Разрезы", 225, 22, 130, 20, False, self.refresh_views_list)
        grp_view.Controls.Add(self.chk_3d)
        grp_view.Controls.Add(self.chk_sched)
        grp_view.Controls.Add(self.chk_plans)
        grp_view.Controls.Add(ui_button(u"Активный вид", 372, 19, 100, 24, self.on_select_active_view))
        grp_view.Controls.Add(ui_label(u"Поиск или точное имя вида:", 12, 48, 460, 18))
        self.tb_view_search = TextBox(Location=Point(12, 68), Size=Size(460, 22), Font=FONT_9_REG)
        self.tb_view_search.TextChanged += self.refresh_views_list
        grp_view.Controls.Add(self.tb_view_search)
        self.lb_views = ListBox(Location=Point(12, 95), Size=Size(460, 128), Font=FONT_9_REG)
        self.lb_views.SelectedIndexChanged += self.on_selected_view_changed
        grp_view.Controls.Add(self.lb_views)
        self.Controls.Add(grp_view)

        # --- ЛЕВАЯ КОЛОНКА: БЛОК 2 (ВЫБРАННЫЕ ПАРАМЕТРЫ) ---
        grp_params = GroupBox(Text=u"2. Выбранные параметры для анализа (через разделитель «;»)", Location=Point(15, 392), Size=Size(485, 285), Font=FONT_9_BOLD, Anchor=ANC_TBL)
        grp_params.Controls.Add(ui_label(
            u"Кликайте по параметрам в каталоге СПРАВА (для добавления/удаления)\nили редактируйте список параметров через точку с запятой (;) вручную:",
            12, 24, 460, 34, FONT_REG, Color.FromArgb(51, 65, 85), None, ANC_TL
        ))
        self.tb_semicolon = TextBox(
            Location=Point(12, 62), Size=Size(460, 170), Multiline=True, ScrollBars=ScrollBars.Vertical,
            Font=Font("Segoe UI", 9.5, FontStyle.Regular), Text=u";".join(initial_params), Anchor=ANC_ALL
        )
        self.tb_semicolon.TextChanged += self.on_semicolon_text_changed
        grp_params.Controls.Add(self.tb_semicolon)
        grp_params.Controls.Add(ui_button(u"Очистить поле", 12, 240, 135, 30, self.on_clear_params_click, FONT_REG, None, None, False, ANC_BL))
        self.lbl_selected_cnt = ui_label(u"Выбрано параметров: {} шт.".format(len(initial_params)), 250, 246, 222, 20, FONT_BOLD, Color.FromArgb(30, 64, 175), ContentAlignment.MiddleRight, ANC_BR)
        grp_params.Controls.Add(self.lbl_selected_cnt)
        self.Controls.Add(grp_params)

        # --- ПРАВАЯ КОЛОНКА: БЛОК 3 (КАТАЛОГ ВСЕХ ПАРАМЕТРОВ) ---
        grp_cat = GroupBox(Text=u"3. Все доступные параметры (Клик по строке = добавить / убрать)", Location=Point(512, 58), Size=Size(420, 619), Font=FONT_9_BOLD, Anchor=ANC_ALL)
        grp_cat.Controls.Add(ui_label(u"Живой поиск параметра (например: Марка, Код, Комментарии, Этаж):", 12, 22, 395, 18, FONT_REG, None, None, ANC_TLR))
        self.tb_catalog_search = TextBox(Location=Point(12, 42), Size=Size(310, 23), Font=FONT_9_REG, Anchor=ANC_TLR)
        self.tb_catalog_search.TextChanged += self.refresh_catalog_grid
        grp_cat.Controls.Add(self.tb_catalog_search)
        grp_cat.Controls.Add(ui_button(u"Сброс", 328, 41, 80, 25, self.on_clear_catalog_search, FONT_REG, None, None, False, ANC_TR))

        self.chk_cat_inst = ui_check(u"Экземпляр", 12, 71, 95, 20, True, self.refresh_catalog_grid, FONT_REG, None, ANC_TL)
        self.chk_cat_type = ui_check(u"Тип", 112, 71, 60, 20, True, self.refresh_catalog_grid, FONT_REG, None, ANC_TL)
        self.chk_click_to_toggle = ui_check(u"One-Click", 180, 71, 120, 20, True, None, FONT_BOLD, Color.FromArgb(22, 101, 52), ANC_TL)
        grp_cat.Controls.Add(self.chk_cat_inst)
        grp_cat.Controls.Add(self.chk_cat_type)
        grp_cat.Controls.Add(self.chk_click_to_toggle)

        self.dgv_catalog = DataGridView(
            Location=Point(12, 96), Size=Size(396, 472), AllowUserToAddRows=False, AllowUserToDeleteRows=False,
            ReadOnly=True, MultiSelect=True, SelectionMode=DataGridViewSelectionMode.FullRowSelect,
            AutoSizeColumnsMode=DataGridViewAutoSizeColumnsMode.Fill, BackgroundColor=Color.White,
            RowHeadersVisible=False, Font=FONT_REG, Anchor=ANC_ALL
        )
        for col_name, hdr_text, weight in (("AddedState", u"В списке", 18), ("ParamName", u"Имя параметра", 57), ("ParamScope", u"Принадлежность", 25)):
            col = DataGridViewTextBoxColumn(Name=col_name, HeaderText=hdr_text, FillWeight=weight)
            self.dgv_catalog.Columns.Add(col)
        self.dgv_catalog.CellMouseClick += self.on_catalog_cell_mouse_click
        self.dgv_catalog.CellDoubleClick += self.on_catalog_cell_double_click
        grp_cat.Controls.Add(self.dgv_catalog)

        grp_cat.Controls.Add(ui_button(u"← Добавить выделенные (Shift/Ctrl)", 12, 576, 235, 32, self.on_add_selected_from_catalog, FONT_BOLD, Color.FromArgb(239, 246, 255), Color.FromArgb(30, 64, 175), True, ANC_BL))
        self.lbl_catalog_total = ui_label(u"Найдено: 0", 252, 583, 155, 20, FONT_REG, Color.FromArgb(100, 116, 139), ContentAlignment.MiddleRight, ANC_BR)
        grp_cat.Controls.Add(self.lbl_catalog_total)
        self.Controls.Add(grp_cat)

        # --- НИЖНИЕ КНОПКИ ЗАПУСКА ---
        self.btn_run = ui_button(u"Запустить анализ и открыть Дашборд", 565, 690, 260, 42, self.on_run_click, Font("Segoe UI", 9.5, FontStyle.Bold), Color.FromArgb(37, 99, 235), Color.White, True, ANC_BR)
        self.btn_cancel = ui_button(u"Отмена", 835, 690, 97, 42, None, FONT_9_REG, Color.White, None, False, ANC_BR, DialogResult.Cancel)
        self.Controls.Add(self.btn_run)
        self.Controls.Add(self.btn_cancel)
        self.AcceptButton = self.btn_run
        self.CancelButton = self.btn_cancel

        self.populate_profiles_combo()
        self.refresh_views_list()
        self.select_initial_active_view()
        self.reload_discovered_parameters_for_current_view()

    def on_toggle_topmost(self, sender, event):
        self.TopMost = self.chk_topmost.Checked

    def on_form_shown(self, sender, event):
        try:
            self.TopMost = self.chk_topmost.Checked
            self.BringToFront()
            self.Activate()
        except:
            pass

    def get_currently_highlighted_view_obj(self):
        if self.lb_views.SelectedItem and self.lb_views.SelectedItem in self.available_views_dict:
            return self.available_views_dict[self.lb_views.SelectedItem]
        return self.doc.ActiveView

    def reload_discovered_parameters_for_current_view(self):
        self.discovered_params_map = discover_available_parameters(self.doc, self.get_currently_highlighted_view_obj())
        for p in FALLBACK_CATALOG_PARAMS:
            self.discovered_params_map.setdefault(p, set([u"Экземпляр/Тип"]))
        self.refresh_catalog_grid()

    def on_selected_view_changed(self, sender, event):
        self.reload_discovered_parameters_for_current_view()

    def on_clear_catalog_search(self, sender, event):
        self.tb_catalog_search.Text = u""

    def refresh_catalog_grid(self, sender=None, event=None):
        if not hasattr(self, 'dgv_catalog'):
            return
        self.dgv_catalog.Rows.Clear()
        q = self.tb_catalog_search.Text.strip().lower()
        show_inst, show_type = self.chk_cat_inst.Checked, self.chk_cat_type.Checked
        current_selected_set = set(self.get_current_ui_params())
        shown_cnt = 0

        for p_name in sorted(self.discovered_params_map.keys(), key=lambda s: s.lower()):
            if q and (q not in p_name.lower()):
                continue
            scopes = self.discovered_params_map[p_name]
            has_inst = (u"Экземпляр" in scopes) or (u"Экземпляр/Тип" in scopes)
            has_type = (u"Тип" in scopes) or (u"Экземпляр/Тип" in scopes)
            if not ((show_inst and has_inst) or (show_type and has_type)):
                continue

            is_added = (p_name in current_selected_set)
            r_idx = self.dgv_catalog.Rows.Add(u"✓ Да" if is_added else u"+", p_name, u" / ".join(sorted(scopes)))
            row_obj = self.dgv_catalog.Rows[r_idx]
            row_obj.DefaultCellStyle.BackColor = Color.FromArgb(220, 252, 231) if is_added else Color.White
            row_obj.DefaultCellStyle.ForeColor = Color.FromArgb(22, 101, 52) if is_added else Color.FromArgb(15, 23, 42)
            shown_cnt += 1

        self.lbl_catalog_total.Text = u"Параметров: {}".format(shown_cnt)

    def update_catalog_visual_highlights_only(self):
        current_selected_set = set(self.get_current_ui_params())
        for i in range(self.dgv_catalog.Rows.Count):
            r_obj = self.dgv_catalog.Rows[i]
            is_added = (r_obj.Cells[1].Value in current_selected_set)
            r_obj.Cells[0].Value = u"✓ Да" if is_added else u"+"
            r_obj.DefaultCellStyle.BackColor = Color.FromArgb(220, 252, 231) if is_added else Color.White
            r_obj.DefaultCellStyle.ForeColor = Color.FromArgb(22, 101, 52) if is_added else Color.FromArgb(15, 23, 42)
        self.lbl_selected_cnt.Text = u"Выбрано параметров: {} шт.".format(len(current_selected_set))

    def toggle_or_add_param_from_catalog(self, p_name):
        if not p_name:
            return
        current_list = self.get_current_ui_params()
        if p_name in current_list:
            current_list = [x for x in current_list if x != p_name]
        else:
            current_list.append(p_name)
        self.apply_params_to_ui(current_list, allow_empty=True)
        self.update_catalog_visual_highlights_only()

    def on_catalog_cell_mouse_click(self, sender, event):
        if event.Button != MouseButtons.Left or event.RowIndex < 0:
            return
        mods = Control.ModifierKeys
        if ((mods & Keys.Shift) == Keys.Shift) or ((mods & Keys.Control) == Keys.Control):
            return
        if not self.chk_click_to_toggle.Checked and event.ColumnIndex != 0:
            return
        self.toggle_or_add_param_from_catalog(self.dgv_catalog.Rows[event.RowIndex].Cells[1].Value)

    def on_catalog_cell_double_click(self, sender, event):
        if event.RowIndex >= 0 and not self.chk_click_to_toggle.Checked:
            self.toggle_or_add_param_from_catalog(self.dgv_catalog.Rows[event.RowIndex].Cells[1].Value)

    def on_add_selected_from_catalog(self, sender, event):
        sel_rows = self.dgv_catalog.SelectedRows
        if sel_rows.Count == 0:
            return
        current_list = self.get_current_ui_params()
        for idx in sorted([sel_rows[i].Index for i in range(sel_rows.Count)]):
            p_name = self.dgv_catalog.Rows[idx].Cells[1].Value
            if p_name and p_name not in current_list:
                current_list.append(p_name)
        self.apply_params_to_ui(current_list, allow_empty=True)
        self.update_catalog_visual_highlights_only()

    def on_semicolon_text_changed(self, sender, event):
        if not self._suppress_text_sync and hasattr(self, 'dgv_catalog'):
            self.update_catalog_visual_highlights_only()

    def on_clear_params_click(self, sender, event):
        self.apply_params_to_ui([], allow_empty=True)
        self.update_catalog_visual_highlights_only()

    def populate_profiles_combo(self):
        self._suppress_profile_change = True
        self.cb_profiles.Items.Clear()
        prof_names = self.cfg_mgr.get_profile_names()
        for name in prof_names:
            self.cb_profiles.Items.Add(name)
        act_prof = self.cfg_mgr.get_active_profile_name()
        self.cb_profiles.Text = act_prof if act_prof in prof_names else (prof_names[0] if prof_names else u"")
        self._suppress_profile_change = False

    def get_current_ui_params(self):
        raw_text = self.tb_semicolon.Text.replace(u"\r", u"").replace(u"\n", u";")
        unique_params = []
        for x in raw_text.split(u";"):
            p = x.strip()
            if p and p not in unique_params:
                unique_params.append(p)
        return unique_params

    def apply_params_to_ui(self, params_list, allow_empty=False):
        self._suppress_text_sync = True
        if not params_list and not allow_empty:
            params_list = list(DEFAULT_PARAMS_LIST)
        self.tb_semicolon.Text = u";".join(params_list)
        self.lbl_selected_cnt.Text = u"Выбрано параметров: {} шт.".format(len(params_list))
        self._suppress_text_sync = False

    def on_profile_selected(self, sender, event):
        if self._suppress_profile_change:
            return
        prof_name = self.cb_profiles.Text.strip()
        prof_data = self.cfg_mgr.get_profile_data(prof_name)
        if prof_data:
            p_list = prof_data.get(u"params", list(DEFAULT_PARAMS_LIST))
            self.apply_params_to_ui(p_list)
            self.selected_category_states = dict(prof_data.get(u"category_states", {}))
            self.cfg_mgr.store[u"active_profile"] = prof_name
            self.cfg_mgr.update_last_session(params_list=p_list, category_states_dict=self.selected_category_states)
            self.update_catalog_visual_highlights_only()
            self.lbl_cfg_status.Text = u"Профиль загружен"

    def on_save_profile_click(self, sender, event):
        prof_name = self.cb_profiles.Text.strip()
        params = self.get_current_ui_params()
        if not prof_name or not params:
            TaskDialog.Show(u"Сохранение профиля", u"Укажите имя профиля и хотя бы один параметр.")
            return
        if self.cfg_mgr.save_profile(prof_name, params, self.selected_category_states):
            self.populate_profiles_combo()
            self.lbl_cfg_status.Text = u"✓ Сохранено!"

    def on_delete_profile_click(self, sender, event):
        if self.cfg_mgr.delete_profile(self.cb_profiles.Text.strip()):
            self.populate_profiles_combo()
            self.on_profile_selected(None, None)
            self.lbl_cfg_status.Text = u"Профиль удален"
        else:
            TaskDialog.Show(u"Удаление профиля", u"Нельзя удалить единственный оставшийся профиль.")

    def on_import_json_click(self, sender, event):
        ofd = OpenFileDialog(Title=u"Загрузить файл конфигурации (.json)", Filter="JSON Config (*.json)|*.json")
        if ofd.ShowDialog() == DialogResult.OK:
            imported = self.cfg_mgr.import_config_from_file(ofd.FileName)
            if imported:
                self.populate_profiles_combo()
                self.apply_params_to_ui(imported[u"params"])
                self.selected_category_states = dict(imported.get(u"category_states", {}))
                self.update_catalog_visual_highlights_only()
                self.lbl_cfg_status.Text = u"✓ Импортирован JSON"

    def on_export_json_click(self, sender, event):
        prof_name = self.cb_profiles.Text.strip() or u"Профиль_BIM_аудита"
        sfd = SaveFileDialog(
            Title=u"Выгрузить конфигурацию в JSON", Filter="JSON Config (*.json)|*.json",
            FileName=u"Конфиг_аудита_{}.json".format(prof_name.replace(u" ", u"_").replace(u":", u"_"))
        )
        if sfd.ShowDialog() == DialogResult.OK:
            if self.cfg_mgr.export_single_config_to_file(sfd.FileName, prof_name, self.get_current_ui_params(), self.selected_category_states):
                self.lbl_cfg_status.Text = u"✓ Выгружен JSON"

    def get_view_prefix(self, v):
        vt = v.ViewType
        if vt == ViewType.ThreeD:
            return u"[3D Вид] "
        if vt == ViewType.Schedule:
            return u"[Спецификация] "
        if vt in (ViewType.FloorPlan, ViewType.CeilingPlan, ViewType.EngineeringPlan, ViewType.AreaPlan):
            return u"[План] "
        if vt in (ViewType.Section, ViewType.Elevation):
            return u"[Разрез/Фасад] "
        return u"[Вид] "

    def refresh_views_list(self, sender=None, event=None):
        self.lb_views.Items.Clear()
        self.available_views_dict.clear()
        search_q = self.tb_view_search.Text.strip().lower()
        display_items = []

        for v in FilteredElementCollector(self.doc).OfClass(View).ToElements():
            try:
                if v.IsTemplate:
                    continue
                vt = v.ViewType
                is_3d = (vt == ViewType.ThreeD)
                is_sched = (vt == ViewType.Schedule and not getattr(v, 'IsInternalKeynoteSchedule', False) and not getattr(v, 'IsTitleblockRevisionSchedule', False))
                is_plan = (vt in (ViewType.FloorPlan, ViewType.CeilingPlan, ViewType.EngineeringPlan, ViewType.Section, ViewType.Elevation))
                if not ((self.chk_3d.Checked and is_3d) or (self.chk_sched.Checked and is_sched) or (self.chk_plans.Checked and is_plan)):
                    continue
                v_name = ElementName(v)
                disp = self.get_view_prefix(v) + v_name
                if not search_q or (search_q in disp.lower()) or (search_q in v_name.lower()):
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
            target_v = self.current_view_override or self.doc.ActiveView
            if target_v:
                target_disp = self.get_view_prefix(target_v) + ElementName(target_v)
                for i in range(self.lb_views.Items.Count):
                    if self.lb_views.Items[i] == target_disp:
                        self.lb_views.SelectedIndex = i
                        return
        except:
            pass

    def on_select_active_view(self, sender, event):
        try:
            if self.doc.ActiveView:
                self.chk_3d.Checked = self.chk_sched.Checked = self.chk_plans.Checked = True
                self.tb_view_search.Text = ElementName(self.doc.ActiveView)
                self.refresh_views_list()
        except:
            pass

    def on_run_click(self, sender, event):
        chosen_view = self.available_views_dict.get(self.lb_views.SelectedItem) if self.lb_views.SelectedItem else None
        if chosen_view is None:
            typed_name = self.tb_view_search.Text.strip().lower()
            for v_obj in self.available_views_dict.values():
                if ElementName(v_obj).lower() == typed_name:
                    chosen_view = v_obj
                    break
        if chosen_view is None:
            TaskDialog.Show(u"Ошибка выбора вида", u"Выберите 3D-вид, план или спецификацию из списка слева.")
            return

        unique_params = self.get_current_ui_params()
        if not unique_params:
            TaskDialog.Show(u"Ошибка параметров", u"Выберите хотя бы один параметр для анализа.")
            return

        self.cfg_mgr.update_last_session(params_list=unique_params, category_states_dict=self.selected_category_states)
        self.selected_view = chosen_view
        self.selected_params = unique_params
        self.DialogResult = DialogResult.OK
        self.Close()


# ==============================================================================
# БЛОК 5. ОКНО 2 — КАРТОЧКА РЕДАКТИРОВАНИЯ ЭЛЕМЕНТА ПО 2Х-КЛИКУ (ElementParameterEditorForm)
# ==============================================================================

class ElementParameterEditorForm(Form):
    """Окно редактирования параметров выбранного элемента с поддержкой прокрутки и растягивания."""
    def __init__(self, doc_ref, elem, param_names, param_stats):
        self.doc = doc_ref
        self.elem = elem
        self.param_names = param_names
        self.param_stats = param_stats
        self.updated_values = {}
        self.input_controls = {}

        el_id_int = elem.Id.IntegerValue
        cat_name = elem.Category.Name if elem.Category else u"<Без категории>"
        fam_type = get_element_type_name(doc_ref, elem)

        self.Text = u"Редактирование параметров элемента — ID {}".format(el_id_int)
        form_h = min(680, max(360, 185 + len(param_names) * 68))
        self.Size = Size(580, form_h)
        self.MinimumSize = Size(480, 320)
        self.StartPosition = FormStartPosition.CenterParent
        self.FormBorderStyle = FormBorderStyle.Sizable
        self.MaximizeBox = True
        self.MinimizeBox = False
        self.TopMost = True
        self.BackColor = Color.FromArgb(245, 247, 250)
        self.Shown += self.on_shown

        pnl_hdr = Panel(Location=Point(0, 0), Size=Size(564, 62), BackColor=Color.FromArgb(30, 41, 59), Anchor=ANC_TLR)
        pnl_hdr.Controls.Add(ui_label(u"Элемент ID: {}  |  {}".format(el_id_int, cat_name), 14, 8, 410, 22, FONT_10_BOLD, Color.White, None, ANC_TLR))
        pnl_hdr.Controls.Add(ui_label(u"Семейство и Тип: {}".format(fam_type), 14, 32, 530, 20, FONT_REG, Color.FromArgb(148, 163, 184), None, ANC_TLR, True))
        self.chk_topmost = ui_check(u"Поверх окон", 440, 8, 112, 22, True, self.on_toggle_topmost, FONT_BOLD, Color.White, ANC_TR)
        pnl_hdr.Controls.Add(self.chk_topmost)
        self.Controls.Add(pnl_hdr)

        self.pnl_list = Panel(Location=Point(12, 70), Size=Size(540, form_h - 165), AutoScroll=True, BackColor=Color.White, BorderStyle=BorderStyle.FixedSingle, Anchor=ANC_ALL)

        y = 10
        for idx, p_name in enumerate(self.param_names):
            meta = inspect_editable_parameter(self.doc, self.elem, p_name)
            scope, is_ro, exists, cur_val = meta['scope'], meta['is_readonly'], meta['exists'], meta['current_val']

            row_pnl = Panel(
                Location=Point(8, y), Size=Size(500, 58), BorderStyle=BorderStyle.FixedSingle, Anchor=ANC_TLR,
                BackColor=Color.FromArgb(248, 250, 252) if exists else Color.FromArgb(254, 242, 242)
            )
            row_pnl.Controls.Add(ui_label(u"{}. {}".format(idx + 1, p_name), 10, 6, 270, 20, FONT_9_BOLD, Color.FromArgb(15, 23, 42), None, ANC_TLR))

            if not exists:
                scope_text, scope_col = u"[Нет параметра у элемента]", Color.FromArgb(185, 28, 28)
            elif is_ro:
                scope_text, scope_col = u"[{} — Только чтение]".format(scope), Color.FromArgb(100, 116, 139)
            elif scope == u"Тип":
                scope_text, scope_col = u"[Параметр ТИПА]", Color.FromArgb(109, 40, 217)
            else:
                scope_text, scope_col = u"[Параметр ЭКЗЕМПЛЯРА]", Color.FromArgb(22, 101, 52)

            row_pnl.Controls.Add(ui_label(scope_text, 285, 6, 202, 20, FONT_BOLD, scope_col, ContentAlignment.MiddleRight, ANC_TR))

            cb_val = ComboBox(Location=Point(10, 28), Size=Size(478, 24), Font=FONT_9_REG, DropDownStyle=ComboBoxStyle.DropDown, Anchor=ANC_TLR)
            for existing_v, _cnt in sorted(self.param_stats.get(p_name, {}).get('value_counts', {}).items(), key=lambda kv: kv[1], reverse=True)[:25]:
                cb_val.Items.Add(existing_v)
            cb_val.Text = cur_val
            if is_ro or not exists:
                cb_val.Enabled = False
            else:
                self.input_controls[p_name] = (cb_val, cur_val)

            row_pnl.Controls.Add(cb_val)
            self.pnl_list.Controls.Add(row_pnl)
            y += 64

        self.pnl_list.AutoScrollMinSize = Size(440, y + 10)
        self.Controls.Add(self.pnl_list)

        btn_y = form_h - 84
        self.btn_ok = ui_button(u"ОК (Записать в модель)", 252, btn_y, 195, 36, self.on_ok_click, FONT_9_BOLD, Color.FromArgb(22, 101, 52), Color.White, True, ANC_BR)
        self.btn_cancel = ui_button(u"Отмена", 457, btn_y, 95, 36, None, FONT_9_REG, Color.White, None, False, ANC_BR, DialogResult.Cancel)
        self.Controls.Add(self.btn_ok)
        self.Controls.Add(self.btn_cancel)
        self.AcceptButton = self.btn_ok
        self.CancelButton = self.btn_cancel

    def on_toggle_topmost(self, sender, event):
        self.TopMost = self.chk_topmost.Checked

    def on_shown(self, sender, event):
        try:
            self.TopMost = self.chk_topmost.Checked
            self.BringToFront()
            self.Activate()
            self.pnl_list.Focus()
        except:
            pass

    def on_ok_click(self, sender, event):
        self.updated_values = {
            p_name: cb_ctrl.Text.strip()
            for p_name, (cb_ctrl, old_val) in self.input_controls.items()
            if cb_ctrl.Text.strip() != old_val
        }
        self.DialogResult = DialogResult.OK
        self.Close()


# ==============================================================================
# БЛОК 6. ОКНО 3 — ГЛАВНЫЙ НЕМОДАЛЬНЫЙ ДАШБОРД (AuditDashboardForm) И ВЫХОДЫ OUT
# ==============================================================================

class AuditDashboardForm(Form):
    """Немодальный дашборд с 4 вкладками, живой связью с моделью Revit и экспортом CSV/JSON."""
    def __init__(self, doc_ref, uidoc_ref, cfg_mgr, view_elem, param_names, raw_records, categories_catalog, initial_audit_data):
        self.doc = doc_ref
        self.uidoc = uidoc_ref
        self.cfg_mgr = cfg_mgr
        self.view_elem = view_elem
        self.view_name = ElementName(view_elem)
        self.param_names = param_names
        self.raw_records = raw_records
        self.categories_catalog = categories_catalog
        self.audit_data = initial_audit_data

        self._is_populating_cat_filter = False
        self.last_checkbox_clicked_row = -1
        self._prev_selected_cat_rows = []
        self._curr_selected_cat_rows = []

        self.ext_handler = RevitModelessActionHandler()
        self.ext_handler.status_callback = self.set_status_message
        self.ext_handler.on_params_written_callback = self.on_element_params_written
        try:
            self.ext_event = ExternalEvent.Create(self.ext_handler)
        except:
            self.ext_event = None

        self.Text = u"Дашборд BIM-аудита v3.1 (Немодальный режим — окно Revit активно) — Вид: {}".format(self.view_name)
        self.Size = Size(1020, 755)
        self.MinimumSize = Size(960, 620)
        self.StartPosition = FormStartPosition.CenterScreen
        self.FormBorderStyle = FormBorderStyle.Sizable
        self.MaximizeBox = True
        self.MinimizeBox = True
        self.TopMost = True
        self.BackColor = Color.FromArgb(241, 245, 249)

        # --- ВЕРХНЯЯ ПАНЕЛЬ KPI ---
        self.pnl_top = Panel(Location=Point(12, 10), Size=Size(980, 115), BackColor=Color.White, Anchor=ANC_TLR)
        self.pnl_top.Paint += self.on_paint_top_kpi
        self.chk_topmost = ui_check(u"Поверх окон", 595, 8, 105, 22, True, self.on_toggle_topmost, FONT_BOLD, Color.FromArgb(30, 58, 138), ANC_TR)
        self.pnl_top.Controls.Add(self.chk_topmost)
        self.pnl_top.Controls.Add(ui_button(u"⚙ Параметры / Вид", 705, 5, 130, 26, self.on_reopen_config_dialog, FONT_BOLD, Color.White, Color.FromArgb(51, 65, 85), False, ANC_TR))
        self.pnl_top.Controls.Add(ui_button(u"Обновить данные", 842, 5, 128, 26, self.on_refresh_audit_from_revit, FONT_BOLD, Color.FromArgb(239, 246, 255), Color.FromArgb(29, 78, 216), True, ANC_TR))
        self.Controls.Add(self.pnl_top)

        # --- ВКЛАДКИ ДАШБОРДА ---
        self.tabs = TabControl(Location=Point(12, 132), Size=Size(980, 490), Font=FONT_9_REG, Anchor=ANC_ALL)

        # Вкладка 1: Шкалы параметров
        self.tab_visual = TabPage(Text=u"1. Графический дашборд по параметрам", BackColor=Color.White)
        self.pnl_bars = Panel(Location=Point(8, 8), Size=Size(956, 444), AutoScroll=True, BackColor=Color.White, Anchor=ANC_ALL)
        self.tab_visual.Controls.Add(self.pnl_bars)
        self.tabs.TabPages.Add(self.tab_visual)

        # Вкладка 2: Сводка по категориям
        self.tab_cats = TabPage(Text=u"2. Сводка по категориям", BackColor=Color.White)
        self.dgv_cats = self.create_styled_grid(10, 10, 952, 440, ANC_ALL)
        self.tab_cats.Controls.Add(self.dgv_cats)
        self.tabs.TabPages.Add(self.tab_cats)

        # Вкладка 3: Поэлементная ведомость
        self.tab_elems = TabPage(Text=u"3. Поэлементный список (Ведомость)", BackColor=Color.White)
        self.chk_only_failed = ui_check(u"Показать только проблемные элементы (с незаполненными параметрами)", 12, 10, 510, 22, False, self.on_filter_elements_changed, FONT_9_BOLD, Color.FromArgb(185, 28, 28), ANC_TL)
        self.chk_auto_zoom = ui_check(u"Приближать в модели (Zoom)", 525, 10, 195, 22, True, None, FONT_REG, None, ANC_TL)
        self.tab_elems.Controls.Add(self.chk_only_failed)
        self.tab_elems.Controls.Add(self.chk_auto_zoom)
        self.tab_elems.Controls.Add(ui_label(u"Поиск:", 725, 12, 50, 20, FONT_REG, None, None, ANC_TR))
        self.tb_el_filter = TextBox(Location=Point(778, 9), Size=Size(184, 22), Anchor=ANC_TR)
        self.tb_el_filter.TextChanged += self.on_filter_elements_changed
        self.tab_elems.Controls.Add(self.tb_el_filter)
        self.dgv_elems = self.create_styled_grid(10, 38, 952, 412, ANC_ALL)
        self.dgv_elems.CellDoubleClick += self.on_element_row_double_click
        self.tab_elems.Controls.Add(self.dgv_elems)
        self.tabs.TabPages.Add(self.tab_elems)

        # Вкладка 4: Фильтр категорий и Конфиг
        self.tab_cat_filter = TabPage(Text=u"4. Фильтр категорий и Конфиг", BackColor=Color.White)
        self.chk_show_zero_cats = ui_check(u"Показывать неактивные категории (0 элементов — серые)", 12, 10, 430, 22, True, self.on_cat_filter_ui_changed, FONT_REG, None, ANC_TL)
        self.chk_auto_recalc_cats = ui_check(u"Мгновенно обновлять дашборд и авто-сохранять фильтр", 448, 10, 335, 22, True, None, FONT_BOLD, Color.FromArgb(22, 101, 52), ANC_TL)
        self.tab_cat_filter.Controls.Add(self.chk_show_zero_cats)
        self.tab_cat_filter.Controls.Add(self.chk_auto_recalc_cats)
        self.tab_cat_filter.Controls.Add(ui_label(u"Поиск:", 785, 12, 48, 20, FONT_REG, None, None, ANC_TR))
        self.tb_cat_search = TextBox(Location=Point(835, 9), Size=Size(127, 22), Anchor=ANC_TR)
        self.tb_cat_search.TextChanged += self.on_cat_filter_ui_changed
        self.tab_cat_filter.Controls.Add(self.tb_cat_search)

        self.tab_cat_filter.Controls.Add(ui_button(u"По умолчанию (без редких)", 12, 37, 175, 27, self.on_cat_preset_standard, FONT_BOLD, Color.FromArgb(239, 246, 255), Color.FromArgb(30, 64, 175), True, ANC_TL))
        self.tab_cat_filter.Controls.Add(ui_button(u"Включить ВСЕ", 192, 37, 105, 27, self.on_cat_preset_all_active, FONT_REG, None, None, False, ANC_TL))
        self.tab_cat_filter.Controls.Add(ui_button(u"Отключить все", 302, 37, 105, 27, self.on_cat_preset_none, FONT_REG, None, None, False, ANC_TL))
        self.btn_cf_save_cfg = ui_button(u"Сохранить в профиль «{}»".format(self.cfg_mgr.get_active_profile_name()), 412, 37, 235, 27, self.on_save_cat_filter_to_active_profile, FONT_BOLD, Color.FromArgb(240, 253, 244), Color.FromArgb(22, 101, 52), True, ANC_TL)
        self.tab_cat_filter.Controls.Add(self.btn_cf_save_cfg)
        self.tab_cat_filter.Controls.Add(ui_button(u"Экспорт конфига (.json)", 652, 37, 145, 27, self.on_export_config_from_dashboard, FONT_REG, None, None, False, ANC_TL))
        self.tab_cat_filter.Controls.Add(ui_button(u"Импорт (.json)", 802, 37, 160, 27, self.on_import_config_from_dashboard, FONT_REG, None, None, False, ANC_TL))

        self.dgv_cat_filter = self.create_styled_grid(10, 70, 952, 382, ANC_ALL)
        self.dgv_cat_filter.MultiSelect = True
        self.dgv_cat_filter.Columns.Add(DataGridViewCheckBoxColumn(Name="Checked", HeaderText=u"Вкл", ReadOnly=True, FillWeight=8))
        for c_name, hdr, weight in (("CatName", u"Категория Revit (вкл. скрытые в В/Г)", 48), ("ElemCount", u"Элементов на виде", 18), ("CatStatus", u"Статус / Тип категории", 26)):
            self.dgv_cat_filter.Columns.Add(DataGridViewTextBoxColumn(Name=c_name, HeaderText=hdr, ReadOnly=True, FillWeight=weight))
        self.dgv_cat_filter.SelectionChanged += self.on_cat_filter_selection_changed
        self.dgv_cat_filter.CellMouseClick += self.on_cat_filter_cell_mouse_click
        self.dgv_cat_filter.KeyDown += self.on_cat_filter_key_down
        self.tab_cat_filter.Controls.Add(self.dgv_cat_filter)
        self.tabs.TabPages.Add(self.tab_cat_filter)

        self.Controls.Add(self.tabs)

        # --- СТРОКА СТАТУСА И НИЖНИЕ КНОПКИ ---
        self.lbl_status = ui_label(
            u"✓ Профиль «{}» активен. Двойной клик по строке во вкладке 3 открывает редактор параметров элемента!".format(self.cfg_mgr.get_active_profile_name()),
            14, 628, 976, 22, FONT_9_BOLD, Color.FromArgb(22, 101, 52), None, ANC_BLR
        )
        self.Controls.Add(self.lbl_status)

        self.Controls.Add(ui_button(u"Выделить выбранные строки", 12, 656, 195, 38, self.on_select_highlighted_in_revit, FONT_BOLD, Color.FromArgb(30, 64, 175), Color.White, True, ANC_BL))
        self.btn_sel_failed = ui_button(u"Выделить ВСЕ проблемные ({})".format(len(self.audit_data['failed_element_ids'])), 214, 656, 215, 38, self.on_select_all_failed_in_revit, FONT_BOLD, Color.FromArgb(180, 83, 9), Color.White, True, ANC_BL)
        self.Controls.Add(self.btn_sel_failed)
        self.Controls.Add(ui_button(u"Изолировать на виде (Авто-HI)", 436, 656, 205, 38, self.on_isolate_in_revit, FONT_BOLD, Color.FromArgb(109, 40, 217), Color.White, True, ANC_BL))
        self.Controls.Add(ui_button(u"Сброс изоляции (HR)", 648, 656, 135, 38, self.on_reset_isolation_in_revit, FONT_REG, Color.White, None, False, ANC_BL))
        self.Controls.Add(ui_button(u"Экспорт CSV", 790, 656, 100, 38, self.on_export_csv, FONT_REG, Color.White, None, False, ANC_BL))
        self.Controls.Add(ui_button(u"Закрыть", 897, 656, 95, 38, self.on_close_click, FONT_BOLD, Color.FromArgb(22, 101, 52), Color.White, True, ANC_BR))

        self.populate_category_filter_grid()
        self.populate_param_bars()
        self.populate_categories_grid()
        self.populate_elements_grid()

    def create_styled_grid(self, x, y, w, h, anchor=None):
        dgv = DataGridView(
            Location=Point(x, y), Size=Size(w, h), AllowUserToAddRows=False, AllowUserToDeleteRows=False,
            ReadOnly=True, SelectionMode=DataGridViewSelectionMode.FullRowSelect,
            AutoSizeColumnsMode=DataGridViewAutoSizeColumnsMode.Fill, BackgroundColor=Color.White,
            RowHeadersVisible=False, Font=FONT_REG
        )
        if anchor is not None:
            dgv.Anchor = anchor
        return dgv

    def set_status_message(self, text_msg, color_obj):
        try:
            self.lbl_status.Text = text_msg
            self.lbl_status.ForeColor = color_obj
        except:
            pass

    def on_toggle_topmost(self, sender, event):
        self.TopMost = self.chk_topmost.Checked

    def get_status_color(self, pct):
        if pct >= 90.0:
            return Color.FromArgb(22, 163, 74)
        return Color.FromArgb(217, 119, 6) if pct >= 60.0 else Color.FromArgb(220, 38, 38)

    def get_current_active_category_states_dict(self):
        return {c_name: bool(info['enabled']) for c_name, info in self.categories_catalog.items() if info['count_on_view'] > 0}

    def auto_persist_category_states(self):
        try:
            self.cfg_mgr.update_last_session(params_list=self.param_names, category_states_dict=self.get_current_active_category_states_dict())
        except:
            pass

    def get_enabled_categories_set(self):
        return set(c_name for c_name, info in self.categories_catalog.items() if info['enabled'] and info['count_on_view'] > 0)

    def recalculate_from_cached_records(self):
        self.audit_data = aggregate_audit_from_records(self.raw_records, self.param_names, self.get_enabled_categories_set())
        self.btn_sel_failed.Text = u"Выделить ВСЕ проблемные ({})".format(len(self.audit_data['failed_element_ids']))
        self.pnl_top.Invalidate()
        self.populate_param_bars()
        self.populate_categories_grid()
        self.populate_elements_grid()
        self.auto_persist_category_states()

    def on_reopen_config_dialog(self, sender, event):
        was_topmost = self.TopMost
        try:
            self.auto_persist_category_states()
            self.TopMost = False
            cfg_dlg = ParameterAuditConfigForm(self.doc, self.cfg_mgr, self.view_elem, self.param_names)
            cfg_dlg.TopMost = True
            if cfg_dlg.ShowDialog(self) == DialogResult.OK:
                self.view_elem = cfg_dlg.selected_view
                self.view_name = ElementName(self.view_elem)
                self.param_names = cfg_dlg.selected_params
                saved_cats = cfg_dlg.selected_category_states
                cfg_dlg.Dispose()

                self.Text = u"Дашборд BIM-аудита v3.1 (Немодальный режим — окно Revit активно) — Вид: {}".format(self.view_name)
                self.btn_cf_save_cfg.Text = u"Сохранить в профиль «{}»".format(self.cfg_mgr.get_active_profile_name())
                self.raw_records, self.categories_catalog = scan_raw_view_elements(self.doc, self.view_elem, self.param_names, saved_cats)
                self.populate_category_filter_grid()
                self.recalculate_from_cached_records()
                self.set_status_message(u"✓ Настройки обновлены: вид «{}», параметров — {}.".format(self.view_name, len(self.param_names)), Color.FromArgb(22, 101, 52))
            else:
                cfg_dlg.Dispose()
        except Exception as ex:
            self.set_status_message(u"Ошибка открытия настроек: " + unicode(ex), Color.FromArgb(185, 28, 28))
        finally:
            self.TopMost = self.chk_topmost.Checked if hasattr(self, "chk_topmost") else was_topmost
            try:
                self.BringToFront()
                self.Activate()
            except:
                pass

    def on_refresh_audit_from_revit(self, sender, event):
        try:
            old_map = self.get_current_active_category_states_dict()
            self.raw_records, self.categories_catalog = scan_raw_view_elements(self.doc, self.view_elem, self.param_names, old_map)
            self.populate_category_filter_grid()
            self.recalculate_from_cached_records()
            self.set_status_message(u"✓ Данные из модели обновлены! Индекс заполненности: {:.1f}%.".format(self.audit_data['overall_pct']), Color.FromArgb(22, 101, 52))
        except Exception as ex:
            self.set_status_message(u"Ошибка при обновлении: " + unicode(ex), Color.FromArgb(185, 28, 28))

    def on_close_click(self, sender, event):
        self.auto_persist_category_states()
        self.Close()

    # --- МЕТОДЫ СОХРАНЕНИЯ / ЭКСПОРТА КОНФИГА (ВКЛАДКА 4) ---

    def on_save_cat_filter_to_active_profile(self, sender, event):
        act_prof = self.cfg_mgr.get_active_profile_name()
        if self.cfg_mgr.update_last_session(params_list=self.param_names, category_states_dict=self.get_current_active_category_states_dict(), also_update_active_profile=True):
            self.set_status_message(u"✓ Настройки фильтра категорий и параметров сохранены в профиль «{}»!".format(act_prof), Color.FromArgb(22, 101, 52))

    def on_export_config_from_dashboard(self, sender, event):
        act_prof = self.cfg_mgr.get_active_profile_name()
        sfd = SaveFileDialog(
            Title=u"Экспортировать конфигурацию в файл JSON", Filter="JSON Config (*.json)|*.json",
            FileName=u"Конфиг_аудита_{}.json".format(act_prof.replace(u" ", u"_").replace(u":", u"_"))
        )
        if sfd.ShowDialog() == DialogResult.OK:
            if self.cfg_mgr.export_single_config_to_file(sfd.FileName, act_prof, self.param_names, self.get_current_active_category_states_dict()):
                self.set_status_message(u"✓ Конфигурация сохранена в файл: " + sfd.FileName, Color.FromArgb(22, 101, 52))

    def on_import_config_from_dashboard(self, sender, event):
        ofd = OpenFileDialog(Title=u"Импортировать конфигурацию из файла JSON", Filter="JSON Config (*.json)|*.json")
        if ofd.ShowDialog() == DialogResult.OK:
            imported = self.cfg_mgr.import_config_from_file(ofd.FileName)
            if imported:
                self.param_names = imported.get(u"params", self.param_names)
                self.btn_cf_save_cfg.Text = u"Сохранить в профиль «{}»".format(self.cfg_mgr.get_active_profile_name())
                self.raw_records, self.categories_catalog = scan_raw_view_elements(self.doc, self.view_elem, self.param_names, imported.get(u"category_states", {}))
                self.populate_category_filter_grid()
                self.recalculate_from_cached_records()
                self.set_status_message(u"✓ Импортирован конфиг «{}»!".format(imported.get(u"profile_name", u"JSON")), Color.FromArgb(22, 101, 52))

    # --- МЕТОДЫ ФИЛЬТРА КАТЕГОРИЙ (ВКЛАДКА 4) ---

    def apply_row_visual_style(self, row_obj, info):
        if info['count_on_view'] == 0:
            row_obj.DefaultCellStyle.BackColor = Color.FromArgb(248, 250, 252)
            row_obj.DefaultCellStyle.ForeColor = Color.FromArgb(160, 174, 192)
        elif info['enabled']:
            row_obj.DefaultCellStyle.BackColor = Color.FromArgb(240, 253, 244)
            row_obj.DefaultCellStyle.ForeColor = Color.FromArgb(15, 23, 42)
        elif info['is_rare']:
            row_obj.DefaultCellStyle.BackColor = Color.FromArgb(255, 251, 235)
            row_obj.DefaultCellStyle.ForeColor = Color.FromArgb(146, 64, 14)
        else:
            row_obj.DefaultCellStyle.BackColor = Color.FromArgb(241, 245, 249)
            row_obj.DefaultCellStyle.ForeColor = Color.FromArgb(100, 116, 139)

    def populate_category_filter_grid(self):
        self._is_populating_cat_filter = True
        self.dgv_cat_filter.Rows.Clear()
        self.last_checkbox_clicked_row = -1
        self._prev_selected_cat_rows, self._curr_selected_cat_rows = [], []

        show_zero = self.chk_show_zero_cats.Checked
        q = self.tb_cat_search.Text.strip().lower()
        all_items = sorted(self.categories_catalog.values(), key=lambda x: (0 if x['count_on_view'] > 0 else 1, x['name'].lower()))

        for info in all_items:
            c_name, cnt = info['name'], info['count_on_view']
            if (cnt == 0 and not show_zero) or (q and q not in c_name.lower()):
                continue
            status_str = u"Нет на виде (Неактивна)" if cnt == 0 else (u"Редкая / Служебная (откл. по умолч.)" if info['is_rare'] else u"Основная категория модели")
            r_idx = self.dgv_cat_filter.Rows.Add(bool(info['enabled'] and cnt > 0), c_name, unicode(cnt), status_str)
            self.apply_row_visual_style(self.dgv_cat_filter.Rows[r_idx], info)

        self._is_populating_cat_filter = False

    def on_cat_filter_ui_changed(self, sender, event):
        self.populate_category_filter_grid()

    def on_cat_filter_selection_changed(self, sender, event):
        if not self._is_populating_cat_filter:
            self._prev_selected_cat_rows = list(self._curr_selected_cat_rows)
            self._curr_selected_cat_rows = sorted([r.Index for r in self.dgv_cat_filter.SelectedRows])

    def set_rows_checked_batch(self, row_indices, target_state):
        changed_count = 0
        for r_idx in row_indices:
            if 0 <= r_idx < self.dgv_cat_filter.Rows.Count:
                row_obj = self.dgv_cat_filter.Rows[r_idx]
                info = self.categories_catalog.get(row_obj.Cells[1].Value)
                if info and info['count_on_view'] > 0:
                    info['enabled'] = bool(target_state)
                    row_obj.Cells[0].Value = bool(target_state)
                    self.apply_row_visual_style(row_obj, info)
                    changed_count += 1

        self.dgv_cat_filter.Invalidate()
        if changed_count > 0:
            if self.chk_auto_recalc_cats.Checked:
                self.recalculate_from_cached_records()
                action_str = u"Включено" if target_state else u"Отключено"
                self.set_status_message(u"✓ {} категорий: {} шт. Элементов в расчете: {}.".format(action_str, changed_count, self.audit_data['total_elements']), Color.FromArgb(30, 64, 175))
            else:
                self.auto_persist_category_states()
                self.set_status_message(u"Изменено категорий: {} шт. Нажмите «Обновить данные» для пересчета.".format(changed_count), Color.FromArgb(180, 83, 9))

    def is_click_strictly_on_checkbox_glyph(self, row_idx, mouse_x, mouse_y):
        try:
            cell_rect = self.dgv_cat_filter.GetCellDisplayRectangle(0, row_idx, False)
            return (abs(mouse_x - cell_rect.Width / 2.0) <= 9.0) and (abs(mouse_y - cell_rect.Height / 2.0) <= 9.0)
        except:
            return False

    def on_cat_filter_cell_mouse_click(self, sender, event):
        if self._is_populating_cat_filter or event.Button != MouseButtons.Left or event.RowIndex < 0 or event.ColumnIndex != 0:
            return
        if not self.is_click_strictly_on_checkbox_glyph(event.RowIndex, event.X, event.Y):
            return

        clicked_row = event.RowIndex
        row_obj = self.dgv_cat_filter.Rows[clicked_row]
        c_name = row_obj.Cells[1].Value
        info = self.categories_catalog.get(c_name)
        if not info or info['count_on_view'] == 0:
            self.set_status_message(u"Категория «{}» неактивна (0 элементов на виде).".format(c_name), Color.FromArgb(100, 116, 139))
            return

        new_state = not bool(row_obj.Cells[0].Value)
        is_shift = ((Control.ModifierKeys & Keys.Shift) == Keys.Shift)

        if len(self._prev_selected_cat_rows) > 1 and (clicked_row in self._prev_selected_cat_rows):
            target_rows = list(self._prev_selected_cat_rows)
        elif is_shift and self.last_checkbox_clicked_row != -1:
            target_rows = list(range(min(self.last_checkbox_clicked_row, clicked_row), max(self.last_checkbox_clicked_row, clicked_row) + 1))
        else:
            target_rows = [clicked_row]

        self.set_rows_checked_batch(target_rows, new_state)
        if len(target_rows) > 1:
            self._is_populating_cat_filter = True
            self.dgv_cat_filter.ClearSelection()
            for r_i in target_rows:
                if 0 <= r_i < self.dgv_cat_filter.Rows.Count:
                    self.dgv_cat_filter.Rows[r_i].Selected = True
            self._is_populating_cat_filter = False
            self._curr_selected_cat_rows = list(target_rows)
        self.last_checkbox_clicked_row = clicked_row

    def on_cat_filter_key_down(self, sender, event):
        if event.KeyCode == Keys.Space:
            sel_indices = sorted([r.Index for r in self.dgv_cat_filter.SelectedRows])
            if sel_indices:
                any_unchecked = any(
                    self.categories_catalog.get(self.dgv_cat_filter.Rows[r_idx].Cells[1].Value, {}).get('count_on_view', 0) > 0 and
                    not self.categories_catalog.get(self.dgv_cat_filter.Rows[r_idx].Cells[1].Value, {}).get('enabled', True)
                    for r_idx in sel_indices
                )
                self.set_rows_checked_batch(sel_indices, any_unchecked)
                event.Handled = True

    def on_cat_preset_standard(self, sender, event):
        for info in self.categories_catalog.values():
            info['enabled'] = (info['count_on_view'] > 0 and not info['is_rare'])
        self.populate_category_filter_grid()
        self.recalculate_from_cached_records()
        self.set_status_message(u"✓ Применен фильтр по умолчанию: редкие и служебные категории отключены.", Color.FromArgb(22, 101, 52))

    def on_cat_preset_all_active(self, sender, event):
        for info in self.categories_catalog.values():
            info['enabled'] = (info['count_on_view'] > 0)
        self.populate_category_filter_grid()
        self.recalculate_from_cached_records()
        self.set_status_message(u"✓ Включены все категории, присутствующие на виде.", Color.FromArgb(30, 64, 175))

    def on_cat_preset_none(self, sender, event):
        for info in self.categories_catalog.values():
            info['enabled'] = False
        self.populate_category_filter_grid()
        self.recalculate_from_cached_records()
        self.set_status_message(u"Все категории отключены. Отметьте нужные категории галочками.", Color.FromArgb(180, 83, 9))

    # --- ОТРИСОВКА KPI И ВКЛАДОК 1, 2, 3 ---

    def on_paint_top_kpi(self, sender, event):
        g = event.Graphics
        d = self.audit_data
        overall_pct = d['overall_pct']
        f_kpi_num = Font("Segoe UI", 16, FontStyle.Bold)

        g.DrawString(
            u"Вид: {}  |  Категорий: {}  |  Параметров: {}".format(self.view_name, len(d['category_stats']), len(self.param_names)),
            FONT_10_BOLD, SolidBrush(Color.FromArgb(15, 23, 42)), 15, 10
        )

        cards = (
            (u"Всего элементов", unicode(d['total_elements']), Color.FromArgb(30, 58, 138), 15),
            (u"Заполнены на 100%", unicode(d['fully_filled_elements']), Color.FromArgb(22, 101, 52), 185),
            (u"Требуют внимания", unicode(d['failed_elements_count']), Color.FromArgb(185, 28, 28), 355),
            (u"Общий индекс BIM-качества", u"{:.1f}%".format(overall_pct), self.get_status_color(overall_pct), 525)
        )
        for title, val, col, x_pos in cards:
            rect = Rectangle(x_pos, 40, 158, 62)
            g.FillRectangle(SolidBrush(Color.FromArgb(248, 250, 252)), rect)
            g.DrawRectangle(Pen(Color.FromArgb(226, 232, 240), 1), rect)
            g.DrawString(title, FONT_REG, SolidBrush(Color.FromArgb(100, 116, 139)), x_pos + 10, 46)
            g.DrawString(val, f_kpi_num, SolidBrush(col), x_pos + 10, 64)

        bar_x, bar_y, bar_w, bar_h = 700, 54, 260, 24
        g.DrawString(u"Шкала заполненности модели:", FONT_REG, SolidBrush(Color.FromArgb(71, 85, 105)), bar_x, 36)
        g.FillRectangle(SolidBrush(Color.FromArgb(226, 232, 240)), Rectangle(bar_x, bar_y, bar_w, bar_h))
        fill_w = int(bar_w * (overall_pct / 100.0))
        if fill_w > 0:
            g.FillRectangle(SolidBrush(self.get_status_color(overall_pct)), Rectangle(bar_x, bar_y, fill_w, bar_h))
        g.DrawRectangle(Pen(Color.FromArgb(148, 163, 184), 1), Rectangle(bar_x, bar_y, bar_w, bar_h))
        g.DrawString(u"Заполнено ячеек: {} из {}".format(d['total_filled_cells'], d['total_cells']), FONT_REG, SolidBrush(Color.FromArgb(71, 85, 105)), bar_x, 83)

    def populate_param_bars(self):
        self.pnl_bars.SuspendLayout()
        self.pnl_bars.AutoScrollPosition = Point(0, 0)
        self.pnl_bars.Controls.Clear()

        y = 8
        card_width = max(880, self.pnl_bars.ClientSize.Width - 28)
        bar_max_w = card_width - 28

        for idx, p_name in enumerate(self.param_names):
            st = self.audit_data['param_stats'][p_name]
            pct, filled, total = st['pct'], st['filled'], st['total']
            missing_cnt = total - filled
            scopes = u"/".join(sorted(st['scopes'])) if st['scopes'] else u"Не найден"
            status_col = self.get_status_color(pct)

            sorted_vals = sorted(st['value_counts'].items(), key=lambda kv: kv[1], reverse=True)[:5]
            top_vals_str = u", ".join([u"{} ({} шт.)".format(k, v) for k, v in sorted_vals]) or u"Нет заполненных значений"

            card = Panel(Location=Point(8, y), Size=Size(card_width, 92), BackColor=Color.FromArgb(248, 250, 252), BorderStyle=BorderStyle.FixedSingle, Anchor=ANC_TLR)
            card.Controls.Add(ui_label(u"{}. {}   [{}]".format(idx + 1, p_name, scopes), 12, 8, 360, 22, FONT_10_BOLD, Color.FromArgb(15, 23, 42)))
            card.Controls.Add(ui_label(u"Заполнено: {} из {} ({:.1f}%)  |  Уникальных значений: {}".format(filled, total, pct, len(st['value_counts'])), 375, 9, 375, 20, FONT_9_BOLD, status_col))

            if missing_cnt > 0:
                btn_sel = ui_button(u"Выделить пустые ({})".format(missing_cnt), card_width - 166, 5, 152, 26, self.on_select_missing_for_param, FONT_BOLD, Color.FromArgb(254, 242, 242), Color.FromArgb(185, 28, 28), True, ANC_TR)
                btn_sel.Tag = p_name
                card.Controls.Add(btn_sel)
            else:
                card.Controls.Add(ui_label(u"✓ Заполнен на 100%", card_width - 162, 9, 145, 20, FONT_BOLD, Color.FromArgb(22, 163, 74), ContentAlignment.MiddleRight, ANC_TR))

            pnl_bar_bg = Panel(Location=Point(12, 36), Size=Size(bar_max_w, 20), BackColor=Color.FromArgb(226, 232, 240), BorderStyle=BorderStyle.FixedSingle)
            fill_w = int(bar_max_w * (pct / 100.0))
            if fill_w > 0:
                pnl_bar_bg.Controls.Add(Panel(Location=Point(0, 0), Size=Size(fill_w, 18), BackColor=status_col))
            card.Controls.Add(pnl_bar_bg)
            card.Controls.Add(ui_label(u"Примеры значений: " + top_vals_str, 12, 62, bar_max_w, 20, FONT_REG, Color.FromArgb(71, 85, 105), None, ANC_TLR, True))

            self.pnl_bars.Controls.Add(card)
            y += 100

        self.pnl_bars.AutoScrollMinSize = Size(850, y + 10)
        self.pnl_bars.ResumeLayout()

    def on_select_missing_for_param(self, sender, event):
        p_name = sender.Tag
        missing_ids = self.audit_data['param_stats'][p_name]['missing_ids']
        if missing_ids:
            ids_list = List[ElementId]()
            for eid in missing_ids:
                ids_list.Add(eid)
            self.select_ids_non_blocking(ids_list, custom_param_name=p_name)

    def get_param_column_header(self, p_name):
        scopes = self.audit_data['param_stats'].get(p_name, {}).get('scopes', set())
        short_tags = ([u"Э"] if u"Экземпляр" in scopes else []) + ([u"Т"] if u"Тип" in scopes else [])
        return u"{} [{}]".format(p_name, u"/".join(short_tags)) if short_tags else p_name

    def populate_categories_grid(self):
        self.dgv_cats.Columns.Clear()
        self.dgv_cats.Rows.Clear()
        for c_id, hdr in (("CatName", u"Категория"), ("TotalEl", u"Элементов (шт.)"), ("ReadyPct", u"Общий %")):
            self.dgv_cats.Columns.Add(c_id, hdr)
        for p_name in self.param_names:
            self.dgv_cats.Columns.Add("P_" + p_name, self.get_param_column_header(p_name))

        for cat_name in sorted(self.audit_data['category_stats'].keys()):
            c_info = self.audit_data['category_stats'][cat_name]
            row_vals = [cat_name, unicode(c_info['count']), u"{:.1f}%".format(c_info['pct'])]
            for p_name in self.param_names:
                p_filled = c_info['param_filled'].get(p_name, 0)
                p_pct = (100.0 * p_filled / c_info['count']) if c_info['count'] > 0 else 0.0
                row_vals.append(u"{}/{} ({:.0f}%)".format(p_filled, c_info['count'], p_pct))

            row_obj = self.dgv_cats.Rows[self.dgv_cats.Rows.Add(*row_vals)]
            row_obj.DefaultCellStyle.BackColor = (
                Color.FromArgb(254, 242, 242) if c_info['pct'] < 60.0 else
                (Color.FromArgb(254, 252, 232) if c_info['pct'] < 100.0 else Color.FromArgb(240, 253, 244))
            )

    def populate_elements_grid(self):
        self.dgv_elems.Columns.Clear()
        self.dgv_elems.Rows.Clear()
        for c_id, hdr in (("ElId", u"ID элемента"), ("Cat", u"Категория"), ("FamType", u"Семейство и Тип"), ("Status", u"Статус")):
            self.dgv_elems.Columns.Add(c_id, hdr)
        for p_name in self.param_names:
            self.dgv_elems.Columns.Add("Val_" + p_name, self.get_param_column_header(p_name))

        only_failed = self.chk_only_failed.Checked
        q = self.tb_el_filter.Text.strip().lower()

        for item in self.audit_data['element_rows']:
            if only_failed and item['is_ok']:
                continue
            if q and q not in (u"{} {} {} ".format(item['id_int'], item['category'], item['fam_type']) + u" ".join(item['values_list'])).lower():
                continue

            status_txt = u"ОК (100%)" if item['is_ok'] else u"Не заполнено ({}/{})".format(item['filled_cnt'], len(self.param_names))
            row_vals = [unicode(item['id_int']), item['category'], item['fam_type'], status_txt] + item['values_list']
            r_obj = self.dgv_elems.Rows[self.dgv_elems.Rows.Add(*row_vals)]
            if not item['is_ok']:
                r_obj.DefaultCellStyle.BackColor = Color.FromArgb(254, 242, 242)

    def on_element_row_double_click(self, sender, event):
        if event.RowIndex < 0:
            return
        try:
            el_id_int = int(self.dgv_elems.Rows[event.RowIndex].Cells[0].Value)
            target_el = self.doc.GetElement(ElementId(el_id_int))
            if target_el is None:
                return

            try:
                ids_sel = List[ElementId]()
                ids_sel.Add(target_el.Id)
                self.uidoc.Selection.SetElementIds(ids_sel)
            except:
                pass

            was_top = self.TopMost
            self.TopMost = False
            try:
                dlg = ElementParameterEditorForm(self.doc, target_el, self.param_names, self.audit_data['param_stats'])
                dlg_res = dlg.ShowDialog(self)
                changes = dict(dlg.updated_values)
                dlg.Dispose()
            finally:
                self.TopMost = self.chk_topmost.Checked if hasattr(self, "chk_topmost") else was_top
                try:
                    self.BringToFront()
                    self.Activate()
                except:
                    pass

            if dlg_res == DialogResult.OK and changes:
                wrote_directly = False
                try:
                    t = Transaction(self.doc, u"BIM Аудит: Запись значений параметров")
                    t.Start()
                    changed_cnt, errors = 0, []
                    for p_name, new_val in changes.items():
                        ok, msg, _ = write_single_parameter_value(self.doc, target_el, p_name, new_val)
                        if ok:
                            changed_cnt += 1
                        else:
                            errors.append(u"{}: {}".format(p_name, msg))
                    t.Commit()
                    wrote_directly = True
                    self.on_element_params_written(el_id_int, changed_cnt, errors)
                except:
                    wrote_directly = False

                if not wrote_directly and self.ext_event:
                    self.ext_handler.action_type = "SET_ELEMENT_PARAMS"
                    self.ext_handler.target_element_id_int = el_id_int
                    self.ext_handler.params_to_set = changes
                    self.ext_event.Raise()
                    self.set_status_message(u"Запрос на запись параметров отправлен (переведите курсор в окно Revit)...", Color.FromArgb(30, 64, 175))
        except Exception as ex:
            self.set_status_message(u"Ошибка открытия карточки элемента: " + unicode(ex), Color.FromArgb(185, 28, 28))

    def on_element_params_written(self, el_id_int, changed_cnt, errors):
        try:
            target_el = self.doc.GetElement(ElementId(int(el_id_int)))
            target_type_id = target_el.GetTypeId() if target_el else None
            for rec in self.raw_records:
                el_obj = rec['element']
                if rec['id_int'] == int(el_id_int) or (target_type_id and el_obj.GetTypeId() == target_type_id):
                    for p_name in self.param_names:
                        rec['param_results'][p_name] = resolve_parameter_value(self.doc, el_obj, p_name)

            self.recalculate_from_cached_records()
            if errors:
                self.set_status_message(u"Записано: {}. Ошибки: {}".format(changed_cnt, u"; ".join(errors)), Color.FromArgb(180, 83, 9))
            else:
                self.set_status_message(u"✓ Обновлено параметров у ID {}: {} шт.! Дашборд пересчитан.".format(el_id_int, changed_cnt), Color.FromArgb(22, 101, 52))
        except Exception as ex:
            self.set_status_message(u"Ошибка обновления: " + unicode(ex), Color.FromArgb(185, 28, 28))

    def on_filter_elements_changed(self, sender, event):
        self.populate_elements_grid()

    def get_target_ids_from_grid_or_failed(self, use_selected_rows=True):
        ids_list = List[ElementId]()
        if use_selected_rows:
            for i in range(self.dgv_elems.SelectedRows.Count):
                try:
                    ids_list.Add(ElementId(int(self.dgv_elems.SelectedRows[i].Cells[0].Value)))
                except:
                    pass
        else:
            for eid in self.audit_data['failed_element_ids']:
                ids_list.Add(eid)
        return ids_list

    def select_ids_non_blocking(self, ids_list, custom_param_name=None):
        if ids_list.Count == 0:
            return
        try:
            self.uidoc.Selection.SetElementIds(ids_list)
            if self.chk_auto_zoom.Checked and ids_list.Count <= 50:
                try:
                    self.uidoc.ShowElements(ids_list)
                except:
                    pass
            msg = (
                u"✓ Выделено {} элементов с пустым параметром «{}».".format(ids_list.Count, custom_param_name)
                if custom_param_name else
                u"✓ Выделено в Revit: {} шт. Можете нажать HI или редактировать свойства!".format(ids_list.Count)
            )
            self.set_status_message(msg, Color.FromArgb(22, 101, 52))
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
            self.set_status_message(u"Выберите строки в таблице на вкладке «3. Поэлементный список».", Color.FromArgb(180, 83, 9))
        else:
            self.select_ids_non_blocking(ids_list)

    def on_select_all_failed_in_revit(self, sender, event):
        ids_list = self.get_target_ids_from_grid_or_failed(use_selected_rows=False)
        if ids_list.Count == 0:
            self.set_status_message(u"✓ Все элементы заполнены на 100%!", Color.FromArgb(22, 101, 52))
        else:
            self.select_ids_non_blocking(ids_list)

    def on_isolate_in_revit(self, sender, event):
        ids_list = self.get_target_ids_from_grid_or_failed(True)
        if ids_list.Count == 0:
            ids_list = self.get_target_ids_from_grid_or_failed(False)
        if ids_list.Count == 0:
            return
        if self.ext_event:
            self.ext_handler.action_type = "ISOLATE"
            self.ext_handler.element_ids = ids_list
            self.ext_event.Raise()
            self.set_status_message(u"Запрос на изоляцию {} элементов отправлен (переведите курсор в окно Revit)...".format(ids_list.Count), Color.FromArgb(109, 40, 217))
        else:
            self.select_ids_non_blocking(ids_list)

    def on_reset_isolation_in_revit(self, sender, event):
        if self.ext_event:
            self.ext_handler.action_type = "RESET_ISOLATION"
            self.ext_event.Raise()
            self.set_status_message(u"Запрос на сброс изоляции отправлен (переведите курсор в окно Revit)...", Color.FromArgb(30, 64, 175))

    def on_export_csv(self, sender, event):
        sfd = SaveFileDialog(
            Title=u"Сохранить отчет проверки параметров (CSV для Excel)", Filter="CSV files (*.csv)|*.csv",
            FileName=u"Аудит_параметров_{}.csv".format(self.view_name.replace(u":", u"_").replace(u"/", u"_"))
        )
        if sfd.ShowDialog() == DialogResult.OK:
            try:
                with codecs.open(sfd.FileName, mode='w', encoding='utf-8-sig') as f:
                    headers = [u"ID элемента", u"Категория", u"Семейство и Тип", u"Статус", u"Заполнено параметров"] + [self.get_param_column_header(p) for p in self.param_names]
                    f.write(u";".join([u'"{}"'.format(h.replace(u'"', u'""')) for h in headers]) + u"\r\n")
                    for item in self.audit_data['element_rows']:
                        st = u"ОК" if item['is_ok'] else u"ОШИБКА"
                        ratio = u"{}/{}".format(item['filled_cnt'], len(self.param_names))
                        row = [unicode(item['id_int']), item['category'], item['fam_type'], st, ratio] + item['values_list']
                        f.write(u";".join([u'"{}"'.format(unicode(c).replace(u'"', u'""')) for c in row]) + u"\r\n")
                self.set_status_message(u"✓ Отчет CSV сохранен: " + sfd.FileName, Color.FromArgb(22, 101, 52))
            except Exception as ex:
                self.set_status_message(u"Ошибка сохранения CSV: " + unicode(ex), Color.FromArgb(185, 28, 28))


# ==============================================================================
# ТОЧКА ВХОДА СКРИПТА И ФОРМИРОВАНИЕ ВЫХОДОВ OUT ДЛЯ DYNAMO
# ==============================================================================

try:
    cfg_manager = AuditConfigManager()
    config_form = ParameterAuditConfigForm(doc, cfg_manager)

    if config_form.ShowDialog() != DialogResult.OK:
        config_form.Dispose()
        OUT = [u"Операция отменена пользователем."]
    else:
        target_view = config_form.selected_view
        target_params = config_form.selected_params
        saved_cat_states = config_form.selected_category_states
        view_title = ElementName(target_view)
        config_form.Dispose()

        raw_records, categories_catalog = scan_raw_view_elements(doc, target_view, target_params, saved_cat_states)

        if not raw_records:
            TaskDialog.Show(u"Нет элементов", u"На виде «{}» не найдено элементов для анализа.".format(view_title))
            OUT = [u"На виде '{}' не найдено элементов.".format(view_title)]
        else:
            enabled_cats = set(c_name for c_name, info in categories_catalog.items() if info['enabled'] and info['count_on_view'] > 0)
            if not enabled_cats:
                for info in categories_catalog.values():
                    if info['count_on_view'] > 0:
                        info['enabled'] = True
                        enabled_cats.add(info['name'])

            audit_result = aggregate_audit_from_records(raw_records, target_params, enabled_cats)

            dash_form = AuditDashboardForm(doc, uidoc, cfg_manager, target_view, target_params, raw_records, categories_catalog, audit_result)
            dash_form.Show()

            summary_report = [
                u"=== СВОДНЫЙ ОТЧЕТ АУДИТА ПАРАМЕТРОВ ===",
                u"Файл конфигурации: {}".format(cfg_manager.config_path),
                u"Активный профиль: {}".format(cfg_manager.get_active_profile_name()),
                u"Вид / Спецификация: {}".format(view_title),
                u"Проверено элементов: {}".format(audit_result['total_elements']),
                u"Полностью заполнены: {} ({:.1f}%)".format(
                    audit_result['fully_filled_elements'],
                    (100.0 * audit_result['fully_filled_elements'] / audit_result['total_elements']) if audit_result['total_elements'] > 0 else 0.0
                ),
                u"Требуют доработки: {}".format(audit_result['failed_elements_count']),
                u"Общий индекс заполненности: {:.1f}% ({} из {})".format(
                    audit_result['overall_pct'], audit_result['total_filled_cells'], audit_result['total_cells']
                ),
                u"",
                u"--- ДЕТАЛИЗАЦИЯ ПО ПАРАМЕТРАМ И КОЛИЧЕСТВУ ЗНАЧЕНИЙ ---"
            ]

            for p_name in target_params:
                st = audit_result['param_stats'][p_name]
                scopes_str = u"/".join(sorted(st['scopes'])) if st['scopes'] else u"Параметр отсутствует"
                summary_report.append(u"• {} [{}] -> Заполнено: {}/{} ({:.1f}%) | Уникальных значений: {}".format(
                    p_name, scopes_str, st['filled'], st['total'], st['pct'], len(st['value_counts'])
                ))
                for val_k, val_cnt in sorted(st['value_counts'].items(), key=lambda kv: kv[1], reverse=True):
                    summary_report.append(u"    - Значение «{}»: {} шт.".format(val_k, val_cnt))

            category_report = [
                u"[{}] Элементов: {} | Заполненность: {:.1f}% | ({})".format(
                    cat_name, c_st['count'], c_st['pct'],
                    u", ".join([u"{}: {}/{}".format(p, c_st['param_filled'][p], c_st['count']) for p in target_params])
                )
                for cat_name, c_st in sorted(audit_result['category_stats'].items())
            ]

            element_report = [
                u"{} ID {} | {} | {} -> {}".format(
                    u"[OK]" if r['is_ok'] else u"[НЕ ЗАПОЛНЕН]",
                    r['id_int'], r['category'], r['fam_type'],
                    u" | ".join([u"{}={}".format(target_params[i], r['values_list'][i]) for i in range(len(target_params))])
                )
                for r in audit_result['element_rows']
            ]

            OUT = [summary_report, category_report, element_report, audit_result['failed_elements']]

except Exception as e:
    OUT = [u"Ошибка выполнения скрипта:\n" + traceback.format_exc()]
