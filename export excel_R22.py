# -*- coding: utf-8 -*-
import clr
import sys
import os
import re
import tempfile
import shutil
import System
from System.Runtime.InteropServices import Marshal

clr.AddReference("RevitServices")
from RevitServices.Persistence import DocumentManager

clr.AddReference("RevitAPI")
import Autodesk.Revit.DB as DB
from Autodesk.Revit.DB import (
    ScheduleSheetInstance, ViewSchedule, SectionType,
    HorizontalAlignmentStyle, VerticalAlignmentStyle,
    BuiltInParameter, GraphicsStyleType, FilteredElementCollector, ImageType
)

clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")
from System.Windows.Forms import (
    Application, Form, Label, TextBox, Button, 
    FolderBrowserDialog, DialogResult, MessageBox, 
    MessageBoxButtons, MessageBoxIcon, FormStartPosition, 
    FormBorderStyle
)
from System.Drawing import Point, Size, Font, FontStyle
from System.Drawing.Imaging import ImageFormat

clr.AddReference("Microsoft.Office.Interop.Excel")
import Microsoft.Office.Interop.Excel as Excel

doc = DocumentManager.Instance.CurrentDBDocument
uidoc = DocumentManager.Instance.CurrentUIApplication.ActiveUIDocument

# --- 1. ПОЛУЧЕНИЕ ВЫБРАННЫХ СПЕЦИФИКАЦИЙ ---
selection_ids = uidoc.Selection.GetElementIds()
schedules_to_export = []
seen_schedule_ids = set()

for el_id in selection_ids:
    el = doc.GetElement(el_id)
    sched = None
    
    if isinstance(el, ScheduleSheetInstance) and not el.IsTitleblockRevisionSchedule:
        sched = doc.GetElement(el.ScheduleId)
    elif isinstance(el, ViewSchedule) and not el.IsTitleblockRevisionSchedule:
        sched = el
        
    if sched and sched.Id.IntegerValue not in seen_schedule_ids:
        seen_schedule_ids.add(sched.Id.IntegerValue)
        schedules_to_export.append(sched)

# --- 2. ПРОВЕРКА ВЫБОРА ---
if not schedules_to_export:
    MessageBox.Show(
        "Не выбрано ни одной спецификации!\n\nПожалуйста, выделите одну или несколько спецификаций на листе перед запуском скрипта.",
        "Экспорт спецификаций АИ",
        MessageBoxButtons.OK,
        MessageBoxIcon.Warning
    )
    OUT = "Отмена: элементы не выбраны."
