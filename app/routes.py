from flask import Blueprint, request, jsonify
from datetime import datetime
from .models import db, Patient, Alert, Wearable, Room, AlertType, MedicalCondition, EmergencyContact, PatientWearable, PatientCondition, PatientContact
from .auth import token_required, keycloak_openid
from .kafka_producer import publicar_evento
from app import cache

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
@cache.cached(timeout=60, query_string=True)
def get_patients(userinfo):
    patients = Patient.query.all()
    results = [format_patient_response(p) for p in patients]
    publicar_evento("pacientes.consultas", {"tipo": "lista_consultada", "usuario": userinfo.get("preferred_username")})
    return jsonify(results), 200

@api_blueprint.route('/patient/<string:patient_id>', methods=['GET'])
@token_required(roles_permitidos=[ROLE_NURSE, ROLE_ADMIN])
@cache.cached(timeout=60, query_string=True)
def get_patient(userinfo, patient_id):
    p = Patient.query.get(patient_id)
    if not p: return jsonify({"error": "No encontrado"}), 404
    return jsonify(format_patient_response(p)), 200

@api_blueprint.route('/patient', methods=['POST'])
@token_required(roles_permitidos=[ROLE_ADMIN])
def create_patient(userinfo):
    data = request.get_json()
    
    first_name = data.get('firstName')
    last_name = data.get('lastName')
    
    # VERIFICACIÓN: Evitar registrar pacientes duplicados
    if first_name and last_name and Patient.query.filter_by(firstName=first_name, lastName=last_name).first():
        return jsonify({"error": f"El paciente {first_name} {last_name} ya está registrado en el sistema."}), 409
    
    room_id = data.get('RoomId')
    if room_id and not Room.query.get(room_id):
        return jsonify({"error": f"La habitación con ID '{room_id}' no existe."}), 400
    
    new_patient = Patient(
        firstName=first_name,
        lastName=last_name,
        roomId=room_id
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
        if wid:
            if not Wearable.query.get(wid):
                db.session.rollback() 
                return jsonify({"error": f"El dispositivo IoT con ID '{wid}' no existe."}), 400
                
            # VERIFICACIÓN: Evitar asignar una manilla que ya tiene otro paciente
            if PatientWearable.query.filter_by(wearableId=wid).first():
                db.session.rollback()
                return jsonify({"error": f"El dispositivo {wid} ya está asignado a otro paciente actualmente."}), 409
                
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
    
    new_first = data.get('firstName', p.firstName)
    new_last = data.get('lastName', p.lastName)
    
    # VERIFICACIÓN: Evitar que al actualizar el nombre choque con otro paciente existente
    if (new_first != p.firstName or new_last != p.lastName) and Patient.query.filter_by(firstName=new_first, lastName=new_last).first():
        return jsonify({"error": f"Ya existe otro paciente registrado como {new_first} {new_last}."}), 409
    
    new_room_id = data.get('RoomId')
    if new_room_id and new_room_id != p.roomId:
        if not Room.query.get(new_room_id):
            return jsonify({"error": f"La habitación con ID '{new_room_id}' no existe."}), 400
        p.roomId = new_room_id
        
    p.firstName = new_first
    p.lastName = new_last
    db.session.commit()
    return jsonify({"status": 200, "message": "Paciente actualizado", "patientId": p.patientId}), 200

@api_blueprint.route('/patient/<string:patient_id>', methods=['DELETE'])
@token_required(roles_permitidos=[ROLE_ADMIN])
def delete_patient(userinfo, patient_id):
    p = Patient.query.get(patient_id)
    if not p: return jsonify({"status": 404, "message": "No encontrado"}), 404
    
    if Alert.query.filter_by(patientId=patient_id).first():
        return jsonify({"error": "No se puede eliminar el paciente porque tiene alertas vinculadas en el sistema."}), 400

    db.session.delete(p)
    db.session.commit()
    return jsonify({"status": 200, "message": "Paciente eliminado", "patientId": p.patientId}), 200

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
    
    patient_id = data.get('patientId')
    if patient_id and not Patient.query.get(patient_id):
        return jsonify({"error": f"El paciente con ID '{patient_id}' no existe."}), 400
        
    wearable_id = data.get('wearableId')
    if wearable_id and not Wearable.query.get(wearable_id):
        return jsonify({"error": f"El dispositivo con ID '{wearable_id}' no existe."}), 400

    alert_type_id = data.get('alertType')
    if alert_type_id and not AlertType.query.get(alert_type_id):
        return jsonify({"error": f"El tipo de alerta '{alert_type_id}' no existe en el catálogo."}), 400

    new_alert = Alert(patientId=patient_id, wearableId=wearable_id, alertType=alert_type_id, alertLevel=data.get('alertLevel'), alertStatus=data.get('alertStatus'))
    db.session.add(new_alert)
    db.session.commit()
    publicar_evento("alertas.emergencias", {"tipo": "alerta_generada", "alertId": new_alert.alertId})
    return jsonify({"alert_id": new_alert.alertId, "createdAt": new_alert.createdAt.isoformat(), "Message": "Alerta registrada"}), 201

@api_blueprint.route('/alert', methods=['GET'])
@token_required(roles_permitidos=[ROLE_NURSE, ROLE_ADMIN])
@cache.cached(timeout=60, query_string=True)
def get_alerts(userinfo):
    alerts = Alert.query.all()
    res = [{"alertId": a.alertId, "patientId": a.patientId, "wearableId": a.wearableId, "alertStatus": a.alertStatus, "alertLevel": a.alertLevel, "alertType": a.alertType, "nurseId": a.nurseId, "createdAt": a.createdAt.isoformat(), "resolvedAt": a.resolvedAt.isoformat() if a.resolvedAt else None} for a in alerts]
    return jsonify(res), 200

@api_blueprint.route('/alert/<string:alert_id>', methods=['GET'])
@token_required(roles_permitidos=[ROLE_NURSE, ROLE_ADMIN])
@cache.cached(timeout=60, query_string=True)
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
    return jsonify({"alertId": a.alertId, "Message": "Alerta eliminada"}), 200

# dispositivos iot
@api_blueprint.route('/device', methods=['POST'])
@token_required(roles_permitidos=[ROLE_ADMIN])
def create_device(userinfo):
    data = request.get_json()
    mac = data.get('macAddress')
    
    if mac and Wearable.query.filter_by(macAddress=mac).first():
        return jsonify({"error": f"Ya existe un dispositivo registrado con la MAC {mac}."}), 409

    d = Wearable(macAddress=mac, batteryLevel=data.get('batteryLevel'), isActive=data.get('isActive'))
    db.session.add(d)
    db.session.commit()
    return jsonify({"wearableId": d.wearableId, "Message": "Dispositivo registrado exitosamente"}), 201

@api_blueprint.route('/device', methods=['GET'])
@token_required(roles_permitidos=[ROLE_NURSE, ROLE_ADMIN])
@cache.cached(timeout=60, query_string=True)
def get_devices(userinfo):
    devices = Wearable.query.all()
    return jsonify([{"wearableId": d.wearableId, "macAddress": d.macAddress, "batteryLevel": d.batteryLevel, "isActive": d.isActive} for d in devices]), 200

@api_blueprint.route('/device/<string:device_id>', methods=['GET'])
@token_required(roles_permitidos=[ROLE_NURSE, ROLE_ADMIN])
@cache.cached(timeout=60, query_string=True)
def get_device(userinfo, device_id):
    d = Wearable.query.get(device_id)
    if not d: return jsonify({"error": "No encontrado"}), 404
    return jsonify({"wearableId": d.wearableId, "macAddress": d.macAddress, "batteryLevel": d.batteryLevel, "isActive": d.isActive}), 200

@api_blueprint.route('/device/<string:device_id>', methods=['PUT'])
@token_required(roles_permitidos=[ROLE_ADMIN])
def update_device(userinfo, device_id):
    d = Wearable.query.get(device_id)
    if not d: return jsonify({"error": "No encontrado"}), 404
    data = request.get_json()
    
    new_mac = data.get('macAddress')
    
    if new_mac and new_mac != d.macAddress and Wearable.query.filter_by(macAddress=new_mac).first():
        return jsonify({"error": f"La dirección MAC {new_mac} ya está en uso por otro dispositivo."}), 409

    d.macAddress = new_mac or d.macAddress
    d.batteryLevel = data.get('batteryLevel', d.batteryLevel)
    d.isActive = data.get('isActive', d.isActive)
    db.session.commit()
    return jsonify({"wearableId": d.wearableId, "Message": "Información del dispositivo actualizada"}), 200

@api_blueprint.route('/device/<string:device_id>', methods=['DELETE'])
@token_required(roles_permitidos=[ROLE_ADMIN])
def delete_device(userinfo, device_id):
    d = Wearable.query.get(device_id)
    if not d: return jsonify({"error": "No encontrado"}), 404
    
    if PatientWearable.query.filter_by(wearableId=device_id).first() or Alert.query.filter_by(wearableId=device_id).first():
        return jsonify({"error": "No se puede eliminar el dispositivo porque está asignado a un paciente o tiene alertas vinculadas."}), 400

    db.session.delete(d)
    db.session.commit()
    return jsonify({"wearableId": d.wearableId, "Message": "Dispositivo eliminado exitosamente"}), 200

# habitaciones
@api_blueprint.route('/room', methods=['POST'])
@token_required(roles_permitidos=[ROLE_ADMIN])
def create_room(userinfo):
    data = request.get_json()
    num = data.get('roomNumber')
    pav = data.get('roomPavilion')
    
    if num and pav and Room.query.filter_by(roomNumber=num, roomPavilion=pav).first():
        return jsonify({"error": f"La habitación {num} ya existe en el pabellón {pav}."}), 409

    r = Room(floor=data.get('floor'), roomNumber=num, roomPavilion=pav)
    db.session.add(r)
    db.session.commit()
    return jsonify({"roomId": r.roomId, "Message": "Habitación registrada exitosamente"}), 201

@api_blueprint.route('/room', methods=['GET'])
@token_required(roles_permitidos=[ROLE_NURSE, ROLE_ADMIN])
@cache.cached(timeout=60, query_string=True)
def get_rooms(userinfo):
    rooms = Room.query.all()
    return jsonify([{"roomId": r.roomId, "floor": r.floor, "roomNumber": r.roomNumber, "roomPavilion": r.roomPavilion} for r in rooms]), 200

@api_blueprint.route('/room/<string:room_id>', methods=['GET'])
@token_required(roles_permitidos=[ROLE_NURSE, ROLE_ADMIN])
@cache.cached(timeout=60, query_string=True)
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
    
    new_num = data.get('roomNumber', r.roomNumber)
    new_pav = data.get('roomPavilion', r.roomPavilion)
    
    if (new_num != r.roomNumber or new_pav != r.roomPavilion) and Room.query.filter_by(roomNumber=new_num, roomPavilion=new_pav).first():
        return jsonify({"error": f"La habitación {new_num} ya existe en el pabellón {new_pav}."}), 409

    r.floor = data.get('floor', r.floor)
    r.roomNumber = new_num
    r.roomPavilion = new_pav
    db.session.commit()
    return jsonify({"roomId": r.roomId, "Message": "Información de la habitación actualizada"}), 200

@api_blueprint.route('/room/<string:room_id>', methods=['DELETE'])
@token_required(roles_permitidos=[ROLE_ADMIN])
def delete_room(userinfo, room_id):
    r = Room.query.get(room_id)
    if not r: return jsonify({"error": "No encontrada"}), 404
    
    if Patient.query.filter_by(roomId=room_id).first():
        return jsonify({"error": "No se puede eliminar la habitación porque tiene pacientes asignados actualmente."}), 400

    db.session.delete(r)
    db.session.commit()
    return jsonify({"roomId": r.roomId, "Message": "Habitación eliminada exitosamente"}), 200

# alertas
@api_blueprint.route('/alert-type', methods=['POST'])
@token_required(roles_permitidos=[ROLE_ADMIN])
def create_alert_type(userinfo):
    data = request.get_json()
    code = data.get('code')
    
    if code and AlertType.query.filter_by(code=code).first():
        return jsonify({"error": f"El código de alerta '{code}' ya está en uso."}), 409

    at = AlertType(name=data.get('name'), code=code, description=data.get('description'))
    db.session.add(at)
    db.session.commit()
    return jsonify({"alertTypeId": at.alertTypeId, "Message": "Tipo de alerta registrado exitosamente"}), 201

@api_blueprint.route('/alert-type', methods=['GET'])
@token_required(roles_permitidos=[ROLE_NURSE, ROLE_ADMIN])
@cache.cached(timeout=60, query_string=True) 
def get_alert_types(userinfo):
    types = AlertType.query.all()
    return jsonify([{"alertTypeId": t.alertTypeId, "name": t.name, "code": t.code, "description": t.description} for t in types]), 200

@api_blueprint.route('/alert-type/<string:type_id>', methods=['GET'])
@token_required(roles_permitidos=[ROLE_NURSE, ROLE_ADMIN])
@cache.cached(timeout=60, query_string=True)
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
    
    new_code = data.get('code')
    
    if new_code and new_code != t.code and AlertType.query.filter_by(code=new_code).first():
        return jsonify({"error": f"El código de alerta '{new_code}' ya está en uso por otro registro."}), 409

    t.name = data.get('name', t.name)
    t.code = new_code or t.code
    t.description = data.get('description', t.description)
    db.session.commit()
    return jsonify({"alertTypeId": t.alertTypeId, "Message": "Tipo de alerta actualizada"}), 200

@api_blueprint.route('/alert-type/<string:type_id>', methods=['DELETE'])
@token_required(roles_permitidos=[ROLE_ADMIN])
def delete_alert_type(userinfo, type_id):
    t = AlertType.query.get(type_id)
    if not t: return jsonify({"error": "No encontrado"}), 404
    
    if Alert.query.filter_by(alertType=type_id).first():
        return jsonify({"error": "No se puede eliminar este tipo de alerta porque existen registros de emergencias que lo utilizan."}), 400

    db.session.delete(t)
    db.session.commit()
    return jsonify({"alertTypeId": t.alertTypeId, "Message": "Tipo de alerta eliminada exitosamente"}), 200