"""Propose a resolution action, grounded in the similar resolved cases retrieve.py already
found - not invented outside the vocabulary the graph's own history actually uses.
"""
from llm.pipeline.state import PipelineState, Recommendation

# The Resolution.action vocabulary observed in the resolved half of the graph (see
# Saudi-Arabia-Regions-Cities-and-Districts/shipment_kg/generate_shipment_kg.py's
# RESOLUTION_ACTIONS) - recommend() should stay within this set, or extend it deliberately,
# not drift from it by paraphrasing.
KNOWN_ACTIONS = [
    "تأكيد العنوان الصحيح مع العميل وإعادة التوجيه",
    "تصحيح العنوان في النظام وإعادة الجدولة",
    "التواصل مع العميل لتحديد الموقع عبر الإحداثيات",
    "إعادة جدولة التسليم في يوم آخر",
    "التنسيق مع العميل عبر الهاتف لتحديد وقت بديل",
    "تسليم لجهة بديلة بموافقة العميل",
    "إعادة محاولة التسليم بعد تصحيح بيانات الشحنة",
    "استبدال الملصق وإعادة فحص الشحنة",
    "تحويل الشحنة إلى مندوب آخر لإعادة المحاولة",
    "إعادة توجيه الشحنة عبر مركز فرز بديل",
    "تسريع الشحنة عبر خط نقل مباشر",
    "إبلاغ العميل بالتأخير وتحديث موعد التسليم",
    "تصعيد الحالة للمشرف واتخاذ إجراء مركب لتصحيح العنوان وإعادة التسليم",
    "التنسيق بين فريق المستودع والمندوب لحل الحالة المركبة",
    "إعادة فتح الطلب ومعالجة جميع أسباب الفشل مجتمعاً",
]


def recommend(state: PipelineState) -> Recommendation:
    """Propose an action for state["classification"], citing the specific similar-case
    resolution_id(s) in state["context"]["similar_cases"] it's grounded in - an LLM call
    via config.LLM_MODEL, constrained to (ideally) pick from KNOWN_ACTIONS rather than
    invent new phrasing for an action the graph already has a name for."""
    ...
