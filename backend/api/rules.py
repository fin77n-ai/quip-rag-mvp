from fastapi import APIRouter
from ..models.rules import FilterRules
from ..services import rules_store

router = APIRouter(prefix="/rules", tags=["rules"])


@router.get("", response_model=FilterRules)
async def get_rules():
    return rules_store.load()


@router.post("", response_model=FilterRules)
async def save_rules(rules: FilterRules):
    rules_store.save(rules)
    return rules_store.load()


@router.post("/reset", response_model=FilterRules)
async def reset_rules():
    return rules_store.reset_to_default()
