from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import or_

from backend.services.db import get_db
from backend.routes.auth import get_current_user, require_roles, require_non_staff
from backend.models import Patient, Appointment, CallLog
from backend.schemas.patient import PatientCreate
from backend.utils.helpers import api_response, serialize_model, serialize_models, to_uuid

router = APIRouter(prefix="/patients", tags=["Patients CRM"])


@router.get("/")
async def list_patients(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    clinic_id = to_uuid(current_user.get("clinic_id"))
    if clinic_id is None:
        return api_response(success=False, message="No clinic associated with user", status_code=400)

    result = await db.execute(select(Patient).where(Patient.clinic_id == clinic_id))
    return api_response(
        success=True,
        message="Patients fetched successfully",
        data=serialize_models(result.scalars().all()),
    )


@router.post("/")
async def create_patient(
    payload: PatientCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    clinic_id = to_uuid(current_user.get("clinic_id"))
    if clinic_id is None:
        return api_response(success=False, message="No clinic associated with user", status_code=400)

    # Enforce unique phone per clinic (also guarded by a DB constraint)
    existing = await db.execute(
        select(Patient).where(Patient.phone == payload.phone, Patient.clinic_id == clinic_id)
    )
    if existing.scalar_one_or_none():
        return api_response(success=False, message="Patient with this phone number already exists", status_code=400)

    creator_id = to_uuid(current_user.get("id"))
    patient = Patient(
        clinic_id=clinic_id,
        source="manual",
        created_by=creator_id,
        **payload.dict(),
    )
    db.add(patient)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return api_response(success=False, message="Patient with this phone number already exists", status_code=400)

    return api_response(
        success=True,
        message="Patient created successfully",
        data=serialize_model(patient),
    )


@router.get("/{patient_id}")
async def get_patient(
    patient_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    clinic_id = to_uuid(current_user.get("clinic_id"))
    pid = to_uuid(patient_id)
    if pid is None:
        return api_response(success=False, message="Patient not found", status_code=404)

    result = await db.execute(
        select(Patient).where(Patient.id == pid, Patient.clinic_id == clinic_id)
    )
    patient = result.scalar_one_or_none()
    if not patient:
        return api_response(success=False, message="Patient not found", status_code=404)

    return api_response(
        success=True,
        message="Patient fetched successfully",
        data=serialize_model(patient),
    )


@router.get("/{patient_id}/detail")
async def get_patient_detail(
    patient_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """A contact with their full history: appointments + calls."""
    clinic_id = to_uuid(current_user.get("clinic_id"))
    pid = to_uuid(patient_id)
    if pid is None or clinic_id is None:
        return api_response(success=False, message="Contact not found", status_code=404)

    patient = (await db.execute(
        select(Patient).where(Patient.id == pid, Patient.clinic_id == clinic_id)
    )).scalar_one_or_none()
    if not patient:
        return api_response(success=False, message="Contact not found", status_code=404)

    # Appointments linked either by stored patient_id or by matching phone.
    appts = (await db.execute(
        select(Appointment).where(
            Appointment.clinic_id == clinic_id,
            or_(Appointment.patient_id == str(pid), Appointment.phone == patient.phone),
        ).order_by(Appointment.appointment_at.desc(), Appointment.created_at.desc())
    )).scalars().all()

    # Calls from this contact's phone number.
    calls = (await db.execute(
        select(CallLog).where(CallLog.clinic_id == clinic_id, CallLog.phone == patient.phone)
        .order_by(CallLog.created_at.desc()).limit(50)
    )).scalars().all()

    return api_response(
        success=True,
        message="Contact detail fetched",
        data={
            "contact": serialize_model(patient),
            "appointments": serialize_models(appts),
            "calls": serialize_models(calls),
        },
    )


@router.put("/{patient_id}")
async def update_patient(
    patient_id: str,
    payload: PatientCreate,
    current_user: dict = Depends(require_non_staff),
    db: AsyncSession = Depends(get_db),
):
    clinic_id = to_uuid(current_user.get("clinic_id"))
    pid = to_uuid(patient_id)
    if pid is None:
        return api_response(success=False, message="Patient not found", status_code=404)

    result = await db.execute(
        select(Patient).where(Patient.id == pid, Patient.clinic_id == clinic_id)
    )
    patient = result.scalar_one_or_none()
    if not patient:
        return api_response(success=False, message="Patient not found", status_code=404)

    for key, value in payload.dict(exclude_unset=True).items():
        setattr(patient, key, value)
    await db.commit()

    return api_response(
        success=True,
        message="Patient updated successfully",
        data=serialize_model(patient),
    )


@router.delete("/{patient_id}")
async def delete_patient(
    patient_id: str,
    current_user: dict = Depends(require_non_staff),
    db: AsyncSession = Depends(get_db),
):
    clinic_id = to_uuid(current_user.get("clinic_id"))
    pid = to_uuid(patient_id)
    if pid is None:
        return api_response(success=False, message="Patient not found", status_code=404)

    result = await db.execute(
        select(Patient).where(Patient.id == pid, Patient.clinic_id == clinic_id)
    )
    patient = result.scalar_one_or_none()
    if not patient:
        return api_response(success=False, message="Patient not found", status_code=404)

    await db.delete(patient)
    await db.commit()
    return api_response(success=True, message="Patient deleted successfully")
