EMBED_ICONS = {
    "error": "bx-x-circle",
    "warn": "bx-alert-triangle",
    "info": "bx-info-circle",
    "success": "bx-check-circle",
    "note": "bx-note",
    "clean": None,
    "default": None
}

class Embed:
    def __init__(self, embed_type="default", title="", description="", color=""):
        self.embed_type = embed_type
        self.title = title
        self.color = color
        self.icon = ""
        self.description = description
        self.attachment = ""
        self.footer = ""
        self.avatar = ""
        self.fields = []
        self.attachment_spoiler = False

    def set_type(self, embed_type):
        self.embed_type = embed_type
        return self

    def set_title(self, text):
        self.title = text
        return self

    def set_icon(self, icon):
        self.icon = icon
        return self

    def set_color(self, color):
        self.color = color
        return self

    def set_description(self, text):
        self.description = text
        return self

    def set_attachment(self, url, spoiler=False):
        self.attachment = url
        self.attachment_spoiler = spoiler
        return self

    def set_footer(self, text):
        self.footer = text
        return self

    def set_avatar(self, url):
        self.avatar = url
        return self

    def add_field(self, name, value, inline=False, color=None, icon=None):
        self.fields.append({
            "name": name,
            "value": value,
            "inline": inline,
            "color": color,
            "icon": icon,
        })
        return self

    def build(self):
        fields = ""
        for field in self.fields:
            fields += f"""\n- name: {field["name"]}
  value: {field["value"]}
  inline: {field["inline"]}"""
        fields.strip()

        return (f"""|embed
type: {self.embed_type}
{f"icon: {self.icon}" if self.icon else ""}
{f"title: {self.title}" if self.title else ""}
{f"description: \"{self.description}\"" if self.description else ""}
{f"color: {self.color}" if self.color else ""}
{f"image: {f"||{self.attachment}||" if self.attachment_spoiler else self.attachment}" if self.attachment else ""}
{f"avatar: {self.avatar}" if self.avatar else ""}
{f"footer: {self.footer}" if self.footer else ""}
{f"fields:" if self.fields else ""}
{fields}
|end""")