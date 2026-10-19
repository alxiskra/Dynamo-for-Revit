# -*- coding: utf-8 -*-
"""
Dynamo Python Node (Revit 2020 / 2022 / 2023+) — Минималистичная студия AI-рендера 3D-видов (v3.0)
через Chutes.ai (Qwen-Image-Edit-2511, Qwen-Image-2512, z-image-turbo, imageclassic и др.)
и совместимые API.

Полная совместимость:
  - Revit 2020 / 2021 (Dynamo 2.x, IronPython 2.7, .NET Framework 4.7.2 / 4.8)
  - Revit 2022+       (Dynamo 2.10+, IronPython 2.7 и CPython 3 / PythonNet)

Изменения в версии 3.0:
  - Убрана вся лишняя искусственная обработка картинок и автогенерация «Скрытой линии» в коде.
  - Универсальная архитектура 3 входных окон (Кадр 1, Кадр 2, Кадр 3) + 4-е окно результата (сетка 2x2):
    теперь для КАЖДОГО из 3 входных слотов пользователь может самостоятельно задать:
      • либо любой настроенный 3D/2D-вид напрямую из проекта Revit (выпадающий список с поиском);
      • либо путь к любому файлу изображения на диске (кнопка «Файл...»).
  - Любую комбинацию из 1, 2 или 3 активных кадров (отмеченных галочками) можно отправить в модель
    редактирования (image_b64s) без искажения исходных картинок и промпта.
  - Сохранены все удобства интерфейса: растягиваемое немодальное окно (параллельная работа с Revit),
    живой поиск видов, полноразмерный просмотр по клику на любое из 4 превью, сравнение «До / После»,
    изумрудная кнопка «START | НАЧАТЬ» и кнопка «EXIT | ВЫХОД» внизу справа.

Необязательные входы нода Dynamo (все параметры можно задать прямо в UI):
    IN[0] (str)  : API Key по умолчанию (сохраняется в профиле UI)
    IN[1] (var)  : Кадр 1 по умолчанию (3D-вид из Dynamo, имя вида или путь к файлу)
    IN[2] (str)  : Промпт по умолчанию
    IN[3] (str)  : Base URL по умолчанию ("https://api.chutes.ai")
    IN[4] (str)  : Папка сохранения рендеров (Рабочий стол/Chutes_Renders)
    IN[5] (int)  : Макс. размер стороны в пикселях (1024)
    IN[6] (int)  : Шаги генерации steps (4)
    IN[7] (var)  : Кадр 2 по умолчанию (необязательно: вид Revit, имя вида или путь к файлу)
    IN[8] (var)  : Кадр 3 по умолчанию (необязательно: вид Revit, имя вида или путь к файлу)
"""

import sys
import os
import time
import json
import base64
import ctypes
import clr

clr.AddReference("System")
clr.AddReference("System.Net")
clr.AddReference("System.Drawing")
clr.AddReference("System.Windows.Forms")
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("RevitServices")

from System import AppDomain, Enum, Convert, Environment, Array, Byte, IntPtr, EventHandler
from System.Collections.Generic import List
from System.Net import (
    ServicePointManager,
    SecurityProtocolType,
    HttpWebRequest,
    WebException,
)
from System.IO import StreamReader, MemoryStream, File, Directory, Path
from System.Text import Encoding
from System.Threading import Thread, ThreadStart
from System.Drawing import (
    Image,
    Bitmap,
    Size,
    Point,
    Font,
    FontStyle,
    Color,
    ContentAlignment,
)
from System.Windows.Forms import (
    Application,
    Form,
    Panel,
    PictureBox,
    PictureBoxSizeMode,
    Label,
    Button,
    TextBox,
    ComboBox,
    ComboBoxStyle,
    ListBox,
    CheckBox,
    NumericUpDown,
    ProgressBar,
    ProgressBarStyle,
    FormBorderStyle,
    FormStartPosition,
    FlatStyle,
    BorderStyle,
    ScrollBars,
    DialogResult,
    MessageBox,
    MessageBoxButtons,
    MessageBoxIcon,
    OpenFileDialog,
    FolderBrowserDialog,
    Cursors,
    ToolTip,
)

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    View,
    View3D,
    ViewType,
    ImageExportOptions,
    ExportRange,
    FitDirectionType,
    ImageFileType,
    ImageResolution,
    ZoomFitType,
    ElementId,
)
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent
from Autodesk.Revit.UI.Events import IdlingEventArgs
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager


# ==============================================================================
# 1. СОВМЕСТИМОСТЬ IRONPYTHON 2.7 (REVIT 2020/2022) И CPYTHON 3 (REVIT 2022+)
# ==============================================================================

try:
    STRING_TYPES = (str, unicode)

    def u_str(val):
        if val is None:
            return u""
        if isinstance(val, unicode):
            return val
        try:
            return unicode(val)
        except Exception:
            try:
                return unicode(str(val), "utf-8", "ignore")
            except Exception:
                return u""
except NameError:
    STRING_TYPES = (str,)

    def u_str(val):
        return "" if val is None else str(val)


def get_element_id_int(el_id):
    """Безопасное получение числового ID элемента для Revit 2020..2025."""
    if el_id is None:
        return -1
    try:
        return int(el_id.IntegerValue)
    except Exception:
        try:
            return int(el_id.Value)
        except Exception:
            return -1

# Принудительно включаем TLS 1.2 / 1.3
try:
    ServicePointManager.SecurityProtocol = Enum.ToObject(
        SecurityProtocolType, 3072 | 768 | 192
    )
    try:
        tls12 = int(SecurityProtocolType.Tls12)
        tls13 = int(getattr(SecurityProtocolType, "Tls13", SecurityProtocolType.Tls12))
        ServicePointManager.SecurityProtocol = Enum.ToObject(
            SecurityProtocolType, tls12 | tls13
        )
    except Exception:
        pass
except Exception:
    pass

ServicePointManager.Expect100Continue = False
ServicePointManager.DefaultConnectionLimit = 20


def get_input(index, default_val=None):
    """Безопасное чтение входных портов Dynamo."""
    try:
        if "IN" in globals() and len(IN) > index and IN[index] is not None:
            val = IN[index]
            if isinstance(val, STRING_TYPES):
                val_clean = u_str(val).strip()
                return val_clean if val_clean != u"" else default_val
            return val
    except Exception:
        pass
    return default_val


def file_to_base64_str(file_path):
    """Кросс-версионное чтение файла в Base64 строку (IronPython 2.7 + CPython 3)."""
    try:
        raw_bytes = File.ReadAllBytes(file_path)
        return u_str(Convert.ToBase64String(raw_bytes))
    except Exception:
        with open(file_path, "rb") as f:
            raw = f.read()
        b64 = base64.b64encode(raw)
        if not isinstance(b64, str):
            b64 = b64.decode("ascii")
        return u_str(b64)


def write_bytes_to_file(file_path, byte_data):
    """Безопасная запись массива Byte[] или Python bytes в файл."""
    try:
        File.WriteAllBytes(file_path, byte_data)
    except Exception:
        with open(file_path, "wb") as f:
            f.write(bytes(bytearray(byte_data)))


def read_stream_to_bytes(stream):
    """Безопасное чтение потока .NET в массив Byte[] для IronPython 2.7 и CPython 3."""
    mem = MemoryStream()
    buf = Array.CreateInstance(Byte, 8192)
    while True:
        read_count = stream.Read(buf, 0, buf.Length)
        if read_count <= 0:
            break
        mem.Write(buf, 0, read_count)
    data = mem.ToArray()
    mem.Close()
    return data


def load_image_unlocked(file_path):
    """Загружает System.Drawing.Image в память без блокировки файла на диске."""
    if not file_path or not File.Exists(file_path):
        return None
    raw_bytes = File.ReadAllBytes(file_path)
    ms = MemoryStream(raw_bytes)
    img = Image.FromStream(ms)
    bmp = Bitmap(img)
    img.Dispose()
    ms.Close()
    return bmp


# ==============================================================================
# 2. МОСТ К REVIT API ДЛЯ НЕМОДАЛЬНОГО ОКНА (РАБОТА ПАРАЛЛЕЛЬНО С REVIT)
# ==============================================================================


def wake_revit_main_window(uiapp):
    """Отправляет пустое сообщение окну Revit, чтобы мгновенно разбудить очередь ExternalEvent/Idling."""
    try:
        hwnd = IntPtr.Zero
        try:
            hwnd = uiapp.MainWindowHandle
        except Exception:
            pass
        h_int = int(hwnd.ToInt64()) if hwnd != IntPtr.Zero else 0
        if h_int != 0:
            ctypes.windll.user32.PostMessageW(h_int, 0x0000, 0, 0)
    except Exception:
        pass


class RevitApiInvoker(object):
    """Позволяет вызывать методы Revit API из немодального окна form.Show()."""
    def __init__(self, uiapp):
        self.uiapp = uiapp
        self.pending_fn = None
        self.result_val = None
        self.error_val = None
        self.is_done = True
        self.ext_event = None
        self.handler = None

        try:
            class _BridgeHandler(IExternalEventHandler):
                __namespace__ = "DynamoChutesAI_" + str(int(time.time() * 1000))

                def __init__(self, parent_invoker):
                    self.parent = parent_invoker

                def Execute(self, app):
                    self.parent._execute_pending(app)

                def GetName(self):
                    return "DynamoChutesAI External Event v3.0"

            self.handler = _BridgeHandler(self)
            self.ext_event = ExternalEvent.Create(self.handler)
        except Exception:
            self.ext_event = None

    def _execute_pending(self, uiapp_arg=None):
        fn = self.pending_fn
        self.pending_fn = None
        if fn is None:
            self.is_done = True
            return
        try:
            self.result_val = fn()
            self.error_val = None
        except Exception as ex:
            self.result_val = None
            self.error_val = ex
        finally:
            self.is_done = True

    def _on_idling(self, sender, args):
        try:
            if self.uiapp is not None:
                self.uiapp.Idling -= self._idling_delegate
        except Exception:
            pass
        self._execute_pending(sender)

    def run(self, fn, force_direct=False):
        """Выполняет функцию fn() в контексте Revit API и возвращает результат."""
        try:
            return fn()
        except Exception as direct_ex:
            if force_direct or self.uiapp is None:
                raise direct_ex

        self.pending_fn = fn
        self.result_val = None
        self.error_val = None
        self.is_done = False

        dispatched = False
        if self.ext_event is not None:
            try:
                self.ext_event.Raise()
                dispatched = True
            except Exception:
                dispatched = False

        if not dispatched:
            try:
                self._idling_delegate = EventHandler[IdlingEventArgs](self._on_idling)
                self.uiapp.Idling += self._idling_delegate
                dispatched = True
            except Exception as idl_ex:
                self.is_done = True
                raise idl_ex

        wake_revit_main_window(self.uiapp)

        t0 = time.time()
        while not self.is_done and (time.time() - t0) < 10.0:
            Application.DoEvents()
            Thread.Sleep(25)
            wake_revit_main_window(self.uiapp)

        if not self.is_done:
            try:
                if hasattr(self, "_idling_delegate") and self.uiapp is not None:
                    self.uiapp.Idling -= self._idling_delegate
            except Exception:
                pass
            raise Exception(u"Операция Revit API недоступна (завершите активную команду в Revit и повторите).")

        if self.error_val is not None:
            raise self.error_val
        return self.result_val


# ==============================================================================
# 3. МЕНЕДЖЕР ПРОФИЛЕЙ (СОХРАНЕНИЕ BASE URL И API KEY)
# ==============================================================================


def get_profiles_file_path():
    """Возвращает путь к JSON-файлу профилей в %APPDATA%\\DynamoChutesAI."""
    try:
        appdata = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData)
        cfg_dir = Path.Combine(appdata, u"DynamoChutesAI")
        if not Directory.Exists(cfg_dir):
            Directory.CreateDirectory(cfg_dir)
        return Path.Combine(cfg_dir, u"profiles.json")
    except Exception:
        desktop = Environment.GetFolderPath(Environment.SpecialFolder.Desktop)
        return Path.Combine(desktop, u"dynamo_chutes_profiles.json")


def load_profiles_data():
    """Загружает сохранённые профили из JSON."""
    cfg_path = get_profiles_file_path()
    default_data = {
        "active_profile": u"Chutes.ai (Основной)",
        "profiles": {
            u"Chutes.ai (Основной)": {
                "base_url": u"https://api.chutes.ai",
                "api_key": u"",
                "last_model": u"Qwen-Image-Edit-2511",
            }
        },
    }
    if not File.Exists(cfg_path):
        return default_data
    try:
        raw_text = File.ReadAllText(cfg_path, Encoding.UTF8)
        parsed = json.loads(u_str(raw_text))
        if isinstance(parsed, dict) and "profiles" in parsed and isinstance(parsed["profiles"], dict):
            if len(parsed["profiles"]) == 0:
                return default_data
            return parsed
    except Exception:
        pass
    return default_data


def save_profiles_data(data_dict):
    """Сохраняет словарь профилей в JSON."""
    cfg_path = get_profiles_file_path()
    try:
        json_str = json.dumps(data_dict, ensure_ascii=False, indent=2)
        File.WriteAllText(cfg_path, u_str(json_str), Encoding.UTF8)
        return True
    except Exception:
        try:
            json_str = json.dumps(data_dict, ensure_ascii=True, indent=2)
            File.WriteAllText(cfg_path, u_str(json_str), Encoding.UTF8)
            return True
        except Exception:
            return False


# ==============================================================================
# 4. КАТАЛОГ МОДЕЛЕЙ ГЕНЕРАЦИИ ИЗОБРАЖЕНИЙ (ИСХОДНЫЕ ИМЕНА МОДЕЛЕЙ)
# ==============================================================================

BUILTIN_CHUTES_IMAGE_MODELS = [
    {
        "id": u"Qwen-Image-Edit-2511",
        "title": u"Qwen-Image-Edit-2511",
        "slug": u"vonkaiser-qwen-image-edit-2511",
        "endpoint": u"https://vonkaiser-qwen-image-edit-2511.chutes.ai/generate",
        "mode": u"img2img_qwen",
        "owner": u"vonkaiser",
        "description": u"Edit images with prompts (до 3 картинок в image_b64s)",
        "default_steps": 4,
    },
    {
        "id": u"Qwen-Image-2512",
        "title": u"Qwen-Image-2512",
        "slug": u"vonkaiser-qwen-image-2512",
        "endpoint": u"https://vonkaiser-qwen-image-2512.chutes.ai/generate",
        "mode": u"txt2img_chute",
        "owner": u"vonkaiser",
        "description": u"Generate images with prompts (Qwen-Image-2512)",
        "default_steps": 8,
    },
    {
        "id": u"z-image-turbo",
        "title": u"z-image-turbo",
        "slug": u"vonkaiser-z-image-turbo",
        "endpoint": u"https://vonkaiser-z-image-turbo.chutes.ai/generate",
        "mode": u"txt2img_chute",
        "owner": u"vonkaiser",
        "description": u"Z-Image Turbo: fast text-to-image generation",
        "default_steps": 4,
    },
    {
        "id": u"imageclassic",
        "title": u"imageclassic",
        "slug": u"vonkaiser-imageclassic",
        "endpoint": u"https://vonkaiser-imageclassic.chutes.ai/generate",
        "mode": u"txt2img_chute",
        "owner": u"vonkaiser",
        "description": u"Four classic image models on one chute: FLUX / SD",
        "default_steps": 8,
    },
    {
        "id": u"Qwen-Image-Edit-2509",
        "title": u"Qwen-Image-Edit-2509",
        "slug": u"chutes-qwen-image-edit-2509",
        "endpoint": u"https://chutes-qwen-image-edit-2509.chutes.ai/generate",
        "mode": u"img2img_qwen",
        "owner": u"chutes",
        "description": u"Qwen-Image-Edit-2509 (до 3 картинок в image_b64s + prompt)",
        "default_steps": 4,
    },
    {
        "id": u"FLUX.1-dev",
        "title": u"FLUX.1-dev",
        "slug": u"image",
        "endpoint": u"https://image.chutes.ai/generate",
        "mode": u"txt2img_unified",
        "owner": u"chutes",
        "description": u"Unified Image endpoint (FLUX.1-dev)",
        "default_steps": 10,
    },
]

