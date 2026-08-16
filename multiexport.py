import os, json, zipfile, tempfile, re
from io import BytesIO
from krita import *

def check_has_night_layer(node):
    name = node.name().lower()
    if name.startswith("night;"):
        return True
    for child in node.childNodes():
        if check_has_night_layer(child):
            return True
    return False


def prepare_night_visibility(node):
    name = node.name().lower()
    
    # Hide day layers
    if name.startswith("day;"):
        node.setVisible(False)
        
    # Force night layers to be visible
    elif name.startswith("night;"):
        node.setVisible(True)
        
        # Ensure parent groups are also visible so the night layer isn't hidden
        parent = node.parentNode()
        while parent and parent.type() != "root":
            if parent.name().lower().startswith("day;"):
                break
            parent.setVisible(True)
            parent = parent.parentNode()

    # Recurse through all child nodes
    for child in node.childNodes():
        prepare_night_visibility(child)


def export_night_avif(doc, folder, base_name):
    # Only proceed if at least one layer starts with "night;"
    has_night = any(check_has_night_layer(node) for node in doc.topLevelNodes())
    if not has_night:
        return

    # Save original visibility states
    vis_map = dict()
    for node in doc.topLevelNodes():
        save_visibility_recursive(node, vis_map)

    # Apply night mode visibilities
    for node in doc.topLevelNodes():
        prepare_night_visibility(node)

    doc.refreshProjection()

    # Export AVIF image
    night_output_path = os.path.join(folder, f"{base_name}-night.avif")
    info = InfoObject()
    info.setProperty("quality", 90)
    doc.exportImage(night_output_path, info)

    # Restore original visibility state
    restore_visibility(vis_map)
    doc.refreshProjection()
pass

class MultiExport(Extension):
    def __init__(self, parent):
        super().__init__(parent)

    def setup(self):
        pass

    def createActions(self, window):
        # Multi-export
        action = window.createAction(
            "multi_export",
            "Multi Export (PNG, JPG, WEBP, AVIF)",
            "tools/scripts"
        )
        action.triggered.connect(self.export_all)

        
        action = window.createAction(
            "multi_export_no_legacy",
            "Multi Export (WEBP, AVIF)",
            "tools/scripts"
        )
        action.triggered.connect(self.export_modern)

        # LayerZip export
        action_lzip = window.createAction(
            "export_layerzip",
            "Export as LayerZip (.lzp)",
            "tools/scripts"
        )
        action_lzip.triggered.connect(self.export_layerzip)

    # ---------------- Multi Export ----------------
    def export_all(self):
        self.perform_export(("png", "jpg", "webp", "avif"))

    def export_modern(self):
        self.perform_export(("webp", "avif"))

    def perform_export(self, formats):
        doc = Krita.instance().activeDocument()
        if not doc:
            return

        if not doc.fileName():
            doc.saveAs()
            if not doc.fileName():
                return

        doc.save()

        full_path = doc.fileName()
        folder = os.path.dirname(full_path)
        base_name = os.path.splitext(os.path.basename(full_path))[0]

        tmp_doc = doc

        tmp_doc.setBatchmode(True)
        for fmt in formats:
            output_path = os.path.join(folder, f"{base_name}.{fmt}")
            info = InfoObject()
            info.setProperty("quality", 90)
            doc.exportImage(output_path, info)

        export_night_avif(doc, folder, base_name)

        tmp_doc.setBatchmode(False)

        print("Multi-format export complete.")

    # ---------------- LayerZip export ----------------
    def export_layerzip(self):
        doc = Krita.instance().activeDocument()
        if not doc:
            return

        if not doc.fileName():
            doc.saveAs()
            if not doc.fileName():
                return

        doc.save(); tmp_doc = doc;
        tmp_doc.setBatchmode(True)

        folder = os.path.dirname(doc.fileName())
        base_name = os.path.splitext(os.path.basename(doc.fileName()))[0]
        lzip_path = os.path.join(folder, f"{base_name}.zip")

        mem_zip = BytesIO(); layer_save = dict(layer_save=0)

        with zipfile.ZipFile(mem_zip, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            layers_json = {
                "width": doc.width(),
                "height": doc.height(),
                "layers": []
            }

            for node in doc.topLevelNodes():
                result = process_layer(node, [], doc, zf, layer_save)
                if result:
                    layers_json["layers"].append(result)

            # Save the JSON config in the zip
            zf.writestr("lzip.conf.json", json.dumps(layers_json, indent=2))

        # Write the zip to disk
        with open(lzip_path, "wb") as f:
            f.write(mem_zip.getvalue())

        print(f"LayerZip export complete: {lzip_path}")

        tmp_doc.setBatchmode(False)
        tmp_doc.refreshProjection()


# ---------------- Layer Processing ----------------
def process_layer(node, path_list, source_doc, zf, layer_save):
    layer_save['layer_save'] += 1
    node_name = node.name()
    safe_name = sanitize_name(node_name) + f'_' + str(layer_save['layer_save']) + 'n'
    common_node_attributes = dict(visibility=node.visible(), locked=node.locked(), opacity=node.opacity() / 255)

    if node.type() == "grouplayer":
        export_path = "/".join(path_list + [safe_name])
        group_data = {
            "type": node.type(),
            "name": (node_name),
            "path": export_path,
            "layers": list(),
        } | common_node_attributes

        for child in node.childNodes():
            child_result = process_layer(child, path_list + [safe_name], source_doc, zf, layer_save)
            if child_result:
                group_data["layers"].append(child_result)

        return group_data

    elif node.type() in ("paintlayer", "vectorlayer"):
        export_path = "/".join(path_list + [safe_name + ".png"])

        # Save current visibility states
        visibility_map = {}
        for n in source_doc.topLevelNodes():
            save_visibility_recursive(n, visibility_map)

        # Hide everything
        for n in source_doc.topLevelNodes():
            set_visibility_recursive(n, False)

        # Show only this node and its parents
        current = node
        while current:
            current.setVisible(True)
            current = current.parentNode()

        source_doc.refreshProjection()

        # Export to temporary file
        tmp_file = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp_name = tmp_file.name
        tmp_file.close()

        info = InfoObject()
        info.setProperty("quality", 100)
        info.setProperty("alpha", True)

        success = source_doc.exportImage(tmp_name, info)
        if not success:
            restore_visibility(visibility_map)
            os.remove(tmp_name)
            raise Exception("Layer export failed")

        with open(tmp_name, "rb") as f:
            zf.writestr(export_path, f.read())

        os.remove(tmp_name)

        # Restore visibility
        restore_visibility(visibility_map)
        #source_doc.refreshProjection()

        return dict(type=node.type(), path=export_path, name=node_name) | common_node_attributes

    else:
        return None


# ---------------- Utilities ----------------
def sanitize_name(name):
    return re.sub(r'[\/\[\]\\<>?*^"| :]', '_', name)


def save_visibility_recursive(node, vis_map):
    vis_map[id(node)] = (node, node.visible())
    for child in node.childNodes():
        save_visibility_recursive(child, vis_map)


def restore_visibility(vis_map):
    for node_id, (node, state) in vis_map.items():
        try:
            node.setVisible(state)
        except RuntimeError:
            pass


def set_visibility_recursive(node, visible):
    node.setVisible(visible)
    for child in node.childNodes():
        set_visibility_recursive(child, visible)


# ---------------- Register Extension ----------------
Krita.instance().addExtension(MultiExport(Krita.instance()))
