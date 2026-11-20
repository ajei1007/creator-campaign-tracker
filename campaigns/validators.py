import os

from django.conf import settings
from django.core.exceptions import ValidationError


def _check(file, allowed_extensions):
    ext = os.path.splitext(file.name)[1].lower().lstrip(".")
    if ext not in allowed_extensions:
        raise ValidationError(
            f"'.{ext}' files are not allowed. Allowed: {', '.join(allowed_extensions)}."
        )
    limit = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if file.size and file.size > limit:
        raise ValidationError(
            f"File is too large ({file.size // (1024 * 1024)} MB). "
            f"Maximum is {settings.MAX_UPLOAD_SIZE_MB} MB."
        )


def validate_image_upload(file):
    _check(file, settings.ALLOWED_IMAGE_EXTENSIONS)


def validate_document_upload(file):
    _check(file, settings.ALLOWED_DOC_EXTENSIONS)
