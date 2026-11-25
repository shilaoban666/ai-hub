"""Models visible to the workbench, without provider credentials."""
from sqlalchemy import or_

from models import AIModel


def workbench_models(db, user_id):
    return db.query(AIModel).filter(
        AIModel.is_deleted == False,
        AIModel.is_enabled == True,
        or_(AIModel.scope == "platform", AIModel.user_id == user_id),
    ).order_by(AIModel.id).all()


def chat_model_payload(model):
    return {
        "id": model.id, "name": model.name, "provider": model.provider,
        "remarks": model.remarks, "scope": model.scope,
        "api_protocol": model.api_protocol,
        "compatible_runtimes": model.compatible_runtimes,
    }
