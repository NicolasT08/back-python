from flask import Blueprint, request, jsonify
from datetime import datetime
from .models import db, Patient, Alert, Wearable, Room, AlertType, MedicalCondition, EmergencyContact, PatientWearable, PatientCondition, PatientContact
from .auth import token_required, keycloak_openid
from .kafka_producer import publicar_evento

api_blueprint = Blueprint('api', __name__)

ROLE_ADMIN = "administrator"
ROLE_NURSE = "nurse"

# login
@api_blueprint.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({"error": "Faltan credenciales"}), 400
    try:
        token = keycloak_openid.token(username, password)
        publicar_evento("usuarios.autenticacion", {"tipo": "login_exitoso", "usuario": username})
        return jsonify({"token": token['access_token']}), 200
    except Exception as e:
        publicar_evento("usuarios.autenticacion", {"tipo": "login_fallido", "usuario": username, "error": str(e)})
        return jsonify({"error": "Credenciales inválidas"}), 401

# pacientes
@api_blueprint.route('/patient', methods=['GET'])
@token_required(roles_permitidos=[ROLE_NURSE, ROLE_ADMIN])
def get_patients(userinfo):
    patients = Patient.query.all()
    results = [format_patient_response(p) for p in patients]
    publicar_evento("pacientes.consultas", {"tipo": "lista_consultada", "usuario": userinfo.get("preferred_username")})
    return jsonify(results), 200

@api_blueprint.route('/patient/<string:patient_id>', methods=['GET'])
@token_required(roles_permitidos=[ROLE_NURSE, ROLE_ADMIN])
def get_patient(userinfo, patient_id):
    p = Patient.query.get(patient_id)
    if not p: return jsonify({"error": "No encontrado"}), 404
    return jsonify(format_patient_response(p)), 200

@api_blueprint.route('/patient', methods=['POST'])
@token_required(roles_permitidos=[ROLE_ADMIN])
def create_patient(userinfo):
    data = request.get_json()
    
    new_patient = Patient(
        firstName=data.get('firstName'),
        lastName=data.get('lastName'),
        roomId=data.get('RoomId')
    )
    if data.get('dateOfBirth'):
        new_patient.dateOfBirth = datetime.fromisoformat(data.get('dateOfBirth').replace('Z', '+00:00'))
        
    db.session.add(new_patient)
    db.session.flush()
    
    ec_data = data.get('emergencyContact', {})
    if ec_data:
        ec = EmergencyContact(
            firstName=ec_data.get('firstName'), 
            lastName=ec_data.get('lastName'), 
            phone=ec_data.get('phone'), 
            mail=ec_data.get('mail')
        )
        db.session.add(ec)
        db.session.flush()
        
        rel_contact = PatientContact(patientId=new_patient.patientId, contactId=ec.contactId, relationship=ec_data.get('relationship'))
        db.session.add(rel_contact)

    for alg in data.get('Allergies', []):
        cond_alg = MedicalCondition(name=alg.get('name'), diagnostic=alg.get('diagnostics'), allergenType=alg.get('allergenType'))
        db.session.add(cond_alg)
        db.session.flush()
        
        rel_cond = PatientCondition(patientId=new_patient.patientId, conditionId=cond_alg.conditionId, diagnostic=alg.get('diagnostics'))
        db.session.add(rel_cond)

    for dis in data.get('Diseases', []):
        cond_dis = MedicalCondition(name=dis.get('name'), diagnostic=dis.get('diagnostics'), isContagious=dis.get('isContagious'), transmissionRoute=dis.get('transmissionRoute'))
        db.session.add(cond_dis)
        db.session.flush()
        
        rel_cond2 = PatientCondition(patientId=new_patient.patientId, conditionId=cond_dis.conditionId, diagnostic=dis.get('diagnostics'))
        db.session.add(rel_cond2)

    for w_data in data.get('wearableDevices', []):
        wid = w_data.get('wearableId')
        if wid and Wearable.query.get(wid):
            rel_w = PatientWearable(patientId=new_patient.patientId, wearableId=wid, assignedDate=datetime.utcnow())
            db.session.add(rel_w)

    db.session.commit()
    publicar_evento("pacientes.registro", {"tipo": "paciente_creado", "patientId": new_patient.patientId})
    return jsonify({"status": 201, "message": "Paciente creado", "patientId": new_patient.patientId}), 201

