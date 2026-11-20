"""Builds grounding context for the help assistant from the actual models.

Everything the model is told about a form comes from the Django field
definitions themselves (verbose names, help_text, choices, required-ness), so
answers describe the real schema rather than a guess.
"""
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
    """Return field docs. If model_key is given, scope to that one form."""
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
