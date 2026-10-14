# -*- coding: utf-8 -*-
# _______________________________________________________________________
# Описание: Интерактивный аудит и НЕМОДАЛЬНЫЙ дашборд заполненности параметров
#           элементов (Экземпляр и Тип) на 3D-виде, плане или в спецификации
# Особенности версии v2.9 (Редактирование параметров по двойному клику в ведомости + Каталог + Профили JSON):
#   - В стартовом окне справа добавлен полный каталог ВСЕХ доступных параметров
#     выбранного вида и проекта (Экземпляр и Тип) с живым поиском и фильтрами
#   - Клик мышью по параметру в правом списке сразу добавляет его в блок ввода
#     слева (повторный клик убирает параметр); уже добавленные подсвечены зеленым
#   - Поддержка пакетного добавления параметров через Shift/Ctrl
#   - Автосохранение профилей (параметры + фильтр категорий) и экспорт/импорт JSON
#   - Дашборд открывается в немодальном режиме (form.Show()) и НЕ блокирует Revit
# Автор: Alexander Iskra (alxiskra)
# Протестировано на Revit: v2022 (IronPython 2.7)
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
    Transaction, TemporaryViewMode, InstanceBinding, TypeBinding
)
from Autodesk.Revit.UI import (
    TaskDialog, IExternalEventHandler, ExternalEvent
)

from RevitServices.Persistence import DocumentManager
from System.Collections.Generic import List

from System.Windows.Forms import (
    Form, Button, DialogResult, FormBorderStyle, FormStartPosition,
    CheckBox, Label, ComboBox, ComboBoxStyle, RadioButton, TextBox,
    Control, Keys, MouseButtons, Panel, TrackBar, TabControl, TabPage, DataGridView,
    DataGridViewSelectionMode, DataGridViewAutoSizeColumnsMode,
    DataGridViewCheckBoxColumn, DataGridViewTextBoxColumn,
    ScrollBars, SaveFileDialog, OpenFileDialog, GroupBox,
    ListBox, BorderStyle, FlatStyle
)
from System.Drawing import (
    Size, Point, Font, FontStyle, Color, SolidBrush, Pen, Rectangle,
    ContentAlignment
)

doc = DocumentManager.Instance.CurrentDBDocument
uiapp = DocumentManager.Instance.CurrentUIApplication
uidoc = uiapp.ActiveUIDocument


# ==============================================================================
# 0. МЕНЕДЖЕР КОНФИГУРАЦИЙ (АВТОСОХРАНЕНИЕ + ПРОФИЛИ + ЭКСПОРТ/ИМПОРТ JSON)
# ==============================================================================

DEFAULT_PARAMS_LIST = [
    u"MR_Корпус",
    u"MR_Комплект",
    u"MR_Этаж",
    u"MR_Код по классификатору"
]

EXTRA_PRESET_PARAMS = [
    u"MR_Корпус",
    u"MR_Комплект",
    u"MR_Этаж",
    u"MR_Код по классификатору",
    u"Номер помещения",
    u"Марка"
]


def get_default_config_file_path():
    """Возвращает путь к файлу конфигураций в папке %APPDATA%/RevitParameterAuditor."""
    appdata = os.environ.get('APPDATA')
    if not appdata:
        appdata = os.path.expanduser('~')
    cfg_dir = os.path.join(appdata, u"RevitParameterAuditor")
    if not os.path.exists(cfg_dir):
        try:
            os.makedirs(cfg_dir)
        except:
            pass
    return os.path.join(cfg_dir, u"audit_configs_v24.json")


def get_builtin_default_store():
    """Базовая структура хранилища конфигураций по умолчанию."""
    return {
        u"active_profile": u"Стандарт MR (Базовый)",
        u"last_session": {
            u"params": list(DEFAULT_PARAMS_LIST),
            u"input_mode": u"semicolon",
            u"category_states": {}
        },
        u"profiles": {
            u"Стандарт MR (Базовый)": {
                u"params": list(DEFAULT_PARAMS_LIST),
                u"input_mode": u"semicolon",
                u"category_states": {}
            },
            u"Расширенный (+ Помещения и Марка)": {
                u"params": list(EXTRA_PRESET_PARAMS),
                u"input_mode": u"semicolon",
                u"category_states": {}
            }
        }
    }


def save_json_file(filepath, data_dict):
    """Надежное сохранение словаря в читаемый UTF-8 JSON с поддержкой кириллицы в IronPython 2."""
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
    """Безопасное чтение JSON-файла в IronPython 2."""
    if not os.path.exists(filepath):
        return None
    try:
        with codecs.open(filepath, mode='r', encoding='utf-8-sig') as f:
            content = f.read()
        return json.loads(content)
    except:
        try:
            with codecs.open(filepath, mode='r', encoding='utf-8') as f:
                content = f.read()
            return json.loads(content)
        except:
            return None


class AuditConfigManager(object):
    """Управляет профилями настроек (параметры + состояния фильтра категорий)."""
    def __init__(self):
        self.config_path = get_default_config_file_path()
        self.store = self.load_store()

    def load_store(self):
        data = load_json_file(self.config_path)
        default_store = get_builtin_default_store()
        if not isinstance(data, dict):
            save_json_file(self.config_path, default_store)
            return default_store

        if u"profiles" not in data or not isinstance(data[u"profiles"], dict):
            data[u"profiles"] = default_store[u"profiles"]
        if u"last_session" not in data or not isinstance(data[u"last_session"], dict):
            data[u"last_session"] = default_store[u"last_session"]
        if u"active_profile" not in data:
            data[u"active_profile"] = u"Стандарт MR (Базовый)"
        return data

    def save_store(self):
        return save_json_file(self.config_path, self.store)

    def get_profile_names(self):
        return sorted(self.store.get(u"profiles", {}).keys())

    def get_active_profile_name(self):
        return self.store.get(u"active_profile", u"Стандарт MR (Базовый)")

    def get_last_session(self):
        return self.store.get(u"last_session", {
            u"params": list(DEFAULT_PARAMS_LIST),
            u"input_mode": u"semicolon",
            u"category_states": {}
        })

    def get_profile_data(self, profile_name):
        profiles = self.store.get(u"profiles", {})
        if profile_name in profiles:
            return profiles[profile_name]
        return self.get_last_session()

    def save_profile(self, profile_name, params_list, category_states_dict, input_mode=u"semicolon"):
        profile_name = profile_name.strip()
        if not profile_name:
            return False
        if u"profiles" not in self.store:
            self.store[u"profiles"] = {}

        if category_states_dict is None:
            existing = self.store[u"profiles"].get(profile_name, {})
            category_states_dict = existing.get(
                u"category_states",
                dict(self.get_last_session().get(u"category_states", {}))
            )

        prof_obj = {
            u"params": list(params_list),
            u"input_mode": unicode(input_mode),
            u"category_states": dict(category_states_dict)
        }
        self.store[u"profiles"][profile_name] = prof_obj
        self.store[u"active_profile"] = profile_name
        self.store[u"last_session"] = dict(prof_obj)
        return self.save_store()

    def delete_profile(self, profile_name):
        profiles = self.store.get(u"profiles", {})
        if profile_name in profiles and len(profiles) > 1:
            del profiles[profile_name]
            rem_keys = sorted(profiles.keys())
            self.store[u"active_profile"] = rem_keys[0]
            self.save_store()
            return True
        return False

    def update_last_session(self, params_list=None, category_states_dict=None, input_mode=None, also_update_active_profile=False):
        ls = self.get_last_session()
        if params_list is not None:
            ls[u"params"] = list(params_list)
        if category_states_dict is not None:
            merged_cats = dict(ls.get(u"category_states", {}))
            for k, v in category_states_dict.items():
                merged_cats[k] = bool(v)
            ls[u"category_states"] = merged_cats
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
                    merged_p_cats = dict(p_obj.get(u"category_states", {}))
                    for k, v in category_states_dict.items():
                        merged_p_cats[k] = bool(v)
                    p_obj[u"category_states"] = merged_p_cats
                if input_mode is not None:
                    p_obj[u"input_mode"] = unicode(input_mode)

        return self.save_store()

    def export_single_config_to_file(self, filepath, profile_name, params_list, category_states_dict):
        export_obj = {
            u"format": u"RevitParameterAuditorConfig_v2.9",
            u"profile_name": unicode(profile_name),
            u"params": list(params_list),
            u"category_states": dict(category_states_dict) if category_states_dict else {}
        }
        return save_json_file(filepath, export_obj)

    def import_config_from_file(self, filepath):
        data = load_json_file(filepath)
        if not isinstance(data, dict):
            return None
        if u"params" in data:
            p_name = data.get(u"profile_name") or os.path.splitext(os.path.basename(filepath))[0]
            params = [unicode(x).strip() for x in data.get(u"params", []) if unicode(x).strip()]
            cat_states = data.get(u"category_states", {})
            if not params:
                params = list(DEFAULT_PARAMS_LIST)
            self.save_profile(p_name, params, cat_states)
            return {
                u"profile_name": p_name,
                u"params": params,
                u"category_states": cat_states
            }
        elif u"last_session" in data:
            ls = data[u"last_session"]
            p_name = data.get(u"active_profile", u"Импортированный профиль")
            params = ls.get(u"params", list(DEFAULT_PARAMS_LIST))
            cat_states = ls.get(u"category_states", {})
            self.save_profile(p_name, params, cat_states)
            return {
                u"profile_name": p_name,
                u"params": params,
                u"category_states": cat_states
            }
        return None


# ==============================================================================
# 1. ОБРАБОТЧИК EXTERNAL EVENT ДЛЯ НЕМОДАЛЬНОГО ОКНА (ИЗОЛЯЦИЯ / ЗУМ В REVIT)
# ==============================================================================

class RevitModelessActionHandler(IExternalEventHandler):
    def __init__(self):
        self.action_type = None
        self.element_ids = None
        self.target_element_id_int = None
        self.params_to_set = None  # dict: {param_name: new_value_str}
        self.on_params_written_callback = None
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
                            u"✓ Изолировано элементов на активном виде: {}. Окно Revit доступно для работы.".format(self.element_ids.Count),
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
                            u"✓ Временная изоляция (HI) сброшена на активном виде.",
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
                        u"✓ Показано и выделено в модели: {} шт. Вы можете сразу менять их свойства в Revit!".format(self.element_ids.Count),
                        Color.FromArgb(22, 101, 52)
                    )

            elif self.action_type == "SET_ELEMENT_PARAMS" and self.target_element_id_int is not None and self.params_to_set:
                target_el = active_doc.GetElement(ElementId(int(self.target_element_id_int)))
                if target_el is not None:
                    t = Transaction(active_doc, u"BIM Аудит: Запись значений параметров")
                    t.Start()
                    changed_cnt = 0
                    errors = []
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
# 2. СПИСКИ РЕДКИХ / СЛУЖЕБНЫХ КАТЕГОРИЙ И ФУНКЦИИ АНАЛИЗА ПАРАМЕТРОВ
# ==============================================================================

HARD_IGNORED_BIC_NAMES = [
    "OST_Cameras",
    "OST_SectionBox",
    "OST_Viewers",
    "OST_SharedBasePoint",
    "OST_ProjectBasePoint"
]