else:
    # --- 3. UI ВЫБОРА ПУТИ ---
    class ExportSchedulesForm(Form):
        def __init__(self, count):
            self.Text = "Экспорт спецификаций в Excel"
            self.Size = Size(480, 210)
            self.StartPosition = FormStartPosition.CenterScreen
            self.FormBorderStyle = FormBorderStyle.FixedDialog
            self.MaximizeBox = False
            self.MinimizeBox = False
            self.SelectedPath = ""
            
            lbl_info = Label()
            lbl_info.Text = "Выбрано уникальных спецификаций: {}".format(count)
            lbl_info.Font = Font("Segoe UI", 10, FontStyle.Bold)
            lbl_info.Location = Point(15, 15)
            lbl_info.Size = Size(440, 22)
            self.Controls.Add(lbl_info)
            
            lbl_path = Label()
            lbl_path.Text = "Укажите папку для сохранения файлов Excel:"
            lbl_path.Font = Font("Segoe UI", 9)
            lbl_path.Location = Point(15, 48)
            lbl_path.Size = Size(440, 20)
            self.Controls.Add(lbl_path)
            
            self.txt_path = TextBox()
            self.txt_path.Font = Font("Segoe UI", 9)
            self.txt_path.Location = Point(15, 72)
            self.txt_path.Size = Size(340, 24)
            self.txt_path.Text = os.path.expanduser("~\\Desktop")
            self.Controls.Add(self.txt_path)
            
            btn_browse = Button()
            btn_browse.Text = "Обзор..."
            btn_browse.Font = Font("Segoe UI", 9)
            btn_browse.Location = Point(365, 70)
            btn_browse.Size = Size(85, 26)
            btn_browse.Click += self.on_browse
            self.Controls.Add(btn_browse)
            
            btn_ok = Button()
            btn_ok.Text = "Экспортировать"
            btn_ok.Font = Font("Segoe UI", 9, FontStyle.Bold)
            btn_ok.Location = Point(235, 120)
            btn_ok.Size = Size(120, 32)
            btn_ok.Click += self.on_ok
            self.Controls.Add(btn_ok)
            
            btn_cancel = Button()
            btn_cancel.Text = "Отмена"
            btn_cancel.Font = Font("Segoe UI", 9)
            btn_cancel.Location = Point(365, 120)
            btn_cancel.Size = Size(85, 32)
            btn_cancel.Click += self.on_cancel
            self.Controls.Add(btn_cancel)
            
        def on_browse(self, sender, args):
            fbd = FolderBrowserDialog()
            fbd.Description = "Выберите папку для сохранения таблиц Excel"
            if os.path.exists(self.txt_path.Text):
                fbd.SelectedPath = self.txt_path.Text
            if fbd.ShowDialog() == DialogResult.OK:
                self.txt_path.Text = fbd.SelectedPath
                
        def on_ok(self, sender, args):
            path = self.txt_path.Text.strip()
            if not path or not os.path.exists(path):
                MessageBox.Show("Указанная папка не существует!", "Ошибка", MessageBoxButtons.OK, MessageBoxIcon.Error)
                return
            self.SelectedPath = path
            self.DialogResult = DialogResult.OK
            self.Close()
            
        def on_cancel(self, sender, args):
            self.DialogResult = DialogResult.Cancel
            self.Close()

    # --- 4. ИНДЕКСАЦИЯ ИЗОБРАЖЕНИЙ В ДОКУМЕНТЕ ---
    image_types_map = {}
    for img_t in FilteredElementCollector(doc).OfClass(ImageType):
        try:
            t_name = DB.Element.Name.__get__(img_t)
            if t_name:
                image_types_map[t_name] = img_t
                base_name = os.path.splitext(t_name)[0]
                if base_name not in image_types_map:
                    image_types_map[base_name] = img_t
        except:
            pass

    def get_cached_image_info(cell_text, temp_dir, cache_dict):
        if not cell_text:
            return None
        key = cell_text.strip()
        if not key:
            return None
            
        img_t = image_types_map.get(key)
        if not img_t:
            base_key = os.path.splitext(key)[0]
            img_t = image_types_map.get(base_key)
            
        if not img_t:
            return None
            
        img_id = img_t.Id.IntegerValue
        if img_id in cache_dict:
            return cache_dict[img_id]
            
        try:
            bmp = img_t.GetImage()
            if bmp:
                temp_path = os.path.join(temp_dir, "revit_img_{}.png".format(img_id))
                bmp.Save(temp_path, ImageFormat.Png)
                w_px = float(bmp.Width)
                h_px = float(bmp.Height)
                bmp.Dispose()
                info = (temp_path, w_px, h_px)
                cache_dict[img_id] = info
                return info
        except:
            pass
            
        cache_dict[img_id] = None
        return None

    # --- 5. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
    def clean_filename(name):
        return re.sub(r'[\\/*?:"<>|]', '_', name)

    def rgb_to_ole(revit_color):
        if not revit_color or not revit_color.IsValid:
            return None
        return revit_color.Red + (revit_color.Green * 256) + (revit_color.Blue * 65536)

    def get_xl_halign(revit_halign):
        if revit_halign == HorizontalAlignmentStyle.Center:
            return -4108
        elif revit_halign == HorizontalAlignmentStyle.Right:
            return -4152
        return -4131

    def get_xl_valign(revit_valign):
        if revit_valign == VerticalAlignmentStyle.Middle:
            return -4108
        elif revit_valign == VerticalAlignmentStyle.Bottom:
            return -4107
        return -4160

    def get_xl_border_weight(line_style_id):
        if line_style_id and line_style_id.IntegerValue != -1:
            gs = doc.GetElement(line_style_id)
            if gs and hasattr(gs, "GraphicsStyleCategory") and gs.GraphicsStyleCategory:
                lw = gs.GraphicsStyleCategory.GetLineWeight(GraphicsStyleType.Projection)
                if lw and lw >= 4:
                    return -4138
        return 2

    def get_text_type_props(text_type_id):
        props = {"name": "ISOCPEUR", "size": 10.0, "bold": False, "italic": True, "underline": False}
        if not text_type_id or text_type_id.IntegerValue == -1:
            return props
        el = doc.GetElement(text_type_id)
        if not el:
            return props
            
        p_font = el.get_Parameter(BuiltInParameter.TEXT_FONT)
        if p_font and p_font.AsString():
            props["name"] = p_font.AsString()
            
        p_size = el.get_Parameter(BuiltInParameter.TEXT_SIZE)
        if p_size:
            size_mm = p_size.AsDouble() * 304.8
            props["size"] = max(min(round(size_mm * 3.8, 1), 72.0), 7.0)
            
        p_bold = el.get_Parameter(BuiltInParameter.TEXT_STYLE_BOLD)
        if p_bold:
            props["bold"] = (p_bold.AsInteger() == 1)
            
        p_italic = el.get_Parameter(BuiltInParameter.TEXT_STYLE_ITALIC)
        if p_italic:
            props["italic"] = (p_italic.AsInteger() == 1)
            
        p_under = el.get_Parameter(BuiltInParameter.TEXT_STYLE_UNDERLINE)
        if p_under:
            props["underline"] = (p_under.AsInteger() == 1)
            
        return props

    def get_visible_column_styles(sched):
        col_styles = []
        try:
            sched_def = sched.Definition
            for field_id in sched_def.GetFieldOrder():
                field = sched_def.GetField(field_id)
                if not field.IsHidden:
                    col_styles.append((field, field.GetStyle()))
        except:
            pass
        return col_styles

    def get_header_bottom_row(sched, sec):
        if not sched.Definition.ShowHeaders or not sec or sec.NumberOfRows == 0:
            return -1
        max_bot = 0
        try:
            for c in range(sec.NumberOfColumns):
                m = sec.GetMergedCell(0, c)
                if m.Bottom > max_bot:
                    max_bot = m.Bottom
        except:
            pass
        return max_bot

    def safe_get_cell_text(sched, sec_type, sec, r, c):
        if not sec or r < 0 or r >= sec.NumberOfRows or c < 0 or c >= sec.NumberOfColumns:
            return ""
        try:
            return sched.GetCellText(sec_type, r, c)
        except:
            return ""

    def export_schedule_to_worksheet(sched, ws, temp_dir, img_cache):
        table_data = sched.GetTableData()
        body_sec = table_data.GetSectionData(SectionType.Body)
        header_sec = table_data.GetSectionData(SectionType.Header)
        
        title_font_props = get_text_type_props(sched.TitleTextTypeId)
        header_font_props = get_text_type_props(sched.HeaderTextTypeId)
        body_font_props = get_text_type_props(sched.BodyTextTypeId)
        
        visible_cols = get_visible_column_styles(sched)
        
        # Определяем видимые столбцы и отбрасываем технические/сжатые столбцы
        valid_col_indices = []
        if body_sec and body_sec.NumberOfColumns > 0:
            max_check = body_sec.NumberOfColumns
            if len(visible_cols) > 0:
                max_check = min(max_check, len(visible_cols))
            for c in range(max_check):
                try:
                    w_mm = body_sec.GetColumnWidth(c) * 304.8
                except:
                    w_mm = 10.0
                    
                # 1. Любой столбец уже 4.5 мм — гарантированно технический («схлопнутый» на листе)
                if w_mm < 4.5:
                    continue
                    
                # 2. Если столбец узкий (< 8 мм) и в шапке его заголовок пуст или слит с предыдущим — тоже пропускаем
                if w_mm < 8.0 and body_sec.NumberOfRows > 0:
                    hdr_text = safe_get_cell_text(sched, SectionType.Body, body_sec, 0, c).strip()
                    is_merged_left = False
                    try:
                        m_hdr = body_sec.GetMergedCell(0, c)
                        if m_hdr.Left < c:
                            is_merged_left = True
                    except:
                        pass
                    if not hdr_text or is_merged_left:
                        continue
                        
                valid_col_indices.append(c)

        if not valid_col_indices:
            total_cols = max(len(visible_cols), 1)
            valid_col_indices = list(range(total_cols))
        else:
            total_cols = len(valid_col_indices)

        # 1. Ширина колонок
        if body_sec and body_sec.NumberOfColumns > 0:
            for xl_idx, revit_c in enumerate(valid_col_indices):
                try:
                    width_ft = body_sec.GetColumnWidth(revit_c)
                    width_mm = width_ft * 304.8
                    xl_col_width = max(round(width_mm / 2.1, 2), 0.5)
                    ws.Columns(xl_idx + 1).ColumnWidth = xl_col_width
                except:
                    pass

        current_xl_row = 1
        pending_pictures = []
        
        for sec_type in [SectionType.Header, SectionType.Body]:
            sec = table_data.GetSectionData(sec_type)
            if not sec or sec.NumberOfRows == 0 or sec.NumberOfColumns == 0:
                continue
                
            n_rows = sec.NumberOfRows
            header_bot_row = get_header_bottom_row(sched, sec) if sec_type == SectionType.Body else -1
            
            if sec_type == SectionType.Header:
                sec_col_indices = list(range(min(total_cols, sec.NumberOfColumns)))
            else:
                sec_col_indices = [c for c in valid_col_indices if c < sec.NumberOfColumns]
                
            if not sec_col_indices:
                continue
                
            visited_merged = set()
            
            for r in range(n_rows):
                xl_r = current_xl_row + r
                row_is_header = (sec_type == SectionType.Header) or (r <= header_bot_row)
                row_has_image = False
                
                non_empty_header_cells = []
                if sec_type == SectionType.Header:
                    for c_check in sec_col_indices:
                        txt_check = safe_get_cell_text(sched, sec_type, sec, r, c_check)
                        if txt_check and txt_check.strip():
                            non_empty_header_cells.append((c_check, txt_check))

                for xl_c_idx, c in enumerate(sec_col_indices):
                    xl_c = xl_c_idx + 1
                    val = safe_get_cell_text(sched, sec_type, sec, r, c)
                    cell = ws.Cells(xl_r, xl_c)
                    
                    img_info = None
                    if sec_type == SectionType.Body and not row_is_header and val:
                        img_info = get_cached_image_info(val, temp_dir, img_cache)
                    
                    cell.NumberFormat = "@"
                    cell.Value2 = "" if img_info else val
                    
                    try:
                        merged = sec.GetMergedCell(r, c)
                        merged_right = min(merged.Right, sec_col_indices[-1])
                        merged_bottom = min(merged.Bottom, n_rows - 1)
                        merge_key = (merged.Top, merged.Left, merged_bottom, merged_right)
                        is_merged_area = (merged.Top != merged_bottom or merged.Left != merged_right)
                    except:
                        is_merged_area = False
                        merge_key = (r, c, r, c)
                        merged_right = c
                        merged_bottom = r
                        
                    if is_merged_area:
                        if merge_key in visited_merged:
                            continue
                        visited_merged.add(merge_key)
                        
                        left_xl = sec_col_indices.index(merged.Left) + 1 if merged.Left in sec_col_indices else xl_c
                        right_xl = sec_col_indices.index(merged_right) + 1 if merged_right in sec_col_indices else total_cols
                        
                        if sec_type == SectionType.Header and len(non_empty_header_cells) <= 1 and right_xl < total_cols:
                            right_xl = total_cols
                            
                        top_left = ws.Cells(current_xl_row + merged.Top, left_xl)
                        bot_right = ws.Cells(current_xl_row + merged_bottom, right_xl)
                        target_range = ws.Range(top_left, bot_right)
                        target_range.Merge()
                    else:
                        if sec_type == SectionType.Header and len(non_empty_header_cells) <= 1 and total_cols > 1:
                            if xl_c_idx > 0:
                                continue
                            if len(non_empty_header_cells) == 1:
                                cell.Value2 = non_empty_header_cells[0][1]
                            top_left = ws.Cells(xl_r, 1)
                            bot_right = ws.Cells(xl_r, total_cols)
                            target_range = ws.Range(top_left, bot_right)
                            target_range.Merge()
                        else:
                            target_range = cell

                    if img_info:
                        row_has_image = True
                        pending_pictures.append((target_range, img_info[0], img_info[1], img_info[2]))

                    # Стиль ячейки
                    style = None
                    try:
                        style = sec.GetTableCellStyle(r, c)
                    except:
                        pass
                        
                    col_field = None
                    col_style = None
                    if c < len(visible_cols):
                        col_field, col_style = visible_cols[c]
                        if not style:
                            style = col_style

                    if sec_type == SectionType.Header:
                        base_font = title_font_props
                    elif row_is_header:
                        base_font = header_font_props
                    else:
                        base_font = body_font_props

                    font = target_range.Font
                    f_name = style.FontName if (style and getattr(style, "FontName", None)) else base_font["name"]
                    if f_name:
                        font.Name = f_name
                        
                    font.Size = base_font["size"]
                    font.Bold = style.IsFontBold if (style and hasattr(style, "IsFontBold")) else base_font["bold"]
                    font.Italic = style.IsFontItalic if (style and hasattr(style, "IsFontItalic")) else base_font["italic"]
                    is_under = style.IsFontUnderline if (style and hasattr(style, "IsFontUnderline")) else base_font["underline"]
                    font.Underline = 2 if is_under else -4142

                    if style:
                        text_ole = rgb_to_ole(getattr(style, "TextColor", None))
                        if text_ole is not None:
                            font.Color = text_ole
                            
                        bg = getattr(style, "BackgroundColor", None)
                        if bg and bg.IsValid and not (bg.Red == 255 and bg.Green == 255 and bg.Blue == 255):
                            target_range.Interior.Color = rgb_to_ole(bg)

                    # Выравнивание
                    if sec_type == SectionType.Header or row_is_header:
                        target_range.HorizontalAlignment = -4108
                        target_range.VerticalAlignment = -4108
                    else:
                        if style and hasattr(style, "FontHorizontalAlignment"):
                            target_range.HorizontalAlignment = get_xl_halign(style.FontHorizontalAlignment)
                        elif col_field:
                            h_al = int(col_field.HorizontalAlignment)
                            target_range.HorizontalAlignment = -4108 if h_al == 1 else (-4152 if h_al == 2 else -4131)
                        else:
                            target_range.HorizontalAlignment = -4131
                            
                        if style and hasattr(style, "FontVerticalAlignment"):
                            target_range.VerticalAlignment = get_xl_valign(style.FontVerticalAlignment)
                        else:
                            target_range.VerticalAlignment = -4108

                    if is_merged_area and sec_type == SectionType.Body:
                        target_range.HorizontalAlignment = -4108
                        target_range.VerticalAlignment = -4108

                    target_range.WrapText = True
                    
                    # Границы
                    borders_map = [
                        (7, getattr(style, "BorderLeftLineStyle", None)),
                        (8, getattr(style, "BorderTopLineStyle", None)),
                        (9, getattr(style, "BorderBottomLineStyle", None)),
                        (10, getattr(style, "BorderRightLineStyle", None))
                    ]
                    for xl_edge, line_style_id in borders_map:
                        b = target_range.Borders(xl_edge)
                        if line_style_id and line_style_id.IntegerValue != -1:
                            b.LineStyle = 1
                            b.Weight = get_xl_border_weight(line_style_id)
                        elif sec_type == SectionType.Body:
                            b.LineStyle = 1
                            b.Weight = 2
                        else:
                            b.LineStyle = -4142

                # Высота строк
                revit_row_pt = 0.0
                try:
                    height_ft = sec.GetRowHeight(r)
                    revit_row_pt = round(height_ft * 864.0, 1)
                except:
                    pass

                if sec_type == SectionType.Header:
                    ws.Rows(xl_r).RowHeight = max(revit_row_pt, 26.0)
                elif row_is_header:
                    header_rows_count = max(header_bot_row + 1, 1)
                    min_header_pt = 54.0 / header_rows_count
                    ws.Rows(xl_r).EntireRow.AutoFit()
                    autofit_h = ws.Rows(xl_r).RowHeight
                    ws.Rows(xl_r).RowHeight = max(revit_row_pt, autofit_h + 16.0, min_header_pt)
                else:
                    ws.Rows(xl_r).EntireRow.AutoFit()
                    autofit_h = ws.Rows(xl_r).RowHeight
                    min_img_pt = 36.0 if row_has_image else 0.0
                    ws.Rows(xl_r).RowHeight = max(revit_row_pt, autofit_h + 4.0, min_img_pt)
                
            current_xl_row += n_rows

        # 2. Вставка изображений поверх настроенных ячеек
        for target_range, img_path, w_px, h_px in pending_pictures:
            try:
                pad = 2.0
                cell_left = float(target_range.Left)
                cell_top = float(target_range.Top)
                cell_w = float(target_range.Width)
                cell_h = float(target_range.Height)
                
                avail_w = max(cell_w - pad * 2.0, 4.0)
                avail_h = max(cell_h - pad * 2.0, 4.0)
                
                if w_px > 0 and h_px > 0:
                    scale = min(avail_w / w_px, avail_h / h_px)
                    pic_w = w_px * scale
                    pic_h = h_px * scale
                else:
                    pic_w = avail_w
                    pic_h = avail_h
                    
                pic_left = cell_left + (cell_w - pic_w) / 2.0
                pic_top = cell_top + (cell_h - pic_h) / 2.0
                
                shape = ws.Shapes.AddPicture(img_path, 0, -1, pic_left, pic_top, pic_w, pic_h)
                shape.Placement = 1
            except:
                pass

    # --- 6. ЗАПУСК И ЭКСПОРТ ---
    form = ExportSchedulesForm(len(schedules_to_export))
    if form.ShowDialog() == DialogResult.OK:
        save_folder = form.SelectedPath
        exported_files = []
        temp_img_dir = tempfile.mkdtemp(prefix="revit_sched_imgs_")
        img_cache = {}
        
        xl_app = Excel.ApplicationClass()
        xl_app.Visible = False
        xl_app.DisplayAlerts = False
        
        try:
            for sched in schedules_to_export:
                wb = xl_app.Workbooks.Add()
                ws = wb.Worksheets[1]
                
                safe_sheet_name = clean_filename(sched.Name)[:31]
                if safe_sheet_name:
                    ws.Name = safe_sheet_name
                
                export_schedule_to_worksheet(sched, ws, temp_img_dir, img_cache)
                
                file_name = clean_filename(sched.Name) + ".xlsx"
                full_path = os.path.join(save_folder, file_name)
                
                wb.SaveAs(full_path, 51)
                wb.Close(False)
                Marshal.ReleaseComObject(wb)
                exported_files.append(full_path)
                
            MessageBox.Show(
                "Экспорт успешно завершен!\nСохранено файлов: {}\nПапка: {}".format(len(exported_files), save_folder),
                "Готово",
                MessageBoxButtons.OK,
                MessageBoxIcon.Information
            )
            OUT = exported_files
            
        except Exception as e:
            import traceback
            err_msg = traceback.format_exc()
            MessageBox.Show(
                "Ошибка при экспорте в Excel:\n{}".format(err_msg),
                "Ошибка",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error
            )
            OUT = "Ошибка: " + err_msg
            
        finally:
            xl_app.Quit()
            Marshal.ReleaseComObject(xl_app)
            shutil.rmtree(temp_img_dir, ignore_errors=True)
    else:
        OUT = "Экспорт отменен пользователем."
