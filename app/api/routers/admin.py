import secrets
import uuid

from fastapi import APIRouter, Depends

from app.api.deps import DbSessionDep, hash_api_key, require_admin
from app.api.errors import NotFoundError
from app.models import ApiKey
from app.repositories import api_key_repository
from app.schemas.admin import (
    ApiKeyCreatedResponse,
    ApiKeyResponse,
    CreateApiKeyRequest,
    UpdateApiKeyRequest,
)

router = APIRouter(prefix="/admin/api-keys", tags=["admin"], dependencies=[Depends(require_admin)])


def _to_response(api_key: ApiKey) -> ApiKeyResponse:
    return ApiKeyResponse(
        id=api_key.id,
        label=api_key.label,
        status=api_key.status,
        rate_limit_per_minute=api_key.rate_limit_per_minute,
        expires_at=api_key.expires_at,
        created_at=api_key.created_at,
        updated_at=api_key.updated_at,
    )


async def _get_or_404(session: DbSessionDep, key_id: uuid.UUID) -> ApiKey:
    api_key = await api_key_repository.get_by_id(session, key_id)
    if api_key is None:
        raise NotFoundError(f"api key {key_id} not found")
    return api_key


@router.post("", response_model=ApiKeyCreatedResponse, status_code=201)
async def create_api_key(
    body: CreateApiKeyRequest, session: DbSessionDep
) -> ApiKeyCreatedResponse:
    raw_key = secrets.token_urlsafe(32)
    api_key = await api_key_repository.create(
        session,
        key_hash=hash_api_key(raw_key),
        label=body.label,
        rate_limit_per_minute=body.rate_limit_per_minute,
        expires_at=body.expires_at,
    )
    return ApiKeyCreatedResponse(
        id=api_key.id,
        label=api_key.label,
        status=api_key.status,
        rate_limit_per_minute=api_key.rate_limit_per_minute,
        expires_at=api_key.expires_at,
        created_at=api_key.created_at,
        raw_key=raw_key,
    )


@router.get("", response_model=list[ApiKeyResponse])
async def list_api_keys(session: DbSessionDep) -> list[ApiKeyResponse]:
    api_keys = await api_key_repository.list_all(session)
    return [_to_response(k) for k in api_keys]


@router.get("/{key_id}", response_model=ApiKeyResponse)
async def get_api_key(key_id: uuid.UUID, session: DbSessionDep) -> ApiKeyResponse:
    api_key = await _get_or_404(session, key_id)
    return _to_response(api_key)


@router.patch("/{key_id}", response_model=ApiKeyResponse)
async def update_api_key(
    key_id: uuid.UUID, body: UpdateApiKeyRequest, session: DbSessionDep
) -> ApiKeyResponse:
    api_key = await _get_or_404(session, key_id)
    fields_set = body.model_fields_set
    if "status" in fields_set and body.status is not None:
        api_key = await api_key_repository.update_status(session, api_key, body.status)
    if "expires_at" in fields_set:
        api_key = await api_key_repository.update_expiry(session, api_key, body.expires_at)
    return _to_response(api_key)


@router.delete("/{key_id}", status_code=204)
async def delete_api_key(key_id: uuid.UUID, session: DbSessionDep) -> None:
    api_key = await _get_or_404(session, key_id)
    await api_key_repository.delete(session, api_key)