@api_blueprint.route('/patient/<string:patient_id>', methods=['PUT'])
@token_required(roles_permitidos=[ROLE_ADMIN])
def update_patient(userinfo, patient_id):
    p = Patient.query.get(patient_id)
    if not p: return jsonify({"status": 404, "message": "No encontrado"}), 404
    data = request.get_json()
    p.firstName = data.get('firstName', p.firstName)
    p.lastName = data.get('lastName', p.lastName)
    p.roomId = data.get('RoomId', p.roomId)
    db.session.commit()
    return jsonify({"status": 200, "message": "Paciente actualizado"}), 200

@api_blueprint.route('/patient/<string:patient_id>', methods=['DELETE'])
@token_required(roles_permitidos=[ROLE_ADMIN])
def delete_patient(userinfo, patient_id):
    p = Patient.query.get(patient_id)
    if not p: return jsonify({"status": 404, "message": "No encontrado"}), 404
    db.session.delete(p)
    db.session.commit()
    return jsonify({"status": 200, "message": "Paciente eliminado"}), 200

def format_patient_response(p):
    room_data = {"idRoom": p.room_rel.roomId, "floor": p.room_rel.floor, "roomNumber": p.room_rel.roomNumber, "roomPavilion": p.room_rel.roomPavilion} if p.room_rel else {}
    
    ec_data = {}
    if p.patient_contacts:
        pc = p.patient_contacts[0]
        c = pc.contact
        ec_data = {"idContact": c.contactId, "firstName": c.firstName, "lastName": c.lastName, "phone": c.phone, "mail": c.mail, "relationship": pc.relationship}
    
    allergies, diseases = [], []
    for pc in p.patient_conditions:
        c = pc.condition

        diag = pc.diagnostic or c.diagnostic 
        if c.allergenType:
            allergies.append({"medicalId": c.conditionId, "name": c.name, "diagnostics": diag, "allergenType": c.allergenType})
        else:
            diseases.append({"medicalId": c.conditionId, "name": c.name, "diagnostics": diag, "isContagious": c.isContagious, "transmissionRoute": c.transmissionRoute})

    wearables = []
    for pw in p.patient_wearables:
        w = pw.wearable
        wearables.append({"wearableId": w.wearableId, "macAddress": w.macAddress, "batteryLevel": w.batteryLevel, "isActive": w.isActive})
        
    return {
        "patientId": p.patientId,
        "firstName": p.firstName,
        "lastName": p.lastName,
        "dateOfBirth": p.dateOfBirth.isoformat() if p.dateOfBirth else None,
        "Room": room_data,
        "Allergies": allergies,
        "Diseases": diseases,
        "emergencyContact": ec_data,
        "wearableDevices": wearables
    }

# alertas
@api_blueprint.route('/alert', methods=['POST'])
@token_required(roles_permitidos=[ROLE_NURSE, ROLE_ADMIN])
def create_alert(userinfo):
    data = request.get_json()
    new_alert = Alert(patientId=data.get('patientId'), wearableId=data.get('wearableId'), alertType=data.get('alertType'), alertLevel=data.get('alertLevel'), alertStatus=data.get('alertStatus'))
    db.session.add(new_alert)
    db.session.commit()
    publicar_evento("alertas.emergencias", {"tipo": "alerta_generada", "alertId": new_alert.alertId})
    return jsonify({"alert_id": new_alert.alertId, "createdAt": new_alert.createdAt.isoformat(), "Message": "Alerta registrada"}), 201

@api_blueprint.route('/alert', methods=['GET'])
@token_required(roles_permitidos=[ROLE_NURSE, ROLE_ADMIN])
def get_alerts(userinfo):
    alerts = Alert.query.all()
    res = [{"alertId": a.alertId, "patientId": a.patientId, "wearableId": a.wearableId, "alertStatus": a.alertStatus, "alertLevel": a.alertLevel, "alertType": a.alertType, "nurseId": a.nurseId, "createdAt": a.createdAt.isoformat(), "resolvedAt": a.resolvedAt.isoformat() if a.resolvedAt else None} for a in alerts]
    return jsonify(res), 200

