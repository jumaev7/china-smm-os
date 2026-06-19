from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.client import Client
from app.schemas.client import ClientCreate, ClientUpdate
from app.core.api_auth_context import apply_tenant_direct_scope, assert_client_in_scope, get_auth_context


class ClientService:

    @staticmethod
    async def create(db: AsyncSession, data: ClientCreate) -> Client:
        payload = data.model_dump()
        ctx = get_auth_context()
        if ctx and ctx.is_tenant:
            payload["tenant_id"] = ctx.tenant_id
        client = Client(**payload)
        db.add(client)
        await db.commit()
        await db.refresh(client)
        return client

    @staticmethod
    async def get(db: AsyncSession, client_id: UUID) -> Client:
        result = await db.execute(select(Client).where(Client.id == client_id))
        client = result.scalar_one_or_none()
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")
        ctx = get_auth_context()
        if ctx and ctx.is_tenant and client.tenant_id != ctx.tenant_id:
            raise HTTPException(status_code=403, detail="Client does not belong to this tenant")
        return client

    @staticmethod
    async def list_all(
        db: AsyncSession, skip: int = 0, limit: int = 100, status: str | None = None
    ) -> tuple[list[Client], int]:
        query = select(Client).order_by(Client.created_at.desc())
        tenant_filt = apply_tenant_direct_scope(tenant_id_column=Client.tenant_id)
        if tenant_filt is not None:
            query = query.where(tenant_filt)
        if status:
            query = query.where(Client.status == status)
        count_query = select(func.count()).select_from(Client)
        if tenant_filt is not None:
            count_query = count_query.where(tenant_filt)
        if status:
            count_query = count_query.where(Client.status == status)

        total = (await db.execute(count_query)).scalar()
        result = await db.execute(query.offset(skip).limit(limit))
        return result.scalars().all(), total

    @staticmethod
    async def update(db: AsyncSession, client_id: UUID, data: ClientUpdate) -> Client:
        client = await ClientService.get(db, client_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(client, field, value)
        await db.commit()
        await db.refresh(client)
        return client

    @staticmethod
    async def delete(db: AsyncSession, client_id: UUID) -> None:
        client = await ClientService.get(db, client_id)
        await db.delete(client)
        await db.commit()
