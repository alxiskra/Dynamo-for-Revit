revit-dynamo-export-views

Create Dynamo Python scripts for Revit 2022 to batch export views or legends as images. Use this skill when the user asks to save multiple Revit views to the project as images, fix "Setting active view is temporarily disabled" errors, or create interactive view selector forms in Dynamo.
Instructions
Revit Dynamo Batch Image Export

This skill provides the structure and patterns for writing Dynamo Python scripts that batch export Revit views (or legends) as images back into the project.
Key Principles

    Revit 2022 Compatibility: Ensure the code runs under CPython 3, which is the standard engine for Revit 2022. Use traceback without appending sys.path.
    Transaction Management: Dynamo's TransactionManager and Revit API's Transaction must be managed carefully. Revit does not allow nested transactions or changing the active view while a transaction is open.
    UI Thread Blocking (The "Setting active view is temporarily disabled" Error): When a custom Windows Form is used to select views, closing the form blocks the UI thread momentarily. To safely switch active views sequentially, you MUST use IExternalEventHandler.
    No sys.path Appends: Do not append IronPython paths like C:\Program Files (x86)\IronPython 2.7\Lib.
    Output Format: Always return Dynamo elements (wrapped Revit elements using ToDSType(False)) so they can be processed further down the Dynamo graph.

Pattern 1: Single View Export (Simple)

Use this pattern when exporting a single view (usually the active view).

import clr
clr.AddReference("RevitNodes")
import Revit
clr.ImportExtensions(Revit.Elements)

clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import *

clr.AddReference("RevitServices")
import RevitServices
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager
import traceback

doc = DocumentManager.Instance.CurrentDBDocument
transaction_name = "DYN_Save Image"

try:
    TransactionManager.Instance.ForceCloseTransaction()
    t = Transaction(doc, transaction_name)
    t.Start()

    options = ImageExportOptions()
    options.ViewName = "Image_" + doc.ActiveView.Name
    options.ExportRange = ExportRange.CurrentView
    options.ImageResolution = ImageResolution.DPI_600
    options.ZoomType = ZoomFitType.Zoom
    options.Zoom = 100

    result_id = doc.SaveToProjectAsImage(options)
    t.Commit()

    created_image = doc.GetElement(result_id)
    OUT = created_image.ToDSType(False)

except Exception as e:
    if 't' in locals() and t.HasStarted() and not t.HasEnded():
        t.RollBack()
    OUT = traceback.format_exc()

Pattern 2: Batch Export with Windows Forms (Advanced)

Use this pattern when you need a UI to select views, followed by a batch export. This requires IExternalEventHandler to safely change the ActiveView without triggering UI lock errors.

import clr
import traceback

clr.AddReference("RevitNodes")
import Revit
clr.ImportExtensions(Revit.Elements)

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI") 
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent, TaskDialog

clr.AddReference("RevitServices")
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')
from System.Windows.Forms import Form, CheckedListBox, Button, DialogResult, FormBorderStyle, FormStartPosition, TextBox, CheckState
from System.Drawing import Size, Point

# [Insert Form Class Here - e.g., LegendSelectorForm]

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
                
                # Safe view switch
                current_uidoc.ActiveView = view
                
                t = Transaction(current_doc, "DYN_Save Image: " + view.Name)
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
                errors.append("Error ({0}): {1}".format(view.Name, str(e)))
        
        try:
            current_uidoc.ActiveView = current_doc.GetElement(original_view_id)
        except:
            pass
            
        if errors:
            TaskDialog.Show("Export Errors", "\\n".join(errors))

    def GetName(self):
        return "SaveViewsAsImagesHandler"

# Execution Logic
# 1. Collect views
# 2. Show Form
# 3. If OK, ForceCloseTransaction()
# 4. Extract View IDs
# 5. Create handler and raise ExternalEvent

Gotchas

    Revit API's SaveToProjectAsImage only works on the active view. You must switch uidoc.ActiveView to the target view before exporting.
    Changing uidoc.ActiveView is completely prohibited while a transaction is open. You must close Dynamo's transaction, switch the view, open a new transaction, save, and commit.
    Dynamo Player heavily restricts view switching. Advise users to run batch export scripts with custom UIs from the Dynamo editor.