IMAGE_POSITIVE_KEYWORDS = (
    "image",
    "img",
    "flux",
    "diffusion",
    "sdxl",
    "stable-diffusion",
    "qwen-image",
    "z-image",
    "hidream",
    "hunyuan-image",
    "juggernaut",
    "chroma",
    "illustrij",
    "inpaint",
    "controlnet",
    "dall-e",
    "gpt-image",
    "playground",
    "kandinsky",
    "kolors",
)

IMAGE_NEGATIVE_KEYWORDS = (
    "llm",
    "vllm",
    "sglang",
    "tei",
    "embedding",
    "rerank",
    "whisper",
    "kokoro",
    "tts",
    "audio",
    "music",
    "speech",
    "video",
    "i2v",
    "t2v",
    "sam3",
    "nsfw-classifier",
    "docuextract",
)


def is_image_generation_chute(item_dict):
    if not isinstance(item_dict, dict):
        return False
    template = u_str(item_dict.get("standard_template", "")).lower()
    name = u_str(item_dict.get("name", "") or item_dict.get("id", "")).lower()
    slug = u_str(item_dict.get("slug", "")).lower()
    tagline = u_str(item_dict.get("tagline", "") or item_dict.get("description", "")).lower()
    combined = u"{} {} {} {}".format(template, name, slug, tagline)
    for neg in IMAGE_NEGATIVE_KEYWORDS:
        if neg in name or neg in slug or neg == template:
            return False
    if template == u"diffusion":
        return True
    cords = item_dict.get("cords")
    if isinstance(cords, list):
        for c in cords:
            if isinstance(c, dict):
                p = u_str(c.get("public_api_path", "") or c.get("path", "")).lower()
                out_ct = u_str(c.get("output_content_type", "")).lower()
                if u"image/" in out_ct or p in (u"/generate", u"/img2img", u"/text2image", u"/sdxl", u"/edit"):
                    if not any(neg in combined for neg in IMAGE_NEGATIVE_KEYWORDS):
                        return True
    for pos in IMAGE_POSITIVE_KEYWORDS:
        if pos in combined:
            return True
    return False


def build_chute_endpoint(item_dict, base_url):
    slug = u_str(item_dict.get("slug", "")).strip()
    name = u_str(item_dict.get("name", "") or item_dict.get("id", "")).strip()
    username = u""
    user_obj = item_dict.get("user")
    if isinstance(user_obj, dict):
        username = u_str(user_obj.get("username", "")).strip()
    if not username:
        username = u_str(item_dict.get("username", "")).strip()

    name_low = name.lower()
    slug_low = slug.lower()
    for preset in BUILTIN_CHUTES_IMAGE_MODELS:
        if (
            preset["id"].lower() == name_low
            or preset["slug"].lower() == slug_low
            or preset["id"].lower() in slug_low
        ):
            return preset["endpoint"], preset["mode"], preset["default_steps"]

    cord_path = u"/generate"
    cords = item_dict.get("cords")
    if isinstance(cords, list) and len(cords) > 0:
        for c in cords:
            if isinstance(c, dict):
                p = u_str(c.get("public_api_path", "") or c.get("path", "")).strip()
                if p in (u"/generate", u"/img2img", u"/text2image", u"/edit"):
                    cord_path = p
                    break

    if slug:
        host = slug
        if username and not host.lower().startswith(username.lower() + u"-"):
            host = u"{}-{}".format(username, slug)
        endpoint = u"https://{}.chutes.ai{}".format(host.lower(), cord_path)
    elif u"chutes.ai" in base_url.lower():
        clean_slug = name.lower().replace(u" ", u"-").replace(u"_", u"-").replace(u"/", u"-")
        if username:
            endpoint = u"https://{}-{}.chutes.ai{}".format(username.lower(), clean_slug, cord_path)
        else:
            endpoint = u"https://image.chutes.ai/generate"
    else:
        endpoint = base_url.rstrip(u"/") + u"/v1/images/generations"

    is_edit = (u"edit" in name_low) or (u"edit" in slug_low) or (u"img2img" in cord_path)
    mode = u"img2img_qwen" if is_edit else u"txt2img_chute"
    steps = 4 if (is_edit or u"turbo" in name_low) else 8
    return endpoint, mode, steps


def http_get_json(url, api_key, timeout_ms=15000):
    try:
        req = HttpWebRequest.Create(url)
        req.Method = "GET"
        req.Timeout = timeout_ms
        req.ReadWriteTimeout = timeout_ms
        req.KeepAlive = False
        req.Accept = "application/json"
        req.UserAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DynamoRevitAI/3.0"

        if api_key:
            clean_key = u_str(api_key).replace(u"Bearer ", u"").strip()
            if clean_key:
                req.Headers.Add("Authorization", "Bearer " + clean_key)

        resp = req.GetResponse()
        code = Convert.ToInt32(resp.StatusCode)
        stream = resp.GetResponseStream()
        raw_bytes = read_stream_to_bytes(stream)
        stream.Close()
        resp.Close()

        text = Encoding.UTF8.GetString(raw_bytes)
        return code, json.loads(u_str(text))
    except WebException as wex:
        err_code = -1
        err_msg = u_str(wex.Message)
        if wex.Response is not None:
            try:
                err_code = Convert.ToInt32(wex.Response.StatusCode)
                reader = StreamReader(wex.Response.GetResponseStream(), Encoding.UTF8)
                err_body = reader.ReadToEnd()
                reader.Close()
                if err_body:
                    err_msg = u_str(err_body)
            except Exception:
                pass
        return err_code, err_msg
    except Exception as ex:
        return -1, u_str(ex)


def fetch_provider_image_models(base_url, api_key):
    clean_base = u_str(base_url).strip().rstrip(u"/")
    if not clean_base:
        clean_base = u"https://api.chutes.ai"

    discovered = []
    seen_ids = set()
    api_notes = []

    def add_model_entry(entry):
        mid = u_str(entry.get("id", "")).strip()
        if not mid:
            return
        key_low = mid.lower()
        if key_low in seen_ids:
            return
        seen_ids.add(key_low)
        entry["title"] = mid
        discovered.append(entry)

    if u".chutes.ai" in clean_base.lower() and not clean_base.lower().startswith(u"https://api.chutes.ai"):
        direct_ep = clean_base if clean_base.endswith(u"/generate") else clean_base + u"/generate"
        host_part = clean_base.split(u"//")[-1].split(u".")[0]
        is_edit = u"edit" in host_part.lower()
        add_model_entry({
            "id": host_part,
            "title": host_part,
            "slug": host_part,
            "endpoint": direct_ep,
            "mode": u"img2img_qwen" if is_edit else u"txt2img_chute",
            "owner": u"custom",
            "description": u"Прямой адрес chute из поля Base URL.",
            "default_steps": 4,
        })

    candidate_urls = []
    if u"chutes.ai" in clean_base.lower():
        candidate_urls.append(u"https://api.chutes.ai/chutes/?include_public=true&limit=200")
        candidate_urls.append(u"https://api.chutes.ai/chutes/?include_public=true&template=diffusion&limit=100")
    else:
        candidate_urls.append(clean_base + u"/v1/models")
        candidate_urls.append(clean_base + u"/models")
        candidate_urls.append(clean_base + u"/chutes/?include_public=true&limit=200")

    for url in candidate_urls:
        code, data = http_get_json(url, api_key, timeout_ms=12000)
        if code == 200 and data is not None:
            items = []
            if isinstance(data, dict):
                items = data.get("items") or data.get("data") or data.get("models") or data.get("chutes") or []
            elif isinstance(data, list):
                items = data

            matched_count = 0
            for item in items:
                if isinstance(item, dict) and is_image_generation_chute(item):
                    raw_name = u_str(item.get("name") or item.get("id") or item.get("slug") or u"").strip()
                    if not raw_name:
                        continue
                    ep, mode, def_steps = build_chute_endpoint(item, clean_base)
                    tagline = u_str(item.get("tagline") or item.get("description") or u"").strip()
                    add_model_entry({
                        "id": raw_name,
                        "title": raw_name,
                        "slug": u_str(item.get("slug", raw_name)),
                        "endpoint": ep,
                        "mode": mode,
                        "owner": u_str((item.get("user") or {}).get("username", "")) if isinstance(item.get("user"), dict) else u"",
                        "description": tagline or u"Модель получена через API поставщика.",
                        "default_steps": def_steps,
                    })
                    matched_count += 1
            api_notes.append(u"API {}: {}".format(code, matched_count))
            if matched_count > 0:
                break
        elif code > 0:
            api_notes.append(u"HTTP {}".format(code))

    if u"chutes.ai" in clean_base.lower() or len(discovered) == 0:
        for preset in BUILTIN_CHUTES_IMAGE_MODELS:
            add_model_entry(dict(preset))

    status_summary = u", ".join(api_notes) if api_notes else u"Каталог Chutes"
    return discovered, status_summary


# ==============================================================================
# 5. РАБОТА С 3D-ВИДАМИ REVIT (ПОИСК, СПИСОК, ПРЯМОЙ ЭКСПОРТ ВИДА В PNG)
# ==============================================================================


def can_export_view(v):
    if v is None:
        return False
    try:
        if v.IsTemplate:
            return False
        return bool(v.CanBePrinted)
    except Exception:
        return False


def collect_project_views(doc, include_non_3d=False):
    result = []
    if doc is None:
        return result

    active_id = -1
    try:
        if doc.ActiveView is not None:
            active_id = get_element_id_int(doc.ActiveView.Id)
    except Exception:
        pass

    collector = FilteredElementCollector(doc).OfClass(View)
    views_3d = []
    views_other = []

    for v in collector:
        if not can_export_view(v):
            continue
        v_name = u_str(v.Name)
        v_id = get_element_id_int(v.Id)
        is_act = (v_id == active_id)
        is_3d = isinstance(v, View3D) or (v.ViewType == ViewType.ThreeD)

        if is_3d:
            prefix = u"★ [Активный 3D] " if is_act else u"[3D] "
            views_3d.append({
                "name": v_name,
                "label": prefix + v_name,
                "view": v,
                "is_3d": True,
                "is_active": is_act,
            })
        elif include_non_3d:
            prefix = u"★ [Активный] " if is_act else u"[Вид] "
            views_other.append({
                "name": v_name,
                "label": prefix + v_name,
                "view": v,
                "is_3d": False,
                "is_active": is_act,
            })

    views_3d.sort(
        key=lambda x: (
            0 if x["is_active"] else (1 if x["name"] == u"{3D}" else 2),
            x["name"].lower(),
        )
    )
    views_other.sort(key=lambda x: (0 if x["is_active"] else 1, x["name"].lower()))
    return views_3d + views_other


def export_revit_view_to_png(doc, target_view, out_dir, pixel_size=1024, file_prefix=u"source_view"):
    """Экспортирует указанный вид Revit в PNG в его собственных настройках графики Revit."""
    if not Directory.Exists(out_dir):
        Directory.CreateDirectory(out_dir)

    try:
        TransactionManager.Instance.ForceCloseTransaction()
    except Exception:
        pass

    stamp = u_str(int(time.time() * 1000))
    temp_prefix = u"chutes_tmp_" + stamp
    base_filepath = Path.Combine(out_dir, temp_prefix)

    opts = ImageExportOptions()
    opts.ZoomType = ZoomFitType.FitToPage
    opts.PixelSize = int(max(256, min(4096, int(pixel_size))))
    opts.FitDirection = FitDirectionType.Horizontal
    opts.HLRandWFViewsFileType = ImageFileType.PNG
    opts.ShadowViewsFileType = ImageFileType.PNG
    opts.ImageResolution = ImageResolution.DPI_150
    opts.ShouldCreateWebSite = False

    view_ids = List[ElementId]()
    view_ids.Add(target_view.Id)
    opts.SetViewsAndSheets(view_ids)
    opts.ExportRange = ExportRange.SetOfViews
    opts.FilePath = base_filepath

    doc.ExportImage(opts)

    found_files = Directory.GetFiles(out_dir, temp_prefix + u"*.png")
    if not found_files or len(found_files) == 0:
        raise Exception(u"Не удалось экспортировать вид '{}'".format(u_str(target_view.Name)))

    exported_file = found_files[0]
    clean_path = Path.Combine(out_dir, u"{}_{}.png".format(file_prefix, stamp))
    try:
        if File.Exists(clean_path):
            File.Delete(clean_path)
        File.Move(exported_file, clean_path)
        for f in found_files:
            if File.Exists(f) and f != clean_path:
                try:
                    File.Delete(f)
                except Exception:
                    pass
        return clean_path
    except Exception:
        return exported_file


def calc_target_dimensions(image_path, max_side=1024):
    """Вычисляет width и height кратно 64 с сохранением пропорций исходного кадра."""
    try:
        img = load_image_unlocked(image_path)
        if img is not None:
            orig_w = img.Width
            orig_h = img.Height
            img.Dispose()
            if orig_w > 0 and orig_h > 0:
                scale = float(max_side) / float(max(orig_w, orig_h))
                w = int(round((orig_w * scale) / 64.0) * 64)
                h = int(round((orig_h * scale) / 64.0) * 64)
                w = max(256, min(2048, w))
                h = max(256, min(2048, h))
                return w, h
    except Exception:
        pass
    return 1024, 1024


# ==============================================================================
# 6. ОТПРАВКА ЗАПРОСА НА ГЕНЕРАЦИЮ / РЕДАКТИРОВАНИЕ (ДО 3 КАРТИНОК В IMAGE_B64S)
# ==============================================================================


def normalize_b64_images_list(b64_images_or_single):
    """Приводит входные Base64-данные к списку из максимум 3 непустых строк."""
    if not b64_images_or_single:
        return []
    if isinstance(b64_images_or_single, (list, tuple)):
        cleaned = [u_str(x).strip() for x in b64_images_or_single if x and u_str(x).strip()]
        return cleaned[:3]
    single = u_str(b64_images_or_single).strip()
    return [single] if single else []


