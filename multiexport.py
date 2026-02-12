from krita import *
import os

class MultiExport(Extension):

    def __init__(self, parent):
        super().__init__(parent)

    def setup(self):
        pass

    def createActions(self, window):
        action = window.createAction(
            "multi_export",
            "Multi Export (PNG, JPG, WebP, AVIF)",
            "tools/scripts"
        )
        action.triggered.connect(self.export_all)

    def export_all(self):
        doc = Krita.instance().activeDocument()
        if not doc:
            return

        # If unsaved, trigger save dialog
        if not doc.fileName():
            doc.saveAs()
            if not doc.fileName():
                return

        # Save the .kra
        doc.save()

        full_path = doc.fileName()
        folder = os.path.dirname(full_path)
        base_name = os.path.splitext(os.path.basename(full_path))[0]

        formats = ["png", "jpg", "webp", "avif"]

        for fmt in formats:
            output_path = os.path.join(folder, f"{base_name}.{fmt}")
            info = InfoObject()
            info.setProperty("quality", 90)  # works for jpg/webp (ignored for png)
            doc.exportImage(output_path, info)

        print("Export complete.")

# And add the extension to Krita's list of extensions:
Krita.instance().addExtension(MultiExport(Krita.instance()))
