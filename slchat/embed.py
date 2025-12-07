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
        parts = [f"|embed", f"type: {self.embed_type}"]
        if self.icon:
            parts.append(f"icon: {self.icon}")
        if self.title:
            parts.append(f"title: {self.title}")
        if self.description:
            parts.append(f"""description: \"{self.description}\"""")
        if self.color:
            parts.append(f"color: {self.color}")
        if self.attachment:
            attachment = f"||{self.attachment}||" if self.attachment_spoiler else self.attachment
            parts.append(f"image: {attachment}")
        if self.avatar:
            parts.append(f"avatar: {self.avatar}")
        if self.footer:
            parts.append(f"footer: {self.footer}")
        if self.fields:
            parts.append("fields:")
            for field in self.fields:
                parts.append(f"- name: {field["name"]}")
                parts.append(f"  value: {field["value"]}")
                parts.append(f"  inline: {field["inline"]}")
        parts.append("|end")
        return "\n".join(parts)