RARE_BIC_NAMES = [
    "OST_CurtainGrids",
    "OST_CurtainGridsWall",
    "OST_CurtainGridsSystem",
    "OST_CurtainGridsRoof",
    "OST_CurtainGridsCurtaSystem",
    "OST_Lines",
    "OST_SketchLines",
    "OST_CurveElem",
    "OST_RoomSeparationLines",
    "OST_AreaSchemeLines",
    "OST_SpaceSeparationLines",
    "OST_MEPSpaceSeparationLines",
    "OST_InsulationLines",
    "OST_Materials",
    "OST_ShaftOpening",
    "OST_ArcWallRectOpening",
    "OST_SWallRectOpening",
    "OST_ColumnOpening",
    "OST_FloorOpening",
    "OST_RoofOpening",
    "OST_CeilingOpening",
    "OST_PipingSystem",
    "OST_DuctSystem",
    "OST_SwitchSystem",
    "OST_ElectricalCircuit",
    "OST_DetailComponents",
    "OST_RasterImages",
    "OST_Mass",
    "OST_MassFloor",
    "OST_MassWall",
    "OST_MassRoof",
    "OST_MassGlazing",
    "OST_Topography",
    "OST_Site",
    "OST_Planting",
    "OST_Entourage",
    "OST_Roads",
    "OST_Parking",
    "OST_RvtLinks",
    "OST_Parts",
    "OST_Assemblies",
    "OST_IOSModelGroups",
    "OST_Levels",
    "OST_Grids",
    "OST_CLines",
    "OST_ScopeBoxes",
    "OST_ReferencePoints",
    "OST_HVAC_Zones",
    "OST_ZoneEquipment",
    "OST_AnalyticalNodes",
    "OST_AnalyticalMember",
    "OST_BeamAnalytical",
    "OST_ColumnAnalytical",
    "OST_FloorAnalytical",
    "OST_WallAnalytical",
    "OST_FoundationSlabAnalytical",
    "OST_IsolatedFoundationAnalytical",
    "OST_AnalyticalPipeConnections",
    "OST_RebarShape",
    "OST_FabricAreas",
    "OST_Coupler"
]

HARD_IGNORED_BICS = set()
for _bname in HARD_IGNORED_BIC_NAMES:
    if hasattr(BuiltInCategory, _bname):
        try:
            HARD_IGNORED_BICS.add(int(getattr(BuiltInCategory, _bname)))
        except:
            pass

RARE_BICS = set()
for _bname in RARE_BIC_NAMES:
    if hasattr(BuiltInCategory, _bname):
        try:
            RARE_BICS.add(int(getattr(BuiltInCategory, _bname)))
        except:
            pass

RARE_CATEGORY_KEYWORDS = [
    u"схемы разрезки",
    u"разрезки витраж",
    u"разрезка витраж",
    u"curtain grid",
    u"curtain wall grid",
    u"линии",
    u"lines",
    u"разделител",
    u"separation",
    u"материал",
    u"material",
    u"аналитическ",
    u"analytical",
    u"антураж",
    u"entourage",
    u"озеленени",
    u"planting",
    u"топограф",
    u"topograph",
    u"генплан",
    u"площадк",
    u"парковк",
    u"parking",
    u"проем",
    u"opening",
    u"шахт",
    u"shaft",
    u"элементы узлов",
    u"detail item",
    u"связанн",
    u"rvt link",
    u"группы",
    u"model group",
    u"формы",
    u"формообразующ",
    u"mass",
    u"системы воздуховодов",
    u"трубопроводные системы",
    u"цепи",
    u"duct system",
    u"piping system",
    u"electrical circuit",
    u"зоны",
    u"hvac zone",
    u"пространств",
    u"spaces",
    u"сборки",
    u"части",
    u"parts",
    u"assemblies",
    u"оси",
    u"уровни",
    u"grids",
    u"levels",
    u"област",
    u"scope box",
    u"растров",
    u"raster",
    u"вспомогательн",
    u"эскиз",
    u"sketch"
]


def is_rare_or_service_category(cat_name, cat_id_int=None):
    if cat_id_int is not None and cat_id_int in RARE_BICS:
        return True
    if not cat_name:
        return True
    low_name = cat_name.strip().lower()
    for kw in RARE_CATEGORY_KEYWORDS:
        if kw in low_name:
            return True
    return False


def ElementName(elem):
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



