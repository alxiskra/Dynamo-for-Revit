import clr
import traceback

# Подключаем библиотеки Dynamo
clr.AddReference("RevitNodes")
import Revit
clr.ImportExtensions(Revit.Elements)

# Подключаем Revit API
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI") 
from Autodesk.Revit.DB import (
    FilteredElementCollector, View, ViewType, 
    ImageExportOptions, ExportRange, ImageResolution, ZoomFitType, Transaction
)
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent, TaskDialog

# Подключаем сервисы документа
clr.AddReference("RevitServices")
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

# Подключаем Windows Forms
clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')
from System.Windows.Forms import (
    Form, CheckedListBox, Button, DialogResult, FormBorderStyle, FormStartPosition,
    TextBox, CheckState
)
from System.Drawing import Size, Point

doc = DocumentManager.Instance.CurrentDBDocument
uidoc = DocumentManager.Instance.CurrentUIApplication.ActiveUIDocument

# 1. Получаем все легенды
all_views = FilteredElementCollector(doc).OfClass(View).ToElements()
legend_views = [v for v in all_views if v.ViewType == ViewType.Legend and not v.IsTemplate]
legend_dict = {v.Name: v for v in legend_views}

# 2. Окно выбора (остается без изменений)
class LegendSelectorForm(Form):
    def __init__(self, names):
        self.Text = "Выбор легенд для сохранения"
        self.Size = Size(450, 550)
        self.StartPosition = FormStartPosition.CenterScreen
        self.FormBorderStyle = FormBorderStyle.FixedDialog
        self.MaximizeBox = False
        self.MinimizeBox = False

        self.all_names = sorted(names)
        self.item_states = {name: False for name in self.all_names}

        self.tb_search = TextBox()
        self.tb_search.Location = Point(15, 15)
        self.tb_search.Size = Size(405, 20)
        self.tb_search.TextChanged += self.on_text_changed
        self.Controls.Add(self.tb_search)

        self.clb = CheckedListBox()
        self.clb.Location = Point(15, 45)
        self.clb.Size = Size(405, 400)
        self.clb.CheckOnClick = True
        self.clb.ItemCheck += self.on_item_check
        self.Controls.Add(self.clb)

        self.btn_ok = Button()
        self.btn_ok.Text = "Сохранить виды"
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
        self.update_list("")

    def update_list(self, filter_text):
        self.clb.Items.Clear()
        filter_text = filter_text.lower()
        for name in self.all_names:
            if filter_text in name.lower():
                self.clb.Items.Add(name, self.item_states[name])

    def on_text_changed(self, sender, event):
        self.update_list(sender.Text)

    def on_item_check(self, sender, event):
        item_name = self.clb.Items[event.Index]
        self.item_states[item_name] = (event.NewValue == CheckState.Checked)

    def get_selected_items(self):
        return [name for name, is_checked in self.item_states.items() if is_checked]

# 3. Класс обработчика внешнего события (Безопасный поток Revit)
class SaveViewsAsImagesHandler(IExternalEventHandler):
    def __init__(self, view_ids):
        self.view_ids = view_ids
    
    def Execute(self, app):
        current_uidoc = app.ActiveUIDocument
        current_doc = current_uidoc.Document
        original_view_id = current_uidoc.ActiveView.Id
        errors = []
        
        for v_id in self.view_ids:
            try:
                view = current_doc.GetElement(v_id)
                if not view: continue
                
                # Теперь смена вида происходит в 100% безопасном режиме
                current_uidoc.ActiveView = view
                
                t = Transaction(current_doc, "DYN_Сохранить легенду: " + view.Name)
                t.Start()
                
                options = ImageExportOptions()
                options.ViewName = "Image_" + view.Name
                options.ExportRange = ExportRange.CurrentView
                options.ImageResolution = ImageResolution.DPI_600
                options.ZoomType = ZoomFitType.Zoom
                options.Zoom = 100
                
                current_doc.SaveToProjectAsImage(options)
                t.Commit()
                
            except Exception as e:
                if 't' in locals() and t.HasStarted() and not t.HasEnded():
                    t.RollBack()
                errors.append("Ошибка ({0}): {1}".format(view.Name, str(e)))
        
        # Возвращаем пользователя на изначальный вид
        try:
            current_uidoc.ActiveView = current_doc.GetElement(original_view_id)
        except:
            pass
            
        # Если были ошибки, выводим их стандартным окном Revit
        if errors:
            TaskDialog.Show("Ошибки сохранения", "\n".join(errors))

    def GetName(self):
        return "SaveViewsAsImagesHandler"

# 4. Основная логика запуска
OUT = ""

if not legend_dict:
    OUT = "В проекте не найдено ни одной Легенды"
else:
    form = LegendSelectorForm(legend_dict.keys())
    dialog_result = form.ShowDialog()

    if dialog_result == DialogResult.OK:
        selected_legends = [legend_dict[item] for item in form.get_selected_items()]
        
        if not selected_legends:
            OUT = "Легенды не были выбраны"
        else:
            # Обязательно закрываем транзакции Dynamo
            TransactionManager.Instance.ForceCloseTransaction()
            
            # Извлекаем ID видов
            selected_view_ids = [v.Id for v in selected_legends]
            
            # Создаем и вызываем внешнее событие
            handler = SaveViewsAsImagesHandler(selected_view_ids)
            ext_event = ExternalEvent.Create(handler)
            ext_event.Raise()
            
            OUT = "Задача запущена! Revit переключит виды и сохранит изображения в течение пары секунд."
    else:
        OUT = "Операция отменена"