def build_generation_payload(model_info, prompt_text, b64_images, width, height, steps_val, send_source_image=True):
    """Формирует чистый JSON-payload для Chutes.ai с поддержкой от 1 до 3 кадров в image_b64s."""
    mode = u_str(model_info.get("mode", "img2img_qwen"))
    model_id = u_str(model_info.get("id", "Qwen-Image-Edit-2511"))
    endpoint = u_str(model_info.get("endpoint", "")).lower()

    b64_list = normalize_b64_images_list(b64_images) if send_source_image else []
    cfg_scale = 1.0 if int(steps_val) <= 12 else 4.0

    if mode == u"img2img_qwen" or u"image-edit" in endpoint or (send_source_image and len(b64_list) > 0):
        payload = {
            "prompt": u_str(prompt_text),
            "width": int(width),
            "height": int(height),
            "num_inference_steps": int(steps_val),
        }
        if len(b64_list) > 0 and (mode == u"img2img_qwen" or u"edit" in endpoint or send_source_image):
            payload["image_b64s"] = b64_list[:3]
            payload["true_cfg_scale"] = float(cfg_scale)
        else:
            payload["guidance_scale"] = 3.5 if steps_val <= 8 else 7.0
        if u"image.chutes.ai" in endpoint:
            payload["model"] = model_id
        return payload

    payload = {
        "prompt": u_str(prompt_text),
        "width": int(width),
        "height": int(height),
        "num_inference_steps": int(steps_val),
    }
    if u"z-image-turbo" not in endpoint:
        payload["guidance_scale"] = 3.5 if steps_val <= 8 else 7.0
    if mode == u"txt2img_unified" or u"image.chutes.ai" in endpoint:
        payload["model"] = model_id
    return payload


def send_image_generation_request(endpoint_url, api_key, payload_dict, out_dir, timeout_ms=240000):
    def _do_post(target_payload):
        req = HttpWebRequest.Create(endpoint_url)
        req.Method = "POST"
        req.Timeout = timeout_ms
        req.ReadWriteTimeout = timeout_ms
        req.KeepAlive = False
        req.ContentType = "application/json; charset=utf-8"
        req.Accept = "image/jpeg, image/png, application/json"
        req.UserAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DynamoRevitAI/3.0"

        clean_key = u_str(api_key).replace(u"Bearer ", u"").strip()
        req.Headers.Add("Authorization", "Bearer " + clean_key)

        json_body = json.dumps(target_payload, ensure_ascii=True)
        body_bytes = Encoding.UTF8.GetBytes(json_body)
        req.ContentLength = body_bytes.Length

        req_stream = req.GetRequestStream()
        req_stream.Write(body_bytes, 0, body_bytes.Length)
        req_stream.Close()

        resp = req.GetResponse()
        status_code = Convert.ToInt32(resp.StatusCode)
        content_type = u_str(resp.ContentType).lower()

        resp_stream = resp.GetResponseStream()
        raw_bytes = read_stream_to_bytes(resp_stream)
        resp_stream.Close()
        resp.Close()

        stamp = u_str(int(time.time() * 1000))
        ext = u".png" if u"png" in content_type else u".jpg"
        result_path = Path.Combine(out_dir, u"chutes_ai_{}{}".format(stamp, ext))

        if u"json" in content_type:
            json_text = Encoding.UTF8.GetString(raw_bytes)
            data_obj = json.loads(u_str(json_text))
            b64_res = (
                data_obj.get("image")
                or data_obj.get("image_b64")
                or (
                    data_obj.get("data", [{}])[0].get("b64_json")
                    if isinstance(data_obj.get("data"), list) and len(data_obj.get("data")) > 0
                    else None
                )
            )
            if b64_res:
                img_bytes = Convert.FromBase64String(u_str(b64_res))
                write_bytes_to_file(result_path, img_bytes)
                return status_code, result_path
            return status_code, u"JSON without image: " + u_str(json_text)

        write_bytes_to_file(result_path, raw_bytes)
        return status_code, result_path

    try:
        return _do_post(payload_dict)
    except WebException as web_ex:
        err_code = -1
        err_msg = u_str(web_ex.Message)
        if web_ex.Response is not None:
            try:
                err_code = Convert.ToInt32(web_ex.Response.StatusCode)
                reader = StreamReader(web_ex.Response.GetResponseStream(), Encoding.UTF8)
                body_err = reader.ReadToEnd()
                reader.Close()
                if body_err:
                    err_msg = u_str(body_err)
            except Exception:
                pass

        if err_code == 422 and ("image_b64s" in payload_dict or "true_cfg_scale" in payload_dict):
            fallback_payload = {
                "prompt": payload_dict.get("prompt", ""),
                "width": payload_dict.get("width", 1024),
                "height": payload_dict.get("height", 1024),
                "num_inference_steps": payload_dict.get("num_inference_steps", 4),
            }
            try:
                return _do_post(fallback_payload)
            except Exception:
                pass

        return err_code, err_msg
    except Exception as ex:
        return -1, u_str(ex)


# ==============================================================================
# 7. ОКНА ПРОСМОТРА ПОЛНОГО ИЗОБРАЖЕНИЯ И СРАВНЕНИЯ «ДО / ПОСЛЕ»
# ==============================================================================


def show_full_image_window(image_path, title_text, live_bitmap=None):
    """Открывает актуальное изображение в отдельном растягиваемом окне при нажатии на превью."""
    img_obj = None
    if live_bitmap is not None:
        try:
            img_obj = Bitmap(live_bitmap)
        except Exception:
            img_obj = None
    if img_obj is None and image_path and File.Exists(image_path):
        img_obj = load_image_unlocked(image_path)
    if img_obj is None:
        return

    viewer = Form()
    dims_str = u"{}x{} px".format(img_obj.Width, img_obj.Height)
    fname_str = Path.GetFileName(image_path) if image_path else u"preview.png"
    viewer.Text = u"{}  —  {}  ({})".format(u_str(title_text), fname_str, dims_str)
    viewer.Size = Size(1150, 800)
    viewer.MinimumSize = Size(640, 480)
    viewer.FormBorderStyle = FormBorderStyle.Sizable
    viewer.StartPosition = FormStartPosition.CenterScreen
    viewer.MaximizeBox = True
    viewer.MinimizeBox = True
    viewer.BackColor = Color.FromArgb(15, 23, 42)

    pic = PictureBox()
    pic.SizeMode = PictureBoxSizeMode.Zoom
    pic.BackColor = Color.FromArgb(15, 23, 42)
    pic.Image = img_obj
    viewer.Controls.Add(pic)

    pnl_bottom = Panel()
    pnl_bottom.BackColor = Color.FromArgb(30, 41, 59)
    viewer.Controls.Add(pnl_bottom)

    lbl_info = Label()
    lbl_info.Text = u"Разрешение: {}   |   Файл: {}".format(dims_str, u_str(image_path or fname_str))
    lbl_info.ForeColor = Color.FromArgb(226, 232, 240)
    lbl_info.Font = Font("Segoe UI", 9.0, FontStyle.Regular)
    lbl_info.Location = Point(16, 10)
    lbl_info.Size = Size(820, 32)
    pnl_bottom.Controls.Add(lbl_info)

    btn_close = Button()
    btn_close.Text = u"EXIT | ЗАКРЫТЬ"
    btn_close.FlatStyle = FlatStyle.Flat
    btn_close.BackColor = Color.FromArgb(220, 38, 38)
    btn_close.ForeColor = Color.White
    btn_close.Font = Font("Segoe UI", 9.0, FontStyle.Bold)
    btn_close.Size = Size(150, 34)
    btn_close.Cursor = Cursors.Hand
    btn_close.Click += lambda s, a: viewer.Close()
    pnl_bottom.Controls.Add(btn_close)

    def _layout_viewer(s=None, a=None):
        cw = viewer.ClientSize.Width
        ch = viewer.ClientSize.Height
        bar_h = 52
        pic.Location = Point(0, 0)
        pic.Size = Size(cw, max(100, ch - bar_h))
        pnl_bottom.Location = Point(0, max(100, ch - bar_h))
        pnl_bottom.Size = Size(cw, bar_h)
        lbl_info.Size = Size(max(200, cw - 190), 34)
        btn_close.Location = Point(max(200, cw - 166), 9)

    def _on_viewer_closed(s, a):
        try:
            if pic.Image is not None:
                pic.Image.Dispose()
        except Exception:
            pass

    viewer.Resize += _layout_viewer
    viewer.FormClosed += _on_viewer_closed
    _layout_viewer()
    viewer.Show()


def show_comparison_window(input_items, res_path, view_label, prompt_text, model_title=u"Chutes.ai"):
    """Растягиваемое окно сравнения всех активных входных кадров (1..3) и результата AI."""
    valid_inputs = []
    if isinstance(input_items, (list, tuple)):
        for item in input_items:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                t_lbl, f_path = item[0], item[1]
                if f_path and File.Exists(f_path):
                    valid_inputs.append((u_str(t_lbl), u_str(f_path)))
    elif isinstance(input_items, STRING_TYPES) and File.Exists(u_str(input_items)):
        valid_inputs.append((u"Исходный кадр", u_str(input_items)))

    columns = list(valid_inputs)
    if res_path and File.Exists(res_path):
        columns.append((u"Результат AI ({})".format(u_str(model_title)), u_str(res_path)))
    if len(columns) == 0:
        return

    form = Form()
    form.Text = u"Сравнение До / После — {} ({})".format(u_str(view_label), u_str(model_title))
    form.Size = Size(min(1520, max(1160, 380 * len(columns))), 720)
    form.MinimumSize = Size(860, 520)
    form.FormBorderStyle = FormBorderStyle.Sizable
    form.StartPosition = FormStartPosition.CenterScreen
    form.MaximizeBox = True
    form.MinimizeBox = True
    form.BackColor = Color.FromArgb(248, 250, 252)

    col_widgets = []
    for idx, (col_title, col_path) in enumerate(columns):
        is_result = (idx == len(columns) - 1) and (res_path and col_path == u_str(res_path))
        lbl = Label()
        lbl.Text = col_title + u" (клик — полный размер):"
        lbl.Font = Font("Segoe UI", 9.5, FontStyle.Bold)
        lbl.ForeColor = Color.FromArgb(5, 150, 105) if is_result else Color.FromArgb(30, 41, 59)
        form.Controls.Add(lbl)

        pic = PictureBox()
        pic.SizeMode = PictureBoxSizeMode.Zoom
        pic.BackColor = Color.White
        pic.BorderStyle = BorderStyle.FixedSingle
        pic.Cursor = Cursors.Hand
        pic.Image = load_image_unlocked(col_path)

        def _make_click_handler(p_path, p_title, p_box):
            return lambda s, a: show_full_image_window(p_path, p_title, p_box.Image)

        pic.Click += _make_click_handler(col_path, col_title, pic)
        form.Controls.Add(pic)
        col_widgets.append((lbl, pic))

    lbl_prompt = Label()
    lbl_prompt.Text = u"Промпт: " + u_str(prompt_text)
    lbl_prompt.Font = Font("Segoe UI", 9.0, FontStyle.Regular)
    lbl_prompt.ForeColor = Color.FromArgb(71, 85, 105)
    form.Controls.Add(lbl_prompt)

    btn_close = Button()
    btn_close.Text = u"EXIT | ВЫХОД"
    btn_close.FlatStyle = FlatStyle.Flat
    btn_close.BackColor = Color.FromArgb(15, 23, 42)
    btn_close.ForeColor = Color.White
    btn_close.Font = Font("Segoe UI", 9.5, FontStyle.Bold)
    btn_close.Cursor = Cursors.Hand
    btn_close.Click += lambda s, a: form.Close()
    form.Controls.Add(btn_close)

    def _layout_cmp(s=None, a=None):
        cw = form.ClientSize.Width
        ch = form.ClientSize.Height
        pad = 18
        gap = 14
        n_cols = max(1, len(col_widgets))
        col_w = int((cw - pad * 2 - gap * (n_cols - 1)) / n_cols)
        img_h = max(200, ch - 120)
        for i, (lbl_w, pic_w) in enumerate(col_widgets):
            cx = pad + i * (col_w + gap)
            lbl_w.Location = Point(cx, 14)
            lbl_w.Size = Size(col_w, 24)
            pic_w.Location = Point(cx, 42)
            pic_w.Size = Size(col_w, img_h)
        bottom_y = 42 + img_h + 14
        lbl_prompt.Location = Point(pad, bottom_y)
        lbl_prompt.Size = Size(max(200, cw - pad * 2 - 170), 42)
        btn_close.Location = Point(cw - pad - 150, bottom_y)
        btn_close.Size = Size(150, 36)

    def _on_cmp_closed(s, a):
        for _, pic_w in col_widgets:
            try:
                if pic_w.Image is not None:
                    pic_w.Image.Dispose()
            except Exception:
                pass

    form.Resize += _layout_cmp
    form.FormClosed += _on_cmp_closed
    _layout_cmp()
    form.Show()


# ==============================================================================
# 8. ГЛАВНОЕ ОКНО СТУДИИ (v3.0 — 3 УНИВЕРСАЛЬНЫХ СЛОТА: ВИД REVIT ИЛИ ФАЙЛ)
# ==============================================================================

NONE_VIEW_LABEL = u"— [Не выбран / Выберите вид или файл] —"