@api_blueprint.route('/alert/<string:alert_id>', methods=['GET'])
@token_required(roles_permitidos=[ROLE_NURSE, ROLE_ADMIN])
def get_alert(userinfo, alert_id):
    a = Alert.query.get(alert_id)
    if not a: return jsonify({"error": "No encontrada"}), 404
    return jsonify({"alertId": a.alertId, "patientId": a.patientId, "wearableId": a.wearableId, "alertStatus": a.alertStatus, "alertLevel": a.alertLevel, "alertType": a.alertType, "nurseId": a.nurseId, "createdAt": a.createdAt.isoformat(), "resolvedAt": a.resolvedAt.isoformat() if a.resolvedAt else None}), 200

@api_blueprint.route('/alert/<string:alert_id>', methods=['PUT'])
@token_required(roles_permitidos=[ROLE_NURSE, ROLE_ADMIN])
def update_alert(userinfo, alert_id):
    a = Alert.query.get(alert_id)
    if not a: return jsonify({"error": "No encontrada"}), 404
    data = request.get_json()
    a.alertStatus = data.get('alertStatus', a.alertStatus)
    a.alertLevel = data.get('alertLevel', a.alertLevel)
    a.nurseId = data.get('nurseId', a.nurseId)
    if data.get('resolvedAt'): a.resolvedAt = datetime.fromisoformat(data.get('resolvedAt'))
    db.session.commit()
    return jsonify({"alertId": a.alertId, "Message": "Alerta actualizada"}), 200

@api_blueprint.route('/alert/<string:alert_id>', methods=['DELETE'])
@token_required(roles_permitidos=[ROLE_ADMIN])
def delete_alert(userinfo, alert_id):
    a = Alert.query.get(alert_id)
    if not a: return jsonify({"error": "No encontrada"}), 404
    db.session.delete(a)
    db.session.commit()
    return jsonify({"Message": "Alerta eliminada"}), 200

# dispositivos iot
@api_blueprint.route('/device', methods=['POST'])
@token_required(roles_permitidos=[ROLE_ADMIN])
def create_device(userinfo):
    data = request.get_json()
    d = Wearable(macAddress=data.get('macAddress'), batteryLevel=data.get('batteryLevel'), isActive=data.get('isActive'))
    db.session.add(d)
    db.session.commit()
    return jsonify({"wearableId": d.wearableId, "Message": "Dispositivo registrado exitosamente"}), 201

@api_blueprint.route('/device', methods=['GET'])
@token_required(roles_permitidos=[ROLE_NURSE, ROLE_ADMIN])
def get_devices(userinfo):
    devices = Wearable.query.all()
    return jsonify([{"macAddress": d.macAddress, "batteryLevel": d.batteryLevel, "isActive": d.isActive} for d in devices]), 200

@api_blueprint.route('/device/<string:device_id>', methods=['GET'])
@token_required(roles_permitidos=[ROLE_NURSE, ROLE_ADMIN])
def get_device(userinfo, device_id):
    d = Wearable.query.get(device_id)
    if not d: return jsonify({"error": "No encontrado"}), 404
    return jsonify({"macAddress": d.macAddress, "batteryLevel": d.batteryLevel, "isActive": d.isActive}), 200

@api_blueprint.route('/device/<string:device_id>', methods=['PUT'])
@token_required(roles_permitidos=[ROLE_ADMIN])
def update_device(userinfo, device_id):
    d = Wearable.query.get(device_id)
    if not d: return jsonify({"error": "No encontrado"}), 404
    data = request.get_json()
    d.macAddress = data.get('macAddress', d.macAddress)
    d.batteryLevel = data.get('batteryLevel', d.batteryLevel)
    d.isActive = data.get('isActive', d.isActive)
    db.session.commit()
    return jsonify({"wearableId": d.wearableId, "Message": "Información del dispositivo actualizada"}), 200

@api_blueprint.route('/device/<string:device_id>', methods=['DELETE'])
@token_required(roles_permitidos=[ROLE_ADMIN])
def delete_device(userinfo, device_id):
    d = Wearable.query.get(device_id)
    if not d: return jsonify({"error": "No encontrado"}), 404
    db.session.delete(d)
    db.session.commit()
    return jsonify({"Message": "Dispositivo eliminado exitosamente"}), 200

# habitaciones
@api_blueprint.route('/room', methods=['POST'])
@token_required(roles_permitidos=[ROLE_ADMIN])
def create_room(userinfo):
    data = request.get_json()
    r = Room(floor=data.get('floor'), roomNumber=data.get('roomNumber'), roomPavilion=data.get('roomPavilion'))
    db.session.add(r)
    db.session.commit()
    return jsonify({"roomId": r.roomId, "Message": "Habitación registrada exitosamente"}), 201

