import pytest
from datetime import datetime
from app.auth import tiene_rol
from app.models import (
    generate_uuid, Patient, Room, MedicalCondition, 
    EmergencyContact, Wearable, PatientContact, 
    PatientCondition, PatientWearable
)
from app.routes import format_patient_response

def test_tiene_rol_exitoso():
    token_info_simulado = {
        "realm_access": {
            "roles": ["default-roles-prueba", "nurse", "offline_access"]
        }
    }
    roles_permitidos = ["nurse", "administrator"]
    
    resultado = tiene_rol(token_info_simulado, roles_permitidos)
    assert resultado is True

def test_tiene_rol_fallido():
    token_info_simulado = {
        "realm_access": {
            "roles": ["guest", "offline_access"]
        }
    }
    roles_permitidos = ["nurse", "administrator"]
    
    resultado = tiene_rol(token_info_simulado, roles_permitidos)
    assert resultado is False

def test_tiene_rol_diccionario_malformado():
    token_info_simulado = {"otra_llave": "datos"}
    roles_permitidos = ["administrator"]
    
    resultado = tiene_rol(token_info_simulado, roles_permitidos)
    assert resultado is False

def test_format_patient_response():

    p = Patient(patientId="PAT-123", firstName="Pedro", lastName="Pérez", dateOfBirth=datetime(1990, 1, 1))
    
    p.room_rel = Room(roomId="R-01", floor=2, roomNumber="201", roomPavilion="Norte")
    
    contacto = EmergencyContact(contactId="C-01", firstName="Maria", lastName="Pérez", phone="123", mail="m@m.com")
    pc_contact = PatientContact(relationship="Hija", contact=contacto)
    p.patient_contacts = [pc_contact]
    
    alergia = MedicalCondition(conditionId="M-01", name="Polvo", allergenType="Ambiental")
    pc_alergia = PatientCondition(diagnostic="Tos persistente", condition=alergia)
    
    enfermedad = MedicalCondition(conditionId="M-02", name="Gripe", isContagious=True, transmissionRoute="Aire")
    pc_enfermedad = PatientCondition(diagnostic="Fiebre alta", condition=enfermedad)
    
    p.patient_conditions = [pc_alergia, pc_enfermedad]
    
    w = Wearable(wearableId="W-01", macAddress="AA:BB:CC", batteryLevel=80, isActive=True)
    pw = PatientWearable(wearable=w)
    p.patient_wearables = [pw]

    resultado = format_patient_response(p)

    assert resultado["patientId"] == "PAT-123"
    assert resultado["firstName"] == "Pedro"
    
    assert resultado["Room"]["roomNumber"] == "201"
    assert resultado["emergencyContact"]["relationship"] == "Hija"
    
    assert len(resultado["Allergies"]) == 1
    assert resultado["Allergies"][0]["name"] == "Polvo"
    assert resultado["Allergies"][0]["diagnostics"] == "Tos persistente"
    
    assert len(resultado["Diseases"]) == 1
    assert resultado["Diseases"][0]["name"] == "Gripe"
    assert resultado["Diseases"][0]["isContagious"] is True
    
    assert len(resultado["wearableDevices"]) == 1
    assert resultado["wearableDevices"][0]["batteryLevel"] == 80

def test_format_patient_response_sin_relaciones():
    p = Patient(patientId="PAT-999", firstName="Solo", lastName="Nombre")
    
    p.patient_contacts = []
    p.patient_conditions = []
    p.patient_wearables = []
    
    resultado = format_patient_response(p)
    
    assert resultado["Room"] == {}
    assert resultado["emergencyContact"] == {}
    assert len(resultado["Allergies"]) == 0
    assert len(resultado["Diseases"]) == 0

def test_generate_uuid():
    uuid1 = generate_uuid()
    uuid2 = generate_uuid()
    
    assert isinstance(uuid1, str)
    assert len(uuid1) > 30 
    assert uuid1 != uuid2