class ChutesRevitStudioForm(Form):
    def __init__(
        self,
        doc,
        revit_invoker,
        init_api_key,
        init_slot1_in,
        init_prompt,
        init_base_url,
        init_out_dir,
        init_max_side,
        init_steps,
        init_slot2_in=None,
        init_slot3_in=None,
    ):
        Form.__init__(self)
        self.doc = doc
        self.revit_invoker = revit_invoker
        self.profiles_data = load_profiles_data()
        self._is_initializing = True
        self._suppress_slot_events = False

        # Состояние каждого из 3 универсальных входных слотов (индексы 0, 1, 2):
        # source_type: "none" | "view" | "file"
        # view_id: int (ID вида Revit, если выбран вид)
        # view_obj: View (ссылка на вид Revit)
        # view_name: str (имя вида)
        # file_path: str (путь к пользовательскому файлу, если выбран файл с диска)
        # preview_path: str (путь к актуальному PNG/JPG кадру этого слота)
        self.slots = [
            {
                "index": 0,
                "title": u"Кадр 1 (Основной)",
                "enabled": True,
                "source_type": "none",
                "view_id": -1,
                "view_obj": None,
                "view_name": u"",
                "file_path": u"",
                "preview_path": u"",
            },
            {
                "index": 1,
                "title": u"Кадр 2 (Доп. вид / Скрытая линия / Файл)",
                "enabled": False,
                "source_type": "none",
                "view_id": -1,
                "view_obj": None,
                "view_name": u"",
                "file_path": u"",
                "preview_path": u"",
            },
            {
                "index": 2,
                "title": u"Кадр 3 (Референс / Вид / Файл)",
                "enabled": False,
                "source_type": "none",
                "view_id": -1,
                "view_obj": None,
                "view_name": u"",
                "file_path": u"",
                "preview_path": u"",
            },
        ]

        # Для совместимости с выходами OUT нода Dynamo
        self.source_image_path = u""
        self.result_image_path = u""
        self.status_message = u"Окно студии v3.0 открыто (немодальный режим — можно параллельно работать в Revit)."
        self.meta_result = {}
        self.execution_succeeded = False

        self.all_views = collect_project_views(doc, include_non_3d=False)
        self.filtered_views = list(self.all_views)
        self.available_models = []
        self.selected_model_info = BUILTIN_CHUTES_IMAGE_MODELS[0]

        self.preview_temp_dir = Path.Combine(Path.GetTempPath(), u"DynamoChutesPreview")
        if not Directory.Exists(self.preview_temp_dir):
            try:
                Directory.CreateDirectory(self.preview_temp_dir)
            except Exception:
                pass

        # Палитра
        self.col_bg = Color.FromArgb(246, 248, 250)
        self.col_card = Color.FromArgb(255, 255, 255)
        self.col_dark = Color.FromArgb(15, 23, 42)
        self.col_accent = Color.FromArgb(37, 99, 235)
        self.col_accent_soft = Color.FromArgb(239, 246, 255)
        self.col_emerald = Color.FromArgb(16, 185, 129)
        self.col_emerald_dark = Color.FromArgb(5, 150, 105)
        self.col_text = Color.FromArgb(30, 41, 59)
        self.col_muted = Color.FromArgb(100, 116, 139)
        self.col_border = Color.FromArgb(226, 232, 240)
        self.col_success = Color.FromArgb(22, 163, 74)
        self.col_slot_active = Color.FromArgb(241, 245, 249)
        self.col_slot_inactive = Color.FromArgb(226, 232, 240)

        self.font_title = Font("Segoe UI", 12.0, FontStyle.Bold)
        self.font_sec = Font("Segoe UI", 9.5, FontStyle.Bold)
        self.font_reg = Font("Segoe UI", 9.0, FontStyle.Regular)
        self.font_small = Font("Segoe UI", 8.25, FontStyle.Regular)
        self.font_small_bold = Font("Segoe UI", 8.25, FontStyle.Bold)
        self.font_mono = Font("Consolas", 8.5, FontStyle.Regular)

        self.tooltip = ToolTip()

        # Контролы слотов (списки для удобного доступа по индексу 0..2)
        self.slot_combos = []
        self.slot_file_btns = []
        self.slot_clear_btns = []
        self.slot_checkboxes = []
        self.slot_pic_boxes = []
        self.slot_placeholders = []

        self._build_ui(
            init_api_key,
            init_slot1_in,
            init_prompt,
            init_base_url,
            init_out_dir,
            init_max_side,
            init_steps,
            init_slot2_in,
            init_slot3_in,
        )
        self._is_initializing = False
        self.progress_bar.Value = 0

    def _create_card(self, x, y, w, h):
        pnl = Panel()
        pnl.Location = Point(x, y)
        pnl.Size = Size(w, h)
        pnl.BackColor = self.col_card
        pnl.BorderStyle = BorderStyle.FixedSingle
        self.Controls.Add(pnl)
        return pnl

    def _create_button(self, parent, text, x, y, w, h, bg_color, fg_color, bold=False):
        btn = Button()
        btn.Text = text
        btn.Location = Point(x, y)
        btn.Size = Size(w, h)
        btn.FlatStyle = FlatStyle.Flat
        btn.FlatAppearance.BorderSize = 1
        btn.FlatAppearance.BorderColor = self.col_border if bg_color == self.col_card else bg_color
        btn.BackColor = bg_color
        btn.ForeColor = fg_color
        btn.Font = self.font_sec if bold else self.font_reg
        btn.Cursor = Cursors.Hand
        parent.Controls.Add(btn)
        return btn

    def _build_ui(
        self,
        init_api_key,
        init_slot1_in,
        init_prompt,
        init_base_url,
        init_out_dir,
        init_max_side,
        init_steps,
        init_slot2_in,
        init_slot3_in,
    ):
        self.Text = u"AI Render Studio v3.0 — Revit 2020 / 2022 (Chutes.ai • 3 универсальных слота)"
        self.Size = Size(1220, 890)
        self.MinimumSize = Size(1040, 810)
        self.FormBorderStyle = FormBorderStyle.Sizable
        self.StartPosition = FormStartPosition.CenterScreen
        self.MaximizeBox = True
        self.MinimizeBox = True
        self.BackColor = self.col_bg

        # --- ВЕРХНЯЯ ПАНЕЛЬ (ШАПКА) ---
        self.pnl_header = Panel()
        self.pnl_header.Location = Point(0, 0)
        self.pnl_header.Size = Size(1220, 50)
        self.pnl_header.BackColor = self.col_dark
        self.Controls.Add(self.pnl_header)

        self.lbl_app_title = Label()
        self.lbl_app_title.Text = u"REVIT 3D  ×  CHUTES.AI  |  AI RENDER STUDIO v3.0"
        self.lbl_app_title.Location = Point(20, 13)
        self.lbl_app_title.Size = Size(520, 24)
        self.lbl_app_title.Font = self.font_title
        self.lbl_app_title.ForeColor = Color.White
        self.pnl_header.Controls.Add(self.lbl_app_title)

        self.lbl_app_sub = Label()
        self.lbl_app_sub.Text = u"3 универсальных слота (любой 3D-вид Revit или файл с диска)  •  Параллельная работа с Revit"
        self.lbl_app_sub.Location = Point(540, 16)
        self.lbl_app_sub.Size = Size(650, 20)
        self.lbl_app_sub.Font = self.font_reg
        self.lbl_app_sub.ForeColor = Color.FromArgb(148, 163, 184)
        self.lbl_app_sub.TextAlign = ContentAlignment.MiddleRight
        self.pnl_header.Controls.Add(self.lbl_app_sub)

        # ======================================================================
        # КАРТОЧКА 1 (СЛЕВА ВВЕРХУ): ПРОФИЛЬ, BASE URL И API KEY
        # ======================================================================
        self.card_conn = self._create_card(18, 62, 550, 198)

        self.lbl_sec1 = Label()
        self.lbl_sec1.Text = u"1. ПОДКЛЮЧЕНИЕ И ПРОФИЛЬ ПОСТАВЩИКА"
        self.lbl_sec1.Location = Point(14, 10)
        self.lbl_sec1.Size = Size(510, 20)
        self.lbl_sec1.Font = self.font_sec
        self.lbl_sec1.ForeColor = self.col_dark
        self.card_conn.Controls.Add(self.lbl_sec1)

        lbl_prof = Label()
        lbl_prof.Text = u"Профиль:"
        lbl_prof.Location = Point(14, 38)
        lbl_prof.Size = Size(70, 22)
        lbl_prof.Font = self.font_reg
        lbl_prof.ForeColor = self.col_muted
        self.card_conn.Controls.Add(lbl_prof)

        self.cmb_profile = ComboBox()
        self.cmb_profile.Location = Point(90, 35)
        self.cmb_profile.Size = Size(245, 24)
        self.cmb_profile.Font = self.font_reg
        self.cmb_profile.DropDownStyle = ComboBoxStyle.DropDown
        self.cmb_profile.SelectedIndexChanged += self._on_profile_selected
        self.card_conn.Controls.Add(self.cmb_profile)

        self.btn_save_prof = self._create_button(
            self.card_conn, u"Сохранить", 342, 34, 96, 26, self.col_accent_soft, self.col_accent
        )
        self.btn_save_prof.Click += self._on_save_profile

        self.btn_del_prof = self._create_button(
            self.card_conn, u"Удалить", 444, 34, 80, 26, self.col_card, self.col_muted
        )
        self.btn_del_prof.Click += self._on_delete_profile

        lbl_url = Label()
        lbl_url.Text = u"Base URL:"
        lbl_url.Location = Point(14, 72)
        lbl_url.Size = Size(70, 22)
        lbl_url.Font = self.font_reg
        lbl_url.ForeColor = self.col_muted
        self.card_conn.Controls.Add(lbl_url)

        self.txt_base_url = TextBox()
        self.txt_base_url.Location = Point(90, 70)
        self.txt_base_url.Size = Size(434, 24)
        self.txt_base_url.Font = self.font_reg
        self.txt_base_url.Text = u_str(init_base_url or u"https://api.chutes.ai")
        self.card_conn.Controls.Add(self.txt_base_url)

        lbl_key = Label()
        lbl_key.Text = u"API Key:"
        lbl_key.Location = Point(14, 106)
        lbl_key.Size = Size(70, 22)
        lbl_key.Font = self.font_reg
        lbl_key.ForeColor = self.col_muted
        self.card_conn.Controls.Add(lbl_key)

        self.txt_api_key = TextBox()
        self.txt_api_key.Location = Point(90, 104)
        self.txt_api_key.Size = Size(354, 24)
        self.txt_api_key.Font = self.font_reg
        self.txt_api_key.UseSystemPasswordChar = True
        self.card_conn.Controls.Add(self.txt_api_key)

        self.btn_toggle_key = self._create_button(
            self.card_conn, u"Показать", 450, 103, 74, 25, self.col_card, self.col_muted
        )
        self.btn_toggle_key.Font = self.font_small
        self.btn_toggle_key.Click += self._on_toggle_api_key

        self.btn_fetch_models = self._create_button(
            self.card_conn,
            u"Подключить и загрузить модели изображений  →",
            14,
            139,
            510,
            34,
            self.col_dark,
            Color.White,
            bold=True,
        )
        self.btn_fetch_models.Click += self._on_fetch_models_click

        self.lbl_prof_path = Label()
        self.lbl_prof_path.Text = u"Профили: " + get_profiles_file_path()
        self.lbl_prof_path.Location = Point(14, 177)
        self.lbl_prof_path.Size = Size(510, 16)
        self.lbl_prof_path.Font = self.font_small
        self.lbl_prof_path.ForeColor = self.col_muted
        self.card_conn.Controls.Add(self.lbl_prof_path)

        # ======================================================================
        # КАРТОЧКА 2 (СПРАВА ВВЕРХУ): МОДЕЛИ ГЕНЕРАЦИИ
        # ======================================================================
        self.card_models = self._create_card(582, 62, 604, 198)

        self.lbl_sec2 = Label()
        self.lbl_sec2.Text = u"2. ДОСТУПНЫЕ МОДЕЛИ ГЕНЕРАЦИИ ИЗОБРАЖЕНИЙ"
        self.lbl_sec2.Location = Point(14, 10)
        self.lbl_sec2.Size = Size(400, 20)
        self.lbl_sec2.Font = self.font_sec
        self.lbl_sec2.ForeColor = self.col_dark
        self.card_models.Controls.Add(self.lbl_sec2)

        self.lbl_models_status = Label()
        self.lbl_models_status.Text = u"Готово"
        self.lbl_models_status.Location = Point(420, 11)
        self.lbl_models_status.Size = Size(165, 18)
        self.lbl_models_status.Font = self.font_small
        self.lbl_models_status.ForeColor = self.col_accent
        self.lbl_models_status.TextAlign = ContentAlignment.MiddleRight
        self.card_models.Controls.Add(self.lbl_models_status)

        self.lst_models = ListBox()
        self.lst_models.Location = Point(14, 34)
        self.lst_models.Size = Size(574, 102)
        self.lst_models.Font = self.font_reg
        self.lst_models.BorderStyle = BorderStyle.FixedSingle
        self.lst_models.SelectedIndexChanged += self._on_model_selected
        self.card_models.Controls.Add(self.lst_models)

        lbl_ep = Label()
        lbl_ep.Text = u"Эндпоинт:"
        lbl_ep.Location = Point(14, 144)
        lbl_ep.Size = Size(72, 20)
        lbl_ep.Font = self.font_small
        lbl_ep.ForeColor = self.col_muted
        self.card_models.Controls.Add(lbl_ep)

        self.txt_endpoint = TextBox()
        self.txt_endpoint.Location = Point(88, 141)
        self.txt_endpoint.Size = Size(500, 22)
        self.txt_endpoint.Font = self.font_small
        self.txt_endpoint.Text = BUILTIN_CHUTES_IMAGE_MODELS[0]["endpoint"]
        self.card_models.Controls.Add(self.txt_endpoint)

        self.chk_send_image = CheckBox()
        self.chk_send_image.Text = u"Отправлять отмеченные входные кадры (1..3) в image_b64s (режим редактирования / рендера)"
        self.chk_send_image.Location = Point(14, 169)
        self.chk_send_image.Size = Size(574, 22)
        self.chk_send_image.Font = self.font_small
        self.chk_send_image.ForeColor = self.col_text
        self.chk_send_image.Checked = True
        self.card_models.Controls.Add(self.chk_send_image)

        # ======================================================================
        # КАРТОЧКА 3 (СЛЕВА В СЕРЕДИНЕ): 3 СЛОТА (ВИД REVIT ИЛИ ФАЙЛ) + ПАРАМЕТРЫ
        # ======================================================================
        self.card_view = self._create_card(18, 272, 550, 412)

        self.lbl_sec3 = Label()
        self.lbl_sec3.Text = u"3. ИСТОЧНИКИ КАДРОВ (1..3: ВИД REVIT ИЛИ ФАЙЛ) И ПАРАМЕТРЫ"
        self.lbl_sec3.Location = Point(14, 10)
        self.lbl_sec3.Size = Size(520, 20)
        self.lbl_sec3.Font = self.font_sec
        self.lbl_sec3.ForeColor = self.col_dark
        self.card_view.Controls.Add(self.lbl_sec3)

        # Строка поиска видов Revit + галочка 2D-видов
        lbl_search_v = Label()
        lbl_search_v.Text = u"Поиск вида:"
        lbl_search_v.Location = Point(14, 36)
        lbl_search_v.Size = Size(78, 22)
        lbl_search_v.Font = self.font_reg
        lbl_search_v.ForeColor = self.col_muted
        self.card_view.Controls.Add(lbl_search_v)

        self.txt_view_search = TextBox()
        self.txt_view_search.Location = Point(94, 34)
        self.txt_view_search.Size = Size(205, 24)
        self.txt_view_search.Font = self.font_reg
        self.txt_view_search.TextChanged += self._on_view_search_changed
        self.tooltip.SetToolTip(
            self.txt_view_search,
            u"Начните вводить название вида — списки видов во всех 3 слотах ниже отфильтруются",
        )
        self.card_view.Controls.Add(self.txt_view_search)

        self.btn_clear_search = self._create_button(
            self.card_view, u"Сброс", 304, 33, 56, 25, self.col_card, self.col_muted
        )
        self.btn_clear_search.Font = self.font_small
        self.btn_clear_search.Click += self._on_clear_view_search

        self.chk_all_views = CheckBox()
        self.chk_all_views.Text = u"+ 2D-виды/планы"
        self.chk_all_views.Location = Point(368, 36)
        self.chk_all_views.Size = Size(165, 20)
        self.chk_all_views.Font = self.font_small
        self.chk_all_views.ForeColor = self.col_muted
        self.chk_all_views.CheckedChanged += self._on_toggle_all_views
        self.card_view.Controls.Add(self.chk_all_views)

        # 3 универсальные строки выбора источника для Кадра 1, Кадра 2 и Кадра 3
        self.slot_row_labels = []
        slot_short_names = [u"Кадр 1:", u"Кадр 2:", u"Кадр 3:"]
        for s_idx in range(3):
            row_y = 66 + s_idx * 30
            lbl_s = Label()
            lbl_s.Text = slot_short_names[s_idx]
            lbl_s.Location = Point(14, row_y + 3)
            lbl_s.Size = Size(76, 20)
            lbl_s.Font = self.font_small_bold
            lbl_s.ForeColor = self.col_text if s_idx == 0 else self.col_muted
            self.card_view.Controls.Add(lbl_s)
            self.slot_row_labels.append(lbl_s)

            cmb_s = ComboBox()
            cmb_s.Location = Point(94, row_y)
            cmb_s.Size = Size(328, 24)
            cmb_s.Font = self.font_reg
            cmb_s.DropDownStyle = ComboBoxStyle.DropDownList
            cmb_s.SelectedIndexChanged += self._make_slot_combo_handler(s_idx)
            self.tooltip.SetToolTip(
                cmb_s,
                u"Выберите 3D-вид из проекта Revit для слота {} (или нажмите «Файл...» справа)".format(s_idx + 1),
            )
            self.card_view.Controls.Add(cmb_s)
            self.slot_combos.append(cmb_s)

            btn_f = self._create_button(
                self.card_view,
                u"Файл...",
                428,
                row_y - 1,
                68,
                25,
                self.col_accent_soft,
                self.col_accent,
            )
            btn_f.Font = self.font_small
            btn_f.Click += self._make_slot_file_handler(s_idx)
            self.tooltip.SetToolTip(btn_f, u"Выбрать файл изображения с диска для слота {}".format(s_idx + 1))
            self.slot_file_btns.append(btn_f)

            btn_clr = self._create_button(
                self.card_view,
                u"✕",
                500,
                row_y - 1,
                26,
                25,
                self.col_card,
                self.col_muted,
            )
            btn_clr.Font = self.font_small
            btn_clr.Click += self._make_slot_clear_handler(s_idx)
            self.tooltip.SetToolTip(btn_clr, u"Очистить/отключить слот {}".format(s_idx + 1))
            self.slot_clear_btns.append(btn_clr)

        # Промпт
        self.lbl_pr = Label()
        self.lbl_pr.Text = u"Промпт (описание рендера / изменений на английском или русском):"
        self.lbl_pr.Location = Point(14, 160)
        self.lbl_pr.Size = Size(520, 18)
        self.lbl_pr.Font = self.font_reg
        self.lbl_pr.ForeColor = self.col_text
        self.card_view.Controls.Add(self.lbl_pr)

        self.txt_prompt = TextBox()
        self.txt_prompt.Location = Point(14, 180)
        self.txt_prompt.Size = Size(520, 96)
        self.txt_prompt.Multiline = True
        self.txt_prompt.ScrollBars = ScrollBars.Vertical
        self.txt_prompt.Font = self.font_reg
        self.txt_prompt.Text = u_str(
            init_prompt
            or u"Convert this 3D CAD view into a photorealistic architectural render, preserve exact building contours and geometry, glass and concrete facade, sunny day"
        )
        self.card_view.Controls.Add(self.txt_prompt)

        # Размер и шаги
        self.lbl_sz = Label()
        self.lbl_sz.Text = u"Макс. сторона (px):"
        self.lbl_sz.Location = Point(14, 286)
        self.lbl_sz.Size = Size(125, 22)
        self.lbl_sz.Font = self.font_reg
        self.lbl_sz.ForeColor = self.col_muted
        self.card_view.Controls.Add(self.lbl_sz)

        self.num_size = NumericUpDown()
        self.num_size.Location = Point(142, 284)
        self.num_size.Size = Size(85, 24)
        self.num_size.Minimum = 256
        self.num_size.Maximum = 2048
        self.num_size.Increment = 64
        self.num_size.Value = max(256, min(2048, int(init_max_side or 1024)))
        self.num_size.Font = self.font_reg
        self.card_view.Controls.Add(self.num_size)

        self.lbl_st = Label()
        self.lbl_st.Text = u"Шаги (steps):"
        self.lbl_st.Location = Point(242, 286)
        self.lbl_st.Size = Size(88, 22)
        self.lbl_st.Font = self.font_reg
        self.lbl_st.ForeColor = self.col_muted
        self.card_view.Controls.Add(self.lbl_st)

        self.num_steps = NumericUpDown()
        self.num_steps.Location = Point(332, 284)
        self.num_steps.Size = Size(64, 24)
        self.num_steps.Minimum = 1
        self.num_steps.Maximum = 50
        self.num_steps.Value = max(1, min(50, int(init_steps or 4)))
        self.num_steps.Font = self.font_reg
        self.card_view.Controls.Add(self.num_steps)

        self.lbl_st_hint = Label()
        self.lbl_st_hint.Text = u"(4=быстро, 25=HQ)"
        self.lbl_st_hint.Location = Point(402, 287)
        self.lbl_st_hint.Size = Size(120, 20)
        self.lbl_st_hint.Font = self.font_small
        self.lbl_st_hint.ForeColor = self.col_muted
        self.card_view.Controls.Add(self.lbl_st_hint)

        # Папка сохранения рендеров
        self.lbl_dir = Label()
        self.lbl_dir.Text = u"Папка рендеров:"
        self.lbl_dir.Location = Point(14, 318)
        self.lbl_dir.Size = Size(110, 22)
        self.lbl_dir.Font = self.font_reg
        self.lbl_dir.ForeColor = self.col_muted
        self.card_view.Controls.Add(self.lbl_dir)

        self.txt_out_dir = TextBox()
        self.txt_out_dir.Location = Point(126, 316)
        self.txt_out_dir.Size = Size(320, 24)
        self.txt_out_dir.Font = self.font_small
        self.txt_out_dir.Text = u_str(init_out_dir)
        self.card_view.Controls.Add(self.txt_out_dir)

        self.btn_browse_dir = self._create_button(
            self.card_view, u"Обзор...", 451, 315, 75, 25, self.col_card, self.col_muted
        )
        self.btn_browse_dir.Font = self.font_small
        self.btn_browse_dir.Click += self._on_browse_out_dir

        # Кнопка запуска: START | НАЧАТЬ
        self.btn_generate = self._create_button(
            self.card_view,
            u"START | НАЧАТЬ",
            14,
            352,
            512,
            46,
            self.col_emerald,
            Color.White,
            bold=True,
        )
        self.btn_generate.FlatAppearance.BorderColor = self.col_emerald_dark
        self.btn_generate.Font = Font("Segoe UI", 11.5, FontStyle.Bold)
        self.btn_generate.Click += self._on_generate_click

        # ======================================================================
        # КАРТОЧКА 4 (СПРАВА В СЕРЕДИНЕ): 4 ПРЕВЬЮ (СЕТКА 2x2: КАДРЫ 1..3 + РЕЗУЛЬТАТ)
        # ======================================================================
        self.card_prev = self._create_card(582, 272, 604, 412)

        self.lbl_sec4 = Label()
        self.lbl_sec4.Text = u"4. ПРЕВЬЮ КАДРОВ (1..3) И РЕЗУЛЬТАТ AI (КЛИК — УВЕЛИЧИТЬ)"
        self.lbl_sec4.Location = Point(14, 10)
        self.lbl_sec4.Size = Size(440, 20)
        self.lbl_sec4.Font = self.font_sec
        self.lbl_sec4.ForeColor = self.col_dark
        self.card_prev.Controls.Add(self.lbl_sec4)

        self.btn_open_compare = self._create_button(
            self.card_prev, u"Окно До / После", 466, 7, 122, 24, self.col_card, self.col_accent
        )
        self.btn_open_compare.Font = self.font_small
        self.btn_open_compare.Enabled = False
        self.btn_open_compare.Click += self._on_open_compare_click

        slot_chk_titles = [
            u"1. Кадр 1 (Основной вид / файл)",
            u"2. Кадр 2 (Доп. вид / контуры / файл)",
            u"3. Кадр 3 (Референс / вид / файл)",
        ]
        slot_placeholder_texts = [
            u"Кадр 1 не выбран\n(выберите 3D-вид в списке «Кадр 1»\nили нажмите «Файл...»)",
            u"Неактивно\n(выберите 3D-вид в списке «Кадр 2»\nили нажмите «Файл...»)",
            u"Неактивно\n(выберите 3D-вид в списке «Кадр 3»\nили нажмите «Файл...»)",
        ]

        for s_idx in range(3):
            chk = CheckBox()
            chk.Text = slot_chk_titles[s_idx]
            chk.Font = self.font_small_bold
            chk.ForeColor = self.col_text if s_idx == 0 else self.col_muted
            chk.Checked = (s_idx == 0)
            chk.CheckedChanged += self._make_slot_chk_handler(s_idx)
            self.card_prev.Controls.Add(chk)
            self.slot_checkboxes.append(chk)

            pic = PictureBox()
            pic.SizeMode = PictureBoxSizeMode.Zoom
            pic.BackColor = self.col_slot_active if s_idx == 0 else self.col_slot_inactive
            pic.BorderStyle = BorderStyle.FixedSingle
            pic.Cursor = Cursors.Hand
            pic.Click += self._make_slot_pic_click_handler(s_idx)
            self.tooltip.SetToolTip(
                pic,
                u"Превью {}: нажмите для просмотра в полном размере".format(s_idx + 1),
            )
            self.card_prev.Controls.Add(pic)
            self.slot_pic_boxes.append(pic)

            ph = Label()
            ph.Text = slot_placeholder_texts[s_idx]
            ph.Font = self.font_small
            ph.ForeColor = self.col_muted
            ph.BackColor = Color.Transparent
            ph.TextAlign = ContentAlignment.MiddleCenter
            ph.Cursor = Cursors.Hand
            ph.Visible = (s_idx != 0)
            ph.Click += self._make_slot_placeholder_click_handler(s_idx)
            pic.Controls.Add(ph)
            self.slot_placeholders.append(ph)

        # --- СЛОТ 4: Результат AI-рендера ---
        self.lbl_prev_right = Label()
        self.lbl_prev_right.Text = u"4. Результат AI-рендера (клик — увеличить):"
        self.lbl_prev_right.Font = self.font_small_bold
        self.lbl_prev_right.ForeColor = self.col_emerald_dark
        self.card_prev.Controls.Add(self.lbl_prev_right)

        self.pic_result = PictureBox()
        self.pic_result.SizeMode = PictureBoxSizeMode.Zoom
        self.pic_result.BackColor = self.col_slot_active
        self.pic_result.BorderStyle = BorderStyle.FixedSingle
        self.pic_result.Cursor = Cursors.Hand
        self.pic_result.Click += self._on_result_preview_click
        self.tooltip.SetToolTip(self.pic_result, u"Превью 4: Нажмите, чтобы открыть готовый AI-рендер в полном размере")
        self.card_prev.Controls.Add(self.pic_result)

        self.lbl_preview_meta = Label()
        self.lbl_preview_meta.Text = u"Для каждого из 3 кадров можно задать любой вид Revit или файл с диска."
        self.lbl_preview_meta.Font = self.font_small
        self.lbl_preview_meta.ForeColor = self.col_muted
        self.card_prev.Controls.Add(self.lbl_preview_meta)

        # ======================================================================
        # КАРТОЧКА 5 (ВНИЗУ): ПРОЦЕСС РАБОТЫ, ПРОГРЕСС-БАР И ЖУРНАЛ СОБЫТИЙ
        # ======================================================================
        self.card_prog = self._create_card(18, 694, 1168, 104)

        self.lbl_stage = Label()
        self.lbl_stage.Text = u"Готов к работе. Можно параллельно вращать и настраивать виды в Revit."
        self.lbl_stage.Location = Point(14, 8)
        self.lbl_stage.Size = Size(1140, 20)
        self.lbl_stage.Font = self.font_sec
        self.lbl_stage.ForeColor = self.col_dark
        self.card_prog.Controls.Add(self.lbl_stage)

        self.progress_bar = ProgressBar()
        self.progress_bar.Location = Point(14, 31)
        self.progress_bar.Size = Size(1140, 13)
        self.progress_bar.Minimum = 0
        self.progress_bar.Maximum = 100
        self.progress_bar.Value = 0
        self.progress_bar.Style = ProgressBarStyle.Continuous
        self.card_prog.Controls.Add(self.progress_bar)

        self.txt_log = TextBox()
        self.txt_log.Location = Point(14, 49)
        self.txt_log.Size = Size(1140, 46)
        self.txt_log.Multiline = True
        self.txt_log.ReadOnly = True
        self.txt_log.ScrollBars = ScrollBars.Vertical
        self.txt_log.BackColor = Color.FromArgb(248, 250, 252)
        self.txt_log.ForeColor = self.col_text
        self.txt_log.Font = self.font_mono
        self.card_prog.Controls.Add(self.txt_log)

        # ======================================================================
        # КНОПКА ВЫХОДА ВНИЗУ СПРАВА ПОД ВСЕМИ БЛОКАМИ: "EXIT | ВЫХОД"
        # ======================================================================
        self.lbl_bottom_hint = Label()
        self.lbl_bottom_hint.Text = u"Окно работает параллельно с Revit — для каждого из 3 слотов можно выбрать свой вид Revit или картинку с диска."
        self.lbl_bottom_hint.Location = Point(20, 810)
        self.lbl_bottom_hint.Size = Size(920, 24)
        self.lbl_bottom_hint.Font = self.font_small
        self.lbl_bottom_hint.ForeColor = self.col_muted
        self.Controls.Add(self.lbl_bottom_hint)

        self.btn_exit_bottom = self._create_button(
            self,
            u"EXIT | ВЫХОД",
            1006,
            804,
            180,
            36,
            self.col_dark,
            Color.White,
            bold=True,
        )
        self.btn_exit_bottom.Click += lambda s, a: self.Close()

        self.Resize += self._on_form_resize
        self.FormClosed += self._on_form_closed

        # --- ИНИЦИАЛИЗАЦИЯ ДАННЫХ ---
        self._init_profiles_and_inputs(init_api_key, init_base_url)
        self._init_all_slots(init_slot1_in, init_slot2_in, init_slot3_in)
        self._refresh_models_list(auto_startup=True)
        self._apply_responsive_layout()

    # --------------------------------------------------------------------------
    # АДАПТИВНАЯ ВЕРСТКА ПРИ РАСТЯГИВАНИИ / УМЕНЬШЕНИИ ОКНА
    # --------------------------------------------------------------------------
    def _on_form_resize(self, sender, args):
        try:
            self._apply_responsive_layout()
        except Exception:
            pass

    def _apply_responsive_layout(self):
        cw = self.ClientSize.Width
        ch = self.ClientSize.Height
        if cw < 400 or ch < 400:
            return

        margin = 16
        gap = 14
        header_h = 50
        top_row_h = 198
        prog_h = 104
        footer_h = 46

        self.pnl_header.Size = Size(cw, header_h)
        self.lbl_app_sub.Location = Point(max(480, cw - 665), 16)
        self.lbl_app_sub.Size = Size(645, 20)

        total_w = cw - margin * 2
        left_w = max(480, int(total_w * 0.46))
        right_w = max(490, total_w - left_w - gap)
        right_x = margin + left_w + gap

        mid_y = header_h + 12 + top_row_h + 12
        mid_h = max(385, ch - mid_y - prog_h - footer_h - 20)

        # Карточка 1
        self.card_conn.Location = Point(margin, header_h + 12)
        self.card_conn.Size = Size(left_w, top_row_h)
        inner_l = left_w - 28
        self.btn_del_prof.Location = Point(left_w - 14 - 78, 34)
        self.btn_save_prof.Location = Point(self.btn_del_prof.Location.X - 6 - 94, 34)
        self.cmb_profile.Size = Size(max(140, self.btn_save_prof.Location.X - 96), 24)
        self.txt_base_url.Size = Size(max(200, left_w - 104), 24)
        self.btn_toggle_key.Location = Point(left_w - 14 - 74, 103)
        self.txt_api_key.Size = Size(max(180, self.btn_toggle_key.Location.X - 96), 24)
        self.btn_fetch_models.Size = Size(inner_l, 34)
        self.lbl_prof_path.Size = Size(inner_l, 16)

        # Карточка 2
        self.card_models.Location = Point(right_x, header_h + 12)
        self.card_models.Size = Size(right_w, top_row_h)
        inner_r = right_w - 28
        self.lbl_sec2.Size = Size(max(280, right_w - 175), 20)
        self.lbl_models_status.Location = Point(max(300, right_w - 164), 11)
        self.lbl_models_status.Size = Size(150, 18)
        self.lst_models.Size = Size(inner_r, 102)
        self.txt_endpoint.Size = Size(max(200, right_w - 102), 22)
        self.chk_send_image.Size = Size(inner_r, 22)

        # Карточка 3 (слева: поиск + 3 универсальных слота + промпт + параметры + START)
        self.card_view.Location = Point(margin, mid_y)
        self.card_view.Size = Size(left_w, mid_h)
        self.lbl_sec3.Size = Size(inner_l, 20)

        self.chk_all_views.Location = Point(left_w - 14 - 145, 36)
        self.chk_all_views.Size = Size(145, 20)
        self.btn_clear_search.Location = Point(self.chk_all_views.Location.X - 6 - 56, 33)
        self.txt_view_search.Size = Size(max(120, self.btn_clear_search.Location.X - 100), 24)

        for s_idx in range(3):
            row_y = 66 + s_idx * 30
            self.slot_clear_btns[s_idx].Location = Point(left_w - 14 - 26, row_y - 1)
            self.slot_file_btns[s_idx].Location = Point(self.slot_clear_btns[s_idx].Location.X - 4 - 68, row_y - 1)
            cmb_w = max(160, self.slot_file_btns[s_idx].Location.X - 94 - 6)
            self.slot_combos[s_idx].Location = Point(94, row_y)
            self.slot_combos[s_idx].Size = Size(cmb_w, 24)

        btn_start_y = mid_h - 56
        dir_row_y = btn_start_y - 35
        size_row_y = dir_row_y - 32
        prompt_top_y = 180
        prompt_h = max(56, size_row_y - prompt_top_y - 8)

        self.lbl_pr.Location = Point(14, 160)
        self.lbl_pr.Size = Size(inner_l, 18)
        self.txt_prompt.Location = Point(14, prompt_top_y)
        self.txt_prompt.Size = Size(inner_l, prompt_h)

        self.lbl_sz.Location = Point(14, size_row_y + 2)
        self.num_size.Location = Point(142, size_row_y)
        self.lbl_st.Location = Point(242, size_row_y + 2)
        self.num_steps.Location = Point(332, size_row_y)
        self.lbl_st_hint.Location = Point(402, size_row_y + 3)

        self.lbl_dir.Location = Point(14, dir_row_y + 2)
        self.btn_browse_dir.Location = Point(left_w - 14 - 75, dir_row_y - 1)
        self.txt_out_dir.Location = Point(126, dir_row_y)
        self.txt_out_dir.Size = Size(max(150, self.btn_browse_dir.Location.X - 132), 24)

        self.btn_generate.Location = Point(14, btn_start_y)
        self.btn_generate.Size = Size(inner_l, 44)

        # Карточка 4 (справа — сетка 2x2 из 4 превью)
        self.card_prev.Location = Point(right_x, mid_y)
        self.card_prev.Size = Size(right_w, mid_h)
        self.btn_open_compare.Location = Point(right_w - 14 - 122, 7)
        self.lbl_sec4.Size = Size(max(260, right_w - 150), 20)

        col_gap = 14
        cell_w = max(180, int((inner_r - col_gap) / 2))
        avail_h = max(210, mid_h - 34 - 44)
        row_block_h = int((avail_h - 8) / 2)
        pic_h = max(90, row_block_h - 22)

        col1_x = 14
        col2_x = 14 + cell_w + col_gap
        row1_hdr_y = 34
        row1_pic_y = row1_hdr_y + 21
        row2_hdr_y = row1_pic_y + pic_h + 8
        row2_pic_y = row2_hdr_y + 21

        # Слот 1 (верхний левый)
        self.slot_checkboxes[0].Location = Point(col1_x, row1_hdr_y)
        self.slot_checkboxes[0].Size = Size(cell_w, 20)
        self.slot_pic_boxes[0].Location = Point(col1_x, row1_pic_y)
        self.slot_pic_boxes[0].Size = Size(cell_w, pic_h)
        self.slot_placeholders[0].Location = Point(4, 4)
        self.slot_placeholders[0].Size = Size(max(60, cell_w - 8), max(40, pic_h - 8))

        # Слот 2 (верхний правый)
        self.slot_checkboxes[1].Location = Point(col2_x, row1_hdr_y)
        self.slot_checkboxes[1].Size = Size(cell_w, 20)
        self.slot_pic_boxes[1].Location = Point(col2_x, row1_pic_y)
        self.slot_pic_boxes[1].Size = Size(cell_w, pic_h)
        self.slot_placeholders[1].Location = Point(4, 4)
        self.slot_placeholders[1].Size = Size(max(60, cell_w - 8), max(40, pic_h - 8))

        # Слот 3 (нижний левый)
        self.slot_checkboxes[2].Location = Point(col1_x, row2_hdr_y)
        self.slot_checkboxes[2].Size = Size(cell_w, 20)
        self.slot_pic_boxes[2].Location = Point(col1_x, row2_pic_y)
        self.slot_pic_boxes[2].Size = Size(cell_w, pic_h)
        self.slot_placeholders[2].Location = Point(4, 4)
        self.slot_placeholders[2].Size = Size(max(60, cell_w - 8), max(40, pic_h - 8))

        # Слот 4 (нижний правый — Результат AI)
        self.lbl_prev_right.Location = Point(col2_x, row2_hdr_y + 1)
        self.lbl_prev_right.Size = Size(cell_w, 18)
        self.pic_result.Location = Point(col2_x, row2_pic_y)
        self.pic_result.Size = Size(cell_w, pic_h)

        self.lbl_preview_meta.Location = Point(14, row2_pic_y + pic_h + 5)
        self.lbl_preview_meta.Size = Size(inner_r, 34)

        # Карточка 5
        prog_y = mid_y + mid_h + 10
        self.card_prog.Location = Point(margin, prog_y)
        self.card_prog.Size = Size(total_w, prog_h)
        self.lbl_stage.Size = Size(total_w - 28, 20)
        self.progress_bar.Size = Size(total_w - 28, 13)
        self.txt_log.Size = Size(total_w - 28, 46)

        # Кнопка EXIT | ВЫХОД внизу справа
        exit_y = prog_y + prog_h + 8
        self.lbl_bottom_hint.Location = Point(margin + 2, exit_y + 8)
        self.lbl_bottom_hint.Size = Size(max(300, total_w - 200), 22)
        self.btn_exit_bottom.Location = Point(cw - margin - 180, exit_y)
        self.btn_exit_bottom.Size = Size(180, 36)

    def _on_form_closed(self, sender, args):
        for pic_box in list(self.slot_pic_boxes) + [self.pic_result]:
            try:
                if pic_box.Image is not None:
                    pic_box.Image.Dispose()
            except Exception:
                pass
        try:
            AppDomain.CurrentDomain.SetData("DynamoChutesAI_ActiveForm", None)
        except Exception:
            pass

    # --------------------------------------------------------------------------
    # ЛОГИРОВАНИЕ И ИНФОРМАЦИОННАЯ СТРОКА СЛОТОВ
    # --------------------------------------------------------------------------
    def log_step(self, message, progress_val=0, status_color=None):
        stamp = time.strftime("%H:%M:%S")
        line = u"[{}] {}".format(stamp, u_str(message))
        self.lbl_stage.Text = u_str(message)
        if status_color is not None:
            self.lbl_stage.ForeColor = status_color
        else:
            self.lbl_stage.ForeColor = self.col_dark
        if progress_val is not None:
            self.progress_bar.Value = max(0, min(100, int(progress_val)))
        prev_text = u_str(self.txt_log.Text)
        if prev_text:
            self.txt_log.Text = prev_text + u"\r\n" + line
        else:
            self.txt_log.Text = line
        try:
            self.txt_log.SelectionStart = len(self.txt_log.Text)
            self.txt_log.ScrollToCaret()
        except Exception:
            pass
        Application.DoEvents()

    def _get_slot_short_description(self, s_idx):
        slot = self.slots[s_idx]
        if slot["source_type"] == "file" and slot["file_path"]:
            return u"Файл: {}".format(Path.GetFileName(slot["file_path"]))
        if slot["source_type"] == "view" and slot["view_name"]:
            return u"Вид: {}".format(slot["view_name"])
        return u"не задан"

    def _update_active_slots_summary(self):
        active_parts = []
        for s_idx in range(3):
            slot = self.slots[s_idx]
            if slot["enabled"] and slot["source_type"] in ("view", "file"):
                active_parts.append(u"#{}: {}".format(s_idx + 1, self._get_slot_short_description(s_idx)))
        if active_parts:
            summary_str = u"  |  ".join(active_parts)
        else:
            summary_str = u"нет активных кадров (режим Txt2Img)"
        self.lbl_preview_meta.Text = u"Активные кадры ({}/3): {}".format(len(active_parts), summary_str)

    # --------------------------------------------------------------------------
    # УПРАВЛЕНИЕ ПРОФИЛЯМИ
    # --------------------------------------------------------------------------
    def _init_profiles_and_inputs(self, init_api_key, init_base_url):
        self.cmb_profile.Items.Clear()
        profiles_dict = self.profiles_data.get("profiles", {})
        for p_name in sorted(profiles_dict.keys()):
            self.cmb_profile.Items.Add(u_str(p_name))
        active_name = u_str(self.profiles_data.get("active_profile", u""))
        if active_name in profiles_dict:
            self.cmb_profile.Text = active_name
            prof = profiles_dict[active_name]
            self.txt_base_url.Text = u_str(prof.get("base_url", u"https://api.chutes.ai"))
            self.txt_api_key.Text = u_str(prof.get("api_key", u""))
        elif len(profiles_dict) > 0:
            first_key = sorted(profiles_dict.keys())[0]
            self.cmb_profile.Text = u_str(first_key)
            prof = profiles_dict[first_key]
            self.txt_base_url.Text = u_str(prof.get("base_url", u"https://api.chutes.ai"))
            self.txt_api_key.Text = u_str(prof.get("api_key", u""))
        if init_base_url:
            self.txt_base_url.Text = u_str(init_base_url)
        if init_api_key:
            self.txt_api_key.Text = u_str(init_api_key)

    def _on_profile_selected(self, sender, args):
        p_name = u_str(self.cmb_profile.Text).strip()
        profiles_dict = self.profiles_data.get("profiles", {})
        if p_name in profiles_dict:
            prof = profiles_dict[p_name]
            self.txt_base_url.Text = u_str(prof.get("base_url", u"https://api.chutes.ai"))
            self.txt_api_key.Text = u_str(prof.get("api_key", u""))
            self.profiles_data["active_profile"] = p_name
            save_profiles_data(self.profiles_data)
            self.log_step(u"Загружен профиль '{}'.".format(p_name), progress_val=0)

    def _on_save_profile(self, sender, args):
        p_name = u_str(self.cmb_profile.Text).strip()
        if not p_name:
            p_name = u"Chutes.ai (Основной)"
            self.cmb_profile.Text = p_name
        base_url = u_str(self.txt_base_url.Text).strip() or u"https://api.chutes.ai"
        api_key = u_str(self.txt_api_key.Text).strip()
        last_model = u_str(self.selected_model_info.get("id", u"Qwen-Image-Edit-2511"))
        if "profiles" not in self.profiles_data or not isinstance(self.profiles_data["profiles"], dict):
            self.profiles_data["profiles"] = {}
        self.profiles_data["profiles"][p_name] = {
            "base_url": base_url,
            "api_key": api_key,
            "last_model": last_model,
        }
        self.profiles_data["active_profile"] = p_name
        if p_name not in [u_str(self.cmb_profile.Items[i]) for i in range(self.cmb_profile.Items.Count)]:
            self.cmb_profile.Items.Add(p_name)
        ok = save_profiles_data(self.profiles_data)
        if ok:
            self.log_step(u"Профиль '{}' сохранён.".format(p_name), progress_val=0, status_color=self.col_success)
        else:
            self.log_step(u"Не удалось сохранить файл профиля.", progress_val=0)

    def _on_delete_profile(self, sender, args):
        p_name = u_str(self.cmb_profile.Text).strip()
        profiles_dict = self.profiles_data.get("profiles", {})
        if p_name in profiles_dict and len(profiles_dict) > 1:
            del profiles_dict[p_name]
            first_remaining = sorted(profiles_dict.keys())[0]
            self.profiles_data["active_profile"] = first_remaining
            save_profiles_data(self.profiles_data)
            self._init_profiles_and_inputs(None, None)
            self.log_step(u"Профиль '{}' удалён.".format(p_name), progress_val=0)
        else:
            self.log_step(u"Нельзя удалить единственный профиль.", progress_val=0)

    def _on_toggle_api_key(self, sender, args):
        self.txt_api_key.UseSystemPasswordChar = not self.txt_api_key.UseSystemPasswordChar
        self.btn_toggle_key.Text = u"Показать" if self.txt_api_key.UseSystemPasswordChar else u"Скрыть"

    # --------------------------------------------------------------------------
    # ЗАГРУЗКА И ВЫБОР МОДЕЛЕЙ
    # --------------------------------------------------------------------------
    def _on_fetch_models_click(self, sender, args):
        self._refresh_models_list(auto_startup=False)

    def _refresh_models_list(self, auto_startup=False):
        base_url = u_str(self.txt_base_url.Text).strip() or u"https://api.chutes.ai"
        api_key = u_str(self.txt_api_key.Text).strip()
        if not auto_startup:
            self.log_step(u"Запрос доступных моделей генерации изображений у поставщика...", progress_val=0, status_color=self.col_accent)
        models, note = fetch_provider_image_models(base_url, api_key)
        self.available_models = models
        self.lst_models.Items.Clear()
        for m in self.available_models:
            self.lst_models.Items.Add(u_str(m["id"]))
        target_idx = 0
        prof_name = u_str(self.cmb_profile.Text).strip()
        last_model_id = u"Qwen-Image-Edit-2511"
        if prof_name in self.profiles_data.get("profiles", {}):
            last_model_id = u_str(self.profiles_data["profiles"][prof_name].get("last_model", last_model_id))
        for i, m in enumerate(self.available_models):
            if m["id"].lower() == last_model_id.lower() or m["slug"].lower() == last_model_id.lower():
                target_idx = i
                break
        if self.lst_models.Items.Count > 0:
            self.lst_models.SelectedIndex = target_idx
        self.lbl_models_status.Text = u"Моделей: {} ({})".format(len(self.available_models), note)
        if not auto_startup:
            self.log_step(
                u"Список моделей обновлён ({} шт.).".format(len(self.available_models)),
                progress_val=0,
                status_color=self.col_success,
            )

    def _on_model_selected(self, sender, args):
        idx = self.lst_models.SelectedIndex
        if idx < 0 or idx >= len(self.available_models):
            return
        m = self.available_models[idx]
        self.selected_model_info = m
        self.txt_endpoint.Text = u_str(m.get("endpoint", u""))
        is_edit_model = (m.get("mode") == u"img2img_qwen") or (u"edit" in m.get("id", u"").lower())
        self.chk_send_image.Checked = True if is_edit_model else self.chk_send_image.Checked
        try:
            self.num_steps.Value = int(m.get("default_steps", 4))
        except Exception:
            pass
        self.log_step(
            u"Выбрана модель: {}  |  {}".format(u_str(m.get("id")), u_str(m.get("description", u""))),
            progress_val=0,
        )

    # --------------------------------------------------------------------------
    # УНИВЕРСАЛЬНАЯ ЛОГИКА 3 ВХОДНЫХ СЛОТОВ (ВИД REVIT ИЛИ ФАЙЛ ДЛЯ КАЖДОГО СЛОТА)
    # --------------------------------------------------------------------------
    def _init_all_slots(self, init_slot1_in, init_slot2_in, init_slot3_in):
        """Настраивает стартовые значения всех 3 слотов при открытии окна."""
        # По умолчанию для Слота 1 берем первый доступный (активный) 3D-вид проекта, если не задан вход IN[1]
        if init_slot1_in is not None:
            self._apply_initial_input_to_slot(0, init_slot1_in, default_to_first_view=True)
        elif len(self.all_views) > 0:
            first_v = self.all_views[0]
            self._assign_view_to_slot(0, first_v, enable_slot=True, render_now=False)

        if init_slot2_in is not None:
            self._apply_initial_input_to_slot(1, init_slot2_in, default_to_first_view=False)

        if init_slot3_in is not None:
            self._apply_initial_input_to_slot(2, init_slot3_in, default_to_first_view=False)

        # Заполняем выпадающие списки всех 3 слотов
        self._rebuild_all_slot_combos()

        # Рендерим стартовые превью для активных слотов
        for s_idx in range(3):
            if self.slots[s_idx]["enabled"] and self.slots[s_idx]["source_type"] in ("view", "file"):
                self._refresh_slot_preview(s_idx)
            else:
                self._sync_slot_visual_state(s_idx)

        self._update_active_slots_summary()

    def _apply_initial_input_to_slot(self, s_idx, raw_input, default_to_first_view=False):
        """Разбирает поданный на вход IN[...] объект (путь к файлу, имя вида или элемент View)."""
        if isinstance(raw_input, list) and len(raw_input) > 0:
            raw_input = raw_input[0]

        if isinstance(raw_input, STRING_TYPES):
            s_val = u_str(raw_input).strip()
            if s_val and File.Exists(s_val):
                self._assign_file_to_slot(s_idx, s_val, enable_slot=True, render_now=False)
                return
            if s_val:
                s_low = s_val.lower()
                for v_item in self.all_views:
                    if v_item["name"].lower() == s_low or v_item["label"].lower() == s_low:
                        self._assign_view_to_slot(s_idx, v_item, enable_slot=True, render_now=False)
                        return
        elif raw_input is not None:
            try:
                unwrapped = UnwrapElement(raw_input)
                target_id = get_element_id_int(unwrapped.Id)
                for v_item in self.all_views:
                    if get_element_id_int(v_item["view"].Id) == target_id:
                        self._assign_view_to_slot(s_idx, v_item, enable_slot=True, render_now=False)
                        return
            except Exception:
                pass

        if default_to_first_view and len(self.all_views) > 0:
            self._assign_view_to_slot(s_idx, self.all_views[0], enable_slot=True, render_now=False)

    def _assign_view_to_slot(self, s_idx, v_item, enable_slot=True, render_now=True):
        slot = self.slots[s_idx]
        slot["source_type"] = "view"
        slot["view_obj"] = v_item["view"]
        slot["view_id"] = get_element_id_int(v_item["view"].Id)
        slot["view_name"] = u_str(v_item["name"])
        slot["file_path"] = u""
        if enable_slot:
            slot["enabled"] = True
        if render_now:
            self._refresh_slot_preview(s_idx)
        self._sync_slot_visual_state(s_idx)
        self._update_active_slots_summary()

    def _assign_file_to_slot(self, s_idx, file_path, enable_slot=True, render_now=True):
        if not file_path or not File.Exists(file_path):
            return
        slot = self.slots[s_idx]
        slot["source_type"] = "file"
        slot["file_path"] = u_str(file_path)
        slot["preview_path"] = u_str(file_path)
        slot["view_obj"] = None
        slot["view_id"] = -1
        slot["view_name"] = u""
        if enable_slot:
            slot["enabled"] = True
        self._rebuild_slot_combo(s_idx)
        if render_now:
            self._refresh_slot_preview(s_idx)
        self._sync_slot_visual_state(s_idx)
        self._update_active_slots_summary()

    def _clear_slot(self, s_idx):
        slot = self.slots[s_idx]
        slot["enabled"] = False
        slot["source_type"] = "none"
        slot["view_obj"] = None
        slot["view_id"] = -1
        slot["view_name"] = u""
        slot["file_path"] = u""
        slot["preview_path"] = u""

        pic = self.slot_pic_boxes[s_idx]
        if pic.Image is not None:
            try:
                pic.Image.Dispose()
            except Exception:
                pass
            pic.Image = None

        self._rebuild_slot_combo(s_idx)
        self._sync_slot_visual_state(s_idx)
        self._update_active_slots_summary()
        self.log_step(u"Кадр {} очищен и отключён.".format(s_idx + 1), progress_val=0)

    def _sync_slot_visual_state(self, s_idx):
        """Синхронизирует состояние чекбокса, цвета рамок и заглушки для слота s_idx."""
        slot = self.slots[s_idx]
        is_on = bool(slot["enabled"]) and (slot["source_type"] in ("view", "file"))

        self._suppress_slot_events = True
        try:
            self.slot_checkboxes[s_idx].Checked = is_on
        finally:
            self._suppress_slot_events = False

        self.slot_checkboxes[s_idx].ForeColor = self.col_text if is_on else self.col_muted
        self.slot_row_labels[s_idx].ForeColor = self.col_text if is_on else self.col_muted

        pic = self.slot_pic_boxes[s_idx]
        ph = self.slot_placeholders[s_idx]
        pic.BackColor = self.col_slot_active if is_on else self.col_slot_inactive
        ph.Visible = (pic.Image is None)

        if slot["source_type"] == "file" and slot["file_path"]:
            self.slot_checkboxes[s_idx].Text = u"{}. Кадр {} [Файл: {}]".format(
                s_idx + 1, s_idx + 1, Path.GetFileName(slot["file_path"])
            )
        elif slot["source_type"] == "view" and slot["view_name"]:
            self.slot_checkboxes[s_idx].Text = u"{}. Кадр {} [Вид: {}]".format(
                s_idx + 1, s_idx + 1, slot["view_name"]
            )
        else:
            default_titles = [
                u"1. Кадр 1 (Основной вид / файл)",
                u"2. Кадр 2 (Доп. вид / контуры / файл)",
                u"3. Кадр 3 (Референс / вид / файл)",
            ]
            self.slot_checkboxes[s_idx].Text = default_titles[s_idx]

    def _rebuild_all_slot_combos(self):
        for s_idx in range(3):
            self._rebuild_slot_combo(s_idx)

    def _rebuild_slot_combo(self, s_idx):
        """Заполняет выпадающий список видов для слота s_idx с учётом фильтра поиска и выбранного файла."""
        cmb = self.slot_combos[s_idx]
        slot = self.slots[s_idx]

        self._suppress_slot_events = True
        try:
            cmb.Items.Clear()
            # Позиция 0 — всегда «Не выбран»
            cmb.Items.Add(NONE_VIEW_LABEL)

            selected_combo_idx = 0

            # Если для слота выбран внешний файл с диска, добавляем его строку следующей позицией
            file_item_offset = 0
            if slot["source_type"] == "file" and slot["file_path"]:
                file_label = u"📁 [Файл] " + Path.GetFileName(slot["file_path"])
                cmb.Items.Add(file_label)
                selected_combo_idx = 1
                file_item_offset = 1

            for i, v_item in enumerate(self.filtered_views):
                cmb.Items.Add(u_str(v_item["label"]))
                if slot["source_type"] == "view" and get_element_id_int(v_item["view"].Id) == slot["view_id"]:
                    selected_combo_idx = 1 + file_item_offset + i

            # Если выбранный вид отфильтрован строкой поиска, всё равно показываем его в списке, чтобы выбор не сбрасывался
            if (
                slot["source_type"] == "view"
                and slot["view_id"] != -1
                and selected_combo_idx == 0
                and slot["view_name"]
            ):
                keep_label = u"[Выбранный вид] " + slot["view_name"]
                cmb.Items.Insert(1, keep_label)
                selected_combo_idx = 1

            cmb.SelectedIndex = selected_combo_idx
        finally:
            self._suppress_slot_events = False

    def _refresh_slot_preview(self, s_idx):
        """Строит или загружает превью для указанного слота (0, 1 или 2) и отображает в его PictureBox."""
        slot = self.slots[s_idx]
        pic = self.slot_pic_boxes[s_idx]
        ph = self.slot_placeholders[s_idx]

        if slot["source_type"] == "file":
            f_path = slot["file_path"]
            if not f_path or not File.Exists(f_path):
                return
            try:
                img = load_image_unlocked(f_path)
                if img is not None:
                    if pic.Image is not None:
                        pic.Image.Dispose()
                    pic.Image = img
                    slot["preview_path"] = f_path
                    if s_idx == 0:
                        self.source_image_path = f_path
                    ph.Visible = False
                    self._sync_slot_visual_state(s_idx)
                    self.log_step(
                        u"Кадр {}: загружен файл '{}' ({}x{} px).".format(
                            s_idx + 1, Path.GetFileName(f_path), img.Width, img.Height
                        ),
                        progress_val=0,
                    )
            except Exception as ex:
                self.log_step(u"Ошибка чтения файла для Кадра {}: {}".format(s_idx + 1, u_str(ex)), progress_val=0)

        elif slot["source_type"] == "view":
            target_view = slot["view_obj"]
            if target_view is None or self.doc is None:
                return
            preview_px = max(640, min(2048, int(self.num_size.Value)))
            try:
                prefix_str = u"preview_slot{}".format(s_idx + 1)
                preview_path = self.revit_invoker.run(
                    lambda: export_revit_view_to_png(
                        self.doc,
                        target_view,
                        self.preview_temp_dir,
                        pixel_size=preview_px,
                        file_prefix=prefix_str,
                    ),
                    force_direct=self._is_initializing,
                )
                img = load_image_unlocked(preview_path)
                if img is not None:
                    if pic.Image is not None:
                        pic.Image.Dispose()
                    pic.Image = img
                    slot["preview_path"] = preview_path
                    if s_idx == 0:
                        self.source_image_path = preview_path
                    ph.Visible = False
                    self._sync_slot_visual_state(s_idx)
                    self.log_step(
                        u"Кадр {}: обновлено превью вида '{}' ({}x{} px).".format(
                            s_idx + 1, slot["view_name"], img.Width, img.Height
                        ),
                        progress_val=0,
                    )
            except Exception as ex:
                self.log_step(
                    u"Кадр {}: не удалось построить превью вида '{}': {}".format(
                        s_idx + 1, slot["view_name"], u_str(ex)
                    ),
                    progress_val=0,
                )

    # --------------------------------------------------------------------------
    # ОБРАБОТЧИКИ СОБЫТИЙ СЛОТОВ 1..3 И ПОИСКА ВИДОВ
    # --------------------------------------------------------------------------
    def _on_view_search_changed(self, sender, args):
        q = u_str(self.txt_view_search.Text).strip().lower()
        if q:
            self.filtered_views = [
                v for v in self.all_views
                if (q in v["name"].lower()) or (q in v["label"].lower())
            ]
        else:
            self.filtered_views = list(self.all_views)
        self._rebuild_all_slot_combos()

    def _on_clear_view_search(self, sender, args):
        if u_str(self.txt_view_search.Text) != u"":
            self.txt_view_search.Text = u""

    def _on_toggle_all_views(self, sender, args):
        inc_2d = bool(self.chk_all_views.Checked)
        try:
            self.all_views = self.revit_invoker.run(
                lambda: collect_project_views(self.doc, include_non_3d=inc_2d)
            )
        except Exception:
            self.all_views = collect_project_views(self.doc, include_non_3d=inc_2d)
        self._on_view_search_changed(None, None)

    def _make_slot_combo_handler(self, s_idx):
        def _handler(sender, args):
            if self._suppress_slot_events:
                return
            cmb = self.slot_combos[s_idx]
            sel_text = u_str(cmb.SelectedItem or u"")
            if cmb.SelectedIndex <= 0 or sel_text == NONE_VIEW_LABEL:
                self._clear_slot(s_idx)
                return
            if sel_text.startswith(u"📁 [Файл]") or sel_text.startswith(u"[Выбранный вид]"):
                return

            # Ищем выбранный вид по метке в filtered_views
            matched_v = None
            for v_item in self.filtered_views:
                if u_str(v_item["label"]) == sel_text:
                    matched_v = v_item
                    break
            if matched_v is not None:
                self._assign_view_to_slot(s_idx, matched_v, enable_slot=True, render_now=True)
                self._rebuild_slot_combo(s_idx)

        return _handler

    def _make_slot_file_handler(self, s_idx):
        def _handler(sender, args):
            self._pick_file_for_slot(s_idx)

        return _handler

    def _make_slot_clear_handler(self, s_idx):
        def _handler(sender, args):
            self._clear_slot(s_idx)

        return _handler

    def _make_slot_chk_handler(self, s_idx):
        def _handler(sender, args):
            if self._suppress_slot_events:
                return
            chk = self.slot_checkboxes[s_idx]
            slot = self.slots[s_idx]
            want_on = bool(chk.Checked)
            if want_on and slot["source_type"] == "none":
                # Если источник для слота еще не задан — предлагаем выбрать файл (или пользователь может выбрать вид в списке)
                picked = self._pick_file_for_slot(s_idx)
                if not picked and slot["source_type"] == "none":
                    self._suppress_slot_events = True
                    chk.Checked = False
                    self._suppress_slot_events = False
                    return
            else:
                slot["enabled"] = want_on
                self._sync_slot_visual_state(s_idx)
                self._update_active_slots_summary()

        return _handler

    def _make_slot_placeholder_click_handler(self, s_idx):
        def _handler(sender, args):
            slot = self.slots[s_idx]
            if slot["source_type"] in ("view", "file"):
                slot["enabled"] = True
                self._refresh_slot_preview(s_idx)
            else:
                self._pick_file_for_slot(s_idx)

        return _handler

    def _make_slot_pic_click_handler(self, s_idx):
        def _handler(sender, args):
            slot = self.slots[s_idx]
            pic = self.slot_pic_boxes[s_idx]
            p_path = slot["preview_path"] or slot["file_path"]
            if pic.Image is not None or (p_path and File.Exists(p_path)):
                show_full_image_window(
                    p_path,
                    u"Превью {}: {}".format(s_idx + 1, self._get_slot_short_description(s_idx)),
                    live_bitmap=pic.Image,
                )
            else:
                self._pick_file_for_slot(s_idx)

        return _handler

    def _pick_file_for_slot(self, s_idx):
        dlg = OpenFileDialog()
        dlg.Title = u"Выберите изображение для Кадра {} (или выберите 3D-вид в выпадающем списке)".format(s_idx + 1)
        dlg.Filter = u"Изображения (*.png;*.jpg;*.jpeg;*.bmp;*.webp)|*.png;*.jpg;*.jpeg;*.bmp;*.webp|Все файлы (*.*)|*.*"

        # По умолчанию открываем папку сохранения рендеров (или папку текущего файла слота)
        slot = self.slots[s_idx]
        init_dir = u""
        if slot["file_path"] and File.Exists(slot["file_path"]):
            init_dir = Path.GetDirectoryName(slot["file_path"])
        if not init_dir or not Directory.Exists(init_dir):
            out_dir_curr = u_str(self.txt_out_dir.Text).strip()
            if out_dir_curr:
                if not Directory.Exists(out_dir_curr):
                    try:
                        Directory.CreateDirectory(out_dir_curr)
                    except Exception:
                        pass
                if Directory.Exists(out_dir_curr):
                    init_dir = out_dir_curr
        if init_dir and Directory.Exists(init_dir):
            dlg.InitialDirectory = init_dir

        if dlg.ShowDialog() == DialogResult.OK:
            picked_path = u_str(dlg.FileName)
            self._assign_file_to_slot(s_idx, picked_path, enable_slot=True, render_now=True)
            return picked_path
        return u""

    # --------------------------------------------------------------------------
    # ПРОСМОТР РЕЗУЛЬТАТА И ОКНО СРАВНЕНИЯ «ДО / ПОСЛЕ»
    # --------------------------------------------------------------------------
    def _on_result_preview_click(self, sender, args):
        if self.pic_result.Image is not None or (self.result_image_path and File.Exists(self.result_image_path)):
            show_full_image_window(
                self.result_image_path,
                u"Превью 4: Результат AI — " + u_str(self.selected_model_info.get("id", u"Chutes.ai")),
                live_bitmap=self.pic_result.Image,
            )

    def _on_browse_out_dir(self, sender, args):
        dlg = FolderBrowserDialog()
        dlg.Description = u"Выберите папку для сохранения AI-рендеров"
        dlg.SelectedPath = u_str(self.txt_out_dir.Text)
        if dlg.ShowDialog() == DialogResult.OK:
            self.txt_out_dir.Text = u_str(dlg.SelectedPath)

    def _on_open_compare_click(self, sender, args):
        inputs_for_cmp = []
        for s_idx in range(3):
            slot = self.slots[s_idx]
            p_path = slot["preview_path"] or slot["file_path"]
            if slot["enabled"] and p_path and File.Exists(p_path):
                inputs_for_cmp.append(
                    (u"Кадр {} ({})".format(s_idx + 1, self._get_slot_short_description(s_idx)), p_path)
                )
        if len(inputs_for_cmp) == 0:
            for s_idx in range(3):
                p_path = self.slots[s_idx]["preview_path"] or self.slots[s_idx]["file_path"]
                if p_path and File.Exists(p_path):
                    inputs_for_cmp.append((u"Кадр {}".format(s_idx + 1), p_path))
                    break

        if self.result_image_path and File.Exists(self.result_image_path):
            show_comparison_window(
                inputs_for_cmp,
                self.result_image_path,
                self._get_primary_label(),
                u_str(self.txt_prompt.Text),
                u_str(self.selected_model_info.get("id", u"Chutes.ai")),
            )

    def _get_primary_label(self):
        for s_idx in range(3):
            slot = self.slots[s_idx]
            if slot["enabled"] and slot["source_type"] in ("view", "file"):
                return self._get_slot_short_description(s_idx)
        return u"AI Render"

    # --------------------------------------------------------------------------
    # ЗАПУСК ЭКСПОРТА АКТИВНЫХ КАДРОВ (1..3) И AI-ГЕНЕРАЦИИ ("START | НАЧАТЬ")
    # --------------------------------------------------------------------------
    def _on_generate_click(self, sender, args):
        api_key = u_str(self.txt_api_key.Text).strip()
        if not api_key:
            MessageBox.Show(
                u"Пожалуйста, введите API Key (например, cpk_...) в разделе 1 и при необходимости сохраните профиль.",
                u"Требуется API Key",
                MessageBoxButtons.OK,
                MessageBoxIcon.Warning,
            )
            return

        endpoint_url = u_str(self.txt_endpoint.Text).strip()
        if not endpoint_url:
            endpoint_url = u"https://vonkaiser-qwen-image-edit-2511.chutes.ai/generate"
            self.txt_endpoint.Text = endpoint_url

        out_dir = u_str(self.txt_out_dir.Text).strip()
        if not out_dir:
            desktop = Environment.GetFolderPath(Environment.SpecialFolder.Desktop)
            out_dir = Path.Combine(desktop, u"Chutes_Renders")
            self.txt_out_dir.Text = out_dir

        max_side_px = int(self.num_size.Value)
        steps_val = int(self.num_steps.Value)
        prompt_text = u_str(self.txt_prompt.Text).strip()
        send_img_master = bool(self.chk_send_image.Checked)

        try:
            p_name = u_str(self.cmb_profile.Text).strip()
            if p_name and p_name in self.profiles_data.get("profiles", {}):
                self.profiles_data["profiles"][p_name]["last_model"] = u_str(
                    self.selected_model_info.get("id", u"")
                )
                save_profiles_data(self.profiles_data)
        except Exception:
            pass

        self.btn_generate.Enabled = False
        self.Cursor = Cursors.WaitCursor

        try:
            if not Directory.Exists(out_dir):
                Directory.CreateDirectory(out_dir)

            b64_images_list = []
            active_labels = []
            exported_slot_paths = [u"", u"", u""]
            dimension_ref_path = u""

            # ЭТАП 1: Подготовка всех отмеченных галочками входных слотов (1..3)
            if send_img_master:
                for s_idx in range(3):
                    slot = self.slots[s_idx]
                    if not slot["enabled"] or slot["source_type"] == "none":
                        continue

                    if slot["source_type"] == "view":
                        target_view = slot["view_obj"]
                        if target_view is None or self.doc is None:
                            raise Exception(u"Кадр {}: выбранный вид Revit недоступен.".format(s_idx + 1))

                        self.log_step(
                            u"[1/4] Кадр {}: экспорт вида '{}' из Revit ({} px)...".format(
                                s_idx + 1, slot["view_name"], max_side_px
                            ),
                            progress_val=10 + s_idx * 8,
                            status_color=self.col_accent,
                        )
                        prefix_str = u"slot{}_view".format(s_idx + 1)
                        exp_path = self.revit_invoker.run(
                            lambda: export_revit_view_to_png(
                                self.doc,
                                target_view,
                                out_dir,
                                pixel_size=max_side_px,
                                file_prefix=prefix_str,
                            )
                        )
                        slot["preview_path"] = exp_path
                        exported_slot_paths[s_idx] = exp_path
                        if not dimension_ref_path:
                            dimension_ref_path = exp_path

                        img_upd = load_image_unlocked(exp_path)
                        if img_upd is not None:
                            pic_box = self.slot_pic_boxes[s_idx]
                            if pic_box.Image is not None:
                                pic_box.Image.Dispose()
                            pic_box.Image = img_upd
                            self.slot_placeholders[s_idx].Visible = False

                        b64_images_list.append(file_to_base64_str(exp_path))
                        active_labels.append(u"#{}:Вид({})".format(s_idx + 1, slot["view_name"]))

                    elif slot["source_type"] == "file":
                        f_path = slot["file_path"]
                        if not f_path or not File.Exists(f_path):
                            raise Exception(u"Кадр {}: файл '{}' не найден.".format(s_idx + 1, f_path))

                        self.log_step(
                            u"[1/4] Кадр {}: чтение файла '{}'...".format(
                                s_idx + 1, Path.GetFileName(f_path)
                            ),
                            progress_val=10 + s_idx * 8,
                            status_color=self.col_accent,
                        )
                        slot["preview_path"] = f_path
                        exported_slot_paths[s_idx] = f_path
                        if not dimension_ref_path:
                            dimension_ref_path = f_path

                        b64_images_list.append(file_to_base64_str(f_path))
                        active_labels.append(u"#{}:Файл({})".format(s_idx + 1, Path.GetFileName(f_path)))

            if exported_slot_paths[0]:
                self.source_image_path = exported_slot_paths[0]
            elif dimension_ref_path:
                self.source_image_path = dimension_ref_path

            # ЭТАП 2: Вычисление пропорций кадра (по первому активному слоту) и сборка JSON-пакета
            if dimension_ref_path and File.Exists(dimension_ref_path):
                target_w, target_h = calc_target_dimensions(dimension_ref_path, max_side_px)
            else:
                target_w, target_h = max_side_px, max_side_px

            self.log_step(
                u"[2/4] Расчёт пропорций ({}x{}) и упаковка {} кадров в Base64...".format(
                    target_w, target_h, len(b64_images_list)
                ),
                progress_val=38,
                status_color=self.col_accent,
            )

            payload = build_generation_payload(
                self.selected_model_info,
                prompt_text,
                b64_images_list,
                target_w,
                target_h,
                steps_val,
                send_source_image=(send_img_master and len(b64_images_list) > 0),
            )

            # ЭТАП 3: Фоновая отправка HTTP-запроса с живым таймером в UI
            model_id = u_str(self.selected_model_info.get("id", u"Chutes.ai"))
            imgs_info_str = u", ".join(active_labels) if active_labels else u"txt2img"
            self.log_step(
                u"[3/4] Отправка в {} ({}x{}, steps={}, кадры: [{}])... Ожидание ответа".format(
                    model_id, target_w, target_h, steps_val, imgs_info_str
                ),
                progress_val=50,
                status_color=self.col_accent,
            )

            worker_state = {"done": False, "status": -1, "result": u""}

            def _bg_request():
                st, res = send_image_generation_request(endpoint_url, api_key, payload, out_dir)
                worker_state["status"] = st
                worker_state["result"] = res
                worker_state["done"] = True

            t_start = time.time()
            bg_thread = Thread(ThreadStart(_bg_request))
            bg_thread.IsBackground = True
            bg_thread.Start()

            while not worker_state["done"]:
                elapsed = round(time.time() - t_start, 1)
                dyn_prog = min(95, 50 + int(elapsed * 2.5))
                self.progress_bar.Value = dyn_prog
                self.lbl_stage.Text = u"[3/4] Генерация на сервере {} (отправлено кадров: {})... Прошло {:.1f} сек.".format(
                    model_id, len(b64_images_list), elapsed
                )
                Application.DoEvents()
                Thread.Sleep(100)

            elapsed_sec = round(time.time() - t_start, 2)
            http_status = worker_state["status"]
            result_val = worker_state["result"]

            # ЭТАП 4: Обработка результата и показ в Превью 4
            if http_status == 200 and File.Exists(u_str(result_val)):
                self.result_image_path = u_str(result_val)
                res_img = load_image_unlocked(self.result_image_path)
                if res_img is not None:
                    if self.pic_result.Image is not None:
                        self.pic_result.Image.Dispose()
                    self.pic_result.Image = res_img

                self.btn_open_compare.Enabled = True
                self.execution_succeeded = True

                self.status_message = u"HTTP 200 | model: {} | imgs: {} | {}x{} | steps: {} | {}s".format(
                    model_id, len(b64_images_list), target_w, target_h, steps_val, elapsed_sec
                )
                self.meta_result = {
                    "version": u"3.0",
                    "model": model_id,
                    "endpoint": endpoint_url,
                    "prompt": prompt_text,
                    "width": target_w,
                    "height": target_h,
                    "num_inference_steps": steps_val,
                    "elapsed_sec": elapsed_sec,
                    "images_sent_count": len(b64_images_list),
                    "active_inputs": active_labels,
                    "slot1_image": exported_slot_paths[0],
                    "slot2_image": exported_slot_paths[1],
                    "slot3_image": exported_slot_paths[2],
                    "result_image": self.result_image_path,
                }
                self.lbl_preview_meta.Text = u"Готово за {} сек. (отправлено кадров: {}/3)! Кликните на любое превью для увеличения.".format(
                    elapsed_sec, len(b64_images_list)
                )
                self.log_step(
                    u"[4/4] Успешно! Рендер сохранён: {} ({} сек., кадров: {})".format(
                        self.result_image_path, elapsed_sec, len(b64_images_list)
                    ),
                    progress_val=100,
                    status_color=self.col_success,
                )
            else:
                self.status_message = u"HTTP {} | error: {}".format(http_status, u_str(result_val))
                self.meta_result = {
                    "version": u"3.0",
                    "model": model_id,
                    "endpoint": endpoint_url,
                    "error": u_str(result_val),
                }
                self.log_step(
                    u"Ошибка генерации (HTTP {}): {}".format(http_status, u_str(result_val)[:180]),
                    progress_val=0,
                    status_color=Color.FromArgb(220, 38, 38),
                )

        except Exception as ex:
            self.status_message = u"ERROR: {}".format(u_str(ex))
            self.log_step(u"Ошибка выполнения: {}".format(u_str(ex)), progress_val=0, status_color=Color.FromArgb(220, 38, 38))
        finally:
            self.btn_generate.Enabled = True
            self.Cursor = Cursors.Default


