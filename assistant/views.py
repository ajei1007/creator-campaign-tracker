import json

from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from .client import AssistantError, ask
from .context import build_context

MAX_QUESTION_LEN = 500


@staff_member_required
@require_POST
def ask_view(request):
    try:
        body = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid request body."}, status=400)

    question = (body.get("question") or "").strip()
    model_key = (body.get("model") or "").strip() or None

    if not question:
        return JsonResponse({"error": "Please enter a question."}, status=400)
    if len(question) > MAX_QUESTION_LEN:
        return JsonResponse(
            {"error": f"Question is too long (max {MAX_QUESTION_LEN} characters)."},
            status=400,
        )

    context = build_context(model_key)
    try:
        answer = ask(question, context)
    except AssistantError as exc:
        return JsonResponse({"error": str(exc)}, status=503)

    return JsonResponse({"answer": answer})
