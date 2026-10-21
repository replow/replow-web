from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.api.audit_route import AuditRoute
from app.core.security import require_admin
from app.db.session import get_db
from app.services.dynamics import DynamicsService

router = APIRouter(prefix="/public/dynamics", tags=["dynamics"])
admin_router = APIRouter(prefix="/admin/dynamics", tags=["admin dynamics"],
    route_class=AuditRoute, dependencies=[Depends(require_admin)])

@router.get("")
def public_dynamics(limit:int=Query(20,ge=1,le=100), offset:int=Query(0,ge=0),
                    db:Session=Depends(get_db)):
    return DynamicsService(db).listing(limit,offset,public=True)

@router.get("/{dynamic_id}")
def public_dynamic(dynamic_id:int,db:Session=Depends(get_db)):
    return {"data":DynamicsService(db).get(dynamic_id,public=True)}

@admin_router.get("")
def admin_dynamics(limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0),
                   search:str=Query("",max_length=100),state:str="",
                   db:Session=Depends(get_db)):
    return DynamicsService(db).listing(limit,offset,search.strip(),state)

@admin_router.get("/{dynamic_id}")
def admin_dynamic(dynamic_id:int,db:Session=Depends(get_db)):
    return {"data":DynamicsService(db).get(dynamic_id)}

@admin_router.post("")
def create_dynamic(payload:dict,db:Session=Depends(get_db)):
    return {"data":DynamicsService(db).save(payload)}

@admin_router.put("/{dynamic_id}")
def update_dynamic(dynamic_id:int,payload:dict,db:Session=Depends(get_db)):
    return {"data":DynamicsService(db).save(payload,dynamic_id)}

@admin_router.delete("/{dynamic_id}")
def delete_dynamic(dynamic_id:int,db:Session=Depends(get_db)):
    DynamicsService(db).delete(dynamic_id)
    return {"success":True}