# ==============================================================================
# 9. ТОЧКА ВХОДА НОДА DYNAMO (НЕМОДАЛЬНЫЙ ЗАПУСК ПАРАЛЛЕЛЬНО С REVIT)
# ==============================================================================

init_api_key = get_input(0, None)
init_slot1_in = get_input(1, None)
init_prompt = get_input(
    2,
    u"Convert this 3D CAD view into a photorealistic architectural render, preserve exact building contours and geometry, glass and concrete facade, sunny day",
)
init_base_url = get_input(3, u"https://api.chutes.ai")

desktop_dir = Environment.GetFolderPath(Environment.SpecialFolder.Desktop)
default_out_dir = Path.Combine(desktop_dir, u"Chutes_Renders")
init_out_dir = u_str(get_input(4, default_out_dir))

try:
    init_max_side = int(get_input(5, 1024))
except Exception:
    init_max_side = 1024

try:
    init_steps = int(get_input(6, 4))
except Exception:
    init_steps = 4

# Необязательные входы IN[7] и IN[8] для стартовой инициализации Кадра 2 и Кадра 3 (вид Revit или путь к файлу)
init_slot2_in = get_input(7, None)
init_slot3_in = get_input(8, None)

try:
    current_doc = DocumentManager.Instance.CurrentDBDocument
except Exception:
    current_doc = None

try:
    current_uiapp = DocumentManager.Instance.CurrentUIApplication
except Exception:
    current_uiapp = None

try:
    prev_form = AppDomain.CurrentDomain.GetData("DynamoChutesAI_ActiveForm")
    if prev_form is not None:
        prev_form.Close()
except Exception:
    pass

try:
    revit_invoker = RevitApiInvoker(current_uiapp)
    studio_form = ChutesRevitStudioForm(
        current_doc,
        revit_invoker,
        init_api_key,
        init_slot1_in,
        init_prompt,
        init_base_url,
        init_out_dir,
        init_max_side,
        init_steps,
        init_slot2_in,
        init_slot3_in,
    )
    AppDomain.CurrentDomain.SetData("DynamoChutesAI_ActiveForm", studio_form)
    studio_form.Show()

    OUT = [
        studio_form.result_image_path,
        studio_form.source_image_path,
        studio_form.status_message,
        studio_form.meta_result,
    ]
except Exception as main_ex:
    OUT = [u"", u"", u"UI ERROR: {}".format(u_str(main_ex)), {}]
