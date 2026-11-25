# Builds the field reference we feed the assistant, straight from the model
# fields (verbose name, help_text, choices, required), so it answers from the
# real schema instead of guessing.
from django.apps import apps

DOCUMENTED_MODELS = [
    ("campaigns", "Campaign"),
    ("campaigns", "Creator"),
    ("campaigns", "SocialAccount"),
    ("campaigns", "Participation"),
]


def _field_line(field):
    bits = [f"- {field.name} ({field.get_internal_type()})"]
    if getattr(field, "verbose_name", None) and field.verbose_name != field.name:
        bits.append(f'labelled "{field.verbose_name}"')
    if not field.blank and field.editable and not field.auto_created:
        bits.append("required")
    if getattr(field, "choices", None):
        values = ", ".join(str(c[0]) for c in field.choices)
        bits.append(f"choices: {values}")
    text = " ".join(bits)
    if field.help_text:
        text += f"\n    help: {field.help_text}"
    return text


def model_context(model):
    lines = [f"Model: {model.__name__}"]
    for field in model._meta.get_fields():
        if not hasattr(field, "get_internal_type"):
            continue
        if field.auto_created and not field.concrete:
            continue
        lines.append(_field_line(field))
    return "\n".join(lines)


def build_context(model_key=None):
    """Field docs for all models, or just one if model_key is given."""
    targets = DOCUMENTED_MODELS
    if model_key:
        targets = [(a, m) for (a, m) in DOCUMENTED_MODELS if m.lower() == model_key.lower()]
        if not targets:
            targets = DOCUMENTED_MODELS
    chunks = []
    for app_label, model_name in targets:
        model = apps.get_model(app_label, model_name)
        chunks.append(model_context(model))
    return "\n\n".join(chunks)