@api_blueprint.route('/room', methods=['GET'])
@token_required(roles_permitidos=[ROLE_NURSE, ROLE_ADMIN])
def get_rooms(userinfo):
    rooms = Room.query.all()
    return jsonify([{"roomId": r.roomId, "floor": r.floor, "roomNumber": r.roomNumber, "roomPavilion": r.roomPavilion} for r in rooms]), 200

@api_blueprint.route('/room/<string:room_id>', methods=['GET'])
@token_required(roles_permitidos=[ROLE_NURSE, ROLE_ADMIN])
def get_room(userinfo, room_id):
    r = Room.query.get(room_id)
    if not r: return jsonify({"error": "No encontrada"}), 404
    return jsonify({"roomId": r.roomId, "floor": r.floor, "roomNumber": r.roomNumber, "roomPavilion": r.roomPavilion}), 200

@api_blueprint.route('/room/<string:room_id>', methods=['PUT'])
@token_required(roles_permitidos=[ROLE_ADMIN])
def update_room(userinfo, room_id):
    r = Room.query.get(room_id)
    if not r: return jsonify({"error": "No encontrada"}), 404
    data = request.get_json()
    r.floor = data.get('floor', r.floor)
    r.roomNumber = data.get('roomNumber', r.roomNumber)
    r.roomPavilion = data.get('roomPavilion', r.roomPavilion)
    db.session.commit()
    return jsonify({"roomId": r.roomId, "Message": "Información de la habitación actualizada"}), 200

@api_blueprint.route('/room/<string:room_id>', methods=['DELETE'])
@token_required(roles_permitidos=[ROLE_ADMIN])
def delete_room(userinfo, room_id):
    r = Room.query.get(room_id)
    if not r: return jsonify({"error": "No encontrada"}), 404
    db.session.delete(r)
    db.session.commit()
    return jsonify({"Message": "Habitación eliminada exitosamente"}), 200

# tipos de alerta
@api_blueprint.route('/alert-type', methods=['POST'])
@token_required(roles_permitidos=[ROLE_ADMIN])
def create_alert_type(userinfo):
    data = request.get_json()
    at = AlertType(name=data.get('name'), code=data.get('code'), description=data.get('description'))
    db.session.add(at)
    db.session.commit()
    return jsonify({"alertTypeId": at.alertTypeId, "Message": "Tipo de alerta registrado exitosamente"}), 201

@api_blueprint.route('/alert-type', methods=['GET'])
@token_required(roles_permitidos=[ROLE_NURSE, ROLE_ADMIN])
def get_alert_types(userinfo):
    types = AlertType.query.all()
    return jsonify([{"alertTypeId": t.alertTypeId, "name": t.name, "code": t.code, "description": t.description} for t in types]), 200

@api_blueprint.route('/alert-type/<string:type_id>', methods=['GET'])
@token_required(roles_permitidos=[ROLE_NURSE, ROLE_ADMIN])
def get_alert_type(userinfo, type_id):
    t = AlertType.query.get(type_id)
    if not t: return jsonify({"error": "No encontrado"}), 404
    return jsonify({"alertTypeId": t.alertTypeId, "name": t.name, "code": t.code, "description": t.description}), 200

@api_blueprint.route('/alert-type/<string:type_id>', methods=['PUT'])
@token_required(roles_permitidos=[ROLE_ADMIN])
def update_alert_type(userinfo, type_id):
    t = AlertType.query.get(type_id)
    if not t: return jsonify({"error": "No encontrado"}), 404
    data = request.get_json()
    t.name = data.get('name', t.name)
    t.code = data.get('code', t.code)
    t.description = data.get('description', t.description)
    db.session.commit()
    return jsonify({"alertTypeId": t.alertTypeId, "Message": "Tipo de alerta actualizada"}), 200

@api_blueprint.route('/alert-type/<string:type_id>', methods=['DELETE'])
@token_required(roles_permitidos=[ROLE_ADMIN])
def delete_alert_type(userinfo, type_id):
    t = AlertType.query.get(type_id)
    if not t: return jsonify({"error": "No encontrado"}), 404
    db.session.delete(t)
    db.session.commit()
    return jsonify({"Message": "Tipo de alerta eliminada exitosamente"}), 200