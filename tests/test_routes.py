import os
import pytest

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

from app import create_app, db

@pytest.fixture
def app():

    app = create_app()
    app.config.update({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"
    })
    
    with app.app_context():
        db.create_all()
        yield app  
        db.session.remove()
        db.drop_all() 

@pytest.fixture
def mock_auth_token(mocker):
    """
    Esta función engaña al decorador @token_required.
    Evita que intente conectarse al servidor real de Keycloak.
    """
    def _mock_token(rol):

        mocker.patch('app.auth.keycloak_openid.public_key', return_value="llave_publica_falsa")
        
        mocker.patch('app.auth.keycloak_openid.decode_token', return_value={
            "preferred_username": "usuario_prueba",
            "resource_access": {
                "backend-python": {
                    "roles": [rol]
                }
            }
        })
    return _mock_token

@pytest.mark.parametrize("metodo, ruta", [
    ("POST", "/patient"),               # Crear paciente
    ("PUT", "/patient/uuid-123"),       # Editar paciente
    ("DELETE", "/patient/uuid-123"),    # Borrar paciente
    ("POST", "/device"),                # Crear dispositivo
    ("PUT", "/device/uuid-123"),        # Editar dispositivo
    ("DELETE", "/device/uuid-123"),     # Borrar dispositivo
    ("POST", "/room"),                  # Crear habitación
    ("PUT", "/room/uuid-123"),          # Editar habitación
    ("DELETE", "/room/uuid-123"),       # Borrar habitación
    ("DELETE", "/alert/uuid-123"),      # Borrar alerta
    ("POST", "/alert-type"),            # Crear tipo de alerta
    ("PUT", "/alert-type/uuid-123"),    # Editar tipo de alerta
    ("DELETE", "/alert-type/uuid-123")  # Borrar tipo de alerta
])
def test_enfermero_bloqueado_en_rutas_admin(client, mock_auth_token, metodo, ruta):
    """
    Escenario: Un usuario con rol 'nurse' intenta acceder a rutas exclusivas de 'administrator'.
    El sistema debe rechazar la petición con un error 403 (Forbidden).
    """
    mock_auth_token("nurse")
    
    payload_falso = {"data": "intento_de_hackeo"}
    headers = {"Authorization": "Bearer token_falso"}
    
    if metodo == "POST":
        response = client.post(ruta, json=payload_falso, headers=headers)
    elif metodo == "PUT":
        response = client.put(ruta, json=payload_falso, headers=headers)
    elif metodo == "DELETE":
        response = client.delete(ruta, headers=headers)
        
    assert response.status_code == 403
    assert "Acceso denegado" in response.get_json()["error"]


def test_enfermero_acceso_permitido_a_lectura(client, mock_auth_token):

    mock_auth_token("nurse")
    response = client.get("/patient", headers={"Authorization": "Bearer token_falso"})
    assert response.status_code == 200


def test_admin_puede_crear_habitacion(client, mock_auth_token):

    mock_auth_token("administrator")
    
    payload_habitacion = {
        "floor": 3,
        "roomNumber": "305",
        "roomPavilion": "Sur"
    }
    
    response = client.post("/room", json=payload_habitacion, headers={"Authorization": "Bearer token_valido"})
    
    assert response.status_code == 201
    assert "roomId" in response.get_json()
    assert response.get_json()["Message"] == "Habitación registrada exitosamente"


def test_creacion_de_alerta_dispara_evento_kafka(client, mock_auth_token, mocker):
    
    from app.models import Patient, Wearable, AlertType, db

    mock_auth_token("nurse")
    
    paciente_prueba = Patient(patientId="paciente-falso-123", firstName="Shadow", lastName="Hedgehog")
    manilla_prueba = Wearable(wearableId="manilla-falsa-456", macAddress="AA:BB:CC")
    tipo_alerta_prueba = AlertType(alertTypeId="tipo-caida", name="Caída", code="FALL_01")
    
    db.session.add(paciente_prueba)
    db.session.add(manilla_prueba)
    db.session.add(tipo_alerta_prueba) 
    db.session.commit()
    
    espia_kafka = mocker.patch('app.routes.publicar_evento')
    
    payload_alerta = {
        "patientId": "paciente-falso-123",
        "wearableId": "manilla-falsa-456",
        "alertType": "tipo-caida",
        "alertLevel": "roja",
        "alertStatus": "activa"
    }
    
    response = client.post("/alert", json=payload_alerta, headers={"Authorization": "Bearer token_valido"})
    
    assert response.status_code == 201
    
    espia_kafka.assert_called_once()
    argumentos_llamada, _ = espia_kafka.call_args
    assert argumentos_llamada[0] == "alertas.emergencias"