def inspect_editable_parameter(doc_ref, elem, param_name):
    """
    Возвращает подробную информацию о параметре для окна редактирования:
      {
        'exists': bool,
        'is_readonly': bool,
        'scope': u'Экземпляр' | u'Тип' | u'Отсутствует',
        'storage_type': StorageType | None,
        'current_val': unicode
      }
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
        return {
            'exists': False,
            'is_readonly': True,
            'scope': u"Отсутствует",
            'storage_type': None,
            'current_val': u""
        }

    is_ro = bool(param.IsReadOnly)
    st = param.StorageType
    # Для StorageType.ElementId редактирование текстом обычно недоступно (кроме просмотра)
    if st == StorageType.ElementId:
        is_ro = True

    is_filled, val_str, _ = resolve_parameter_value(doc_ref, elem, param_name)
    clean_val = val_str if is_filled else u""

    return {
        'exists': True,
        'is_readonly': is_ro,
        'scope': scope_str,
        'storage_type': st,
        'current_val': clean_val
    }


def write_single_parameter_value(doc_ref, elem, param_name, new_value_str):
    """
    Записывает новое значение в параметр Экземпляра или Типа (внутри открытой транзакции).
    Возвращает (success_bool, message_str, is_type_param_bool).
    """
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
            return (True, u"ОК", is_type_param)
        elif st == StorageType.Integer:
            if val_clean == u"":
                param.Set(0)
            else:
                param.Set(int(float(val_clean.replace(u",", u"."))))
            return (True, u"ОК", is_type_param)
        elif st == StorageType.Double:
            if val_clean == u"":
                param.Set(0.0)
            else:
                ok_vs = param.SetValueString(val_clean)
                if not ok_vs:
                    param.Set(float(val_clean.replace(u",", u".")))
            return (True, u"ОК", is_type_param)
        else:
            return (False, u"Тип данных ElementId не меняется текстом", is_type_param)
    except Exception as ex:
        return (False, unicode(ex), is_type_param)


def collect_elements_from_view(doc_ref, view_elem):
    raw_elements = FilteredElementCollector(doc_ref, view_elem.Id).WhereElementIsNotElementType().ToElements()
    valid_elements = []

    for el in raw_elements:
        try:
            cat = el.Category
            if cat is None:
                continue
            cat_id_int = cat.Id.IntegerValue
            if cat_id_int in HARD_IGNORED_BICS:
                continue
            if cat.CategoryType != CategoryType.Model and not is_rare_or_service_category(cat.Name, cat_id_int):
                continue
            valid_elements.append(el)
        except:
            continue

    return valid_elements


def discover_available_parameters(doc_ref, view_elem=None, only_view_elements=True):
    """
    Быстро собирает все доступные параметры (Экземпляр и Тип) для правого каталога:
    1) Из ParameterBindings документа (все параметры проекта и общие параметры MR_*, ADSK_* и т.д.)
    2) Путем быстрого сэмплирования типоразмеров и категорий элементов на выбранном виде,
       чтобы получить все системные и семейственные параметры (Марка, Номер помещения, Уровень и др.)
       без перебора десятков тысяч однотипных элементов.
    Возвращает словарь: param_name -> set(['Экземпляр', 'Тип'])
    """
    params_map = {}

    def register_p(p_name, scope_label):
        if not p_name:
            return
        p_name = p_name.strip()
        if not p_name:
            return
        if p_name not in params_map:
            params_map[p_name] = set()
        params_map[p_name].add(scope_label)

    if not only_view_elements or view_elem is None:
        try:
            it = doc_ref.ParameterBindings.ForwardIterator()
            it.Reset()
            while it.MoveNext():
                defn = it.Key
                binding = it.Current
                if defn and defn.Name:
                    sc = u"Тип" if isinstance(binding, TypeBinding) else u"Экземпляр"
                    register_p(defn.Name, sc)
        except:
            pass

    if view_elem is not None:
        try:
            raw_els = FilteredElementCollector(doc_ref, view_elem.Id).WhereElementIsNotElementType().ToElements()
            seen_types = set()
            seen_cats = set()
            sampled_count = 0

            for el in raw_els:
                try:
                    cat = el.Category
                    if cat is None:
                        continue
                    c_id = cat.Id.IntegerValue
                    if c_id in HARD_IGNORED_BICS:
                        continue
                    if is_rare_or_service_category(cat.Name, c_id):
                        continue

                    t_id = el.GetTypeId()
                    t_id_int = t_id.IntegerValue if t_id else -1

                    if (t_id_int != -1 and t_id_int in seen_types) and (c_id in seen_cats):
                        continue

                    seen_cats.add(c_id)
                    if t_id_int != -1:
                        seen_types.add(t_id_int)

                    for p in el.Parameters:
                        try:
                            if p.Definition and p.Definition.Name:
                                register_p(p.Definition.Name, u"Экземпляр")
                        except:
                            pass

                    if t_id and t_id != ElementId.InvalidElementId:
                        t_elem = doc_ref.GetElement(t_id)
                        if t_elem:
                            for tp in t_elem.Parameters:
                                try:
                                    if tp.Definition and tp.Definition.Name:
                                        register_p(tp.Definition.Name, u"Тип")
                                except:
                                    pass

                    sampled_count += 1
                    if sampled_count >= 120:
                        break
                except:
                    continue
        except:
            pass

    try:
        it = doc_ref.ParameterBindings.ForwardIterator()
        it.Reset()
        while it.MoveNext():
            defn = it.Key
            binding = it.Current
            if defn and defn.Name:
                sc = u"Тип" if isinstance(binding, TypeBinding) else u"Экземпляр"
                register_p(defn.Name, sc)
    except:
        pass

    return params_map


def build_all_revit_categories_catalog(doc_ref, view_elements, saved_category_states=None):
    if saved_category_states is None:
        saved_category_states = {}

    catalog = {}

    for el in view_elements:
        try:
            cat = el.Category
            if not cat or not cat.Name:
                continue
            c_name = cat.Name
            c_id = cat.Id.IntegerValue
            if c_name not in catalog:
                rare_flag = is_rare_or_service_category(c_name, c_id)
                if c_name in saved_category_states:
                    enabled_flag = bool(saved_category_states[c_name])
                else:
                    enabled_flag = (not rare_flag)
                catalog[c_name] = {
                    'name': c_name,
                    'id_int': c_id,
                    'count_on_view': 0,
                    'is_rare': rare_flag,
                    'enabled': enabled_flag
                }
            catalog[c_name]['count_on_view'] += 1
        except:
            continue

    try:
        doc_cats = doc_ref.Settings.Categories
        for c in doc_cats:
            try:
                if not c or not c.Name:
                    continue
                if c.CategoryType != CategoryType.Model:
                    continue
                c_id = c.Id.IntegerValue
                if c_id in HARD_IGNORED_BICS:
                    continue
                c_name = c.Name
                if c_name not in catalog:
                    rare_flag = is_rare_or_service_category(c_name, c_id)
                    catalog[c_name] = {
                        'name': c_name,
                        'id_int': c_id,
                        'count_on_view': 0,
                        'is_rare': rare_flag,
                        'enabled': False
                    }
            except:
                continue
    except:
        pass

    return catalog


# ==============================================================================
# 3. ДВУХКОЛОНОЧНОЕ ОКНО НАСТРОЙКИ (СЛЕВА — ВИД И ВВОД, СПРАВА — ВСЕ ПАРАМЕТРЫ)
# ==============================================================================

class ParameterAuditConfigForm(Form):
    def __init__(self, doc_ref, cfg_mgr, current_view_override=None, current_params_override=None):
        self.doc = doc_ref
        self.cfg_mgr = cfg_mgr
        self.current_view_override = current_view_override
        self.Text = u"BIM Аудит параметров модели v2.9 (Revit 2022)"
        self.Size = Size(960, 780)
        self.StartPosition = FormStartPosition.CenterScreen
        self.FormBorderStyle = FormBorderStyle.FixedDialog
        self.MaximizeBox = False
        self.MinimizeBox = False
        self.TopMost = True
        self.BackColor = Color.FromArgb(245, 247, 250)
        self.Shown += self.on_form_shown

        self.selected_view = None
        self.selected_params = []
        self.selected_category_states = {}
        self.available_views_dict = {}
        self.discovered_params_map = {}
        self.dynamic_textboxes = []
        self._suppress_profile_change = False
        self._suppress_text_sync = False

        last_sess = self.cfg_mgr.get_last_session()
        if current_params_override:
            initial_params = list(current_params_override)
        else:
            initial_params = last_sess.get(u"params", list(DEFAULT_PARAMS_LIST))
        if not initial_params:
            initial_params = list(DEFAULT_PARAMS_LIST)
        self.selected_category_states = dict(last_sess.get(u"category_states", {}))

        # --- ШАПКА ---
        pnl_header = Panel(Location=Point(0, 0), Size=Size(960, 52), BackColor=Color.FromArgb(30, 41, 59))
        lbl_title = Label(
            Text=u"Проверка заполненности обязательных параметров (v2.9)",
            Location=Point(15, 8), Size=Size(900, 22),
            ForeColor=Color.White, Font=Font("Segoe UI", 11, FontStyle.Bold)
        )
        lbl_sub = Label(
            Text=u"Слева: выбор вида и список проверяемых параметров  |  Справа: живой каталог всех доступных параметров модели (клик = добавить/убрать)",
            Location=Point(15, 30), Size=Size(920, 18),
            ForeColor=Color.FromArgb(148, 163, 184), Font=Font("Segoe UI", 8.5, FontStyle.Regular)
        )
        pnl_header.Controls.Add(lbl_title)
        pnl_header.Controls.Add(lbl_sub)
        self.Controls.Add(pnl_header)

        # ======================================================================
        # ЛЕВАЯ КОЛОНКА (X = 15, Ширина = 485)
        # ======================================================================

        # --- БЛОК 0: ПРОФИЛИ КОНФИГУРАЦИИ ---
        grp_cfg = GroupBox(
            Text=u"Профиль настроек (Параметры + Фильтр категорий)",
            Location=Point(15, 58), Size=Size(485, 86),
            Font=Font("Segoe UI", 9, FontStyle.Bold)
        )

        self.cb_profiles = ComboBox(
            Location=Point(12, 22), Size=Size(250, 24),
            DropDownStyle=ComboBoxStyle.DropDown,
            Font=Font("Segoe UI", 9, FontStyle.Regular)
        )
        self.cb_profiles.SelectedIndexChanged += self.on_profile_selected
        grp_cfg.Controls.Add(self.cb_profiles)

        btn_save_prof = Button(
            Text=u"Сохранить профиль",
            Location=Point(268, 21), Size=Size(130, 26),
            Font=Font("Segoe UI", 8, FontStyle.Bold),
            BackColor=Color.FromArgb(239, 246, 255), ForeColor=Color.FromArgb(30, 64, 175),
            FlatStyle=FlatStyle.Flat
        )
        btn_save_prof.Click += self.on_save_profile_click
        grp_cfg.Controls.Add(btn_save_prof)

        btn_del_prof = Button(
            Text=u"Удалить",
            Location=Point(404, 21), Size=Size(68, 26),
            Font=Font("Segoe UI", 8, FontStyle.Regular), BackColor=Color.White
        )
        btn_del_prof.Click += self.on_delete_profile_click
        grp_cfg.Controls.Add(btn_del_prof)

        btn_imp_json = Button(
            Text=u"Загрузить из JSON...",
            Location=Point(12, 53), Size=Size(165, 25),
            Font=Font("Segoe UI", 8, FontStyle.Regular), BackColor=Color.White
        )
        btn_imp_json.Click += self.on_import_json_click
        grp_cfg.Controls.Add(btn_imp_json)

        btn_exp_json = Button(
            Text=u"Выгрузить в JSON...",
            Location=Point(183, 53), Size=Size(165, 25),
            Font=Font("Segoe UI", 8, FontStyle.Regular), BackColor=Color.White
        )
        btn_exp_json.Click += self.on_export_json_click
        grp_cfg.Controls.Add(btn_exp_json)

        self.lbl_cfg_status = Label(
            Text=u"Автосохранение вкл.",
            Location=Point(352, 56), Size=Size(120, 18),
            Font=Font("Segoe UI", 7.5, FontStyle.Regular),
            ForeColor=Color.FromArgb(22, 101, 52),
            TextAlign=ContentAlignment.MiddleRight
        )
        grp_cfg.Controls.Add(self.lbl_cfg_status)
        self.Controls.Add(grp_cfg)

        # --- БЛОК 1: ВЫБОР ВИДА ИЛИ СПЕЦИФИКАЦИИ ---
        grp_view = GroupBox(
            Text=u"1. Источник элементов (3D-вид, План или Спецификация)",
            Location=Point(15, 150), Size=Size(485, 235),
            Font=Font("Segoe UI", 9, FontStyle.Bold)
        )

        self.chk_3d = CheckBox(
            Text=u"3D-виды", Location=Point(12, 22), Size=Size(85, 20),
            Checked=True, Font=Font("Segoe UI", 8.5, FontStyle.Regular)
        )
        self.chk_3d.CheckedChanged += self.refresh_views_list
        grp_view.Controls.Add(self.chk_3d)

        self.chk_sched = CheckBox(
            Text=u"Спецификации", Location=Point(102, 22), Size=Size(118, 20),
            Checked=True, Font=Font("Segoe UI", 8.5, FontStyle.Regular)
        )
        self.chk_sched.CheckedChanged += self.refresh_views_list
        grp_view.Controls.Add(self.chk_sched)

        self.chk_plans = CheckBox(
            Text=u"Планы / Разрезы", Location=Point(225, 22), Size=Size(130, 20),
            Checked=False, Font=Font("Segoe UI", 8.5, FontStyle.Regular)
        )
        self.chk_plans.CheckedChanged += self.refresh_views_list
        grp_view.Controls.Add(self.chk_plans)

        self.btn_active_view = Button(
            Text=u"Активный вид", Location=Point(372, 19), Size=Size(100, 24),
            Font=Font("Segoe UI", 8, FontStyle.Regular), BackColor=Color.White
        )
        self.btn_active_view.Click += self.on_select_active_view
        grp_view.Controls.Add(self.btn_active_view)

        lbl_search = Label(
            Text=u"Поиск или точное имя вида:", Location=Point(12, 48), Size=Size(460, 18),
            Font=Font("Segoe UI", 8.5, FontStyle.Regular)
        )
        grp_view.Controls.Add(lbl_search)

        self.tb_view_search = TextBox(
            Location=Point(12, 68), Size=Size(460, 22),
            Font=Font("Segoe UI", 9, FontStyle.Regular)
        )
        self.tb_view_search.TextChanged += self.refresh_views_list
        grp_view.Controls.Add(self.tb_view_search)

        self.lb_views = ListBox(
            Location=Point(12, 95), Size=Size(460, 128),
            Font=Font("Segoe UI", 9, FontStyle.Regular)
        )
        self.lb_views.SelectedIndexChanged += self.on_selected_view_changed
        grp_view.Controls.Add(self.lb_views)
        self.Controls.Add(grp_view)

        # --- БЛОК 2: ВЫБРАННЫЕ ПАРАМЕТРЫ ДЛЯ АНАЛИЗА ---
        grp_params = GroupBox(
            Text=u"2. Выбранные параметры для анализа (через разделитель «;»)",
            Location=Point(15, 392), Size=Size(485, 285),
            Font=Font("Segoe UI", 9, FontStyle.Bold)
        )

        lbl_semi_hint = Label(
            Text=u"Кликайте по параметрам в каталоге СПРАВА (для добавления/удаления)\nили редактируйте список параметров через точку с запятой (;) вручную:",
            Location=Point(12, 24), Size=Size(460, 34),
            Font=Font("Segoe UI", 8.5, FontStyle.Regular),
            ForeColor=Color.FromArgb(51, 65, 85)
        )
        grp_params.Controls.Add(lbl_semi_hint)

        self.tb_semicolon = TextBox(
            Location=Point(12, 62), Size=Size(460, 170),
            Multiline=True, ScrollBars=ScrollBars.Vertical,
            Font=Font("Segoe UI", 9.5, FontStyle.Regular),
            Text=u";".join(initial_params)
        )
        self.tb_semicolon.TextChanged += self.on_semicolon_text_changed
        grp_params.Controls.Add(self.tb_semicolon)

        btn_clear_all = Button(
            Text=u"Очистить поле",
            Location=Point(12, 240), Size=Size(135, 30),
            Font=Font("Segoe UI", 8.5, FontStyle.Regular), BackColor=Color.White
        )
        btn_clear_all.Click += self.on_clear_params_click
        grp_params.Controls.Add(btn_clear_all)

        self.lbl_selected_cnt = Label(
            Text=u"Выбрано параметров: {} шт.".format(len(initial_params)),
            Location=Point(250, 246), Size=Size(222, 20),
            Font=Font("Segoe UI", 8.5, FontStyle.Bold),
            ForeColor=Color.FromArgb(30, 64, 175),
            TextAlign=ContentAlignment.MiddleRight
        )
        grp_params.Controls.Add(self.lbl_selected_cnt)

        self.Controls.Add(grp_params)

        # ======================================================================
        # ПРАВАЯ КОЛОНКА: КАТАЛОГ ВСЕХ ДОСТУПНЫХ ПАРАМЕТРОВ МОДЕЛИ / ВИДА
        # (X = 512, Ширина = 420)
        # ======================================================================

        grp_catalog = GroupBox(
            Text=u"3. Все доступные параметры (Клик по строке = добавить / убрать)",
            Location=Point(512, 58), Size=Size(420, 619),
            Font=Font("Segoe UI", 9, FontStyle.Bold)
        )

        lbl_cat_search = Label(
            Text=u"Живой поиск параметра (например: MR_, Марка, Код, Этаж):",
            Location=Point(12, 22), Size=Size(395, 18),
            Font=Font("Segoe UI", 8.5, FontStyle.Regular)
        )
        grp_catalog.Controls.Add(lbl_cat_search)

        self.tb_catalog_search = TextBox(
            Location=Point(12, 42), Size=Size(310, 23),
            Font=Font("Segoe UI", 9, FontStyle.Regular)
        )
        self.tb_catalog_search.TextChanged += self.refresh_catalog_grid
        grp_catalog.Controls.Add(self.tb_catalog_search)

        btn_clear_cat_search = Button(
            Text=u"Сброс",
            Location=Point(328, 41), Size=Size(80, 25),
            Font=Font("Segoe UI", 8, FontStyle.Regular), BackColor=Color.White
        )
        btn_clear_cat_search.Click += self.on_clear_catalog_search
        grp_catalog.Controls.Add(btn_clear_cat_search)

        self.chk_cat_inst = CheckBox(
            Text=u"Экземпляр", Location=Point(12, 71), Size=Size(95, 20),
            Checked=True, Font=Font("Segoe UI", 8.2, FontStyle.Regular)
        )
        self.chk_cat_inst.CheckedChanged += self.refresh_catalog_grid
        grp_catalog.Controls.Add(self.chk_cat_inst)

        self.chk_cat_type = CheckBox(
            Text=u"Тип", Location=Point(112, 71), Size=Size(60, 20),
            Checked=True, Font=Font("Segoe UI", 8.2, FontStyle.Regular)
        )
        self.chk_cat_type.CheckedChanged += self.refresh_catalog_grid
        grp_catalog.Controls.Add(self.chk_cat_type)

        self.chk_click_to_toggle = CheckBox(
            Text=u"Одиночный клик сразу добавляет/убирает",
            Location=Point(175, 71), Size=Size(238, 20),
            Checked=True, Font=Font("Segoe UI", 8, FontStyle.Bold),
            ForeColor=Color.FromArgb(22, 101, 52)
        )
        grp_catalog.Controls.Add(self.chk_click_to_toggle)

        self.dgv_catalog = DataGridView(Location=Point(12, 96), Size=Size(396, 472))
        self.dgv_catalog.AllowUserToAddRows = False
        self.dgv_catalog.AllowUserToDeleteRows = False
        self.dgv_catalog.ReadOnly = True
        self.dgv_catalog.MultiSelect = True
        self.dgv_catalog.SelectionMode = DataGridViewSelectionMode.FullRowSelect
        self.dgv_catalog.AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.Fill
        self.dgv_catalog.BackgroundColor = Color.White
        self.dgv_catalog.RowHeadersVisible = False
        self.dgv_catalog.Font = Font("Segoe UI", 8.5, FontStyle.Regular)

        col_p_stat = DataGridViewTextBoxColumn()
        col_p_stat.Name = "AddedState"
        col_p_stat.HeaderText = u"В списке"
        col_p_stat.FillWeight = 18
        self.dgv_catalog.Columns.Add(col_p_stat)

        col_p_name = DataGridViewTextBoxColumn()
        col_p_name.Name = "ParamName"
        col_p_name.HeaderText = u"Имя параметра"
        col_p_name.FillWeight = 57
        self.dgv_catalog.Columns.Add(col_p_name)

        col_p_scope = DataGridViewTextBoxColumn()
        col_p_scope.Name = "ParamScope"
        col_p_scope.HeaderText = u"Принадлежность"
        col_p_scope.FillWeight = 25
        self.dgv_catalog.Columns.Add(col_p_scope)

        self.dgv_catalog.CellMouseClick += self.on_catalog_cell_mouse_click
        self.dgv_catalog.CellDoubleClick += self.on_catalog_cell_double_click
        grp_catalog.Controls.Add(self.dgv_catalog)

        btn_add_sel_cat = Button(
            Text=u"← Добавить выделенные (Shift/Ctrl)",
            Location=Point(12, 576), Size=Size(235, 32),
            Font=Font("Segoe UI", 8.2, FontStyle.Bold),
            BackColor=Color.FromArgb(239, 246, 255), ForeColor=Color.FromArgb(30, 64, 175),
            FlatStyle=FlatStyle.Flat
        )
        btn_add_sel_cat.Click += self.on_add_selected_from_catalog
        grp_catalog.Controls.Add(btn_add_sel_cat)

        self.lbl_catalog_total = Label(
            Text=u"Найдено: 0",
            Location=Point(252, 583), Size=Size(155, 20),
            Font=Font("Segoe UI", 8, FontStyle.Regular),
            ForeColor=Color.FromArgb(100, 116, 139),
            TextAlign=ContentAlignment.MiddleRight
        )
        grp_catalog.Controls.Add(self.lbl_catalog_total)

        self.Controls.Add(grp_catalog)

        # ======================================================================
        # НИЖНЯЯ ПАНЕЛЬ ЗАПУСКА
        # ======================================================================
        self.btn_run = Button(
            Text=u"Запустить анализ и открыть Дашборд",
            Location=Point(565, 690), Size=Size(260, 42),
            Font=Font("Segoe UI", 9.5, FontStyle.Bold),
            BackColor=Color.FromArgb(37, 99, 235), ForeColor=Color.White,
            FlatStyle=FlatStyle.Flat
        )
        self.btn_run.Click += self.on_run_click
        self.Controls.Add(self.btn_run)

        self.btn_cancel = Button(
            Text=u"Отмена",
            Location=Point(835, 690), Size=Size(97, 42),
            Font=Font("Segoe UI", 9, FontStyle.Regular),
            BackColor=Color.White, DialogResult=DialogResult.Cancel
        )
        self.Controls.Add(self.btn_cancel)

        self.AcceptButton = self.btn_run
        self.CancelButton = self.btn_cancel

        self.populate_profiles_combo()
        self.refresh_views_list()
        self.select_initial_active_view()
        self.reload_discovered_parameters_for_current_view()

    # ==========================================================================
    # МЕТОДЫ КАТАЛОГА ВСЕХ ПАРАМЕТРОВ СПРАВА
    # ==========================================================================

    def get_currently_highlighted_view_obj(self):
        if self.lb_views.SelectedItem and self.lb_views.SelectedItem in self.available_views_dict:
            return self.available_views_dict[self.lb_views.SelectedItem]
        return self.doc.ActiveView

    def reload_discovered_parameters_for_current_view(self):
        v_obj = self.get_currently_highlighted_view_obj()
        self.discovered_params_map = discover_available_parameters(self.doc, v_obj, only_view_elements=False)
        for p in EXTRA_PRESET_PARAMS:
            if p not in self.discovered_params_map:
                self.discovered_params_map[p] = set([u"Экземпляр/Тип"])
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
        show_inst = self.chk_cat_inst.Checked
        show_type = self.chk_cat_type.Checked

        current_selected_set = set(self.get_current_ui_params())

        sorted_names = sorted(self.discovered_params_map.keys(), key=lambda s: s.lower())
        shown_cnt = 0

        for p_name in sorted_names:
            if q and (q not in p_name.lower()):
                continue

            scopes = self.discovered_params_map[p_name]
            has_inst = (u"Экземпляр" in scopes) or (u"Экземпляр/Тип" in scopes)
            has_type = (u"Тип" in scopes) or (u"Экземпляр/Тип" in scopes)

            if not ((show_inst and has_inst) or (show_type and has_type)):
                continue

            scope_str = u" / ".join(sorted(scopes))
            is_added = (p_name in current_selected_set)
            state_txt = u"✓ Да" if is_added else u"+"

            r_idx = self.dgv_catalog.Rows.Add(state_txt, p_name, scope_str)
            row_obj = self.dgv_catalog.Rows[r_idx]
            if is_added:
                row_obj.DefaultCellStyle.BackColor = Color.FromArgb(220, 252, 231)
                row_obj.DefaultCellStyle.ForeColor = Color.FromArgb(22, 101, 52)
            else:
                row_obj.DefaultCellStyle.BackColor = Color.White
                row_obj.DefaultCellStyle.ForeColor = Color.FromArgb(15, 23, 42)

            shown_cnt += 1

        self.lbl_catalog_total.Text = u"Параметров: {}".format(shown_cnt)

    def update_catalog_visual_highlights_only(self):
        """Быстро обновляет зеленую подсветку ✓ в правом каталоге без пересоздания строк."""
        current_selected_set = set(self.get_current_ui_params())
        for i in range(self.dgv_catalog.Rows.Count):
            r_obj = self.dgv_catalog.Rows[i]
            p_name = r_obj.Cells[1].Value
            is_added = (p_name in current_selected_set)
            r_obj.Cells[0].Value = u"✓ Да" if is_added else u"+"
            if is_added:
                r_obj.DefaultCellStyle.BackColor = Color.FromArgb(220, 252, 231)
                r_obj.DefaultCellStyle.ForeColor = Color.FromArgb(22, 101, 52)
            else:
                r_obj.DefaultCellStyle.BackColor = Color.White
                r_obj.DefaultCellStyle.ForeColor = Color.FromArgb(15, 23, 42)
        self.lbl_selected_cnt.Text = u"Выбрано параметров: {} шт.".format(len(current_selected_set))

    def toggle_or_add_param_from_catalog(self, p_name, allow_remove_if_exists=True):
        if not p_name:
            return
        current_list = self.get_current_ui_params()
        if p_name in current_list:
            if allow_remove_if_exists:
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

        p_name = self.dgv_catalog.Rows[event.RowIndex].Cells[1].Value
        self.toggle_or_add_param_from_catalog(p_name, allow_remove_if_exists=True)

    def on_catalog_cell_double_click(self, sender, event):
        if event.RowIndex < 0:
            return
        if not self.chk_click_to_toggle.Checked:
            p_name = self.dgv_catalog.Rows[event.RowIndex].Cells[1].Value
            self.toggle_or_add_param_from_catalog(p_name, allow_remove_if_exists=True)

    def on_add_selected_from_catalog(self, sender, event):
        sel_rows = self.dgv_catalog.SelectedRows
        if sel_rows.Count == 0:
            return
        current_list = self.get_current_ui_params()
        indices = sorted([sel_rows[i].Index for i in range(sel_rows.Count)])
        for idx in indices:
            p_name = self.dgv_catalog.Rows[idx].Cells[1].Value
            if p_name and p_name not in current_list:
                current_list.append(p_name)
        self.apply_params_to_ui(current_list, allow_empty=True)
        self.update_catalog_visual_highlights_only()

    def on_semicolon_text_changed(self, sender, event):
        if self._suppress_text_sync:
            return
        if hasattr(self, 'dgv_catalog'):
            self.update_catalog_visual_highlights_only()

    def on_clear_params_click(self, sender, event):
        self.apply_params_to_ui([], allow_empty=True)
        self.update_catalog_visual_highlights_only()

    # ==========================================================================
    # МЕТОДЫ РАБОТЫ С ПРОФИЛЯМИ КОНФИГУРАЦИИ
    # ==========================================================================

    def populate_profiles_combo(self):
        self._suppress_profile_change = True
        self.cb_profiles.Items.Clear()
        prof_names = self.cfg_mgr.get_profile_names()
        for name in prof_names:
            self.cb_profiles.Items.Add(name)
        act_prof = self.cfg_mgr.get_active_profile_name()
        if act_prof in prof_names:
            self.cb_profiles.Text = act_prof
        elif prof_names:
            self.cb_profiles.Text = prof_names[0]
        self._suppress_profile_change = False

    def get_current_ui_params(self):
        raw_text = self.tb_semicolon.Text.replace(u"\r", u"").replace(u"\n", u";")
        params = [x.strip() for x in raw_text.split(u";") if x.strip()]
        unique_params = []
        for p in params:
            if p not in unique_params:
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
            self.cfg_mgr.update_last_session(
                params_list=p_list,
                category_states_dict=self.selected_category_states
            )
            self.update_catalog_visual_highlights_only()
            self.lbl_cfg_status.Text = u"Профиль загружен"

    def on_save_profile_click(self, sender, event):
        prof_name = self.cb_profiles.Text.strip()
        if not prof_name:
            TaskDialog.Show(u"Сохранение профиля", u"Введите имя профиля в поле выбора профиля.")
            return
        params = self.get_current_ui_params()
        if not params:
            TaskDialog.Show(u"Сохранение профиля", u"Список параметров пуст.")
            return
        ok = self.cfg_mgr.save_profile(prof_name, params, self.selected_category_states, input_mode=u"semicolon")
        self.populate_profiles_combo()
        if ok:
            self.lbl_cfg_status.Text = u"✓ Сохранено!"

    def on_delete_profile_click(self, sender, event):
        prof_name = self.cb_profiles.Text.strip()
        if self.cfg_mgr.delete_profile(prof_name):
            self.populate_profiles_combo()
            self.on_profile_selected(None, None)
            self.lbl_cfg_status.Text = u"Профиль удален"
        else:
            TaskDialog.Show(u"Удаление профиля", u"Нельзя удалить единственный оставшийся профиль.")

    def on_import_json_click(self, sender, event):
        ofd = OpenFileDialog()
        ofd.Title = u"Загрузить файл конфигурации (.json)"
        ofd.Filter = "JSON Config (*.json)|*.json"
        if ofd.ShowDialog() == DialogResult.OK:
            imported = self.cfg_mgr.import_config_from_file(ofd.FileName)
            if imported:
                self.populate_profiles_combo()
                self.apply_params_to_ui(imported[u"params"])
                self.selected_category_states = dict(imported.get(u"category_states", {}))
                self.update_catalog_visual_highlights_only()
                self.lbl_cfg_status.Text = u"✓ Импортирован JSON"
            else:
                TaskDialog.Show(u"Ошибка импорта", u"Не удалось прочитать настройки из выбранного файла JSON.")

    def on_export_json_click(self, sender, event):
        params = self.get_current_ui_params()
        prof_name = self.cb_profiles.Text.strip() or u"Профиль_BIM_аудита"
        sfd = SaveFileDialog()
        sfd.Title = u"Выгрузить конфигурацию параметров и категорий в JSON"
        sfd.Filter = "JSON Config (*.json)|*.json"
        sfd.FileName = u"Конфиг_аудита_{}.json".format(prof_name.replace(u" ", u"_").replace(u":", u"_"))
        if sfd.ShowDialog() == DialogResult.OK:
            ok = self.cfg_mgr.export_single_config_to_file(
                sfd.FileName, prof_name, params, self.selected_category_states
            )
            if ok:
                self.lbl_cfg_status.Text = u"✓ Выгружен JSON"

    # ==========================================================================
    # МЕТОДЫ ВЫБОРА ВИДОВ И ПОЛЕЙ ПАРАМЕТРОВ
    # ==========================================================================

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

    def on_form_shown(self, sender, event):
        try:
            self.TopMost = True
            self.BringToFront()
            self.Activate()
        except:
            pass

    def select_initial_active_view(self):
        try:
            target_v = self.current_view_override if self.current_view_override is not None else self.doc.ActiveView
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
            TaskDialog.Show(u"Ошибка выбора вида", u"Пожалуйста, выберите 3D-вид, план или спецификацию из списка слева.")
            return

        unique_params = self.get_current_ui_params()
        if not unique_params:
            TaskDialog.Show(u"Ошибка параметров", u"Укажите или выберите из правого каталога хотя бы один параметр для анализа.")
            return

        self.cfg_mgr.update_last_session(
            params_list=unique_params,
            category_states_dict=self.selected_category_states,
            input_mode=u"semicolon"
        )

        self.selected_view = chosen_view
        self.selected_params = unique_params
        self.DialogResult = DialogResult.OK
        self.Close()


# ==============================================================================
# 4. ЛОГИКА СБОРА СЫРЫХ ДАННЫХ И БЫСТРОЙ ФИЛЬТРАЦИИ ПО КАТЕГОРИЯМ
# ==============================================================================

def scan_raw_view_elements(doc_ref, view_elem, param_names, saved_category_states=None):
    elements = collect_elements_from_view(doc_ref, view_elem)
    categories_catalog = build_all_revit_categories_catalog(doc_ref, elements, saved_category_states)

    raw_records = []
    for el in elements:
        cat_name = el.Category.Name if el.Category else u"<Без категории>"
        fam_type = get_element_type_name(doc_ref, el)
        param_results = {}
        for p_name in param_names:
            param_results[p_name] = resolve_parameter_value(doc_ref, el, p_name)

        raw_records.append({
            'element': el,
            'id': el.Id,
            'id_int': el.Id.IntegerValue,
            'category': cat_name,
            'fam_type': fam_type,
            'param_results': param_results
        })

    return raw_records, categories_catalog


def aggregate_audit_from_records(raw_records, param_names, enabled_categories_set):
    filtered_records = [r for r in raw_records if r['category'] in enabled_categories_set]
    total_elements = len(filtered_records)
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
            'value_counts': {},
            'missing_ids': []
        }

    category_stats = {}
    element_rows = []
    failed_elements = []
    failed_element_ids = []

    for rec in filtered_records:
        cat_name = rec['category']
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

        el_values = []
        el_filled_cnt = 0

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
                el_values.append(val_str)
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
            'id_int': rec['id_int'],
            'category': cat_name,
            'fam_type': rec['fam_type'],
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

# ==============================================================================
# 4.5. ОКНО РЕДАКТИРОВАНИЯ ПАРАМЕТРОВ ЭЛЕМЕНТА ПО ДВОЙНОМУ КЛИКУ (v2.8)
# ==============================================================================

class ElementParameterEditorForm(Form):
    """
    Открывается при двойном клике по строке на вкладке «3. Поэлементный список».
    Показывает сверху вниз все анализируемые параметры, их принадлежность (Экземпляр/Тип)
    и текущие значения с возможностью вписать новые значения или выбрать из существующих.
    """
    def __init__(self, doc_ref, elem, param_names, param_stats):
        self.doc = doc_ref
        self.elem = elem
        self.param_names = param_names
        self.param_stats = param_stats
        self.updated_values = {}  # param_name -> new_str_value
        self.input_controls = {}  # param_name -> (ComboBox, initial_val_str)

        el_id_int = elem.Id.IntegerValue
        cat_name = elem.Category.Name if elem.Category else u"<Без категории>"
        fam_type = get_element_type_name(doc_ref, elem)

        self.Text = u"Редактирование параметров элемента — ID {}".format(el_id_int)
        form_h = min(680, max(340, 175 + len(param_names) * 68))
        self.Size = Size(560, form_h)
        self.StartPosition = FormStartPosition.CenterParent
        self.FormBorderStyle = FormBorderStyle.FixedDialog
        self.MaximizeBox = False
        self.MinimizeBox = False
        self.TopMost = True
        self.BackColor = Color.FromArgb(245, 247, 250)
        self.Shown += self.on_shown

        # --- ШАПКА КАРТОЧКИ ЭЛЕМЕНТА ---
        pnl_hdr = Panel(Location=Point(0, 0), Size=Size(560, 62), BackColor=Color.FromArgb(30, 41, 59))
        lbl_el_title = Label(
            Text=u"Элемент ID: {}  |  {}".format(el_id_int, cat_name),
            Location=Point(14, 8), Size=Size(520, 22),
            ForeColor=Color.White, Font=Font("Segoe UI", 10.5, FontStyle.Bold)
        )
        lbl_el_sub = Label(
            Text=u"Семейство и Тип: {}".format(fam_type),
            Location=Point(14, 32), Size=Size(520, 20),
            ForeColor=Color.FromArgb(148, 163, 184), Font=Font("Segoe UI", 8.5, FontStyle.Regular),
            AutoEllipsis=True
        )
        pnl_hdr.Controls.Add(lbl_el_title)
        pnl_hdr.Controls.Add(lbl_el_sub)
        self.Controls.Add(pnl_hdr)

        # --- ПРОКРУЧИВАЕМЫЙ СПИСОК ПАРАМЕТРОВ СВЕРХУ ВНИЗ ---
        scroll_h = form_h - 165
        self.pnl_list = Panel(
            Location=Point(12, 70), Size=Size(520, scroll_h),
            AutoScroll=True, BackColor=Color.White,
            BorderStyle=BorderStyle.FixedSingle
        )

        y = 10
        f_pname = Font("Segoe UI", 9, FontStyle.Bold)
        f_scope = Font("Segoe UI", 8, FontStyle.Bold)
        f_input = Font("Segoe UI", 9.5, FontStyle.Regular)

        for idx, p_name in enumerate(self.param_names):
            meta = inspect_editable_parameter(self.doc, self.elem, p_name)
            scope = meta['scope']
            is_ro = meta['is_readonly']
            exists = meta['exists']
            cur_val = meta['current_val']

            row_pnl = Panel(
                Location=Point(8, y), Size=Size(482, 58),
                BackColor=Color.FromArgb(248, 250, 252) if exists else Color.FromArgb(254, 242, 242),
                BorderStyle=BorderStyle.FixedSingle
            )

            lbl_p = Label(
                Text=u"{}. {}".format(idx + 1, p_name),
                Location=Point(10, 6), Size=Size(260, 20),
                Font=f_pname, ForeColor=Color.FromArgb(15, 23, 42)
            )
            row_pnl.Controls.Add(lbl_p)

            if not exists:
                scope_text = u"[Нет параметра у элемента]"
                scope_col = Color.FromArgb(185, 28, 28)
            elif is_ro:
                scope_text = u"[{} — Только чтение]".format(scope)
                scope_col = Color.FromArgb(100, 116, 139)
            elif scope == u"Тип":
                scope_text = u"[Параметр ТИПА]"
                scope_col = Color.FromArgb(109, 40, 217)
            else:
                scope_text = u"[Параметр ЭКЗЕМПЛЯРА]"
                scope_col = Color.FromArgb(22, 101, 52)

            lbl_sc = Label(
                Text=scope_text,
                Location=Point(272, 6), Size=Size(200, 20),
                Font=f_scope, ForeColor=scope_col,
                TextAlign=ContentAlignment.MiddleRight
            )
            row_pnl.Controls.Add(lbl_sc)

            # Поле ввода (ComboBox со свободным вводом текста + подсказки уже существующих значений модели)
            cb_val = ComboBox(
                Location=Point(10, 28), Size=Size(460, 24),
                Font=f_input, DropDownStyle=ComboBoxStyle.DropDown
            )
            if p_name in self.param_stats:
                val_counts = self.param_stats[p_name].get('value_counts', {})
                for existing_v, _cnt in sorted(val_counts.items(), key=lambda kv: kv[1], reverse=True)[:25]:
                    cb_val.Items.Add(existing_v)

            cb_val.Text = cur_val
            if is_ro or not exists:
                cb_val.Enabled = False
            else:
                self.input_controls[p_name] = (cb_val, cur_val)

            row_pnl.Controls.Add(cb_val)
            self.pnl_list.Controls.Add(row_pnl)
            y += 64

        self.Controls.Add(self.pnl_list)

        # --- КНОПКИ ОК / ОТМЕНА ---
        btn_y = form_h - 84
        self.btn_ok = Button(
            Text=u"ОК (Записать в модель)",
            Location=Point(232, btn_y), Size=Size(195, 36),
            Font=Font("Segoe UI", 9, FontStyle.Bold),
            BackColor=Color.FromArgb(22, 101, 52), ForeColor=Color.White,
            FlatStyle=FlatStyle.Flat
        )
        self.btn_ok.Click += self.on_ok_click
        self.Controls.Add(self.btn_ok)

        self.btn_cancel = Button(
            Text=u"Отмена",
            Location=Point(437, btn_y), Size=Size(95, 36),
            Font=Font("Segoe UI", 9, FontStyle.Regular),
            BackColor=Color.White, DialogResult=DialogResult.Cancel
        )
        self.Controls.Add(self.btn_cancel)

        self.AcceptButton = self.btn_ok
        self.CancelButton = self.btn_cancel

    def on_shown(self, sender, event):
        try:
            self.TopMost = True
            self.BringToFront()
            self.Activate()
        except:
            pass

    def on_ok_click(self, sender, event):
        changes = {}
        for p_name, (cb_ctrl, old_val) in self.input_controls.items():
            new_val = cb_ctrl.Text.strip()
            if new_val != old_val:
                changes[p_name] = new_val
        self.updated_values = changes
        self.DialogResult = DialogResult.OK
        self.Close()


# 5. НЕМОДАЛЬНЫЙ ГРАФИЧЕСКИЙ ДАШБОРД (v2.5)
# ==============================================================================

class AuditDashboardForm(Form):
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
        self.ext_event = None
        try:
            self.ext_event = ExternalEvent.Create(self.ext_handler)
        except:
            self.ext_event = None

        self.Text = u"Дашборд BIM-аудита v2.9 (Немодальный режим — окно Revit активно) — Вид: {}".format(self.view_name)
        self.Size = Size(1020, 755)
        self.StartPosition = FormStartPosition.CenterScreen
        self.FormBorderStyle = FormBorderStyle.FixedSingle
        self.MaximizeBox = False
        self.MinimizeBox = True
        self.TopMost = True
        self.BackColor = Color.FromArgb(241, 245, 249)

        # --- ВЕРХНЯЯ ПАНЕЛЬ KPI + ОБЩИЙ ПРОГРЕСС-БАР ---
        self.pnl_top = Panel(Location=Point(12, 10), Size=Size(980, 115), BackColor=Color.White)
        self.pnl_top.Paint += self.on_paint_top_kpi

        self.chk_topmost = CheckBox(
            Text=u"Поверх Revit",
            Location=Point(595, 8), Size=Size(105, 22),
            Checked=True, Font=Font("Segoe UI", 8.5, FontStyle.Bold),
            ForeColor=Color.FromArgb(30, 58, 138)
        )
        self.chk_topmost.CheckedChanged += self.on_toggle_topmost
        self.pnl_top.Controls.Add(self.chk_topmost)

        self.btn_change_params = Button(
            Text=u"⚙ Параметры / Вид",
            Location=Point(705, 5), Size=Size(130, 26),
            Font=Font("Segoe UI", 8, FontStyle.Bold),
            BackColor=Color.White, ForeColor=Color.FromArgb(51, 65, 85)
        )
        self.btn_change_params.Click += self.on_reopen_config_dialog
        self.pnl_top.Controls.Add(self.btn_change_params)

        self.btn_refresh = Button(
            Text=u"Обновить данные",
            Location=Point(842, 5), Size=Size(128, 26),
            Font=Font("Segoe UI", 8.5, FontStyle.Bold),
            BackColor=Color.FromArgb(239, 246, 255), ForeColor=Color.FromArgb(29, 78, 216),
            FlatStyle=FlatStyle.Flat
        )
        self.btn_refresh.Click += self.on_refresh_audit_from_revit
        self.pnl_top.Controls.Add(self.btn_refresh)

        self.Controls.Add(self.pnl_top)

        # --- ВКЛАДКИ ДАШБОРДА ---
        self.tabs = TabControl(Location=Point(12, 132), Size=Size(980, 490), Font=Font("Segoe UI", 9, FontStyle.Regular))

        # Вкладка 1: Карточки параметров
        self.tab_visual = TabPage(Text=u"1. Графический дашборд по параметрам")
        self.tab_visual.BackColor = Color.White
        self.pnl_bars = Panel(
            Location=Point(8, 8), Size=Size(956, 444),
            AutoScroll=True, BackColor=Color.White
        )
        self.tab_visual.Controls.Add(self.pnl_bars)
        self.tabs.TabPages.Add(self.tab_visual)

        # Вкладка 2: Сводка по категориям
        self.tab_cats = TabPage(Text=u"2. Сводка по категориям")
        self.tab_cats.BackColor = Color.White
        self.dgv_cats = self.create_styled_grid(Point(10, 10), Size(952, 440))
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
        self.dgv_elems.CellDoubleClick += self.on_element_row_double_click
        self.tab_elems.Controls.Add(self.dgv_elems)
        self.tabs.TabPages.Add(self.tab_elems)

        # Вкладка 4: ФИЛЬТР КАТЕГОРИЙ + СОХРАНЕНИЕ КОНФИГУРАЦИИ
        self.tab_cat_filter = TabPage(Text=u"4. Фильтр категорий и Конфиг")
        self.tab_cat_filter.BackColor = Color.White

        self.chk_show_zero_cats = CheckBox(
            Text=u"Показывать неактивные категории (0 элементов — серые)",
            Location=Point(12, 10), Size=Size(430, 22),
            Checked=True, Font=Font("Segoe UI", 8.5, FontStyle.Regular)
        )
        self.chk_show_zero_cats.CheckedChanged += self.on_cat_filter_ui_changed
        self.tab_cat_filter.Controls.Add(self.chk_show_zero_cats)

        self.chk_auto_recalc_cats = CheckBox(
            Text=u"Мгновенно обновлять дашборд и авто-сохранять фильтр",
            Location=Point(448, 10), Size=Size(335, 22),
            Checked=True, Font=Font("Segoe UI", 8.5, FontStyle.Bold),
            ForeColor=Color.FromArgb(22, 101, 52)
        )
        self.tab_cat_filter.Controls.Add(self.chk_auto_recalc_cats)

        lbl_cf_search = Label(Text=u"Поиск:", Location=Point(785, 12), Size=Size(48, 20))
        self.tab_cat_filter.Controls.Add(lbl_cf_search)

        self.tb_cat_search = TextBox(Location=Point(835, 9), Size=Size(127, 22))
        self.tb_cat_search.TextChanged += self.on_cat_filter_ui_changed
        self.tab_cat_filter.Controls.Add(self.tb_cat_search)

        btn_cf_std = Button(
            Text=u"По умолчанию (без редких)",
            Location=Point(12, 37), Size=Size(175, 27),
            Font=Font("Segoe UI", 8, FontStyle.Bold),
            BackColor=Color.FromArgb(239, 246, 255), ForeColor=Color.FromArgb(30, 64, 175),
            FlatStyle=FlatStyle.Flat
        )
        btn_cf_std.Click += self.on_cat_preset_standard
        self.tab_cat_filter.Controls.Add(btn_cf_std)

        btn_cf_all = Button(
            Text=u"Включить ВСЕ",
            Location=Point(192, 37), Size=Size(105, 27),
            Font=Font("Segoe UI", 8, FontStyle.Regular), BackColor=Color.White
        )
        btn_cf_all.Click += self.on_cat_preset_all_active
        self.tab_cat_filter.Controls.Add(btn_cf_all)

        btn_cf_none = Button(
            Text=u"Отключить все",
            Location=Point(302, 37), Size=Size(105, 27),
            Font=Font("Segoe UI", 8, FontStyle.Regular), BackColor=Color.White
        )
        btn_cf_none.Click += self.on_cat_preset_none
        self.tab_cat_filter.Controls.Add(btn_cf_none)

        self.btn_cf_save_cfg = Button(
            Text=u"Сохранить в профиль «{}»".format(self.cfg_mgr.get_active_profile_name()),
            Location=Point(412, 37), Size=Size(235, 27),
            Font=Font("Segoe UI", 8, FontStyle.Bold),
            BackColor=Color.FromArgb(240, 253, 244), ForeColor=Color.FromArgb(22, 101, 52),
            FlatStyle=FlatStyle.Flat
        )
        self.btn_cf_save_cfg.Click += self.on_save_cat_filter_to_active_profile
        self.tab_cat_filter.Controls.Add(self.btn_cf_save_cfg)

        btn_cf_exp_json = Button(
            Text=u"Экспорт конфига (.json)",
            Location=Point(652, 37), Size=Size(145, 27),
            Font=Font("Segoe UI", 8, FontStyle.Regular), BackColor=Color.White
        )
        btn_cf_exp_json.Click += self.on_export_config_from_dashboard
        self.tab_cat_filter.Controls.Add(btn_cf_exp_json)

        btn_cf_imp_json = Button(
            Text=u"Импорт (.json)",
            Location=Point(802, 37), Size=Size(160, 27),
            Font=Font("Segoe UI", 8, FontStyle.Regular), BackColor=Color.White
        )
        btn_cf_imp_json.Click += self.on_import_config_from_dashboard
        self.tab_cat_filter.Controls.Add(btn_cf_imp_json)

        self.dgv_cat_filter = DataGridView(Location=Point(10, 70), Size=Size(952, 382))
        self.dgv_cat_filter.AllowUserToAddRows = False
        self.dgv_cat_filter.AllowUserToDeleteRows = False
        self.dgv_cat_filter.ReadOnly = True
        self.dgv_cat_filter.MultiSelect = True
        self.dgv_cat_filter.SelectionMode = DataGridViewSelectionMode.FullRowSelect
        self.dgv_cat_filter.AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.Fill
        self.dgv_cat_filter.BackgroundColor = Color.White
        self.dgv_cat_filter.RowHeadersVisible = False
        self.dgv_cat_filter.Font = Font("Segoe UI", 8.5, FontStyle.Regular)

        col_chk = DataGridViewCheckBoxColumn()
        col_chk.Name = "Checked"
        col_chk.HeaderText = u"Вкл"
        col_chk.ReadOnly = True
        col_chk.FillWeight = 8
        self.dgv_cat_filter.Columns.Add(col_chk)

        col_cname = DataGridViewTextBoxColumn()
        col_cname.Name = "CatName"
        col_cname.HeaderText = u"Категория Revit (вкл. скрытые в В/Г)"
        col_cname.ReadOnly = True
        col_cname.FillWeight = 48
        self.dgv_cat_filter.Columns.Add(col_cname)

        col_cnt = DataGridViewTextBoxColumn()
        col_cnt.Name = "ElemCount"
        col_cnt.HeaderText = u"Элементов на виде"
        col_cnt.ReadOnly = True
        col_cnt.FillWeight = 18
        self.dgv_cat_filter.Columns.Add(col_cnt)

        col_ctype = DataGridViewTextBoxColumn()
        col_ctype.Name = "CatStatus"
        col_ctype.HeaderText = u"Статус / Тип категории"
        col_ctype.ReadOnly = True
        col_ctype.FillWeight = 26
        self.dgv_cat_filter.Columns.Add(col_ctype)

        self.dgv_cat_filter.SelectionChanged += self.on_cat_filter_selection_changed
        self.dgv_cat_filter.CellMouseClick += self.on_cat_filter_cell_mouse_click
        self.dgv_cat_filter.KeyDown += self.on_cat_filter_key_down
        self.tab_cat_filter.Controls.Add(self.dgv_cat_filter)
        self.tabs.TabPages.Add(self.tab_cat_filter)

        self.Controls.Add(self.tabs)

        # --- СТРОКА ЖИВОГО СТАТУСА ---
        self.lbl_status = Label(
            Text=u"✓ Профиль «{}» активен. Чтобы добавить другие параметры из каталога, нажмите «⚙ Параметры / Вид» вверху!".format(
                self.cfg_mgr.get_active_profile_name()
            ),
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

        self.populate_category_filter_grid()
        self.populate_param_bars()
        self.populate_categories_grid()
        self.populate_elements_grid()

    def set_status_message(self, text_msg, color_obj):
        try:
            self.lbl_status.Text = text_msg
            self.lbl_status.ForeColor = color_obj
        except:
            pass

    def on_toggle_topmost(self, sender, event):
        self.TopMost = self.chk_topmost.Checked

    def on_reopen_config_dialog(self, sender, event):
        """Открывает окно выбора вида и параметров СТРОГО ПОВЕРХ дашборда, а после закрытия возвращает фокус дашборду."""
        was_topmost = self.TopMost
        try:
            self.auto_persist_category_states()
            # Временно снимаем TopMost с дашборда, чтобы окно настроек гарантированно было выше по приоритету
            self.TopMost = False
            cfg_dlg = ParameterAuditConfigForm(
                self.doc, self.cfg_mgr,
                current_view_override=self.view_elem,
                current_params_override=self.param_names
            )
            cfg_dlg.TopMost = True
            dlg_res = cfg_dlg.ShowDialog(self)

            if dlg_res == DialogResult.OK:
                self.view_elem = cfg_dlg.selected_view
                self.view_name = ElementName(self.view_elem)
                self.param_names = cfg_dlg.selected_params
                saved_cats = cfg_dlg.selected_category_states
                cfg_dlg.Dispose()

                self.Text = u"Дашборд BIM-аудита v2.9 (Немодальный режим — окно Revit активно) — Вид: {}".format(self.view_name)
                self.btn_cf_save_cfg.Text = u"Сохранить в профиль «{}»".format(self.cfg_mgr.get_active_profile_name())
                self.raw_records, self.categories_catalog = scan_raw_view_elements(
                    self.doc, self.view_elem, self.param_names, saved_cats
                )
                self.populate_category_filter_grid()
                self.recalculate_from_cached_records()
                self.set_status_message(
                    u"✓ Настройки обновлены: вид «{}», параметров — {}.".format(self.view_name, len(self.param_names)),
                    Color.FromArgb(22, 101, 52)
                )
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

    def get_current_active_category_states_dict(self):
        res = {}
        for c_name, info in self.categories_catalog.items():
            if info['count_on_view'] > 0:
                res[c_name] = bool(info['enabled'])
        return res

    def auto_persist_category_states(self):
        try:
            cat_states = self.get_current_active_category_states_dict()
            self.cfg_mgr.update_last_session(
                params_list=self.param_names,
                category_states_dict=cat_states
            )
        except:
            pass

    def get_enabled_categories_set(self):
        return set([
            c_name for c_name, info in self.categories_catalog.items()
            if info['enabled'] and info['count_on_view'] > 0
        ])

    def recalculate_from_cached_records(self):
        enabled_set = self.get_enabled_categories_set()
        self.audit_data = aggregate_audit_from_records(self.raw_records, self.param_names, enabled_set)
        self.btn_sel_failed.Text = u"Выделить ВСЕ проблемные ({})".format(len(self.audit_data['failed_element_ids']))
        self.pnl_top.Invalidate()
        self.populate_param_bars()
        self.populate_categories_grid()
        self.populate_elements_grid()
        self.auto_persist_category_states()

    def on_refresh_audit_from_revit(self, sender, event):
        try:
            old_enabled_map = {c_name: info['enabled'] for c_name, info in self.categories_catalog.items() if info['count_on_view'] > 0}
            new_records, new_catalog = scan_raw_view_elements(self.doc, self.view_elem, self.param_names, old_enabled_map)

            self.raw_records = new_records
            self.categories_catalog = new_catalog
            self.populate_category_filter_grid()
            self.recalculate_from_cached_records()

            self.set_status_message(
                u"✓ Данные из модели Revit обновлены! Общий индекс заполненности: {:.1f}% (проблемных элементов: {}).".format(
                    self.audit_data['overall_pct'], len(self.audit_data['failed_element_ids'])
                ),
                Color.FromArgb(22, 101, 52)
            )
        except Exception as ex:
            self.set_status_message(u"Ошибка при обновлении: " + unicode(ex), Color.FromArgb(185, 28, 28))

    def on_close_click(self, sender, event):
        self.auto_persist_category_states()
        self.Close()

    # ==========================================================================
    # МЕТОДЫ СОХРАНЕНИЯ / ИМПОРТА КОНФИГА ПРЯМО ИЗ ДАШБОРДА (ВКЛАДКА 4)
    # ==========================================================================

    def on_save_cat_filter_to_active_profile(self, sender, event):
        cat_states = self.get_current_active_category_states_dict()
        act_prof = self.cfg_mgr.get_active_profile_name()
        ok = self.cfg_mgr.update_last_session(
            params_list=self.param_names,
            category_states_dict=cat_states,
            also_update_active_profile=True
        )
        if ok:
            self.set_status_message(
                u"✓ Настройки фильтра категорий и параметров сохранены в профиль «{}»!".format(act_prof),
                Color.FromArgb(22, 101, 52)
            )

    def on_export_config_from_dashboard(self, sender, event):
        cat_states = self.get_current_active_category_states_dict()
        act_prof = self.cfg_mgr.get_active_profile_name()
        sfd = SaveFileDialog()
        sfd.Title = u"Экспортировать конфигурацию (параметры + фильтр категорий) в файл JSON"
        sfd.Filter = "JSON Config (*.json)|*.json"
        sfd.FileName = u"Конфиг_аудита_{}.json".format(act_prof.replace(u" ", u"_").replace(u":", u"_"))
        if sfd.ShowDialog() == DialogResult.OK:
            ok = self.cfg_mgr.export_single_config_to_file(
                sfd.FileName, act_prof, self.param_names, cat_states
            )
            if ok:
                self.set_status_message(
                    u"✓ Конфигурация успешно экспортирована в файл: " + sfd.FileName,
                    Color.FromArgb(22, 101, 52)
                )

    def on_import_config_from_dashboard(self, sender, event):
        ofd = OpenFileDialog()
        ofd.Title = u"Импортировать конфигурацию из файла JSON"
        ofd.Filter = "JSON Config (*.json)|*.json"
        if ofd.ShowDialog() == DialogResult.OK:
            imported = self.cfg_mgr.import_config_from_file(ofd.FileName)
            if imported:
                new_params = imported.get(u"params", self.param_names)
                cat_states = imported.get(u"category_states", {})
                self.param_names = new_params
                self.btn_cf_save_cfg.Text = u"Сохранить в профиль «{}»".format(self.cfg_mgr.get_active_profile_name())
                self.raw_records, self.categories_catalog = scan_raw_view_elements(
                    self.doc, self.view_elem, self.param_names, cat_states
                )
                self.populate_category_filter_grid()
                self.recalculate_from_cached_records()
                self.set_status_message(
                    u"✓ Импортирован конфиг «{}»: параметров — {}, фильтр категорий обновлен!".format(
                        imported.get(u"profile_name", u"JSON"), len(self.param_names)
                    ),
                    Color.FromArgb(22, 101, 52)
                )
            else:
                self.set_status_message(u"Ошибка чтения файла конфигурации JSON.", Color.FromArgb(185, 28, 28))

    # ==========================================================================
    # МЕТОДЫ ВКЛАДКИ 4 («ФИЛЬТР КАТЕГОРИЙ» — СРАБАТЫВАНИЕ ТОЛЬКО ПО САМОМУ ЧЕКБОКСУ)
    # ==========================================================================

    def apply_row_visual_style(self, row_obj, info):
        cnt = info['count_on_view']
        is_rare = info['is_rare']
        is_enabled = info['enabled']

        if cnt == 0:
            row_obj.DefaultCellStyle.BackColor = Color.FromArgb(248, 250, 252)
            row_obj.DefaultCellStyle.ForeColor = Color.FromArgb(160, 174, 192)
        elif is_enabled:
            row_obj.DefaultCellStyle.BackColor = Color.FromArgb(240, 253, 244)
            row_obj.DefaultCellStyle.ForeColor = Color.FromArgb(15, 23, 42)
        elif is_rare:
            row_obj.DefaultCellStyle.BackColor = Color.FromArgb(255, 251, 235)
            row_obj.DefaultCellStyle.ForeColor = Color.FromArgb(146, 64, 14)
        else:
            row_obj.DefaultCellStyle.BackColor = Color.FromArgb(241, 245, 249)
            row_obj.DefaultCellStyle.ForeColor = Color.FromArgb(100, 116, 139)

    def populate_category_filter_grid(self):
        self._is_populating_cat_filter = True
        self.dgv_cat_filter.Rows.Clear()
        self.last_checkbox_clicked_row = -1
        self._prev_selected_cat_rows = []
        self._curr_selected_cat_rows = []

        show_zero = self.chk_show_zero_cats.Checked
        q = self.tb_cat_search.Text.strip().lower()

        all_items = list(self.categories_catalog.values())
        all_items.sort(key=lambda x: (0 if x['count_on_view'] > 0 else 1, x['name'].lower()))

        for info in all_items:
            c_name = info['name']
            cnt = info['count_on_view']
            is_rare = info['is_rare']
            is_enabled = info['enabled']

            if cnt == 0 and not show_zero:
                continue
            if q and (q not in c_name.lower()):
                continue

            if cnt == 0:
                status_str = u"Нет на виде (Неактивна)"
            elif is_rare:
                status_str = u"Редкая / Служебная (откл. по умолч.)"
            else:
                status_str = u"Основная категория модели"

            r_idx = self.dgv_cat_filter.Rows.Add(bool(is_enabled and cnt > 0), c_name, unicode(cnt), status_str)
            row_obj = self.dgv_cat_filter.Rows[r_idx]
            self.apply_row_visual_style(row_obj, info)

        self._is_populating_cat_filter = False

    def on_cat_filter_ui_changed(self, sender, event):
        self.populate_category_filter_grid()

    def on_cat_filter_selection_changed(self, sender, event):
        if self._is_populating_cat_filter:
            return
        self._prev_selected_cat_rows = list(self._curr_selected_cat_rows)
        self._curr_selected_cat_rows = sorted([r.Index for r in self.dgv_cat_filter.SelectedRows])

    def set_rows_checked_batch(self, row_indices, target_state):
        changed_count = 0
        for r_idx in row_indices:
            if r_idx < 0 or r_idx >= self.dgv_cat_filter.Rows.Count:
                continue
            row_obj = self.dgv_cat_filter.Rows[r_idx]
            c_name = row_obj.Cells[1].Value
            info = self.categories_catalog.get(c_name)
            if not info or info['count_on_view'] == 0:
                continue

            info['enabled'] = bool(target_state)
            row_obj.Cells[0].Value = bool(target_state)
            self.apply_row_visual_style(row_obj, info)
            changed_count += 1

        self.dgv_cat_filter.Invalidate()

        if changed_count > 0:
            if self.chk_auto_recalc_cats.Checked:
                self.recalculate_from_cached_records()
                action_str = u"Включено" if target_state else u"Отключено"
                self.set_status_message(
                    u"✓ {} категорий: {} шт. Дашборд пересчитан и фильтр сохранен (элементов в расчете: {}).".format(
                        action_str, changed_count, self.audit_data['total_elements']
                    ),
                    Color.FromArgb(30, 64, 175)
                )
            else:
                self.auto_persist_category_states()
                self.set_status_message(
                    u"Изменено категорий: {} шт. Нажмите «Обновить данные» вверху для пересчета.".format(changed_count),
                    Color.FromArgb(180, 83, 9)
                )

    def is_click_strictly_on_checkbox_glyph(self, row_idx, mouse_x, mouse_y):
        try:
            cell_rect = self.dgv_cat_filter.GetCellDisplayRectangle(0, row_idx, False)
            center_x = cell_rect.Width / 2.0
            center_y = cell_rect.Height / 2.0
            return (abs(mouse_x - center_x) <= 9.0) and (abs(mouse_y - center_y) <= 9.0)
        except:
            return False

    def on_cat_filter_cell_mouse_click(self, sender, event):
        if self._is_populating_cat_filter:
            return
        if event.Button != MouseButtons.Left or event.RowIndex < 0:
            return

        if event.ColumnIndex != 0:
            return
        if not self.is_click_strictly_on_checkbox_glyph(event.RowIndex, event.X, event.Y):
            return

        clicked_row = event.RowIndex
        row_obj = self.dgv_cat_filter.Rows[clicked_row]
        c_name = row_obj.Cells[1].Value
        info = self.categories_catalog.get(c_name)

        if not info or info['count_on_view'] == 0:
            self.set_status_message(
                u"Категория «{}» неактивна (на выбранном виде 0 элементов этой категории).".format(c_name),
                Color.FromArgb(100, 116, 139)
            )
            return

        current_val = bool(row_obj.Cells[0].Value)
        new_state = not current_val
        is_shift = ((Control.ModifierKeys & Keys.Shift) == Keys.Shift)

        if len(self._prev_selected_cat_rows) > 1 and (clicked_row in self._prev_selected_cat_rows):
            target_rows = list(self._prev_selected_cat_rows)
            self.set_rows_checked_batch(target_rows, new_state)
            self._is_populating_cat_filter = True
            self.dgv_cat_filter.ClearSelection()
            for r_i in target_rows:
                if 0 <= r_i < self.dgv_cat_filter.Rows.Count:
                    self.dgv_cat_filter.Rows[r_i].Selected = True
            self._is_populating_cat_filter = False
            self._curr_selected_cat_rows = list(target_rows)
            self.last_checkbox_clicked_row = clicked_row
            return

        if is_shift and self.last_checkbox_clicked_row != -1:
            start_r = min(self.last_checkbox_clicked_row, clicked_row)
            end_r = max(self.last_checkbox_clicked_row, clicked_row)
            target_rows = list(range(start_r, end_r + 1))
            self.set_rows_checked_batch(target_rows, new_state)
            self._is_populating_cat_filter = True
            self.dgv_cat_filter.ClearSelection()
            for r_i in target_rows:
                self.dgv_cat_filter.Rows[r_i].Selected = True
            self._is_populating_cat_filter = False
            self._curr_selected_cat_rows = list(target_rows)
            self.last_checkbox_clicked_row = clicked_row
            return

        self.set_rows_checked_batch([clicked_row], new_state)
        self.last_checkbox_clicked_row = clicked_row

    def on_cat_filter_key_down(self, sender, event):
        if event.KeyCode == Keys.Space:
            sel_indices = sorted([r.Index for r in self.dgv_cat_filter.SelectedRows])
            if not sel_indices:
                return
            any_unchecked = False
            for r_idx in sel_indices:
                r_obj = self.dgv_cat_filter.Rows[r_idx]
                c_name = r_obj.Cells[1].Value
                info = self.categories_catalog.get(c_name)
                if info and info['count_on_view'] > 0 and not info['enabled']:
                    any_unchecked = True
                    break
            self.set_rows_checked_batch(sel_indices, any_unchecked)
            event.Handled = True

    def on_cat_preset_standard(self, sender, event):
        for info in self.categories_catalog.values():
            info['enabled'] = (info['count_on_view'] > 0 and not info['is_rare'])
        self.populate_category_filter_grid()
        self.recalculate_from_cached_records()
        self.set_status_message(
            u"✓ Применен и сохранен фильтр по умолчанию: редкие и служебные категории отключены.",
            Color.FromArgb(22, 101, 52)
        )

    def on_cat_preset_all_active(self, sender, event):
        for info in self.categories_catalog.values():
            info['enabled'] = (info['count_on_view'] > 0)
        self.populate_category_filter_grid()
        self.recalculate_from_cached_records()
        self.set_status_message(
            u"✓ Включены все категории, присутствующие на виде (включая редкие/служебные).",
            Color.FromArgb(30, 64, 175)
        )

    def on_cat_preset_none(self, sender, event):
        for info in self.categories_catalog.values():
            info['enabled'] = False
        self.populate_category_filter_grid()
        self.recalculate_from_cached_records()
        self.set_status_message(
            u"Все категории отключены. Отметьте нужные категории галочками.",
            Color.FromArgb(180, 83, 9)
        )

    # ==========================================================================
    # МЕТОДЫ ОСТАЛЬНЫХ ВКЛАДОК ДАШБОРДА
    # ==========================================================================

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

        f_title = Font("Segoe UI", 10, FontStyle.Bold)
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

    def populate_param_bars(self):
        self.pnl_bars.SuspendLayout()
        self.pnl_bars.AutoScrollPosition = Point(0, 0)
        self.pnl_bars.Controls.Clear()

        p_stats = self.audit_data['param_stats']
        f_param = Font("Segoe UI", 10, FontStyle.Bold)
        f_pct = Font("Segoe UI", 9, FontStyle.Bold)
        f_meta = Font("Segoe UI", 8.5, FontStyle.Regular)
        f_btn = Font("Segoe UI", 8, FontStyle.Bold)

        y = 8
        card_width = 922
        bar_max_w = 894

        for idx, p_name in enumerate(self.param_names):
            st = p_stats[p_name]
            pct = st['pct']
            filled = st['filled']
            total = st['total']
            missing_cnt = total - filled
            scopes = u"/".join(sorted(st['scopes'])) if st['scopes'] else u"Не найден"
            uniq_cnt = len(st['value_counts'])
            status_col = self.get_status_color(pct)

            sorted_vals = sorted(st['value_counts'].items(), key=lambda kv: kv[1], reverse=True)[:5]
            top_vals_str = u", ".join([u"{} ({} шт.)".format(k, v) for k, v in sorted_vals])
            if not top_vals_str:
                top_vals_str = u"Нет заполненных значений"

            card = Panel(
                Location=Point(8, y),
                Size=Size(card_width, 92),
                BackColor=Color.FromArgb(248, 250, 252),
                BorderStyle=BorderStyle.FixedSingle
            )

            lbl_name = Label(
                Text=u"{}. {}   [{}]".format(idx + 1, p_name, scopes),
                Location=Point(12, 8),
                Size=Size(360, 22),
                Font=f_param,
                ForeColor=Color.FromArgb(15, 23, 42)
            )
            card.Controls.Add(lbl_name)

            lbl_stat = Label(
                Text=u"Заполнено: {} из {} ({:.1f}%)  |  Уникальных значений: {}".format(filled, total, pct, uniq_cnt),
                Location=Point(375, 9),
                Size=Size(375, 20),
                Font=f_pct,
                ForeColor=status_col
            )
            card.Controls.Add(lbl_stat)

            if missing_cnt > 0:
                btn_sel_param = Button(
                    Text=u"Выделить пустые ({})".format(missing_cnt),
                    Location=Point(756, 5),
                    Size=Size(152, 26),
                    Font=f_btn,
                    BackColor=Color.FromArgb(254, 242, 242),
                    ForeColor=Color.FromArgb(185, 28, 28),
                    FlatStyle=FlatStyle.Flat
                )
                btn_sel_param.Tag = p_name
                btn_sel_param.Click += self.on_select_missing_for_param
                card.Controls.Add(btn_sel_param)
            else:
                lbl_ok = Label(
                    Text=u"✓ Заполнен на 100%",
                    Location=Point(760, 9),
                    Size=Size(145, 20),
                    Font=f_btn,
                    ForeColor=Color.FromArgb(22, 163, 74),
                    TextAlign=ContentAlignment.MiddleRight
                )
                card.Controls.Add(lbl_ok)

            pnl_bar_bg = Panel(
                Location=Point(12, 36),
                Size=Size(bar_max_w, 20),
                BackColor=Color.FromArgb(226, 232, 240),
                BorderStyle=BorderStyle.FixedSingle
            )
            fill_w = int(bar_max_w * (pct / 100.0))
            if fill_w > 0:
                pnl_bar_fill = Panel(
                    Location=Point(0, 0),
                    Size=Size(fill_w, 18),
                    BackColor=status_col
                )
                pnl_bar_bg.Controls.Add(pnl_bar_fill)
            card.Controls.Add(pnl_bar_bg)

            lbl_examples = Label(
                Text=u"Примеры значений: " + top_vals_str,
                Location=Point(12, 62),
                Size=Size(bar_max_w, 20),
                Font=f_meta,
                ForeColor=Color.FromArgb(71, 85, 105),
                AutoEllipsis=True
            )
            card.Controls.Add(lbl_examples)

            self.pnl_bars.Controls.Add(card)
            y += 100

        self.pnl_bars.ResumeLayout()

    def on_select_missing_for_param(self, sender, event):
        p_name = sender.Tag
        missing_ids = self.audit_data['param_stats'][p_name]['missing_ids']
        if not missing_ids:
            return
        ids_list = List[ElementId]()
        for eid in missing_ids:
            ids_list.Add(eid)
        self.select_ids_non_blocking(ids_list, custom_param_name=p_name)

    def get_param_column_header(self, p_name):
        """Формирует заголовок столбца с типом параметра в шапке: напр. MR_Этаж [Э] или MR_Код [Т]."""
        st = self.audit_data['param_stats'].get(p_name, {})
        scopes = st.get('scopes', set())
        short_tags = []
        if u"Экземпляр" in scopes:
            short_tags.append(u"Э")
        if u"Тип" in scopes:
            short_tags.append(u"Т")
        if short_tags:
            return u"{} [{}]".format(p_name, u"/".join(short_tags))
        return p_name

    def populate_categories_grid(self):
        self.dgv_cats.Columns.Clear()
        self.dgv_cats.Rows.Clear()

        self.dgv_cats.Columns.Add("CatName", u"Категория")
        self.dgv_cats.Columns.Add("TotalEl", u"Элементов (шт.)")
        self.dgv_cats.Columns.Add("ReadyPct", u"Общий %")

        for p_name in self.param_names:
            self.dgv_cats.Columns.Add("P_" + p_name, self.get_param_column_header(p_name))

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
            self.dgv_elems.Columns.Add("Val_" + p_name, self.get_param_column_header(p_name))

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


    def on_element_row_double_click(self, sender, event):
        """Открывает карточку редактирования параметров элемента при двойном клике по строке ведомости."""
        if event.RowIndex < 0:
            return
        try:
            id_str = self.dgv_elems.Rows[event.RowIndex].Cells[0].Value
            el_id_int = int(id_str)
            target_el = self.doc.GetElement(ElementId(el_id_int))
            if target_el is None:
                self.set_status_message(u"Элемент ID {} не найден в модели.".format(el_id_int), Color.FromArgb(185, 28, 28))
                return

            # Выделяем элемент в Revit, чтобы проектировщик видел его
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
                # Пробуем записать через прямую транзакцию, а если контекст немодальный — через ExternalEvent
                wrote_directly = False
                try:
                    t = Transaction(self.doc, u"BIM Аудит: Запись значений параметров")
                    t.Start()
                    changed_cnt = 0
                    errors = []
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
                    self.set_status_message(
                        u"Запрос на запись параметров для ID {} отправлен (переведите курсор в окно Revit)...".format(el_id_int),
                        Color.FromArgb(30, 64, 175)
                    )
        except Exception as ex:
            self.set_status_message(u"Ошибка открытия карточки элемента: " + unicode(ex), Color.FromArgb(185, 28, 28))

    def on_element_params_written(self, el_id_int, changed_cnt, errors):
        """Обновляет кэш параметров после записи в модель и мгновенно перерисовывает дашборд."""
        try:
            target_el = self.doc.GetElement(ElementId(int(el_id_int)))
            target_type_id = target_el.GetTypeId() if target_el else None

            # Перечитываем параметры у измененного элемента (и у элементов того же типа, если менялся параметр Типа)
            for rec in self.raw_records:
                el_obj = rec['element']
                if rec['id_int'] == int(el_id_int) or (target_type_id and el_obj.GetTypeId() == target_type_id):
                    for p_name in self.param_names:
                        rec['param_results'][p_name] = resolve_parameter_value(self.doc, el_obj, p_name)

            self.recalculate_from_cached_records()

            if errors:
                self.set_status_message(
                    u"Записано параметров: {}. Ошибки: {}".format(changed_cnt, u"; ".join(errors)),
                    Color.FromArgb(180, 83, 9)
                )
            else:
                self.set_status_message(
                    u"✓ Успешно обновлено параметров у элемента ID {}: {} шт.! Дашборд пересчитан.".format(el_id_int, changed_cnt),
                    Color.FromArgb(22, 101, 52)
                )
        except Exception as ex:
            self.set_status_message(u"Ошибка обновления после записи: " + unicode(ex), Color.FromArgb(185, 28, 28))

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
            if custom_param_name:
                self.set_status_message(
                    u"✓ Выделено {} элементов с пустым параметром «{}». Можете сразу заполнить его в Свойствах Revit!".format(
                        ids_list.Count, custom_param_name
                    ),
                    Color.FromArgb(22, 101, 52)
                )
            else:
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
                    headers = [u"ID элемента", u"Категория", u"Семейство и Тип", u"Статус", u"Заполнено параметров"] + [self.get_param_column_header(p) for p in self.param_names]
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
# 6. ТОЧКА ВХОДА СКРИПТА
# ==============================================================================

try:
    cfg_manager = AuditConfigManager()
    config_form = ParameterAuditConfigForm(doc, cfg_manager)
    res = config_form.ShowDialog()

    if res != DialogResult.OK:
        OUT = [u"Операция отменена пользователем."]
    else:
        target_view = config_form.selected_view
        target_params = config_form.selected_params
        saved_cat_states = config_form.selected_category_states
        view_title = ElementName(target_view)
        config_form.Dispose()

        raw_records, categories_catalog = scan_raw_view_elements(
            doc, target_view, target_params, saved_cat_states
        )

        if len(raw_records) == 0:
            TaskDialog.Show(
                u"Нет элементов",
                u"На выбранном виде «{}» не найдено элементов для анализа.".format(view_title)
            )
            OUT = [u"На виде '{}' не найдено элементов.".format(view_title)]
        else:
            enabled_cats_default = set([
                c_name for c_name, info in categories_catalog.items()
                if info['enabled'] and info['count_on_view'] > 0
            ])
            if not enabled_cats_default:
                for info in categories_catalog.values():
                    if info['count_on_view'] > 0:
                        info['enabled'] = True
                        enabled_cats_default.add(info['name'])

            audit_result = aggregate_audit_from_records(raw_records, target_params, enabled_cats_default)

            dash_form = AuditDashboardForm(
                doc, uidoc, cfg_manager, target_view, target_params,
                raw_records, categories_catalog, audit_result
            )
            dash_form.Show()

            summary_report = []
            summary_report.append(u"=== СВОДНЫЙ ОТЧЕТ АУДИТА ПАРАМЕТРОВ ===")
            summary_report.append(u"Файл конфигурации: {}".format(cfg_manager.config_path))
            summary_report.append(u"Активный профиль: {}".format(cfg_manager.get_active_profile_name()))
            summary_report.append(u"Вид / Спецификация: {}".format(view_title))
            summary_report.append(u"Проверено элементов (с учетом фильтра категорий): {}".format(audit_result['total_elements']))
            if audit_result['total_elements'] > 0:
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
